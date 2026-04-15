from __future__ import annotations

"""
JSON-backed implementation of the same **reader surface** as ``ExcelSectionInputReader``.

``geometry.section_analysis`` consumes this reader so meshing and material code keep using
``ingreso_datos_sheet.get_value(...)`` and related helpers without opening Excel.
"""

from typing import Any, Dict, List, Optional, Tuple


class _CellMapSheet:
    def __init__(self, values: Dict[tuple[str, str], Any]):
        self._values = values
        self.default_rows_range_value = (1, 500)

    def get_value(self, column: str, row: Any) -> Any:
        return self._values.get((column, str(row)))


class JsonSectionInputReader:
    """
    Maps the portable input document into sheet-like facades and contour/rebar iterators
    so existing geometry code does not branch on input format.
    """

    rectangular_element_partition_dict = {
        "Muy Gruesa": 6,
        "Gruesa": 12,
        "Media": 30,
        "Fina": 50,
        "Muy Fina": 100,
        "very_coarse": 6,
        "coarse": 12,
        "medium": 30,
        "fine": 50,
        "very_fine": 100,
    }
    niveles_mallado_circular = {
        "Muy Gruesa": (3, 45),
        "Gruesa": (6, 30),
        "Media": (12, 10),
        "Fina": (25, 5),
        "Muy Fina": (50, 2),
        "very_coarse": (3, 45),
        "coarse": (6, 30),
        "medium": (12, 10),
        "fine": (25, 5),
        "very_fine": (50, 2),
    }

    def __init__(self, input_document: dict):
        self.input_document = input_document
        self._contours = input_document["section_geometry"]["contours"]
        self._rebar_rows = input_document["reinforcement"]["rebar"]
        self._p_rebar_rows = input_document["reinforcement"]["p_rebar"]
        self._rebar_index: Dict[int, tuple[Any, Any, Any, Any]] = {}
        self._p_rebar_index: Dict[int, tuple[Any, Any, Any, Any]] = {}
        self._rows_disc = tuple(range(1, 21))
        self._manual_mesh_inputs = (None, None, None)

        self.ingreso_datos_sheet = self._build_ingreso_sheet()
        self.armaduras_pasivas_sheet = self._build_rebar_sheet()
        self.armaduras_activas_sheet = self._build_p_rebar_sheet()
        self.diagrama_interaccion_sheet = _CellMapSheet({})
        self.diagrama_interaccion_3D_sheet = _CellMapSheet({})

    def _material(self, tag: str) -> dict:
        return self.input_document["materials"][tag]

    @staticmethod
    def _catalog_name_or_custom(material_block: dict) -> str:
        if material_block.get("name") == "user_custom":
            return "Provisto por usuario"
        props = material_block.get("properties", {})
        if "catalog" in props:
            return str(props["catalog"])
        return str(material_block.get("name", "")).replace("-", " ")

    def _build_ingreso_sheet(self) -> _CellMapSheet:
        concrete = self._material("concrete")
        rebar = self._material("rebar_steel")
        p_rebar = self._material("p_rebar")
        transverse = self._material("transverse_reinforcement")
        analysis = self.input_document.get("analysis", {})

        props_c = concrete.get("properties", {})
        props_p = p_rebar.get("properties", {})
        transverse_label = transverse.get("properties", {}).get("label", "")

        values: Dict[tuple[str, str], Any] = {
            ("B", "4"): props_c.get("class", "H"),
            ("C", "4"): props_c.get("fc", 25),
            ("C", "6"): self._catalog_name_or_custom(rebar),
            ("C", "8"): self._catalog_name_or_custom(p_rebar),
            ("E", "8"): props_p.get("effective_strain", 5.0),
            ("C", "10"): transverse_label if transverse.get("properties", {}).get("enabled", False) else "No",
        }
        self._manual_mesh_inputs = (
            analysis.get("manual_mesh", {}).get("dx"),
            analysis.get("manual_mesh", {}).get("dy"),
            analysis.get("manual_mesh", {}).get("d_ang"),
        )
        return _CellMapSheet(values)

    def _build_rebar_sheet(self) -> _CellMapSheet:
        props = self._material("rebar_steel").get("properties", {})
        values = {
            ("E", "3"): props.get("fy"),
            ("E", "4"): props.get("E"),
            ("E", "5"): props.get("eu"),
        }
        return _CellMapSheet(values)

    def _build_p_rebar_sheet(self) -> _CellMapSheet:
        props = self._material("p_rebar").get("properties", {})
        values = {
            ("E", "3"): props.get("Eps"),
            ("E", "4"): props.get("fpy"),
            ("E", "5"): props.get("fpu"),
            ("E", "6"): props.get("epu"),
            ("E", "7"): props.get("N"),
            ("E", "8"): props.get("K"),
            ("E", "9"): props.get("Q"),
        }
        return _CellMapSheet(values)

    def get_result_params(self) -> dict:
        analysis = self.input_document.get("analysis", {})
        load_combos = analysis.get("load_combinations", [])
        problem_type = analysis.get("problem_type")
        if not problem_type:
            problem_type = "2D" if len(analysis.get("bending_plane_angles", [])) <= 1 else "3D"

        points: List[dict] = []
        for combo in load_combos:
            if problem_type == "2D":
                points.append(
                    {
                        "nombre": combo["id"],
                        "P": combo["Pu"],
                        "M": combo.get("M", combo.get("Mu_x", 0.0)),
                    }
                )
            else:
                points.append(
                    {
                        "nombre": combo["id"],
                        "P": combo["Pu"],
                        "Mx": combo.get("Mu_x", 0.0),
                        "My": combo.get("Mu_y", 0.0),
                        "plano_de_carga": combo.get("loading_plane_angle", 0.0),
                    }
                )

        phi_variable = analysis.get("is_phi_variable", True)
        phi_value = analysis.get("phi")
        return {
            "tipo": problem_type,
            "verificacion": bool(analysis.get("verification_enabled", False)),
            "lista_planos_de_carga": list(analysis.get("bending_plane_angles", [])),
            "puntos_a_verificar": points,
            "resultados_en_wb": bool(self.input_document.get("output", {}).get("paste_results_to_wb", False)),
            "phi_variable": phi_value if (phi_value is not None and not phi_variable) else "según CIRSOC 201-2024",
        }

    def _index_rebar_rows(self) -> None:
        if self._rebar_index:
            return
        for idx, rb in enumerate(self._rebar_rows, start=1):
            self._rebar_index[idx] = (rb["x"], rb["y"], rb["diameter"], rb.get("id", idx))
        for idx, rb in enumerate(self._p_rebar_rows, start=10001):
            self._p_rebar_index[idx] = (rb["x"], rb["y"], rb["area"], rb.get("id", idx))

    def get_rebar_excel_values(self, row_number: int) -> Tuple[Any, Any, Any, Any]:
        self._index_rebar_rows()
        if row_number in self._rebar_index:
            return self._rebar_index[row_number]
        return self._p_rebar_index[row_number]

    def get_passive_rebar_row_numbers(self) -> List[int]:
        self._index_rebar_rows()
        return list(self._rebar_index.keys())

    def get_active_rebar_row_numbers(self) -> List[int]:
        self._index_rebar_rows()
        return list(self._p_rebar_index.keys())

    def iter_concrete_regions(self) -> List[List[int]]:
        return [[idx] for idx in range(len(self._contours))]

    def _contour_by_region(self, region: List[int]) -> dict:
        return self._contours[int(region[0])]

    def get_contour_index(self, region: List[int]) -> str:
        return str(self._contour_by_region(region)["id"])

    def get_contour_matrix_sign(self, region: List[int]) -> int:
        return -1 if self._contour_by_region(region).get("is_hole", False) else +1

    def get_contour_shape_type(self, region: List[int]) -> str:
        ctype = self._contour_by_region(region).get("type")
        return "Circular" if ctype == "circular" else "Poligonal"

    def get_contour_node_count(self, region: List[int]) -> Any:
        return len(self._contour_by_region(region).get("nodes", []))

    def parse_polygon_contour(self, filas_region: List[int]) -> List[List[float]]:
        nodes = self._contour_by_region(filas_region).get("nodes", [])
        return [[float(n["x"]), float(n["y"])] for n in nodes]

    def parse_circular_contour(self, filas_region: List[int]) -> dict:
        c = self._contour_by_region(filas_region)
        center = c["center"]
        return {
            "center_x": float(center["x"]),
            "center_y": float(center["y"]),
            "r_int": float(c["inner_radius_cm"]),
            "r_ext": float(c["outer_radius_cm"]),
        }

    def get_discretization_block_rows(self) -> Tuple[int, ...]:
        return self._rows_disc

    def read_discretization_level(self, rows_range: Tuple[int, ...]) -> str:
        return self.input_document.get("analysis", {}).get("discretization_level", "fine")

    def read_manual_mesh_inputs(self, rows_range: Tuple[int, ...]) -> Tuple[Any, Any, Any]:
        return self._manual_mesh_inputs

    def obtener_def_de_rotura_a_pasivo(self) -> Any:
        return self._material("rebar_steel").get("properties", {}).get("eu", 0.12)

    def get_initial_prestressed_strain(self) -> float:
        eff = self._material("p_rebar").get("properties", {}).get("effective_strain", 5.0)
        return float(eff) / 1000
