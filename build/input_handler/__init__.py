"""
ACSAHE input layer: everything upstream of section geometry.

Flow (recommended for applications):

1. ``load_input_document(path)`` — loads ``.json`` or converts ``.xlsm`` / ``.xlsx`` to the
   same portable dict (Excel is opened only inside this step).
2. ``ACSAHEGeometricSolution(document, workbook_path=...)`` — consumes that dict only;
   geometry code does not open Excel for reading.

Lower-level pieces:

- ``excel_workbook_to_input_dict`` / ``AcsaheInputJsonBuilder`` — workbook → dict.
- ``ExcelSectionInputReader`` — direct cell access when building the dict or writing results.
- ``JsonSectionInputReader`` — dict → same method surface as the Excel reader (used by geometry).
"""

from build.input_handler.excel_section_input_reader import (
    ExcelSectionInputReader,
    discretization_level_to_identifier,
    excel_workbook_to_input_dict,
)
from build.input_handler.input_loader import load_input_document
from build.input_handler.input_json_builder import AcsaheInputJsonBuilder
from build.input_handler.json_section_input_reader import JsonSectionInputReader


class AcsaheExcelInputHandler:
    """
    Excel workbook → portable input document (JSON-serializable dict).
    Prefer :func:`load_input_document` unless you only handle Excel.
    """

    def __init__(self, workbook_path: str):
        self.workbook_path = workbook_path

    def to_input_dict(self, *, read_only: bool = True, source_display_name: str | None = None) -> dict:
        return excel_workbook_to_input_dict(
            self.workbook_path,
            read_only=read_only,
            source_display_name=source_display_name,
        )


__all__ = [
    "AcsaheExcelInputHandler",
    "AcsaheInputJsonBuilder",
    "ExcelSectionInputReader",
    "JsonSectionInputReader",
    "discretization_level_to_identifier",
    "excel_workbook_to_input_dict",
    "load_input_document",
]
