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
