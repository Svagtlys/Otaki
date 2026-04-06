"""Tests for services/file_relocator.py"""
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.config import settings
from app.models.chapter_assignment import RelocationStatus
from app.services import file_relocator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_comic(title="My Comic", library_title="My Comic Library", cover_path=None):
    return SimpleNamespace(title=title, library_title=library_title, cover_path=cover_path)


def _make_cbz(path: Path, files: dict[str, bytes] | None = None) -> None:
    """Write a minimal valid CBZ (ZIP) file at *path*.

    *files* maps archive entry name → bytes content.
    Defaults to a single page ``001.jpg``.
    """
    if files is None:
        files = {"001.jpg": b"page"}
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)


def _make_assignment(
    chapter_number=1.0,
    volume_number=None,
    source_name="TestSource",
    library_path=None,
    chapter_published_at=None,
):
    return SimpleNamespace(
        id=1,
        chapter_number=chapter_number,
        volume_number=volume_number,
        library_path=library_path,
        relocation_status=RelocationStatus.pending,
        chapter_published_at=chapter_published_at or datetime(2024, 6, 15, tzinfo=timezone.utc),
        source=SimpleNamespace(name=source_name),
    )


# ---------------------------------------------------------------------------
# resolve_path tests
# ---------------------------------------------------------------------------


def test_resolve_path_basic(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(tmp_path / "library"))
    monkeypatch.setattr(
        settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz"
    )

    comic = _make_comic(library_title="Attack on Titan")
    assignment = _make_assignment(chapter_number=12.0)

    result = file_relocator.resolve_path(assignment, comic)

    assert result == tmp_path / "library" / "Attack on Titan" / "Attack on Titan - Ch.0012.0.cbz"


def test_resolve_path_with_volume(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(tmp_path / "library"))
    monkeypatch.setattr(
        settings,
        "CHAPTER_NAMING_FORMAT",
        "{title}/Vol.{volume}/{title} - Ch.{chapter}.cbz",
    )

    comic = _make_comic(library_title="Berserk")
    assignment = _make_assignment(chapter_number=5.0, volume_number=3)

    result = file_relocator.resolve_path(assignment, comic)

    assert result == tmp_path / "library" / "Berserk" / "Vol.03" / "Berserk - Ch.0005.0.cbz"


def test_resolve_path_volume_omitted_gracefully(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(tmp_path / "library"))
    monkeypatch.setattr(
        settings,
        "CHAPTER_NAMING_FORMAT",
        "{title}/Vol.{volume}/{title} - Ch.{chapter}.cbz",
    )

    comic = _make_comic(library_title="Naruto")
    assignment = _make_assignment(chapter_number=7.0, volume_number=None)

    # Should not raise, and should not have a stray {volume} in the output
    result = file_relocator.resolve_path(assignment, comic)

    assert "{volume}" not in str(result)
    assert "Naruto" in str(result)
    assert "0007.0" in str(result)


def test_resolve_path_uses_library_title(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(tmp_path / "library"))
    monkeypatch.setattr(
        settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz"
    )

    comic = _make_comic(title="Display Title", library_title="Canonical Library Title")
    assignment = _make_assignment(chapter_number=1.0)

    result = file_relocator.resolve_path(assignment, comic)

    assert "Canonical Library Title" in str(result)
    assert "Display Title" not in str(result)


# ---------------------------------------------------------------------------
# relocate tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relocate_hardlink(tmp_path, monkeypatch):
    """auto strategy on same filesystem: os.link is called and staging is removed."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz")

    source_display = "MangaSource"
    manga_title = "OnePiece"
    chapter_name = "Chapter 001"

    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    comic = _make_comic(library_title="OnePiece")
    assignment = _make_assignment(chapter_number=1.0)

    with patch("app.services.file_relocator.os.link", wraps=os.link) as mock_link:
        await file_relocator.relocate(
            assignment, comic, None, chapter_name, manga_title, source_display
        )
        assert mock_link.called  # hardlink path taken

    assert assignment.relocation_status == RelocationStatus.done
    dest = Path(assignment.library_path)
    assert dest.exists()
    assert zipfile.is_zipfile(dest)
    assert not staging_file.exists()  # auto strategy removes staging


@pytest.mark.asyncio
async def test_relocate_cross_filesystem(tmp_path, monkeypatch):
    """Different filesystem: verify copy+delete path; staging file removed."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(
        settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz"
    )

    source_display = "MangaSource"
    manga_title = "Bleach"
    chapter_name = "Chapter 001"

    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    comic = _make_comic(library_title="Bleach")
    assignment = _make_assignment(chapter_number=1.0)

    # Simulate cross-filesystem by making os.link raise OSError
    with patch("app.services.file_relocator.os.link", side_effect=OSError("cross-device link not permitted")):
        await file_relocator.relocate(
            assignment, comic, None, chapter_name, manga_title, source_display
        )

    assert assignment.relocation_status == RelocationStatus.done
    dest = Path(assignment.library_path)
    assert dest.exists()
    # Staging must be removed in cross-filesystem path
    assert not staging_file.exists()


