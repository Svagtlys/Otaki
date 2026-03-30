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


def _make_comic(title="My Comic", library_title="My Comic Library"):
    return SimpleNamespace(title=title, library_title=library_title)


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
    _make_cbz(staging_file)

    assignment = _make_assignment(chapter_number=1.0)
    await file_relocator.relocate(
        assignment, _make_comic(library_title="TestManga"), None, chapter_name, manga_title, source_display
    )

    assert assignment.relocation_status == RelocationStatus.done
    assert Path(assignment.library_path).exists()
    # copy strategy preserves the repacked staging CBZ
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
    assert dest.stat().st_size == cbz.stat().st_size
    assert cbz.exists()  # copy strategy — staging preserved

    print(f"Relocated to: {dest}")


# ---------------------------------------------------------------------------
# _find_staging_path — folder detection
# ---------------------------------------------------------------------------


def test_find_staging_path_returns_folder(tmp_path, monkeypatch):
    """Chapter staging area is a folder (not a CBZ): _find_staging_path returns it."""
    downloads = tmp_path / "downloads"
    source_display = "MangaSource"
    manga_title = "OnePiece"
    chapter_name = "Chapter 001"

    chapter_folder = downloads / source_display / manga_title / chapter_name
    chapter_folder.mkdir(parents=True)
    (chapter_folder / "001.jpg").write_bytes(b"page1")
    (chapter_folder / "002.jpg").write_bytes(b"page2")

    monkeypatch.setattr(settings, "SUWAYOMI_DOWNLOAD_PATH", str(downloads))

    result = file_relocator._find_staging_path(chapter_name, manga_title, source_display)

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
