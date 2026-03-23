"""Tests for services/file_relocator.py"""
import os
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


def _make_comic(title="My Comic", library_title="My Comic Library"):
    return SimpleNamespace(title=title, library_title=library_title)


def _make_assignment(
    chapter_number=1.0,
    volume_number=None,
    source_name="TestSource",
    library_path=None,
    chapter_published_at=None,
):
    return SimpleNamespace(
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
    staging_file.write_bytes(b"fake cbz content")

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
    assert dest.read_bytes() == b"fake cbz content"
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
    staging_file.write_bytes(b"fake cbz data cross")

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
    staging_file.write_bytes(b"cbz")

    comic = _make_comic(library_title="DragonBall")
    assignment = _make_assignment(chapter_number=1.0)

    await file_relocator.relocate(
        assignment, comic, None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done
    dest = Path(assignment.library_path)
    assert dest.exists()
    assert dest.parent.exists()


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
    staging_file.write_bytes(b"new better content")

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
    # Library file now contains new content
    assert existing_lib.read_bytes() == b"new better content"
    # Staging removed
    assert not staging_file.exists()


@pytest.mark.asyncio
async def test_relocate_strategy_copy_keeps_staging(tmp_path, monkeypatch):
    """RELOCATION_STRATEGY=copy: dest file created, staging file preserved."""
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
    staging_file.write_bytes(b"content")

    assignment = _make_assignment(chapter_number=1.0)
    await file_relocator.relocate(
        assignment, _make_comic(library_title="TestManga"), None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done
    assert Path(assignment.library_path).exists()
    assert staging_file.exists()  # preserved


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
    staging_file.write_bytes(b"content")

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
    staging_file.write_bytes(b"new content")

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
    assert existing_lib.read_bytes() == b"new content"
    assert staging_file.exists()  # preserved


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
    assert dest.stat().st_size == cbz.stat().st_size
    assert cbz.exists()  # copy strategy — staging preserved

    print(f"Relocated to: {dest}")