@pytest.mark.asyncio
async def test_relocate_staging_not_found(tmp_path, monkeypatch):
    """No file in staging dir: verify relocation_status=failed, no crash."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(
        settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz"
    )

    comic = _make_comic(library_title="Fairy Tail")
    assignment = _make_assignment(chapter_number=3.0)

    # No staging file created
    await file_relocator.relocate(
        assignment, comic, None, "Chapter 003", "FairyTail", "SomeSource"
    )

    assert assignment.relocation_status == RelocationStatus.failed
    assert assignment.library_path is None


@pytest.mark.asyncio
async def test_relocate_creates_parent_dirs(tmp_path, monkeypatch):
    """Destination parent dir does not exist yet: verify it is created."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(
        settings,
        "CHAPTER_NAMING_FORMAT",
        "{title}/nested/deep/{title} - Ch.{chapter}.cbz",
    )

    source_display = "SrcA"
    manga_title = "DragonBall"
    chapter_name = "Chapter 001"

    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    comic = _make_comic(library_title="DragonBall")
    assignment = _make_assignment(chapter_number=1.0)

    await file_relocator.relocate(
        assignment, comic, None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done
    dest = Path(assignment.library_path)
    assert dest.exists()
    assert dest.parent.exists()


@pytest.mark.asyncio
async def test_relocate_with_folder_staging(tmp_path, monkeypatch):
    """Staging area is a folder (not a CBZ): relocate() packs it, injects ComicInfo.xml, and places it."""
    import xml.etree.ElementTree as ET

    downloads = tmp_path / "downloads"
    library = tmp_path / "library"

    source_display = "Source"
    manga_title = "My Manga"
    chapter_name = "Chapter 1"

    chapter_folder = downloads / source_display / manga_title / chapter_name
    chapter_folder.mkdir(parents=True)
    (chapter_folder / "001.jpg").write_bytes(b"\xff\xd8\xff" + b"x" * 100)
    (chapter_folder / "002.jpg").write_bytes(b"\xff\xd8\xff" + b"y" * 100)

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{chapter}")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    comic = _make_comic(library_title="My Manga")
    assignment = _make_assignment(chapter_number=1.0, volume_number=None)

    await file_relocator.relocate(
        assignment, comic, None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done

    dest = Path(assignment.library_path)
    assert dest.exists()
    assert zipfile.is_zipfile(dest)

    with zipfile.ZipFile(dest, "r") as zf:
        names = zf.namelist()
        assert "ComicInfo.xml" in names
        assert "001.jpg" in names
        assert "002.jpg" in names

        xml_bytes = zf.read("ComicInfo.xml")

    root = ET.fromstring(xml_bytes)
    assert root.findtext("Series") == "My Manga"
    assert root.findtext("Number") == "1.0"


# ---------------------------------------------------------------------------
# replace_in_library tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_in_library_atomic(tmp_path, monkeypatch):
    """Existing library file is replaced atomically; staging removed."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))

    source_display = "BetterSource"
    manga_title = "HxH"
    chapter_name = "Chapter 001"

    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    # Existing library file
    existing_lib = library / "HxH" / "HxH - Ch.0001.0.cbz"
    existing_lib.parent.mkdir(parents=True)
    existing_lib.write_bytes(b"old content")

    comic = _make_comic(library_title="HxH")
    old_assignment = _make_assignment(
        chapter_number=1.0, library_path=str(existing_lib)
    )
    old_assignment.relocation_status = RelocationStatus.done
    new_assignment = _make_assignment(chapter_number=1.0)

    await file_relocator.replace_in_library(
        old_assignment, new_assignment, comic, None, chapter_name, manga_title, source_display
    )

    assert new_assignment.relocation_status == RelocationStatus.done
    assert old_assignment.relocation_status == RelocationStatus.skipped
    assert new_assignment.library_path == str(existing_lib)
    # Library file now contains a valid CBZ (repacked after ComicInfo.xml injection)
    assert zipfile.is_zipfile(existing_lib)
    # Staging removed
    assert not staging_file.exists()


@pytest.mark.asyncio
async def test_relocate_strategy_copy_keeps_staging(tmp_path, monkeypatch):
    """RELOCATION_STRATEGY=copy: destination CBZ is a valid zip and a repacked staging CBZ remains."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    source_display = "Src"
    manga_title = "TestManga"
    chapter_name = "Chapter 001"
    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    assignment = _make_assignment(chapter_number=1.0)
    await file_relocator.relocate(
        assignment, _make_comic(library_title="TestManga"), None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done
    dest_cbz = Path(assignment.library_path)
    assert dest_cbz.exists()
    assert zipfile.is_zipfile(dest_cbz)
    # copy strategy: a repacked staging CBZ remains alongside the destination
    assert (source_dir / f"{chapter_name}.cbz").exists()


@pytest.mark.asyncio
async def test_relocate_strategy_move_deletes_staging(tmp_path, monkeypatch):
    """RELOCATION_STRATEGY=move: dest file created, staging file removed."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "move")

    source_display = "Src"
    manga_title = "TestManga"
    chapter_name = "Chapter 001"
    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    assignment = _make_assignment(chapter_number=1.0)
    await file_relocator.relocate(
        assignment, _make_comic(library_title="TestManga"), None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done
    assert Path(assignment.library_path).exists()
    assert not staging_file.exists()  # removed


@pytest.mark.asyncio
async def test_replace_in_library_copy_strategy_keeps_staging(tmp_path, monkeypatch):
    """RELOCATION_STRATEGY=copy: library replaced, staging preserved."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    source_display = "Src"
    manga_title = "TestManga"
    chapter_name = "Chapter 001"
    source_dir = downloads / source_display / manga_title
    source_dir.mkdir(parents=True)
    staging_file = source_dir / f"{chapter_name}.cbz"
    _make_cbz(staging_file)

    existing_lib = library / "TestManga" / "TestManga - Ch.0001.0.cbz"
    existing_lib.parent.mkdir(parents=True)
    existing_lib.write_bytes(b"old content")

    old_assignment = _make_assignment(chapter_number=1.0, library_path=str(existing_lib))
    old_assignment.relocation_status = RelocationStatus.done
    new_assignment = _make_assignment(chapter_number=1.0)

    await file_relocator.replace_in_library(
        old_assignment, new_assignment, _make_comic(), None, chapter_name, manga_title, source_display
    )

    assert new_assignment.relocation_status == RelocationStatus.done
    # Library file is now a valid repacked CBZ
    assert zipfile.is_zipfile(existing_lib)
    # copy strategy preserves the repacked staging CBZ
    assert (source_dir / f"{chapter_name}.cbz").exists()


@pytest.mark.asyncio
async def test_replace_in_library_staging_not_found(tmp_path, monkeypatch):
    """Missing new staging file: new.relocation_status=failed, old untouched."""
    downloads = tmp_path / "downloads"
    library = tmp_path / "library"
    downloads.mkdir()
    library.mkdir()

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))

    existing_lib = library / "SomeComic" / "SomeComic - Ch.0001.0.cbz"
    existing_lib.parent.mkdir(parents=True)
    existing_lib.write_bytes(b"original")

    comic = _make_comic(library_title="SomeComic")
    old_assignment = _make_assignment(
        chapter_number=1.0, library_path=str(existing_lib)
    )
    old_assignment.relocation_status = RelocationStatus.done
    new_assignment = _make_assignment(chapter_number=1.0)

    await file_relocator.replace_in_library(
        old_assignment, new_assignment, comic, None, "Chapter 001", "SomeComic", "NoSource"
    )

    assert new_assignment.relocation_status == RelocationStatus.failed
    # Old assignment untouched
    assert old_assignment.relocation_status == RelocationStatus.done
    # Library file not corrupted
    assert existing_lib.read_bytes() == b"original"


# ---------------------------------------------------------------------------
# Integration test — requires SUWAYOMI_DOWNLOAD_PATH set in .env.test
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.asyncio
async def test_relocate_real_staging_file(path_config, monkeypatch):
    """Find an existing CBZ in SUWAYOMI_DOWNLOAD_PATH and relocate it to LIBRARY_PATH.

    Suwayomi's download folder structure: {source}/{manga}/{chapter}.cbz
    This test locates the first CBZ it finds, derives the path components,
    and runs the full relocate() pipeline against real files.

    Skipped if SUWAYOMI_DOWNLOAD_PATH is not configured in .env.test or if
    no downloaded chapters are found.
    """
    download_path = Path(path_config["download_path"])
    library_path = Path(path_config["library_path"])

    cbz_files = list(download_path.rglob("*.cbz"))
    if not cbz_files:
        pytest.skip("No downloaded CBZ files found in SUWAYOMI_DOWNLOAD_PATH")

    # Derive path components from Suwayomi's folder structure:
    # {download_path}/{source_display_name}/{manga_title}/{chapter_name}.cbz
    cbz = cbz_files[0]
    chapter_name = cbz.stem
    manga_title = cbz.parent.name
    source_display_name = cbz.parent.parent.name

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(download_path))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library_path))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{title} - Ch.{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")  # preserve staging

    comic = _make_comic(library_title=manga_title)
    assignment = _make_assignment(chapter_number=1.0, source_name=source_display_name)

    print(f"\nRelocating: {source_display_name}/{manga_title}/{chapter_name}.cbz")

    await file_relocator.relocate(
        assignment, comic, None, chapter_name, manga_title, source_display_name
    )

    assert assignment.relocation_status == RelocationStatus.done
    dest = Path(assignment.library_path)
    assert dest.exists(), f"Expected file at {dest}"
    assert dest.stat().st_size > 0
    import zipfile as _zf
    assert _zf.is_zipfile(dest)
    assert cbz.exists()  # copy strategy — staging preserved

    print(f"Relocated to: {dest}")


# ---------------------------------------------------------------------------
# _find_staging_path — folder detection
# ---------------------------------------------------------------------------


def test_find_staging_path_returns_folder(tmp_path, monkeypatch):
    """Chapter staging area is a folder (not a CBZ): find_staging_path returns it."""
    downloads = tmp_path / "downloads"
    source_display = "MangaSource"
    manga_title = "OnePiece"
    chapter_name = "Chapter 001"

    chapter_folder = downloads / source_display / manga_title / chapter_name
    chapter_folder.mkdir(parents=True)
    (chapter_folder / "001.jpg").write_bytes(b"page1")
    (chapter_folder / "002.jpg").write_bytes(b"page2")

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    result = file_relocator.find_staging_path(chapter_name, manga_title, source_display)

    assert result == chapter_folder
    assert result.is_dir()


# ---------------------------------------------------------------------------
# _normalize_to_folder
# ---------------------------------------------------------------------------


def test_normalize_to_folder_noop_for_folder(tmp_path):
    """A directory is returned as-is; nothing is deleted or created."""
    folder = tmp_path / "chapter_folder"
    folder.mkdir()
    (folder / "001.jpg").write_bytes(b"page")

    result = file_relocator._normalize_to_folder(folder)

    assert result == folder
    assert result.is_dir()
    assert (result / "001.jpg").exists()


def test_normalize_to_folder_extracts_cbz(tmp_path):
    """A CBZ file is extracted to a sibling folder; the original CBZ is deleted."""
    cbz_path = tmp_path / "Chapter 001.cbz"
    with zipfile.ZipFile(cbz_path, "w") as zf:
        zf.writestr("001.jpg", b"page1")
        zf.writestr("002.jpg", b"page2")

    result = file_relocator._normalize_to_folder(cbz_path)

    assert result.is_dir()
    assert result == tmp_path / "Chapter 001"
    assert not cbz_path.exists()
    assert (result / "001.jpg").exists()
    assert (result / "002.jpg").exists()


# ---------------------------------------------------------------------------
# _pack_to_cbz
# ---------------------------------------------------------------------------


def test_pack_to_cbz_zips_and_deletes_folder(tmp_path):
    """Folder is packed to a CBZ at the correct path; source folder is deleted."""
    folder = tmp_path / "Chapter 001"
    folder.mkdir()
    (folder / "001.jpg").write_bytes(b"page1")
    (folder / "002.jpg").write_bytes(b"page2")

    cbz_path = file_relocator._pack_to_cbz(folder)

    assert cbz_path == tmp_path / "Chapter 001.cbz"
    assert cbz_path.exists()
    assert not folder.exists()

    with zipfile.ZipFile(cbz_path, "r") as zf:
        names = zf.namelist()
    assert "001.jpg" in names
    assert "002.jpg" in names


def test_pack_to_cbz_preserves_sort_order(tmp_path):
    """Pages are sorted alphabetically so zero-padded names produce correct page order."""
    folder = tmp_path / "Chapter 010"
    folder.mkdir()
    # Create in non-sorted order
    for name in ("010.jpg", "001.jpg", "002.jpg"):
        (folder / name).write_bytes(b"data")

    cbz_path = file_relocator._pack_to_cbz(folder)

    with zipfile.ZipFile(cbz_path, "r") as zf:
        names = zf.namelist()

    assert names == ["001.jpg", "002.jpg", "010.jpg"]


def test_pack_to_cbz_cover_sorts_first(tmp_path):
    """cover.* is always the first entry in the packed CBZ."""
    folder = tmp_path / "Chapter 001"
    folder.mkdir()
    for name in ("002.jpg", "001.jpg", "cover.jpg"):
        (folder / name).write_bytes(b"data")

    cbz_path = file_relocator._pack_to_cbz(folder)

    with zipfile.ZipFile(cbz_path, "r") as zf:
        names = zf.namelist()

    assert names[0] == "cover.jpg"
    assert set(names) == {"cover.jpg", "001.jpg", "002.jpg"}


async def test_relocate_injects_cover(tmp_path, monkeypatch):
    """relocate() copies comic.cover_path into the staging folder as cover.{ext}."""
    source_display = "TestSource"
    manga_title = "My Manga"
    chapter_name = "Chapter 1"

    # Staging folder with two pages
    staging_dir = tmp_path / "downloads" / source_display / manga_title / chapter_name
    staging_dir.mkdir(parents=True)
    (staging_dir / "001.jpg").write_bytes(b"page1")
    (staging_dir / "002.jpg").write_bytes(b"page2")

    # Cover file
    cover_file = tmp_path / "covers" / "1.jpg"
    cover_file.parent.mkdir(parents=True)
    cover_file.write_bytes(b"cover-data")

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(tmp_path / "downloads"))
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(tmp_path / "library"))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{chapter}")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    comic = _make_comic(library_title=manga_title, cover_path=str(cover_file))
    assignment = _make_assignment(chapter_number=1.0, source_name=source_display)

    await file_relocator.relocate(
        assignment, comic, None,
        chapter_name=chapter_name, manga_title=manga_title, source_display_name=source_display,
    )

    assert assignment.relocation_status == RelocationStatus.done
    dest = Path(assignment.library_path)
    assert zipfile.is_zipfile(dest)

    with zipfile.ZipFile(dest, "r") as zf:
        names = zf.namelist()

    assert "cover.jpg" in names
    assert names[0] == "cover.jpg"


