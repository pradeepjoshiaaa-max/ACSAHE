"""
Numeric preparation for Plotly 3D interaction surfaces.

This module does not import Plotly; it only maps solver output dicts to axis values.
"""

from __future__ import annotations

from typing import Any


def interaction_diagram_points_to_plot_axes(
    list_of_results_2d: list[dict[str, Any]] | None,
):
    """
    Map each 2D interaction point to the (x, y, z, φ) tuples used by the 3D result figure.

    Returns ``None`` if there are no points. Otherwise returns
    ``((x, y, z, phi), colors, is_capped)`` in the same layout as the legacy
    ``ACSAHEGeometricSolution.get_3d_coordinates`` helper.
    """
    if not list_of_results_2d:
        return None
    x_out, y_out, z_out = [], [], []
    color_list = []
    phi_list = []
    is_capped_list = []
    for result in list_of_results_2d:
        x_out.append(-result["Mx"] / 100)  # From kNcm to kNm
        y_out.append(-result["My"] / 100)  # From kNcm to kNm
        z_out.append(-result["sumF"]) # Negative so compression points lye on quadrants I and II
        phi_list.append(result["phi"])
        color = result["color"]
        color_list.append(f"rgb({color[0]},{color[1]},{color[2]})")
        is_capped_list.append(result["is_capped"])

    return (x_out, y_out, z_out, phi_list), color_list, is_capped_list


def accumulate_3d_surface_points(
    geometric_solution,
    *,
    loading_angles_deg: list[float] | None = None,
) -> dict[str, list]:
    """
    Run a uniaxial interaction diagram for each loading angle and concatenate plot-axis points.

    Parameters
    ----------
    geometric_solution
        :class:`~geometry.section_analysis.ACSAHEGeometricSolution` instance.
    loading_angles_deg
        If ``None``, uses ``sorted(geometric_solution.lista_ang_plano_de_carga)`` (same as the GUI loop).
    """
    from interaction_diagram.interaction_diagram_builder import UniaxialInteractionDiagram

    angles = (
        list(loading_angles_deg)
        if loading_angles_deg is not None
        else sorted(geometric_solution.lista_ang_plano_de_carga)
    )
    x_total: list[float] = []
    y_total: list[float] = []
    z_total: list[float] = []
    phi_total: list[float] = []
    for angle in angles:
        partial = UniaxialInteractionDiagram(
            angle if angle != -1 else 0.0,
            geometric_solution,
        )
        packed = interaction_diagram_points_to_plot_axes(partial.interaction_diagram_points_list)
        if packed is None:
            continue
        (xp, yp, zp, phip), _, _ = packed
        x_total.extend(xp)
        y_total.extend(yp)
        z_total.extend(zp)
        phi_total.extend(phip)
    return {"x": x_total, "y": y_total, "z": z_total, "phi": phi_total}
