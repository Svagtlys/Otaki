"""Write or update ComicInfo.xml inside a chapter folder before it is packed to CBZ."""
import xml.etree.ElementTree as ET
from pathlib import Path

from ..models.chapter_assignment import ChapterAssignment
from ..models.comic import Comic

_COMICINFO_FILENAME = "ComicInfo.xml"


def write(folder: Path, comic: Comic, assignment: ChapterAssignment) -> None:
    """Write (or update) ``ComicInfo.xml`` in *folder*.

    If a ``ComicInfo.xml`` is already present it is parsed and its existing
    tags are preserved; otherwise a new ``<ComicInfo/>`` element is created.

    Always sets:
      - ``<Series>`` → ``comic.library_title``
      - ``<Number>`` → ``str(assignment.chapter_number)``

    Sets ``<Volume>`` only when ``assignment.volume_number`` is not ``None``.
    If ``<Volume>`` was previously present and volume_number is now ``None``,
    the element is removed.

    The updated document is written back to ``folder / "ComicInfo.xml"``.
    """
    xml_path = folder / _COMICINFO_FILENAME

    if xml_path.exists():
        tree = ET.parse(xml_path)
        root = tree.getroot()
    else:
        root = ET.Element("ComicInfo")
        tree = ET.ElementTree(root)

    # --- Series ---
    series_el = root.find("Series")
    if series_el is None:
        series_el = ET.SubElement(root, "Series")
    series_el.text = comic.library_title

    # --- Number ---
    number_el = root.find("Number")
    if number_el is None:
        number_el = ET.SubElement(root, "Number")
    number_el.text = str(assignment.chapter_number)

    # --- Volume ---
    volume_el = root.find("Volume")
    if assignment.volume_number is not None:
        if volume_el is None:
            volume_el = ET.SubElement(root, "Volume")
        volume_el.text = str(assignment.volume_number)
    else:
        # Remove the element if it was previously present
        if volume_el is not None:
            root.remove(volume_el)

    tree.write(xml_path, encoding="utf-8", xml_declaration=True)