# ---------------------------------------------------------------------------
# update_library_file tests
# ---------------------------------------------------------------------------


async def test_update_library_file_updates_comicinfo_in_place(tmp_path, monkeypatch):
    """update_library_file rewrites ComicInfo.xml when library_title has not changed."""
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    # Place a CBZ at the exact path resolve_path would compute
    dest = library / "My Comic" / "0001.0.cbz"
    dest.parent.mkdir(parents=True)
    _make_cbz(dest, {"001.jpg": b"page"})

    assignment = _make_assignment(chapter_number=1.0, library_path=str(dest))
    assignment.relocation_status = RelocationStatus.done
    comic = _make_comic(library_title="My Comic")

    await file_relocator.update_library_file(assignment, comic, None)

    # File still exists at original path (no rename needed)
    assert Path(assignment.library_path).exists()
    with zipfile.ZipFile(assignment.library_path) as zf:
        assert "ComicInfo.xml" in zf.namelist()


async def test_update_library_file_moves_on_library_title_change(tmp_path, monkeypatch):
    """update_library_file moves the CBZ when library_title has changed."""
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    # Old path used the previous library title — matches what resolve_path("Old Title") would give
    old_cbz = library / "Old Title" / "0001.0.cbz"
    old_cbz.parent.mkdir(parents=True)
    _make_cbz(old_cbz, {"001.jpg": b"page"})

    assignment = _make_assignment(chapter_number=1.0, library_path=str(old_cbz))
    assignment.relocation_status = RelocationStatus.done
    comic = _make_comic(library_title="New Title")  # title changed

    await file_relocator.update_library_file(assignment, comic, None)

    expected_new = library / "New Title" / "0001.0.cbz"
    assert expected_new.exists()
    assert not old_cbz.exists()
    assert assignment.library_path == str(expected_new)


