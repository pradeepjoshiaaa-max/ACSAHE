"""
End-to-end check: ``01_box_girder.json`` → geometry → interaction diagrams
→ aggregated 3D plot points.

Regenerate the golden file after intentional solver changes::

    python -c "from pathlib import Path; import json; from build.input_handler import load_input_document; from geometry.section_analysis import ACSAHEGeometricSolution; from plot.interaction_coords import accumulate_3d_surface_points; ROOT=Path('tests/fixtures'); src=ROOT/'json'/'01_box_girder.json'; doc=load_input_document(src); g=ACSAHEGeometricSolution(doc, workbook_path=str(src)); d=accumulate_3d_surface_points(g); out={k:[round(float(v),6) for v in d[k]] for k in d}; json.dump({'case':'01_box_girder','n':len(out['x']),**out}, (ROOT/'golden'/'01_box_girder_e2e_3d_surface_points.json').open('w',encoding='utf-8'), indent=2)"
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from build.input_handler import load_input_document
from geometry.section_analysis import ACSAHEGeometricSolution
from plot.interaction_coords import accumulate_3d_surface_points


REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES_DIR = REPO_ROOT / "tests" / "fixtures"
JSON_INPUT = FIXTURES_DIR / "json" / "01_box_girder.json"
GOLDEN = FIXTURES_DIR / "golden" / "01_box_girder_e2e_3d_surface_points.json"


def _round_lists(d: dict, ndigits: int = 6) -> dict:
    return {k: [round(float(v), ndigits) for v in d[k]] for k in ("x", "y", "z", "phi")}


@pytest.mark.e2e
def test_01_box_girder_e2e_3d_surface_matches_golden():
    assert JSON_INPUT.is_file(), f"Missing input JSON: {JSON_INPUT}"
    assert GOLDEN.is_file(), f"Missing golden {GOLDEN}"

    doc = load_input_document(JSON_INPUT, read_only=True)
    gs = ACSAHEGeometricSolution(doc, workbook_path=str(JSON_INPUT))
    assert gs.problema["tipo"] == "3D"

    computed = accumulate_3d_surface_points(gs)
    assert len(computed["x"]) == len(computed["y"]) == len(computed["z"]) == len(computed["phi"])
    assert len(computed["x"]) > 100

    expected = json.loads(GOLDEN.read_text(encoding="utf-8"))
    exp_x = [float(v) for v in expected["x"]]
    exp_y = [float(v) for v in expected["y"]]
    exp_z = [float(v) for v in expected["z"]]
    exp_phi = [float(v) for v in expected["phi"]]

    got = _round_lists(computed)
    assert len(got["x"]) == len(exp_x), "Point count drift — regenerate golden if the change is intended"
    assert got["x"] == [round(v, 6) for v in exp_x]
    assert got["y"] == [round(v, 6) for v in exp_y]
    assert got["z"] == [round(v, 6) for v in exp_z]
    assert got["phi"] == [round(v, 6) for v in exp_phi]
