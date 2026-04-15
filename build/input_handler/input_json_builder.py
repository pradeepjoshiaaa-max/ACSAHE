"""
Builds the portable ACSAHE input document (``01_box_girder.json`` shape) from Excel.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Union

from materials.acero_pasivo import BarraAceroPasivo
from materials.acero_pretensado import BarraAceroPretensado
from materials.concrete import Concrete

from build.input_handler.excel_section_input_reader import (
    ExcelSectionInputReader,
    concrete_class_letter,
    discretization_level_to_identifier,
    guess_building_code_from_workbook,
    recommended_prestress_strain_per_mille,
)

# Keys in ``materials`` and ``reinforcement.*[].material_tag``.
MATERIAL_TAG_CONCRETE = "concrete"
MATERIAL_TAG_REBAR_STEEL = "rebar_steel"
MATERIAL_TAG_P_REBAR = "p_rebar"
MATERIAL_TAG_TRANSVERSE = "transverse_reinforcement"

# ``materials[tag].type`` — physical kind.
MATERIAL_KIND_CONCRETE = "concrete"
MATERIAL_KIND_STEEL = "steel"
MATERIAL_KIND_NONE = "none"

# ``materials[tag].model`` — constitutive / design model id.
MODEL_CONCRETE_ACI = "ACI"
MODEL_STEEL_ELASTIC_PERFECTLY_PLASTIC = "elastic_perfectly_plastic"
MODEL_STEEL_MENEGOTTO_PINTO = "menegotto_pinto"
MODEL_NONE = "none"


def _is_phi_variable(phi_value: Any) -> bool:
    return not isinstance(phi_value, (int, float))


def _transverse_enabled(tipo_estribo: Any) -> bool:
    if tipo_estribo is None:
        return False
    s = str(tipo_estribo).strip().lower()
    if s in ("", "no", "ninguno", "ninguna", "sin estribos"):
        return False
    return True


def _normalized_text(value: Any) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _is_user_provided_steel(value: Any) -> bool:
    normalized = _normalized_text(value)
    return normalized in ("provisto por usuario", "provisto por el usuario")


def _catalog_display_name(raw: str) -> str:
    """Turn ``ADN 420`` / ``Cordones C1900`` into ``ADN-420`` / ``Cordones-C1900``."""
    s = str(raw or "").strip()
    if not s:
        return "unknown"
    return re.sub(r"\s+", "-", s)


def _concrete_fc_mpa(quality: Any) -> float:
    try:
        return float(quality)
    except (TypeError, ValueError):
        return 25.0


def _r6(value: Any) -> Any:
    """Round floats for stable JSON; pass through non-numeric."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 6)
    return value


def _round_props(props: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _r6(v) for k, v in props.items()}


