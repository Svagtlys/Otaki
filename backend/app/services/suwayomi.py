import base64
import ssl
from typing import AsyncGenerator

import httpx
from gql import Client, gql
from gql.transport.httpx import HTTPXAsyncTransport
from gql.transport.websockets import WebsocketsTransport

from ..config import settings


def classify_error(exc: Exception) -> str:
    """Return a user-friendly reason string for a Suwayomi connectivity failure."""
    if isinstance(exc, httpx.TimeoutException):
        return "connection timed out"
    if isinstance(exc, httpx.ConnectError):
        return "connection refused or DNS failure"
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 401:
        return "authentication failed (401)"
    if isinstance(exc, httpx.HTTPStatusError):
        return f"unexpected HTTP {exc.response.status_code}"
    return "unexpected error"


def _auth_headers() -> dict[str, str]:
    """Return HTTP Basic auth header if credentials are configured."""
    if settings.SUWAYOMI_USERNAME and settings.SUWAYOMI_PASSWORD:
        token = base64.b64encode(
            f"{settings.SUWAYOMI_USERNAME}:{settings.SUWAYOMI_PASSWORD}".encode()
        ).decode()
        return {"Authorization": f"Basic {token}"}
    return {}


def _make_client(url: str, username: str | None, password: str | None) -> Client:
    auth = (username, password) if username else None
    transport = HTTPXAsyncTransport(url=f"{url}/api/graphql", auth=auth, verify=False)
    return Client(transport=transport, fetch_schema_from_transport=False)


async def ping(url: str, username: str | None, password: str | None) -> bool:
    """Return True if Suwayomi is reachable with the given credentials.

    Uses a raw httpx POST so we can inspect the HTTP status code directly.
    Suwayomi allows introspection queries unauthenticated, so we must check for
    a 401 response explicitly rather than relying on gql to raise.
    """
    try:
        auth = (username, password) if username else None
        async with httpx.AsyncClient(verify=False) as client:
            r = await client.post(
                f"{url}/api/graphql",
                json={"query": "{ __typename }"},
                auth=auth,
            )
        if r.status_code == 401:
            return False
        r.raise_for_status()
        return True
    except Exception as e:
        print(f"[ping] failed: {e!r}")
        return False


async def search_source(source_id: str, query: str) -> list[dict]:
    async with _make_client(
        settings.SUWAYOMI_URL,
        settings.SUWAYOMI_USERNAME,
        settings.SUWAYOMI_PASSWORD,
    ) as session:
        result = await session.execute(
            gql("""
                mutation SearchSource($input: FetchSourceMangaInput!) {
                    fetchSourceManga(input: $input) {
                        mangas {
                            id
                            title
                            thumbnailUrl
                            description
                            url
                        }
                    }
                }
            """),
            variable_values={
                "input": {"source": source_id, "query": query, "type": "SEARCH", "page": 1}
            },
        )
    return [
        {
            "manga_id": str(node["id"]),
            "title": node["title"],
            "cover_url": node.get("thumbnailUrl"),
            "synopsis": node.get("description") or None,
            "url": node.get("url"),
        }
        for node in result["fetchSourceManga"]["mangas"]
    ]


async def fetch_chapters(manga_id: str) -> list[dict]:
    from datetime import datetime, timezone

    async with _make_client(
        settings.SUWAYOMI_URL,
        settings.SUWAYOMI_USERNAME,
        settings.SUWAYOMI_PASSWORD,
    ) as session:
        result = await session.execute(
            gql("""
                mutation FetchChapters($input: FetchChaptersInput!) {
                    fetchChapters(input: $input) {
                        chapters {
                            id
                            chapterNumber
                            uploadDate
                        }
                    }
                }
            """),
            variable_values={"input": {"mangaId": int(manga_id)}},
        )
    chapters = []
    for node in result["fetchChapters"]["chapters"]:
        published_at = datetime.fromtimestamp(
            int(node["uploadDate"]) / 1000, tz=timezone.utc
        )
        chapters.append(
            {
                "chapter_number": float(node["chapterNumber"]),
                "volume_number": None,  # not available from Suwayomi chapter data
                "suwayomi_chapter_id": str(node["id"]),
                "chapter_published_at": published_at,
            }
        )
    return chapters


