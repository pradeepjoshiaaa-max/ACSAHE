"""
Section geometry and materials for ACSAHE.

**Inputs (reading)**  
Only the portable input ``dict`` is used. Obtain it with
``build.input_handler.load_input_document`` (from ``.json`` or workbook).
:class:`ACSAHEGeometricSolution` uses :class:`~build.input_handler.json_section_input_reader.JsonSectionInputReader`,
which exposes the same cell-oriented sheet objects the legacy Excel layout used, so the solver code in this module is unchanged.

**Visualization**  
Plotly figures are built in ``plot.section_plotly`` and ``build.utils.plotly_engine``, not here.

**Outputs (Excel, optional)**  
:meth:`insertar_valores_2D` / :meth:`insertar_valores_3D` open a workbook to push results; pass
``workbook_path`` when constructing the geometric solution if you need these.
"""

import logging

import math
import numpy as np

from scipy.optimize import fsolve

from materials.acero_pasivo import BarraAceroPasivo
from materials.acero_pretensado import BarraAceroPretensado
from build.utils.excel_manager import ExcelManager
from build.input_handler.excel_section_input_reader import ExcelSectionInputReader
from build.input_handler.json_section_input_reader import JsonSectionInputReader
from geometry.section_geometry_engine import Node, Region, ArbitraryCrossSection, CircularRegion
from materials.concrete import Concrete
from materials.matrices import MatrizAceroPasivo, MatrizAceroActivo
logger = logging.getLogger(__name__)


