"""Shared Plotly theme settings for the Streamlit dashboard charts."""

from __future__ import annotations

import plotly.graph_objects as go


PRIMARY_BLUE = "#3b82f6"
TEAL = "#3b9b8a"
SLATE_BLUE = "#64748b"
DARK_SLATE = "#475569"
SUCCESS_GREEN = "#10b981"
NEGATIVE_RED = "rgba(239,68,68,0.7)"
TEXT_PRIMARY = "#ededf0"
TEXT_SECONDARY = "#a1a1aa"
TEXT_TERTIARY = "#71717a"
GRID_SUBTLE = "rgba(255,255,255,0.04)"
TRANSPARENT = "rgba(0,0,0,0)"


def apply_chart_theme(
    fig: go.Figure,
    title: str,
    subtitle: str | None = None,
    height: int = 430,
    legend_position: str = "bottom",
) -> go.Figure:
    """Apply one consistent, restrained Plotly style to dashboard charts."""
    legend = {
        "orientation": "h",
        "bgcolor": TRANSPARENT,
        "bordercolor": TRANSPARENT,
        "font": {"color": TEXT_SECONDARY, "size": 12},
        "x": 0,
        "xanchor": "left",
    }
    safe_subtitle = "" if subtitle is None else str(subtitle).strip()
    margin = {"l": 20, "r": 40, "t": 92 if safe_subtitle else 68, "b": 76}
    if legend_position == "bottom":
        legend.update({"y": -0.18, "yanchor": "top"})
        margin["b"] = 76
    else:
        legend.update({"y": 1.04, "yanchor": "bottom"})
        margin["t"] = 92 if safe_subtitle else 68
        margin["b"] = 40

    fig.update_layout(
        title={"text": ""},
        template="plotly_dark",
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        font={"color": TEXT_SECONDARY, "size": 12, "family": "Inter, sans-serif"},
        height=height,
        margin=margin,
        legend=legend,
        hovermode="x unified",
        hoverlabel={
            "bgcolor": "#1a1a24",
            "bordercolor": "rgba(255,255,255,0.12)",
            "font": {"color": TEXT_PRIMARY, "size": 12, "family": "Inter, sans-serif"},
        },
        bargap=0.3,
    )
    fig.update_xaxes(
        showgrid=False,
        zeroline=False,
        title_text=None,
        tickangle=0,
        tickfont={"color": TEXT_SECONDARY, "size": 12},
        type="category",
    )
    fig.update_yaxes(
        showgrid=True,
        gridcolor=GRID_SUBTLE,
        zerolinecolor=GRID_SUBTLE,
        title_text=None,
        tickfont={"color": TEXT_SECONDARY, "size": 12},
    )
    fig.add_annotation(
        text=f"<b>{title}</b>",
        x=0,
        y=1.18 if safe_subtitle else 1.10,
        xref="paper",
        yref="paper",
        showarrow=False,
        xanchor="left",
        yanchor="bottom",
        font={"color": TEXT_PRIMARY, "size": 18, "family": "Inter, sans-serif"},
    )
    if safe_subtitle:
        fig.add_annotation(
            text=safe_subtitle,
            x=0,
            y=1.08,
            xref="paper",
            yref="paper",
            showarrow=False,
            xanchor="left",
            yanchor="bottom",
            font={"color": TEXT_TERTIARY, "size": 13, "family": "Inter, sans-serif"},
        )
    return fig