async def enqueue_downloads(chapter_ids: list[str]) -> None:
    async with _make_client(
        settings.SUWAYOMI_URL,
        settings.SUWAYOMI_USERNAME,
        settings.SUWAYOMI_PASSWORD,
    ) as session:
        await session.execute(
            gql("""
                mutation EnqueueChapterDownloads($input: EnqueueChapterDownloadsInput!) {
                    enqueueChapterDownloads(input: $input) {
                        clientMutationId
                    }
                }
            """),
            variable_values={"input": {"ids": [int(cid) for cid in chapter_ids]}},
        )


async def list_sources() -> list[dict]:
    async with _make_client(
        settings.SUWAYOMI_URL,
        settings.SUWAYOMI_USERNAME,
        settings.SUWAYOMI_PASSWORD,
    ) as session:
        result = await session.execute(
            gql("{ sources { nodes { id name lang iconUrl } } }")
        )
    return [
        {
            "id": node["id"],
            "name": node["name"],
            "lang": node["lang"],
            "icon_url": node["iconUrl"],
        }
        for node in result["sources"]["nodes"]
    ]


DOWNLOAD_STATUS_SUBSCRIPTION = gql("""
    subscription OnDownloadStatusChanged($input: DownloadChangedInput!) {
        downloadStatusChanged(input: $input) {
            updates {
                type
                download {
                    chapter { id name }
                    manga { title source { displayName } }
                }
            }
            initial {
                state
                chapter { id name }
                manga { title source { displayName } }
            }
        }
    }
""")


async def subscribe_download_changed() -> AsyncGenerator[tuple[str, str, str, str, str], None]:
    """Async generator yielding (event_type, chapter_id, chapter_name, manga_title,
    source_display_name) tuples for FINISHED and ERROR download events from Suwayomi's
    WebSocket subscription."""
    ws_url = settings.SUWAYOMI_URL.replace("https://", "wss://").replace("http://", "ws://")
    ws_url += "/api/graphql"
    _ssl_ctx = ssl.create_default_context()
    _ssl_ctx.check_hostname = False
    _ssl_ctx.verify_mode = ssl.CERT_NONE
    transport = WebsocketsTransport(
        url=ws_url,
        headers=_auth_headers(),
        ssl=_ssl_ctx,
        subprotocols=["graphql-transport-ws"],
    )
    async with Client(transport=transport) as session:
        first = True
        async for result in session.subscribe(
            DOWNLOAD_STATUS_SUBSCRIPTION, variable_values={"input": {}}
        ):
            data = result["downloadStatusChanged"]
            # On first event, also process initial (DownloadType list — chapters already
            # in the queue when we connected, filtered to FINISHED/ERROR state)
            if first:
                first = False
                for item in (data.get("initial") or []):
                    if item["state"] in ("FINISHED", "ERROR"):
                        chapter = item["chapter"]
                        manga = item["manga"]
                        source_name = (manga.get("source") or {}).get("displayName", "")
                        yield (item["state"], str(chapter["id"]), chapter["name"], manga["title"], source_name)
            # updates is a list of DownloadUpdate: { type: DownloadUpdateType, download: DownloadType }
            for update in data["updates"]:
                if update["type"] in ("FINISHED", "ERROR"):
                    chapter = update["download"]["chapter"]
                    manga = update["download"]["manga"]
                    source_name = (manga.get("source") or {}).get("displayName", "")
                    yield (update["type"], str(chapter["id"]), chapter["name"], manga["title"], source_name)


async def poll_downloads() -> list[dict]:
    """Poll Suwayomi's downloadStatus GraphQL query for the current download queue.

    Returns a list of dicts with keys: state, chapter_id, chapter_name,
    manga_title, source_name for every item currently in the queue (any state).
    Callers are responsible for interpreting state changes.
    """
    async with _make_client(
        settings.SUWAYOMI_URL,
        settings.SUWAYOMI_USERNAME,
        settings.SUWAYOMI_PASSWORD,
    ) as session:
        result = await session.execute(
            gql("""
                {
                    downloadStatus {
                        queue {
                            state
                            chapter { id name }
                            manga { title source { displayName } }
                        }
                    }
                }
            """)
        )

    queue = []
    for item in result["downloadStatus"]["queue"]:
        chapter = item.get("chapter") or {}
        manga = item.get("manga") or {}
        source_name = (manga.get("source") or {}).get("displayName", "")
        queue.append({
            "state": item.get("state", ""),
            "chapter_id": str(chapter.get("id", "")),
            "chapter_name": chapter.get("name", ""),
            "manga_title": manga.get("title", ""),
            "source_name": source_name,
        })
    return queue