async def test_update_library_file_noop_missing_path(tmp_path, monkeypatch):
    """update_library_file does nothing when library_path is None."""
    assignment = _make_assignment(library_path=None)
    assignment.relocation_status = RelocationStatus.done
    comic = _make_comic()
    # Should not raise
    await file_relocator.update_library_file(assignment, comic, None)


async def test_update_library_file_noop_missing_file(tmp_path, monkeypatch):
    """update_library_file does nothing when the library file doesn't exist."""
    assignment = _make_assignment(library_path=str(tmp_path / "nonexistent.cbz"))
    assignment.relocation_status = RelocationStatus.done
    comic = _make_comic()
    # Should not raise
    await file_relocator.update_library_file(assignment, comic, None)


async def test_update_library_file_injects_cover(tmp_path, monkeypatch):
    """update_library_file injects the comic cover into the repacked CBZ."""
    library = tmp_path / "library"
    library.mkdir()
    monkeypatch.setattr(settings, "LIBRARY_PATH", str(library))
    monkeypatch.setattr(settings, "CHAPTER_NAMING_FORMAT", "{title}/{chapter}.cbz")
    monkeypatch.setattr(settings, "RELOCATION_STRATEGY", "copy")

    dest = library / "My Comic" / "0001.0.cbz"
    dest.parent.mkdir(parents=True)
    _make_cbz(dest, {"001.jpg": b"page"})

    cover_file = tmp_path / "covers" / "1.jpg"
    cover_file.parent.mkdir()
    cover_file.write_bytes(b"cover-data")

    assignment = _make_assignment(chapter_number=1.0, library_path=str(dest))
    assignment.relocation_status = RelocationStatus.done
    comic = _make_comic(library_title="My Comic", cover_path=str(cover_file))

    await file_relocator.update_library_file(assignment, comic, None)

    with zipfile.ZipFile(assignment.library_path) as zf:
        assert "cover.jpg" in zf.namelist()


