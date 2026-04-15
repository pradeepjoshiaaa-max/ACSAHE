"""
Plotly figure for the discretized section (concrete mesh + reinforcement).

Kept separate from :class:`~geometry.section_analysis.ACSAHEGeometricSolution` so the solver
layer does not depend on Plotly.
"""

from __future__ import annotations

import plotly.graph_objects as go


def discretized_section_figure(
    meshed_section,
    rebar_array,
    prestressed_rebar_array,
    bending_plane_angles,
    fig: go.Figure | None = None,
) -> go.Figure:
    """
    Build the 2D Plotly figure of the meshed cross-section and bars.

    Parameters match the data held on a geometric solution after ``build()``.
    """
    x_range = meshed_section.x_max - meshed_section.x_min
    y_range = meshed_section.y_max - meshed_section.y_min
    common_range = max(x_range, y_range) * 1.1

    x_mid = (meshed_section.x_max + meshed_section.x_min) / 2
    y_mid = (meshed_section.y_max + meshed_section.y_min) / 2

    if fig is None:
        fig = go.Figure(layout_template="plotly_white")
    fig.update_yaxes(
        scaleanchor="x",
        scaleratio=1,
    )

    from build.utils.plotly_engine import ACSAHEPlotlyEngine

    plotly_util = ACSAHEPlotlyEngine(fig)
    plotly_util.plot_reinforcement_bars_as_circles(rebar_array, prestressed_rebar_array)

    meshed_section.plotly(fig, bending_plane_angles)

    fig.update_layout(
        xaxis=dict(
            title='<span style="font-size: 20px;">X</span><span style="font-size: 14px;"> baricéntrica</span><span style="font-size: 20px;"> [cm]</span>',
            title_font=dict(family='Times New Roman'),
            showticklabels=True, showgrid=True,
            zeroline=True,
            range=[x_mid - common_range / 2, x_mid + common_range / 2]
        ),
        yaxis=dict(
            title='<span style="font-size: 20px;">Y</span><span style="font-size: 14px;"> baricéntrica</span><span style="font-size: 20px;"> [cm]</span>',
            title_font=dict(family='Times New Roman', size=12),
            zeroline=True,
            showticklabels=True, showgrid=True,
            range=[y_mid - common_range / 2, y_mid + common_range / 2]
        )
    )
    return fig