@dataclass(frozen=True)
class AcsaheInputJsonBuilder:
    reader: ExcelSectionInputReader
    source_name: str
    schema_version: str = "1.0"

    def build(self) -> dict:
        sh = self.reader.ingreso_datos_sheet
        problema = self.reader.get_result_params()
        rows_disc = self.reader.get_discretization_block_rows()
        nivel = self.reader.read_discretization_level(rows_disc)

        phi_raw = problema["phi_variable"]
        dx, dy, d_ang = self.reader.read_manual_mesh_inputs(rows_disc)
        analysis_block: Dict[str, Any] = {
            "discretization_level": discretization_level_to_identifier(nivel),
            "problem_type": problema["tipo"],
            "verification_enabled": bool(problema["verificacion"]),
            "bending_plane_angles": sorted(float(a) for a in problema["lista_planos_de_carga"]),
            "is_phi_variable": _is_phi_variable(phi_raw),
            "phi": None if _is_phi_variable(phi_raw) else float(phi_raw),
            "manual_mesh": {
                "dx": _r6(dx),
                "dy": _r6(dy),
                "d_ang": _r6(d_ang),
            },
            "load_combinations": self._load_combinations_json(problema),
        }

        doc = {
            "schema_version": self.schema_version,
            "source": {"format": "excel", "name": self.source_name},
            "building_code": guess_building_code_from_workbook(self.reader),
            "units": {
                "force": "kN",
                "moment": "kNm",
                "length": "cm",
                "bar_diameter": "mm",
                "active_bar_area": "cm2",
                "angle": "deg",
            },
            "materials": self._materials_json(),
            "section_geometry": {"contours": self._contours_json()},
            "reinforcement": {
                "rebar": self._rebars_json(MATERIAL_TAG_REBAR_STEEL),
                "p_rebar": self._p_rebars_json(MATERIAL_TAG_P_REBAR),
            },
            "analysis": analysis_block,
            "output": {"paste_results_to_wb": bool(problema["resultados_en_wb"])},
        }
        return doc

    def _materials_json(self) -> Dict[str, Any]:
        sh = self.reader.ingreso_datos_sheet
        rebar_sheet = self.reader.armaduras_pasivas_sheet
        prebar_sheet = self.reader.armaduras_activas_sheet

        concrete_quality = sh.get_value("C", "4")
        try:
            concrete_quality_json: Union[int, float] = int(float(concrete_quality))
        except (TypeError, ValueError):
            concrete_quality_json = concrete_quality

        fc_mpa = _concrete_fc_mpa(concrete_quality_json)
        cls = concrete_class_letter(self.reader)
        conc = Concrete(int(round(fc_mpa)))

        concrete_block: Dict[str, Any] = {
            "type": MATERIAL_KIND_CONCRETE,
            "model": MODEL_CONCRETE_ACI,
            "name": f"{cls}-{int(round(fc_mpa))}",
            "properties": _round_props(
                {
                    "class": cls,
                    "fc": fc_mpa,
                    "Ec": float(conc.E),
                    "beta_1": float(conc.B1) if conc.B1 is not None else None,
                }
            ),
        }

        rebar_type = str(sh.get_value("C", "6")).strip()
        rebar_block = self._rebar_steel_material(rebar_type, rebar_sheet)

        prebar_type = str(sh.get_value("C", "8")).strip()
        p_rebar_block = self._p_rebar_material(prebar_type, prebar_sheet, sh)

        transverse_raw = str(sh.get_value("C", "10") or "").strip() or "Estribos"
        transverse_enabled = _transverse_enabled(sh.get_value("C", "10"))
        if transverse_enabled:
            transverse_block: Dict[str, Any] = {
                "type": MATERIAL_KIND_STEEL,
                "model": MODEL_STEEL_ELASTIC_PERFECTLY_PLASTIC,
                "name": _catalog_display_name(transverse_raw),
                "properties": {
                    "enabled": True,
                    "label": transverse_raw,
                },
            }
        else:
            transverse_block = {
                "type": MATERIAL_KIND_NONE,
                "model": MODEL_NONE,
                "name": "none",
                "properties": {"enabled": False, "label": transverse_raw or ""},
            }

        return {
            MATERIAL_TAG_CONCRETE: concrete_block,
            MATERIAL_TAG_REBAR_STEEL: rebar_block,
            MATERIAL_TAG_P_REBAR: p_rebar_block,
            MATERIAL_TAG_TRANSVERSE: transverse_block,
        }

    def _rebar_steel_material(self, rebar_type: str, rebar_sheet: Any) -> Dict[str, Any]:
        if _is_user_provided_steel(rebar_type) and rebar_sheet is not None:
            return {
                "type": MATERIAL_KIND_STEEL,
                "model": MODEL_STEEL_ELASTIC_PERFECTLY_PLASTIC,
                "name": "user_custom",
                "properties": _round_props(
                    {
                        "fy": float(rebar_sheet.get_value("E", "3")) / 10.0,
                        "E": float(rebar_sheet.get_value("E", "4")) / 10.0,
                        "eu": float(rebar_sheet.get_value("E", "5")),
                    }
                ),
            }
        catalog = BarraAceroPasivo.default_strain_stress_relation_vars.get(rebar_type)
        fy_mpa = float(catalog["fy"]) if catalog else None
        try:
            eu = float(self.reader.obtener_def_de_rotura_a_pasivo())
        except (TypeError, ValueError):
            eu = None
        props: Dict[str, Any] = {
            "catalog": rebar_type,
            "E": 20000.0,
            "eu": eu,
        }
        if fy_mpa is not None:
            props["fy"] = fy_mpa
        return {
            "type": MATERIAL_KIND_STEEL,
            "model": MODEL_STEEL_ELASTIC_PERFECTLY_PLASTIC,
            "name": _catalog_display_name(rebar_type),
            "properties": _round_props(props),
        }

    def _p_rebar_material(self, prebar_type: str, prebar_sheet: Any, sh: Any) -> Dict[str, Any]:
        eff = float(sh.get_value("E", 8))
        rec = recommended_prestress_strain_per_mille(self.reader)

        if _is_user_provided_steel(prebar_type) and prebar_sheet is not None:
            return {
                "type": MATERIAL_KIND_STEEL,
                "model": MODEL_STEEL_MENEGOTTO_PINTO,
                "name": "user_custom",
                "properties": _round_props(
                    {
                        "effective_strain": eff,
                        "recommended_effective_strain": rec,
                        "Eps": float(prebar_sheet.get_value("E", "3")) / 10.0,
                        "fpy": float(prebar_sheet.get_value("E", "4")) / 10.0,
                        "fpu": float(prebar_sheet.get_value("E", "5")) / 10.0,
                        "epu": float(prebar_sheet.get_value("E", "6")),
                        "N": float(prebar_sheet.get_value("E", "7")),
                        "K": float(prebar_sheet.get_value("E", "8")),
                        "Q": float(prebar_sheet.get_value("E", "9")),
                    }
                ),
            }

        defaults = BarraAceroPretensado.default_strain_stress_relation_vars.get(
            prebar_type.strip().upper()
        )
        props: Dict[str, Any] = {
            "effective_strain": eff,
            "recommended_effective_strain": rec,
            "Eps": 20000.0,
        }
        if defaults:
            props.update(
                {
                    "fpy": float(defaults["fpy"]),
                    "fpu": float(defaults["fpu"]),
                    "epu": float(defaults["epu"]),
                    "N": float(defaults["N"]),
                    "K": float(defaults["K"]),
                    "Q": float(defaults["Q"]),
                }
            )
        return {
            "type": MATERIAL_KIND_STEEL,
            "model": MODEL_STEEL_MENEGOTTO_PINTO,
            "name": _catalog_display_name(prebar_type),
            "properties": _round_props(props),
        }

    @staticmethod
    def _xy_pairs_to_nodes(pairs: List[List[float]]) -> List[Dict[str, float]]:
        return [{"x": float(xy[0]), "y": float(xy[1])} for xy in pairs]

    def _contours_json(self) -> List[dict]:
        contours: List[dict] = []
        for filas_region in self.reader.iter_concrete_regions():
            is_hole = self.reader.get_contour_matrix_sign(filas_region) < 0
            shape_type = self.reader.get_contour_shape_type(filas_region)
            idx = int(self.reader.get_contour_index(filas_region))
            if shape_type == "Poligonal":
                contours.append(
                    {
                        "id": idx,
                        "is_hole": is_hole,
                        "type": "polygon",
                        "nodes": self._xy_pairs_to_nodes(self.reader.parse_polygon_contour(filas_region)),
                    }
                )
            elif shape_type == "Circular":
                c = self.reader.parse_circular_contour(filas_region)
                contours.append(
                    {
                        "id": idx,
                        "is_hole": is_hole,
                        "type": "circular",
                        "center": {"x": float(c["center_x"]), "y": float(c["center_y"])},
                        "inner_radius_cm": float(c["r_int"]),
                        "outer_radius_cm": float(c["r_ext"]),
                    }
                )
        return contours

    def _rebars_json(self, material_tag: str) -> List[dict]:
        out: List[dict] = []
        for row in self.reader.get_passive_rebar_row_numbers():
            x, y, d, i = self.reader.get_rebar_excel_values(row)
            if d == 0 or d is None:
                continue
            try:
                bid = int(i)
            except (TypeError, ValueError):
                bid = str(i)
            out.append(
                {
                    "id": bid,
                    "material_tag": material_tag,
                    "x": float(x),
                    "y": float(y),
                    "diameter": float(d),
                }
            )
        return out

    def _p_rebars_json(self, material_tag: str) -> List[dict]:
        out: List[dict] = []
        for row in self.reader.get_active_rebar_row_numbers():
            x, y, area, i = self.reader.get_rebar_excel_values(row)
            if area == 0 or area is None:
                continue
            try:
                bid = int(i)
            except (TypeError, ValueError):
                bid = str(i)
            out.append(
                {
                    "id": bid,
                    "material_tag": material_tag,
                    "x": float(x),
                    "y": float(y),
                    "area": float(area),
                }
            )
        return out

    def _load_combinations_json(self, problema: dict) -> List[dict]:
        tipo = problema["tipo"]
        combos = problema["puntos_a_verificar"]
        result: List[dict] = []
        if tipo == "2D":
            angle_deg = problema["lista_planos_de_carga"][0] if problema["lista_planos_de_carga"] else 0.0
            for c in combos:
                m = float(c["M"])
                result.append(
                    {
                        "id": str(c["nombre"]),
                        "Pu": float(c["P"]),
                        "Mu_x": m * math.cos(math.radians(angle_deg)),
                        "Mu_y": m * math.sin(math.radians(angle_deg)),
                    }
                )
        else:
            for c in combos:
                result.append(
                    {
                        "id": str(c["nombre"]),
                        "Pu": float(c["P"]),
                        "Mu_x": float(c["Mx"]),
                        "Mu_y": float(c["My"]),
                        "loading_plane_angle": float(c.get("plano_de_carga", 0.0)),
                    }
                )
        return result