# ---------------------------------------------------------------------------
# find_staging_path fuzzy source directory fallback tests
# ---------------------------------------------------------------------------


def test_find_staging_path_source_dir_space_stripped(tmp_path, monkeypatch):
    """displayName 'Weeb Central' but on-disk dir is 'WeebCentral' (no space).
    find_staging_path should find the CBZ via the fuzzy fallback."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Dungeon Odyssey"
    chapter_name = "Episode 141"
    # Suwayomi created a directory without the space
    source_dir = downloads / "WeebCentral" / manga_title
    source_dir.mkdir(parents=True)
    cbz = source_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(chapter_name, manga_title, "Weeb Central")
    assert result == cbz


def test_find_staging_path_source_dir_with_suffix(tmp_path, monkeypatch):
    """displayName 'Weeb Central' but on-disk dir is 'Weeb Central (EN)'.
    find_staging_path should find the CBZ via the fuzzy fallback."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Dungeon Odyssey"
    chapter_name = "Episode 141"
    source_dir = downloads / "Weeb Central (EN)" / manga_title
    source_dir.mkdir(parents=True)
    cbz = source_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(chapter_name, manga_title, "Weeb Central")
    assert result == cbz


def test_find_staging_path_source_dir_case_mismatch(tmp_path, monkeypatch):
    """Case-only difference: displayName 'weebcentral', on-disk 'WeebCentral'."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Some Manga"
    chapter_name = "Chapter 1"
    source_dir = downloads / "WeebCentral" / manga_title
    source_dir.mkdir(parents=True)
    cbz = source_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(chapter_name, manga_title, "weebcentral")
    assert result == cbz


def test_find_staging_path_source_dir_ambiguous_returns_none(tmp_path, monkeypatch):
    """Two source directories both fuzzy-match the display name with no exact match —
    should return None to avoid relocating to the wrong source."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Some Manga"
    chapter_name = "Chapter 1"
    # Neither directory is an exact match for "Weeb Central";
    # both fuzzy-match (normalized "weebcentral" is a prefix of both)
    for dirname in ("Weeb Central (EN)", "Weeb Central (JP)"):
        d = downloads / dirname / manga_title
        d.mkdir(parents=True)
        _make_cbz(d / f"{chapter_name}.cbz")

    result = file_relocator.find_staging_path(chapter_name, manga_title, "Weeb Central")
    assert result is None


