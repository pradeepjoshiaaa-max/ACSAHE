"""

Excel → portable input JSON (xlwings / Excel only).



The pipeline under test is ``excel_workbook_to_input_dict``: ``ExcelManager`` opens the

workbook with xlwings; ``ExcelSectionInputReader`` reads sheets, ``AcsaheInputJsonBuilder``

builds the dict. There is no openpyxl path in these tests.

"""



from __future__ import annotations



import json

from pathlib import Path

from typing import Any, List



import pytest



from build.input_handler import excel_workbook_to_input_dict



REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
INPUT_DIR = FIXTURES_DIR / "excel"
OUTPUT_DIR = FIXTURES_DIR / "json"



# (workbook stem, description for failure messages)

_EXCEL_JSON_FIXTURES = (

    ("01_box_girder", "catalog steels; materials are tag-keyed type/model/name/properties"),

    ("03_box_girder_custom_steels", "Provisto por usuario; rebar_steel and p_rebar use name user_custom"),

)





def _assert_close_json(a: Any, b: Any, *, float_tol: float, path: List[Any]) -> None:

    if isinstance(a, dict) and isinstance(b, dict):

        assert set(a.keys()) == set(b.keys()), f"Key mismatch at {path}: {set(a.keys())!r} vs {set(b.keys())!r}"

        for k in sorted(a.keys(), key=str):

            _assert_close_json(a[k], b[k], float_tol=float_tol, path=path + [k])

    elif isinstance(a, list) and isinstance(b, list):

        assert len(a) == len(b), f"Length mismatch at {path}: {len(a)} vs {len(b)}"

        for i, (x, y) in enumerate(zip(a, b)):

            _assert_close_json(x, y, float_tol=float_tol, path=path + [i])

    elif isinstance(a, bool) or isinstance(b, bool):

        assert a is b, f"Bool mismatch at {path}: {a!r} vs {b!r}"

    elif isinstance(a, (int, float)) and isinstance(b, (int, float)):

        assert abs(float(a) - float(b)) <= float_tol, f"Numeric mismatch at {path}: {a!r} vs {b!r}"

    else:

        assert a == b, f"Value mismatch at {path}: {a!r} vs {b!r}"





@pytest.mark.integration

@pytest.mark.parametrize("stem,note", _EXCEL_JSON_FIXTURES, ids=[s for s, _ in _EXCEL_JSON_FIXTURES])

def test_excel_workbook_translates_to_reference_json(stem: str, note: str) -> None:

    """

    Golden files under ``tests/fixtures/json``: export must match byte-for-byte structure

    (numeric tolerance for floating-point geometry and sheet values).

    """

    workbook = INPUT_DIR / f"{stem}.xlsm"

    reference = OUTPUT_DIR / f"{stem}.json"

    assert workbook.is_file(), f"Missing workbook: {workbook}"

    assert reference.is_file(), f"Missing reference JSON: {reference} ({note})"



    actual = excel_workbook_to_input_dict(

        workbook,

        read_only=True,

        source_display_name="input",

    )

    with reference.open(encoding="utf-8") as f:

        expected = json.load(f)



    _assert_close_json(actual, expected, float_tol=0.02, path=[])


