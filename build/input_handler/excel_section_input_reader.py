"""
Reads cross-section and analysis parameters from the ACSAHE Excel workbook layout.

Workbook cell lookups used to build the portable input document (``excel_workbook_to_input_dict``).
Section geometry reads that document via ``JsonSectionInputReader``, not Excel directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Optional, Set, Tuple

from build.utils.excel_manager import ExcelManager, ExcelSheetManager


class ExcelSectionInputReader:
    """Thin adapter over ``ExcelManager`` / ``ExcelSheetManager`` for ACSAHE ingreso sheets."""

    rectangular_element_partition_dict = {
        "Muy Gruesa": 6,
        "Gruesa": 12,
        "Media": 30,
        "Fina": 50,
        "Muy Fina": 100,
    }
    niveles_mallado_circular = {
        "Muy Gruesa": (3, 45),
        "Gruesa": (6, 30),
        "Media": (12, 10),
        "Fina": (25, 5),
        "Muy Fina": (50, 2),
    }

    def __init__(self, excel_manager: ExcelManager):
        self.excel_manager = excel_manager
        self.ingreso_datos_sheet: Optional[ExcelSheetManager] = None
        self.armaduras_pasivas_sheet: Optional[ExcelSheetManager] = None
        self.armaduras_activas_sheet: Optional[ExcelSheetManager] = None
        self.diagrama_interaccion_sheet: Optional[ExcelSheetManager] = None
        self.diagrama_interaccion_3D_sheet: Optional[ExcelSheetManager] = None
        self.lista_ang_plano_de_carga: Set[float] = set()
        self._load_excel_sheets()

    def _load_excel_sheets(self) -> None:
        self.ingreso_datos_sheet = self.excel_manager.get_sheet("Ingreso de Datos")
        self.armaduras_pasivas_sheet = self.excel_manager.get_sheet("Armaduras Pasivas")
        self.armaduras_activas_sheet = self.excel_manager.get_sheet("Armaduras Activas")
        self.diagrama_interaccion_sheet = self.excel_manager.get_sheet("Resultados 2D")
        self.diagrama_interaccion_3D_sheet = self.excel_manager.get_sheet("Resultados 3D")

    def _append_uniaxial_angle(self, ang: Any) -> None:
        if ang is not None:
            self.lista_ang_plano_de_carga.add(round(float(ang), 2))

    @staticmethod
    def get_phi_criteria(tratado_de_phi: Any, phi_handling_cell: Optional[Tuple[str, int]]) -> Any:
        exception = Exception(
            "Valor incorrecto en la celda 'Factor de Minoración de Resistencia ϕ'.\n"
            "Por favor, ingresar alguno de los valores disponibles en el menú desplegable."
        )
        try:
            if isinstance(tratado_de_phi, str):
                tratado_de_phi = tratado_de_phi.replace(",", ".")
                tratado_de_phi = tratado_de_phi.replace("\n", " ")
            return float(tratado_de_phi)
        except ValueError:
            if isinstance(tratado_de_phi, str):
                if "SELECCIONAR CRITERIO" in tratado_de_phi.upper():
                    cell_address_str = (
                        f"Debe seleccionar su valor en el menú desplegable de la celda: {phi_handling_cell[0]}{phi_handling_cell[1]}."
                        if phi_handling_cell is not None
                        else ""
                    )
                    raise ValueError(
                        f"ERROR: No ha seleccionado un criterio para el valor de tratado de ϕ. {cell_address_str}"
                    )
                if "CIRSOC 201-2024" in tratado_de_phi.upper():
                    return "según CIRSOC 201-2024"
                if "CIRSOC 201" in tratado_de_phi.upper():
                    return "según CIRSOC 201-2005"
                raise exception
            raise exception

    def _get_uniaxial_angles_list(self, tipo: str, rows_range: Tuple[int, ...]) -> None:
        sh = self.ingreso_datos_sheet
        if tipo == "2D":
            self._append_uniaxial_angle(
                sh.get_value_on_the_right("Ángulo plano de carga λ =", rows_range, 2)
            )
        else:
            cantidad_planos_de_carga = int(
                sh.get_value_on_the_right("Cantidad de Planos de Carga", rows_range, 2)
            )
            planos_de_carga_fila = sh.get_n_rows_after_value(
                "Cantidad de Planos de Carga",
                cantidad_planos_de_carga + 2,
            )
            for ang in [sh.get_value("C", row_n) for row_n in planos_de_carga_fila[2:]]:
                self._append_uniaxial_angle(ang)

    def _get_loading_combinations_points(self, type_of_problem: str) -> List[dict]:
        sh = self.ingreso_datos_sheet
        rows_range = tuple(range(46, sh.default_rows_range_value[-1]))
        load_combinations_count = sh.get_value_on_the_right(
            "Cantidad de Estados", n_column=2, rows_range=rows_range
        )
        if not load_combinations_count:
            return []
        load_combinations_count = int(load_combinations_count)
        load_combination_row_list = sh.get_n_rows_after_value(
            "Cantidad de Estados",
            load_combinations_count + 3,
        )
        load_combinations_list: List[dict] = []
        for combination_row in load_combination_row_list[3:]:
            if type_of_problem == "2D":
                load_combination = {
                    "nombre": sh.get_value("A", combination_row),
                    "P": sh.get_value("C", combination_row),
                    "M": sh.get_value("E", combination_row),
                }
            else:
                plano_de_carga = sh.get_value("H", combination_row)
                load_combination = {
                    "nombre": sh.get_value("A", combination_row),
                    "P": sh.get_value("C", combination_row),
                    "Mx": sh.get_value("E", combination_row),
                    "My": sh.get_value("G", combination_row),
                    "plano_de_carga": plano_de_carga if plano_de_carga is not None else 0,
                }
                self._append_uniaxial_angle(load_combination["plano_de_carga"])
            load_combinations_list.append(load_combination)
        if type_of_problem == "3D":
            load_combinations_list = sorted(load_combinations_list, key=lambda x: x["plano_de_carga"])
        return load_combinations_list

    def get_result_params(self) -> dict:
        """``problema`` dict shape consumed by ``JsonSectionInputReader.get_result_params``."""
        self.lista_ang_plano_de_carga = set()
        sh = self.ingreso_datos_sheet
        rows_range = sh.get_n_rows_after_value("RESULTADOS", number_of_rows_after_value=20, columns_range="A")

        type_of_result = sh.get_value_on_the_right("Tipo", rows_range, 2)
        verifies_design_loads = sh.get_value_on_the_right("Verificación de Estados", rows_range, 2)
        pastes_results_in_wb = sh.get_value_on_the_right("Pegar resultados en planilla", rows_range, 2)
        phi_handling_str = sh.get_value_on_the_right(
            "ϕ\nFactor de Minoración de Resistencia", rows_range, 2
        )
        phi_handling_cell = sh.get_cell_address_on_the_right(
            "ϕ\nFactor de Minoración de Resistencia", rows_range, 2
        )
        self._get_uniaxial_angles_list(type_of_result, rows_range)
        puntos_a_verificar = self._get_loading_combinations_points(type_of_result)
        self.lista_ang_plano_de_carga = list(self.lista_ang_plano_de_carga)
        return {
            "tipo": type_of_result,
            "verificacion": isinstance(verifies_design_loads, str) and verifies_design_loads == "Sí",
            "lista_planos_de_carga": list(self.lista_ang_plano_de_carga),
            "puntos_a_verificar": puntos_a_verificar,
            "resultados_en_wb": isinstance(pastes_results_in_wb, str) and pastes_results_in_wb == "Sí",
            "phi_variable": self.get_phi_criteria(phi_handling_str, phi_handling_cell),
        }

    def obtener_def_de_rotura_a_pasivo(self) -> Any:
        problem_type = self.ingreso_datos_sheet.get_value("C", "6")
        possible_reinforcement_options = {"ADN 420": "B", "ADN 500": "C", "AL 220": "D", "Provisto por Usuario": "E"}
        return self.armaduras_pasivas_sheet.get_value(
            possible_reinforcement_options.get(problem_type, "B"), 5
        )

    def get_initial_prestressed_strain(self) -> float:
        value = self.ingreso_datos_sheet.get_value("E", 8)
        return value / 1000

    def get_rebar_excel_values(self, row_number: int) -> Tuple[Any, Any, Any, Any]:
        sh = self.ingreso_datos_sheet
        return (
            sh.get_value("C", row_number),
            sh.get_value("E", row_number),
            sh.get_value("G", row_number),
            sh.get_value("A", row_number),
        )

    def get_passive_rebar_row_numbers(self) -> List[int]:
        sh = self.ingreso_datos_sheet
        rows_list = sh.get_rows_range_between_values(
            ("ARMADURAS PASIVAS (H°- Armado)", "ARMADURAS ACTIVAS (H°- Pretensado)"),
            columns_range=["A"],
        )
        return list(rows_list[5:-1])

    def get_active_rebar_row_numbers(self) -> List[int]:
        sh = self.ingreso_datos_sheet
        lista_filas = sh.get_rows_range_between_values(
            ("ARMADURAS ACTIVAS (H°- Pretensado)", "DISCRETIZACIÓN DE LA SECCIÓN"),
            columns_range=["A"],
        )
        return list(lista_filas[5:-1])

    def get_contour_index(self, region: List[int]) -> str:
        value = self.ingreso_datos_sheet.get_value("A", region[0])
        return value.split()[-1]

    def get_contour_matrix_sign(self, region: List[int]) -> int:
        value = self.ingreso_datos_sheet.get_value("C", region[0])
        return +1 if "Pos" in value else -1

    def get_contour_shape_type(self, region: List[int]) -> str:
        return self.ingreso_datos_sheet.get_value("E", region[0])

    def get_contour_node_count(self, region: List[int]) -> Any:
        return self.ingreso_datos_sheet.get_value("G", region[0])

    def iter_concrete_regions(self) -> List[List[int]]:
        sh = self.ingreso_datos_sheet
        filas_hormigon = sh.get_rows_range_between_values(
            ("GEOMETRÍA DE LA SECCIÓN DE HORMIGÓN", "ARMADURAS PASIVAS (H°- Armado)"),
            columns_range=["A"],
        )
        return sh.subdivide_range_in_contain_word("A", filas_hormigon, "Contorno")

    def parse_polygon_contour(self, filas_region: List[int]) -> List[List[float]]:
        sh = self.ingreso_datos_sheet
        cantidad_de_nodos = int(self.get_contour_node_count(filas_region))
        nodes: List[List[float]] = []
        for fila_n in sh.get_n_rows_after_value("Nodo Nº", cantidad_de_nodos + 1, rows_range=filas_region)[1:]:
            x = sh.get_value("C", fila_n)
            y = sh.get_value("E", fila_n)
            nodes.append([round(float(x), 3), round(float(y), 3)])
        return nodes

    def parse_circular_contour(self, filas_region: List[int]) -> dict:
        sh = self.ingreso_datos_sheet
        return {
            "center_x": sh.get_value_on_the_right("Nodo Centro", filas_region, 2),
            "center_y": sh.get_value_on_the_right("Nodo Centro", filas_region, 4),
            "r_int": sh.get_value_on_the_right("Radio Interno [cm]", filas_region, 2),
            "r_ext": sh.get_value_on_the_right("Radio Externo [cm]", filas_region, 2),
        }

    def get_discretization_block_rows(self) -> Tuple[int, ...]:
        return self.ingreso_datos_sheet.get_n_rows_after_value(
            "DISCRETIZACIÓN DE LA SECCIÓN",
            number_of_rows_after_value=20,
            columns_range="A",
        )

    def get_mesh_rectangular_factors(self) -> dict:
        return dict(self.rectangular_element_partition_dict)

    def get_mesh_circular_factors(self) -> dict:
        return dict(self.niveles_mallado_circular)

    def read_discretization_level(self, rows_range: Tuple[int, ...]) -> str:
        return self.ingreso_datos_sheet.get_value_on_the_right("Nivel de Discretización", rows_range, 2)

    def read_manual_mesh_inputs(self, rows_range: Tuple[int, ...]) -> Tuple[Any, Any, Any]:
        sh = self.ingreso_datos_sheet
        return (
            sh.get_value_on_the_right("ΔX [cm] =", rows_range, 2),
            sh.get_value_on_the_right("ΔY [cm] =", rows_range, 2),
            sh.get_value_on_the_right("Δθ [°] =", rows_range, 2),
        )


def discretization_level_to_identifier(nivel: str) -> str:
    mapping_dict = {
        "Muy Gruesa": "very_coarse",
        "Gruesa": "coarse",
        "Media": "medium",
        "Fina": "fine",
        "Muy Fina": "very_fine",
        "Avanzada (Ingreso Manual)": "advanced_manual",
    }
    return mapping_dict.get(nivel, nivel)


def guess_building_code_from_workbook(reader: ExcelSectionInputReader) -> str:
    """Best-effort lookup; defaults to the canonical example when not found in the sheet."""
    sh = reader.ingreso_datos_sheet
    row_start, row_end = 1, min(80, sh.default_rows_range_value[-1])
    for col in ("A", "B", "C", "D", "E"):
        values = sh.get_column_values(col, row_start, row_end)
        for v in values:
            if isinstance(v, str) and "ACI" in v.upper():
                return v.strip()
    return "ACI 318-19"


def concrete_class_letter(reader: ExcelSectionInputReader) -> str:
    raw = reader.ingreso_datos_sheet.get_value("B", "4")
    if raw is None or str(raw).strip() == "":
        return "H"
    s = str(raw).strip()
    if len(s) == 1 and s.isalpha():
        return s.upper()
    return "H"


def recommended_prestress_strain_per_mille(reader: ExcelSectionInputReader) -> float:
    """Optional companion cell to ``E8`` (effective strain); falls back to a rounded effective value."""
    sh = reader.ingreso_datos_sheet
    for col, row in (("F", 8), ("G", 8)):
        v = sh.get_value(col, row)
        if v is not None and v != "":
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    eff = reader.ingreso_datos_sheet.get_value("E", 8)
    try:
        return round(float(eff), 3)
    except (TypeError, ValueError):
        return 5.0


def excel_workbook_to_input_dict(
    workbook_path: str | Path,
    *,
    read_only: bool = True,
    source_display_name: Optional[str] = None,
) -> dict:
    """
    Opens an ``.xlsm`` / ``.xlsx`` workbook and returns the portable JSON document.

    This is the high-level entry point intended for CLI / future non-Excel sources.
    """
    from build.input_handler.input_json_builder import AcsaheInputJsonBuilder

    path = Path(workbook_path)
    manager = ExcelManager(str(path), read_only=read_only, visible=False)
    try:
        reader = ExcelSectionInputReader(manager)
        name = source_display_name if source_display_name is not None else path.stem
        return AcsaheInputJsonBuilder(reader, source_name=name).build()
    finally:
        manager.close(save=False)