def test_find_staging_path_exact_match_skips_fallback(tmp_path, monkeypatch):
    """When the exact directory exists, the fuzzy fallback is not needed and
    the correct CBZ is returned directly."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "ExactManga"
    chapter_name = "Ch 1"
    source_dir = downloads / "ExactSource" / manga_title
    source_dir.mkdir(parents=True)
    cbz = source_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    # Also create a fuzzy-match directory to confirm it is NOT picked over the exact one
    fuzzy_dir = downloads / "ExactSource (EN)" / manga_title
    fuzzy_dir.mkdir(parents=True)
    _make_cbz(fuzzy_dir / f"{chapter_name}.cbz")

    result = file_relocator.find_staging_path(chapter_name, manga_title, "ExactSource")
    assert result == cbz


# ---------------------------------------------------------------------------
# Sanitized manga title matching tests
# ---------------------------------------------------------------------------


def test_find_staging_path_sanitized_colon_in_title(tmp_path, monkeypatch):
    """Suwayomi replaces ':' with '_' on disk; find_staging_path should still find the CBZ."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Re:Zero"
    chapter_name = "Ch 1"
    # On disk the colon is replaced with an underscore
    sanitized_dir = downloads / "SomeSource" / "Re_Zero"
    sanitized_dir.mkdir(parents=True)
    cbz = sanitized_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(chapter_name, manga_title, "SomeSource")
    assert result == cbz


