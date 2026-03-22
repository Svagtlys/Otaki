from gql import Client, gql
from gql.transport.httpx import HTTPXAsyncTransport

from ..config import settings


def _make_client(url: str, username: str | None, password: str | None) -> Client:
    auth = (username, password) if username else None
    transport = HTTPXAsyncTransport(url=f"{url}/api/graphql", auth=auth, verify=False)
    return Client(transport=transport, fetch_schema_from_transport=False)


async def ping(url: str, username: str | None, password: str | None) -> bool:
    try:
        async with _make_client(url, username, password) as session:
            await session.execute(gql("{ __typename }"))
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
