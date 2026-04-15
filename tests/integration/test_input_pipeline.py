from __future__ import annotations

from pathlib import Path

import pytest

from build.input_handler import load_input_document
from geometry.section_analysis import ACSAHEGeometricSolution


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
WORKBOOK = FIXTURES_DIR / "excel" / "01_box_girder.xlsm"
PORTABLE_JSON = FIXTURES_DIR / "json" / "01_box_girder.json"


def _float_list(values):
    return [round(float(v), 6) for v in values]


def _assert_geometric_parity(a: ACSAHEGeometricSolution, b: ACSAHEGeometricSolution) -> None:
    assert a.problema["tipo"] == b.problema["tipo"]
    assert sorted(_float_list(a.problema["lista_planos_de_carga"])) == sorted(
        _float_list(b.problema["lista_planos_de_carga"])
    )
    assert len(a.concrete_array) == len(b.concrete_array)
    assert len(a.rebar_array) == len(b.rebar_array)
    assert len(a.prestressed_rebar_array) == len(b.prestressed_rebar_array)

    assert round(float(a.meshed_section.xg), 6) == round(float(b.meshed_section.xg), 6)
    assert round(float(a.meshed_section.yg), 6) == round(float(b.meshed_section.yg), 6)
    assert round(float(a.meshed_section.Ast), 6) == round(float(b.meshed_section.Ast), 6)
    assert round(float(a.meshed_section.Apt), 6) == round(float(b.meshed_section.Apt), 6)

    rebar_a = [(round(x.xg, 6), round(x.yg, 6), round(x.area, 6)) for x in a.rebar_array]
    rebar_b = [(round(x.xg, 6), round(x.yg, 6), round(x.area, 6)) for x in b.rebar_array]
    assert rebar_a == rebar_b

    p_a = [(round(x.xg, 6), round(x.yg, 6), round(x.area, 6)) for x in a.prestressed_rebar_array]
    p_b = [(round(x.xg, 6), round(x.yg, 6), round(x.area, 6)) for x in b.prestressed_rebar_array]
    assert p_a == p_b

@pytest.mark.integration
def test_json_pipeline_stable_for_same_document():
    """
    Two builds from the same portable document must yield identical geometry objects.
    """
    assert WORKBOOK.is_file(), f"Missing workbook: {WORKBOOK}"

    doc = load_input_document(WORKBOOK, read_only=True)
    first = ACSAHEGeometricSolution(doc, workbook_path=str(WORKBOOK))
    second = ACSAHEGeometricSolution(doc, workbook_path=str(WORKBOOK))
    _assert_geometric_parity(first, second)

@pytest.mark.integration
def test_json_file_pipeline_matches_workbook_pipeline():
    """A saved JSON for the same case matches building from the workbook via load_input_document."""
    assert WORKBOOK.is_file(), f"Missing workbook: {WORKBOOK}"
    assert PORTABLE_JSON.is_file(), f"Missing JSON fixture: {PORTABLE_JSON}"

    doc_wb = load_input_document(WORKBOOK, read_only=True)
    doc_json = load_input_document(PORTABLE_JSON, read_only=True)
    from_wb = ACSAHEGeometricSolution(doc_wb, workbook_path=str(WORKBOOK))
    from_json = ACSAHEGeometricSolution(doc_json, workbook_path=str(PORTABLE_JSON))
    _assert_geometric_parity(from_wb, from_json)