def test_find_staging_path_sanitized_multiple_special_chars(tmp_path, monkeypatch):
    """Multiple special chars in title each map to a single on-disk substitution."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "A: B? C!"
    chapter_name = "Ch 1"
    sanitized_dir = downloads / "SomeSource" / "A_ B_ C_"
    sanitized_dir.mkdir(parents=True)
    cbz = sanitized_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(chapter_name, manga_title, "SomeSource")
    assert result == cbz


def test_find_staging_path_sanitized_ambiguous(tmp_path, monkeypatch):
    """Two directories both match the title regex — should return None."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Re:Zero"
    chapter_name = "Ch 1"
    # Both 'Re_Zero' and 'Re-Zero' match 'Re:Zero'
    for on_disk in ("Re_Zero", "Re-Zero"):
        d = downloads / "SomeSource" / on_disk
        d.mkdir(parents=True)
        _make_cbz(d / f"{chapter_name}.cbz")

    result = file_relocator.find_staging_path(chapter_name, manga_title, "SomeSource")
    assert result is None


def test_find_staging_path_sanitized_in_fuzzy_source_dir(tmp_path, monkeypatch):
    """Source dir is fuzzy-matched AND manga subdir is sanitized — both layers work."""
    downloads = tmp_path / "downloads"
    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    manga_title = "Re:Zero"
    chapter_name = "Ch 1"
    # Source dir is 'WeebCentral' (display name 'Weeb Central'), manga subdir sanitized
    sanitized_dir = downloads / "WeebCentral" / "Re_Zero"
    sanitized_dir.mkdir(parents=True)
    cbz = sanitized_dir / f"{chapter_name}.cbz"
    _make_cbz(cbz)

    result = file_relocator.find_staging_path(chapter_name, manga_title, "Weeb Central")
    assert result == cbz
