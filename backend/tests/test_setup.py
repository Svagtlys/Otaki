"""Integration tests for the first-run setup wizard (issue #6).

Requires a live Suwayomi instance. Configure credentials in .env.test:

    SUWAYOMI_URL=https://suwayomi.example.com
    SUWAYOMI_USERNAME=admin
    SUWAYOMI_PASSWORD=secret

Optional — defaults to pytest tmp_path if omitted:

    SUWAYOMI_DOWNLOAD_PATH=/path/to/downloads
    LIBRARY_PATH=/path/to/library
"""
import pytest


async def test_non_setup_route_blocked_before_setup(client):
    r = await client.get("/api/comics")
    assert r.status_code == 503
    assert r.json()["detail"] == "Setup required"


async def test_setup_flow(client, suwayomi_credentials, path_config):
    # Connect to Suwayomi
    r = await client.post("/api/setup/connect", json=suwayomi_credentials)
    assert r.status_code == 200

    # Get sources list
    r = await client.get("/api/setup/sources")
    assert r.status_code == 200
    sources = r.json()
    assert isinstance(sources, list)
    assert len(sources) > 0

    # Save source priority order
    r = await client.post("/api/setup/sources", json={"sources": sources[:3]})
    assert r.status_code == 200

    # Save filesystem paths
    r = await client.post("/api/setup/paths", json=path_config)
    assert r.status_code == 200

    # Setup complete — all setup endpoints now return 409
    r = await client.post("/api/setup/connect", json=suwayomi_credentials)
    assert r.status_code == 409
    assert r.json()["detail"] == "Setup already complete"

    r = await client.get("/api/setup/sources")
    assert r.status_code == 409

    r = await client.post("/api/setup/sources", json={"sources": sources[:1]})
    assert r.status_code == 409

    r = await client.post("/api/setup/paths", json=path_config)
    assert r.status_code == 409

    # Non-setup routes now unblocked
    r = await client.get("/api/comics")
    assert r.status_code != 503


async def test_connect_bad_credentials(client, suwayomi_credentials):
    import httpx

    # Skip if this Suwayomi instance does not enforce Basic auth — when auth is
    # disabled in Suwayomi's settings, all requests return 200 regardless of
    # credentials, so there is nothing for Otaki to reject.
    url = suwayomi_credentials["url"]
    async with httpx.AsyncClient(verify=False) as probe:
        r = await probe.post(f"{url}/api/graphql", json={"query": "{ __typename }"})
    if r.status_code != 401:
        pytest.skip("Suwayomi instance does not enforce Basic auth — skipping bad-credential test")

    bad = {**suwayomi_credentials, "password": "definitely-wrong-password-xxxxx"}
    r = await client.post("/api/setup/connect", json=bad)
    assert r.status_code == 400
    assert r.json()["detail"] == "Could not connect to Suwayomi"


async def test_paths_invalid_directory(client, suwayomi_credentials, path_config):
    await client.post("/api/setup/connect", json=suwayomi_credentials)

    r = await client.post(
        "/api/setup/paths",
        json={
            "download_path": "/nonexistent/path/xyz",
            "library_path": path_config["library_path"],
        },
    )
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert detail["code"] == "directories_missing"
    assert any(e["field"] == "download_path" for e in detail["missing"])
