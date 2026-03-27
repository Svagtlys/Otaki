import base64
import logging
import mimetypes
from pathlib import Path

import httpx

from ..config import settings

log = logging.getLogger(__name__)


async def save_from_url(comic_id: int, url: str) -> Path | None:
    """Download cover image from *url* and save to COVERS_PATH/{comic_id}.{ext}.

    Returns the saved Path on success, or None if the download fails.
    """
    covers_dir = Path(settings.COVERS_PATH)
    covers_dir.mkdir(parents=True, exist_ok=True)

    headers: dict[str, str] = {}
    if settings.SUWAYOMI_URL and url.startswith(settings.SUWAYOMI_URL):
        if settings.SUWAYOMI_USERNAME and settings.SUWAYOMI_PASSWORD:
            token = base64.b64encode(
                f"{settings.SUWAYOMI_USERNAME}:{settings.SUWAYOMI_PASSWORD}".encode()
            ).decode()
            headers["Authorization"] = f"Basic {token}"

    try:
        async with httpx.AsyncClient(verify=False) as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=15)

        if response.status_code != 200:
            log.warning("cover download failed for comic %s: HTTP %s", comic_id, response.status_code)
            return None

        content_type = response.headers.get("content-type", "image/jpeg").split(";")[0].strip()
        ext = mimetypes.guess_extension(content_type) or ".jpg"
        # mimetypes can return .jpe for image/jpeg on some systems
        if ext == ".jpe":
            ext = ".jpg"

        dest = covers_dir / f"{comic_id}{ext}"
        dest.write_bytes(response.content)
        return dest

    except Exception:
        log.exception("cover download error for comic %s url=%s", comic_id, url)
        return None