class ACSAHEGeometricSolution:
    """Mesh, rebars, and ``problema`` state from a portable input document (see module docstring)."""

    #  Both dimensions will be divided in N equal parts.
    rectangular_element_partition_dict = {"Muy Gruesa": 6, "Gruesa": 12, "Media": 30, "Fina": 50, "Muy Fina": 100}
    #  Discretization levels
    niveles_mallado_circular = {"Muy Gruesa": (3, 45), "Gruesa": (6, 30), "Media": (12, 10),
                                "Fina": (25, 5), "Muy Fina": (50, 2)}

    def __init__(self, input_document: dict, *, workbook_path: str | None = None):
        # Sheet facades and reader are assigned in build().
        self.ingreso_datos_sheet = None
        self.armaduras_pasivas_sheet = None
        self.armaduras_activas_sheet = None
        self.diagrama_interaccion_sheet = None
        self.diagrama_interaccion_3D_sheet = None
        self.max_x_seccion, self.min_x_seccion, self.max_y_seccion, self.min_y_seccion = None, None, None, None
        self._input_reader: JsonSectionInputReader | ExcelSectionInputReader | None = None
        self.workbook_path = workbook_path
        self.input_document = input_document
        self.excel_manager = None

        self.concrete_array, self.rebar_array, self.prestressed_rebar_array = None, None, None

        self.build()

    def _bind_sheet_facade_from_reader(self) -> None:
        """Mirror Excel sheet managers from the active input reader (JSON- or Excel-backed)."""
        r = self._input_reader
        self.ingreso_datos_sheet = r.ingreso_datos_sheet
        self.armaduras_pasivas_sheet = r.armaduras_pasivas_sheet
        self.armaduras_activas_sheet = r.armaduras_activas_sheet
        self.diagrama_interaccion_sheet = r.diagrama_interaccion_sheet
        self.diagrama_interaccion_3D_sheet = r.diagrama_interaccion_3D_sheet

    def build(self) -> None:
        self._input_reader = JsonSectionInputReader(self.input_document)
        self._bind_sheet_facade_from_reader()
        self.problema = self._input_reader.get_result_params()
        self.lista_ang_plano_de_carga = self.problema["lista_planos_de_carga"]

        self.concrete, self.acero_pasivo, self.acero_activo, self.estribo = None, None, None, None
        self._load_material_properties()
        try:
            self.meshed_section = self.get_meshed_concrete_section()
            self.XG, self.YG = self.meshed_section.xg, self.meshed_section.yg

            self.concrete_array = self.meshed_section.elements_list  # Concrete Array.
            self.rebar_array = self._get_rebar_array()
            self.prestressed_rebar_array = self._get_prestressed_bars_array()
            self.meshed_section.Ast = sum([x.area for x in self.rebar_array])
            self.meshed_section.Apt = sum([x.area for x in self.prestressed_rebar_array])

            self.deformacion_maxima_de_acero = self._get_max_steel_strain()
            self.planos_de_deformacion = self.get_strain_planes()

            self.ec, self.phix, self.phiy = self._get_initial_prestressed_plain()
            self.ec_plano_deformacion_elastica_inicial = lambda x, y: self.ec + math.tan(math.radians(self.phix)) * (
                y) + math.tan(
                math.radians(self.phiy)) * x
            self.assign_elastic_strains_to_prestressed_bars()
        except Exception:
            logger.exception("Error en la generación de la geometría")
            raise

    def _load_material_properties(self):

        self.concrete = Concrete(tipo=self.ingreso_datos_sheet.get_value("C", "4"))
        self.tipo_estribo = self.ingreso_datos_sheet.get_value("C", "10")

        def_de_rotura_a_pasivo = self._input_reader.obtener_def_de_rotura_a_pasivo()
        self.set_rebar_properties(def_de_rotura_a_pasivo)

        def_de_pretensado_inicial = self._input_reader.get_initial_prestressed_strain()
        self.def_de_pretensado_inicial = def_de_pretensado_inicial
        self.setear_propiedades_acero_activo(def_de_pretensado_inicial)

    def _get_initial_prestressed_plain(self):
        """Gets the paratemers of the initial section elastic deformation, based on the prestressing action."""
        if not self.prestressed_rebar_array:  # Caso de Hormigón Armado
            return 0, 0, 0
        non_linear_solution = fsolve(
            self.strain_function_to_converge, [-BarraAceroPretensado.deformacion_de_pretensado_inicial, 0, 0],
            maxfev=50, full_output=1)

        if not (non_linear_solution[2]):
            raise Exception("No se encontró deformación inicial que satisfaga las ecuaciones de equilibrio")
        ec, phix, phiy = non_linear_solution[0]
        return ec, phix, phiy

    def strain_function_to_converge(self, strains):
        (ec, phix, phiy) = strains
        return self.get_baricentric_section_forces(ec, phix, phiy)

    def _get_max_steel_strain(self):
        def_max_acero_pasivo = BarraAceroPasivo.eu
        def_max_acero_activo = BarraAceroPretensado.epu
        return min(def_max_acero_pasivo, def_max_acero_activo)

    def _get_mesh_characteristics(self):
        return {
            "ΔX": f"{round(self.meshed_section.dx, 2)} cm" if self.meshed_section.dx else None,
            "ΔY": f"{round(self.meshed_section.dy, 2)} cm" if self.meshed_section.dy else None,
            "Δr": f"{round(self.meshed_section.dr, 2)} cm" if self.meshed_section.dr else None,
            "Δθ": f"{round(self.meshed_section.d_ang, 2)}°" if self.meshed_section.d_ang else None}

    def _get_colors_kwargs(self, plano_de_def, arcoiris=False, blanco_y_negro=False):
        lista_colores = ["k", "r", "b", "g", "c", "m", "y", "k"]
        if arcoiris:
            return {"color": self.numero_a_color_arcoiris(abs(plano_de_def[3]))}
        return {"c": lista_colores[abs(plano_de_def[2])] if blanco_y_negro is False else "k"}

    def get_strain_planes(self):
        """Obtiene una lista de los planos de deformación últimos a utilizarse para determinar los estados de resistencia
        últimos, cada element de esta lista representa, en principio, un punto sobre el diagrama de interacción.
        Este puede no ser el caso si hay puntos para los cuales no se encuentra una convergencia, en ese caso será
        descartado."""
        plane_list = []
        try:
            for j in range(350):
                if j <= 25:
                    final_strain = -0.5
                    top_strain = -3
                    bottom_strain = -3 + (final_strain + 3) * j / (25)  # Hasta -0.3
                    plane_index = 1
                elif 25 < j <= 100:
                    def_inicial = -0.5
                    final_strain = 0
                    top_strain = -3
                    bottom_strain = def_inicial + (final_strain - def_inicial) * (j - 25) / (100 - 25)  # Hasta 0
                    plane_index = 2
                elif 100 < j <= 200:
                    top_strain = -3
                    bottom_strain = 10 * (j - 100) / (200 - 100)
                    plane_index = 3
                elif 200 < j <= 275:  # Hasta la deformación máxima del acero.
                    top_strain = -3
                    bottom_strain = 10 + (j - 200) * (self.deformacion_maxima_de_acero * 1000 - 10) / (275 - 200)
                    plane_index = 4
                elif j <= 325:
                    top_strain = -3 + (6 + 3) * (j - 275) / (325 - 275)
                    bottom_strain = self.deformacion_maxima_de_acero * 1000
                    plane_index = 5
                else:
                    top_strain = 6 + (self.deformacion_maxima_de_acero * 1000 - 6) * (j - 325) / (350 - 326)
                    bottom_strain = self.deformacion_maxima_de_acero * 1000
                    plane_index = 6
                plane_list.append((top_strain / 1000, bottom_strain / 1000, plane_index, j))
        except AttributeError as e:
            pass
        inverted_plane_list = [(x[1], x[0], -x[2], -x[3]) for x in plane_list]  # Misma lista, invertida de sign
        return plane_list + inverted_plane_list

    def assign_elastic_strains_to_prestressed_bars(self):
        ec_plano = self.ec_plano_deformacion_elastica_inicial
        for elemento_pretensado in self.prestressed_rebar_array:
            elemento_pretensado.def_elastica_hormigon_perdidas = ec_plano(elemento_pretensado.xg,
                                                                          elemento_pretensado.yg)

    def _get_rebar_array(self):
        result_array = MatrizAceroPasivo()
        for row_number in self._input_reader.get_passive_rebar_row_numbers():
            x, y, d, i = self._input_reader.get_rebar_excel_values(row_number)
            if d == 0:
                continue
            xg = round(x - self.XG, 3)
            yg = round(y - self.YG, 3)
            result_array.append(BarraAceroPasivo(xg, yg, d, i))
        return result_array

    def set_rebar_properties(self, def_de_rotura_a_pasivo):
        try:
            tipo = self.ingreso_datos_sheet.get_value("C", "6")
            self.acero_pasivo = tipo
            if tipo == "Provisto por usuario":
                valores = {
                    "tipo": "Provisto por usuario",
                    "fy": self.armaduras_pasivas_sheet.get_value("E", "3")/10,
                    "E": self.armaduras_pasivas_sheet.get_value("E", "4")/10,
                    "eu": self.armaduras_pasivas_sheet.get_value("E", "5")
                }

                if not all(bool(v) for k, v in valores.items()):
                    raise Exception("Usted ha seleccionado Acero Pasivo tipo 'Provisto por usuario'\n"
                                    "Pero no ha ingresado todos los parámetros necesarios. Por favor,"
                                    " diríjase a pestaña 'Armaduras Pasivas' e intentelo de nuevo.")

            else:
                values = BarraAceroPasivo.default_strain_stress_relation_vars.get(tipo)
                for k, v in values.items():
                    self.__setattr__(k, v)
                fy = BarraAceroPasivo.default_strain_stress_relation_vars.get(tipo.upper())["fy"]
                BarraAceroPasivo.E = 20000
                BarraAceroPasivo.tipo = tipo
                BarraAceroPasivo.fy = fy/10
                BarraAceroPasivo.eu = def_de_rotura_a_pasivo
        except Exception:
            raise Exception("No se pudieron setear las propiedades del acero pasivo, revise configuración")

    def _get_prestressed_bars_array(self):
        resultado = MatrizAceroActivo()
        for fila in self._input_reader.get_active_rebar_row_numbers():
            x, y, area, i = self._input_reader.get_rebar_excel_values(fila)
            if area == 0:
                continue
            xg = round(x - self.XG, 3)
            yg = round(y - self.YG, 3)
            resultado.append(BarraAceroPretensado(xg, yg, area, i))
        return resultado

    def setear_propiedades_acero_activo(self, def_de_pretensado_inicial):
        try:
            tipo = self.ingreso_datos_sheet.get_value("C", "8")
            tipo = tipo
            self.acero_activo = tipo
            if tipo == "Provisto por usuario":
                valores = {
                    "tipo": "Provisto por usuario",
                    "Eps": self.armaduras_activas_sheet.get_value("E", "3"),
                    "fpy": self.armaduras_activas_sheet.get_value("E", "4"),
                    "fpu": self.armaduras_activas_sheet.get_value("E", "5"),
                    "epu": self.armaduras_activas_sheet.get_value("E", "6"),
                    "N": self.armaduras_activas_sheet.get_value("E", "7"),
                    "K": self.armaduras_activas_sheet.get_value("E", "8"),
                    "Q": self.armaduras_activas_sheet.get_value("E", "9"),
                    "deformacion_de_pretensado_inicial": def_de_pretensado_inicial
                }

                if not all(bool(v) for k, v in valores.items()):
                    raise Exception("Usted ha seleccionado Acero Pasivo tipo 'Provisto por usuario'\n"
                                    "Pero no ha ingresado todos los parámetros necesarios. Por favor,"
                                    " diríjase a pestaña 'Armaduras Pasivas' e intentelo de nuevo.")

                for k, v in valores.items():
                    if k in ["fpy", "fpu", "Eps"]:
                        v = v / 10  # kN/cm²
                    setattr(BarraAceroPretensado, k, v)

            else:
                values = BarraAceroPretensado.default_strain_stress_relation_vars.get(tipo.upper())
                for k, v in values.items():
                    setattr(BarraAceroPretensado, k, v)
                BarraAceroPretensado.tipo = tipo
                BarraAceroPretensado.Eps = 20000  # kN/cm²
                BarraAceroPretensado.deformacion_de_pretensado_inicial = def_de_pretensado_inicial
            temp_bar = BarraAceroPretensado(0, 0, 0, 0)
            BarraAceroPretensado.fse = temp_bar.stress_strain_eq(temp_bar.deformacion_de_pretensado_inicial)
        except Exception as e:
            raise Exception("No se pudieron establecer las propiedades del acero activo, revise configuración")

    def get_meshed_concrete_section(self):
        concrete_shapes_list = self._input_reader.iter_concrete_regions()
        concrete_polygons = {}
        node_coordinates_list = []
        max_x, min_x = [], []
        max_y, min_y = [], []
        delta_x = []
        delta_y = []
        for i, filas_region in enumerate(concrete_shapes_list):
            sign = self._input_reader.get_contour_matrix_sign(filas_region)
            shape_type = self._input_reader.get_contour_shape_type(filas_region)
            indice = self._input_reader.get_contour_index(filas_region)
            if shape_type == "Poligonal":
                for x, y in self._input_reader.parse_polygon_contour(filas_region):
                    node_coordinates_list.append(Node(round(x, 3), round(y, 3)))  # Medidas en centímetros
                concrete_shape = Region(node_coordinates_list, sign, indice, sort_nodes=True)
                if sign > 0:  # Solo se utilizan los regions positivos para definir la discretización
                    max_x.append(max(concrete_shape.x))
                    min_x.append(min(concrete_shape.x))
                    max_y.append(max(concrete_shape.y))
                    min_y.append(min(concrete_shape.y))
                    delta_x.append(abs(max(concrete_shape.x) - min(concrete_shape.x)))
                    delta_y.append(abs(max(concrete_shape.y) - min(concrete_shape.y)))
                concrete_polygons[str(i + 1)] = concrete_shape
                node_coordinates_list = []
            elif shape_type == "Circular":
                circular_data = self._input_reader.parse_circular_contour(filas_region)
                x = circular_data["center_x"]
                y = circular_data["center_y"]
                r_int = circular_data["r_int"]
                r_ext = circular_data["r_ext"]
                if sign > 0:
                    max_x.append(x + r_ext)
                    min_x.append(x - r_ext)
                    max_y.append(y + r_ext)
                    min_y.append(y - r_ext)
                    delta_x.append(r_ext - r_int)
                    delta_y.append(r_ext - r_int)
                concrete_polygons[str(i + 1)] = CircularRegion(centroid_node=Node(x, y), indice=indice, boundary_radii_list=(r_int, r_ext),
                                                                 sign=sign)
            else:
                pass
        self.max_x_seccion = max(max_x)
        self.min_x_seccion = min(min_x)
        self.max_y_seccion = max(max_y)
        self.min_y_seccion = min(min_y)
        EEH = ArbitraryCrossSection(concrete_polygons, mesh_data=self.get_discretizacion(delta_x, delta_y, concrete_polygons))
        return EEH

    def get_discretizacion(self, delta_x, delta_y, regions):
        hay_region_circular = any(isinstance(v, CircularRegion) for k, v in regions.items())
        hay_region_rectangular = any(not isinstance(x, CircularRegion) for x in regions)
        rows_range = self._input_reader.get_discretization_block_rows()
        nivel_discretizacion = self._input_reader.read_discretization_level(rows_range)
        if nivel_discretizacion == "advanced_manual":
            nivel_discretizacion = "Avanzada (Ingreso Manual)"
        self.nivel_disc = nivel_discretizacion
        if nivel_discretizacion == "Avanzada (Ingreso Manual)":
            dx, dy, d_ang = self._input_reader.read_manual_mesh_inputs(rows_range)
            return (dx if hay_region_rectangular else None,
                    dy if hay_region_rectangular else None,
                    min(dx, dy) if hay_region_circular else None,
                    d_ang if hay_region_circular else None)
        factor_rectangular = 1 / self._input_reader.rectangular_element_partition_dict.get(nivel_discretizacion)
        factor_circular = self._input_reader.niveles_mallado_circular.get(nivel_discretizacion)

        return (factor_rectangular * max(delta_x) if hay_region_rectangular else None,
                factor_rectangular * max(delta_y) if hay_region_rectangular else None,
                factor_circular[0] if hay_region_circular else None,
                factor_circular[1] if hay_region_circular else None)

    def get_baricentric_section_forces(self, ec, phix, phiy):
        ecuacion_plano_deformacion = lambda x, y: ec + math.tan(math.radians(phix)) * (y) + math.tan(
            math.radians(phiy)) * (x)
        sumFA = sumFP = sumFH = 0
        MxA = MxAP = MxH = 0
        MyA = MyAP = MyH = 0
        for barra in self.rebar_array:
            def_elemento, area = ecuacion_plano_deformacion(barra.xg, barra.yg), barra.area
            FA = barra.stress_strain_eq(def_elemento) * area
            sumFA = sumFA + FA
            MxA = FA * barra.yg + MxA
            MyA = -FA * barra.xg + MyA
        for barra_p in self.prestressed_rebar_array:
            deformacion_elastica_hormingon, area = ecuacion_plano_deformacion(barra_p.xg, barra_p.yg), barra_p.area
            deformacion_pretensado_inicial = barra_p.deformacion_de_pretensado_inicial
            deformacion_total = deformacion_elastica_hormingon + deformacion_pretensado_inicial

            Fp = barra_p.stress_strain_eq(deformacion_total) * area
            sumFP = sumFP + Fp
            MxAP = Fp * barra_p.yg + MxAP
            MyAP = -Fp * barra_p.xg + MyAP

        for element in self.concrete_array:
            def_elemento, area = ecuacion_plano_deformacion(element.xg, element.yg), element.area
            F_hor = self.concrete.elastic_stress_strain_eq(def_elemento) * area
            sumFH = sumFH + F_hor
            MxH = F_hor * element.yg + MxH
            MyH = -F_hor * element.xg + MyH

        sumF = sumFA + sumFP + sumFH
        Mx = round(MxA + MxAP + MxH, 8)
        My = round(MyA + MyAP + MyH, 8)

        return [sumF, Mx, My]

    def print_result_tridimensional(self, ec, phix, phiy):
        ec_plano = lambda x, y: ec + math.tan(math.radians(phix)) * y + math.tan(math.radians(phiy)) * x
        self.meshed_section.mostrar_regions_3d(ecuacion_plano_a_desplazar=ec_plano)

    def insertar_valores_2D(self, data_subset, lista_puntos_a_verificar):
        """
        Write 2D interaction results into the workbook. Requires ``workbook_path`` at construction.

        Temporarily replaces ``_input_reader`` with an Excel-backed reader for sheet I/O only.
        """
        if not self.workbook_path:
            raise ValueError("workbook_path was not set; cannot write results to Excel.")
        self.excel_manager = ExcelManager(self.workbook_path, read_only=False, visible=True)
        self._input_reader = ExcelSectionInputReader(self.excel_manager)
        self._bind_sheet_facade_from_reader()
        diagrama_de_interaccion_sheet = self.diagrama_interaccion_sheet
        for k, v in data_subset.items():
            lista_x_total = [(1 if x > 0 else -1 if x!=0 else 1 if y>=0 else -1) * math.sqrt(x ** 2 + y ** 2) for x, y in
                             zip(v["x"], v["y"])].copy()
            list_values = np.array([v["z"], lista_x_total, v["phi"]])
            list_values = list_values.transpose().tolist()

            diagrama_de_interaccion_sheet.change_cell_value_by_range("G1", k)
            diagrama_de_interaccion_sheet.insert_values_vertically("I3", list_values, columns_to_clean=["I", "J", "K"], start_row=3)

            X = [x["M"] for x in lista_puntos_a_verificar]
            Y = [x["P"] for x in lista_puntos_a_verificar]

            puntos_a_verificar = np.array([Y, X]).transpose().tolist()
            diagrama_de_interaccion_sheet.insert_values_vertically("N3", puntos_a_verificar, columns_to_clean=["N", "O"], start_row=3)
            self.excel_manager.close()

    def insertar_valores_3D(self, data_subset):
        """Write 3D interaction block into the ``Resultados 3D`` sheet."""
        if not self.workbook_path:
            raise ValueError("workbook_path was not set; cannot write results to Excel.")
        excel_manager = ExcelManager(self.workbook_path, read_only=False)
        diagrama_de_interaccion_sheet = excel_manager.get_sheet("Resultados 3D")

        i = 0  # contador
        for k, v in data_subset.items():
            list_values = np.array([v["x"], v["y"], v["z"], v["phi"]])
            list_values = list_values.transpose().tolist()
            if i == 0:  # Poniendo el valor de lambda en la primera celda
                diagrama_de_interaccion_sheet.change_cell_value_by_range("A1", f"λ= {k}°")
                diagrama_de_interaccion_sheet.delete_contents_from_column(6)
                diagrama_de_interaccion_sheet.insert_values_vertically("A4", list_values, start_row=4)
                i = i + 1
                continue
            new_range = diagrama_de_interaccion_sheet.calculate_new_range_by_coll_offset("A1:D3", column_offset=5 * i)
            diagrama_de_interaccion_sheet.copy_paste_range("A1:D3", new_range)
            top_bottom_cell = new_range.split(":")[0]
            diagrama_de_interaccion_sheet.change_cell_value_by_range(top_bottom_cell, f"λ= {k} °")
            diagrama_de_interaccion_sheet.insert_values_vertically(
                diagrama_de_interaccion_sheet.shift_cell_by_offset(top_bottom_cell, col_offset=0, row_offset=3),
                list_values,
                start_row=4)
            i = i + 1
        excel_manager.close(save=False)
