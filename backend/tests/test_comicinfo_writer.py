"""Unit tests for services/comicinfo_writer.py"""
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import comicinfo_writer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_comic(library_title="My Series"):
    return SimpleNamespace(library_title=library_title)


def _make_assignment(chapter_number=1.0, volume_number=None):
    return SimpleNamespace(chapter_number=chapter_number, volume_number=volume_number)


def _parse(folder: Path):
    return ET.parse(folder / "ComicInfo.xml").getroot()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_write_creates_comicinfo_in_empty_folder(tmp_path):
    """Empty folder: write() creates ComicInfo.xml with Series and Number but no Volume."""
    comic = _make_comic(library_title="Attack on Titan")
    assignment = _make_assignment(chapter_number=5.0, volume_number=None)

    comicinfo_writer.write(tmp_path, comic, assignment)

    assert (tmp_path / "ComicInfo.xml").exists()
    root = _parse(tmp_path)
    assert root.findtext("Series") == "Attack on Titan"
    assert root.findtext("Number") == "5.0"
    assert root.find("Volume") is None


def test_write_sets_volume_when_present(tmp_path):
    """volume_number is set: Volume element is present with correct value."""
    comic = _make_comic(library_title="Berserk")
    assignment = _make_assignment(chapter_number=10.0, volume_number=3)

    comicinfo_writer.write(tmp_path, comic, assignment)

    root = _parse(tmp_path)
    assert root.findtext("Volume") == "3"


def test_write_omits_volume_when_none(tmp_path):
    """volume_number is None: no Volume element written."""
    comic = _make_comic(library_title="Naruto")
    assignment = _make_assignment(chapter_number=7.0, volume_number=None)

    comicinfo_writer.write(tmp_path, comic, assignment)

    root = _parse(tmp_path)
    assert root.find("Volume") is None


def test_write_preserves_existing_tags(tmp_path):
    """Existing ComicInfo.xml with extra tags: those tags are preserved after write."""
    existing_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<ComicInfo>"
        "<Publisher>Shueisha</Publisher>"
        "<Series>Old Series</Series>"
        "</ComicInfo>"
    )
    (tmp_path / "ComicInfo.xml").write_text(existing_xml, encoding="utf-8")

    comic = _make_comic(library_title="One Piece")
    assignment = _make_assignment(chapter_number=1.0)

    comicinfo_writer.write(tmp_path, comic, assignment)

    root = _parse(tmp_path)
    assert root.findtext("Publisher") == "Shueisha"
    assert root.findtext("Series") == "One Piece"


def test_write_updates_existing_series(tmp_path):
    """Existing ComicInfo.xml has wrong Series: write() corrects it."""
    existing_xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        "<ComicInfo>"
        "<Series>Wrong Title</Series>"
        "<Number>1.0</Number>"
        "</ComicInfo>"
    )
    (tmp_path / "ComicInfo.xml").write_text(existing_xml, encoding="utf-8")

    comic = _make_comic(library_title="Correct Title")
    assignment = _make_assignment(chapter_number=1.0)

    comicinfo_writer.write(tmp_path, comic, assignment)

    root = _parse(tmp_path)
    assert root.findtext("Series") == "Correct Title"
    # Should be exactly one Series element
    assert len(root.findall("Series")) == 1
