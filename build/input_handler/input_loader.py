from __future__ import annotations

"""
Single entry to obtain the **portable input document** (``dict``) consumed by
:class:`geometry.section_analysis.ACSAHEGeometricSolution`.

- **JSON file** → parse only (no Excel).
- **Workbook** → open once, run ``excel_workbook_to_input_dict``, close workbook.

Downstream code should depend on this dict, not on Excel.
"""

import json
from pathlib import Path
from typing import Any, Dict

from build.input_handler.excel_section_input_reader import excel_workbook_to_input_dict


def load_input_document(path: str | Path, *, read_only: bool = True) -> Dict[str, Any]:
    """
    Return the portable input document for the given file.

    ``read_only`` applies when opening a workbook (ignored for ``.json``).
    """
    source_path = Path(path)
    suffix = source_path.suffix.lower()
    if suffix == ".json":
        with source_path.open(encoding="utf-8") as f:
            return json.load(f)
    if suffix in (".xlsm", ".xlsx", ".xls"):
        return excel_workbook_to_input_dict(source_path, read_only=read_only, source_display_name="input")
    raise ValueError(f"Unsupported input format: {source_path}")
