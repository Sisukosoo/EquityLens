"""Plotly visualizations for financial statement analysis."""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from utils.chart_theme import (
    DARK_SLATE,
    GRID_SUBTLE,
    NEGATIVE_RED,
    PRIMARY_BLUE,
    SLATE_BLUE,
    SUCCESS_GREEN,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    TEXT_TERTIARY,
    TEAL,
    TRANSPARENT,
    apply_chart_theme,
)


PRIMARY_COLOR = PRIMARY_BLUE


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    """Return a numeric series with missing values removed."""
    if frame.empty or column not in frame.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").dropna()


def _cagr(values: pd.Series) -> float | None:
    """Return CAGR percentage from a numeric series."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 2 or clean.iloc[0] in (0, None) or pd.isna(clean.iloc[0]):
        return None
    periods = len(clean) - 1
    if clean.iloc[0] <= 0 or periods <= 0:
        return None
    return ((clean.iloc[-1] / clean.iloc[0]) ** (1 / periods) - 1) * 100


def _latest_yoy(values: pd.Series) -> float | None:
    """Return latest year-over-year growth percentage."""
    clean = pd.to_numeric(values, errors="coerce").dropna()
    if len(clean) < 2 or clean.iloc[-2] in (0, None) or pd.isna(clean.iloc[-2]):
        return None
    return (clean.iloc[-1] / clean.iloc[-2] - 1) * 100


def _fmt_pct(value: float | None) -> str:
    """Format percentage for chart subtitles."""
    if value is None or pd.isna(value):
        return "n/a"
    return f"{value:+.1f}%" if value >= 0 else f"{value:.1f}%"


def revenue_growth_headline(cagr: float | None) -> str:
    """Return revenue headline based on CAGR bands."""
    if cagr is None:
        return "Revenue trend is unclear from available data"
    if cagr < 0:
        return "Revenue is declining across the available period"
    if cagr < 2:
        return "Revenue growth has stalled below 2%"
    if cagr <= 7:
        return "Revenue shows steady growth"
    return "Revenue shows strong growth"


def margin_trajectory_headline(income_metrics: pd.DataFrame) -> str:
    """Return margin headline from first-to-last margin changes."""
    columns = ["gross_margin", "ebitda_margin", "ebit_margin", "net_margin"]
    changes = []
    for column in columns:
        values = _numeric_series(income_metrics, column)
        if len(values) >= 2:
            changes.append(values.iloc[-1] - values.iloc[0])
    if not changes:
        return "Margin trajectory is unclear"
    if all(change > 0 for change in changes):
        return "Margins expanding across the board"
    if all(change < 0 for change in changes):
        return "Margin pressure visible"
    return "Mixed margin trajectory"


def leverage_headline(latest: float | None) -> str:
    """Return leverage headline from latest net debt / EBITDA."""
    if latest is None or pd.isna(latest):
        return "Leverage trend is unavailable"
    if latest < 1:
        return "Conservative leverage profile"
    if latest <= 2:
        return "Moderate leverage profile"
    return "Elevated leverage profile"


def fcf_conversion_headline(latest: float | None) -> str:
    """Return cash conversion headline from latest FCF conversion."""
    if latest is None or pd.isna(latest):
        return "Cash conversion is unavailable"
    if latest >= 80:
        return f"Strong cash conversion: FCF covers {latest:.0f}% of reported earnings"
    if latest >= 50:
        return f"Moderate cash conversion: FCF covers {latest:.0f}% of reported earnings"
    return f"Weak cash conversion: FCF covers only {latest:.0f}% of reported earnings"


def dividend_headline(latest_payout: float | None) -> str:
    """Return dividend sustainability headline from payout ratio."""
    if latest_payout is None or pd.isna(latest_payout):
        return "Dividend sustainability is unclear"
    if latest_payout < 50:
        return "Sustainable dividend with room to grow"
    if latest_payout <= 75:
        return "Healthy payout ratio"
    if latest_payout <= 100:
        return "High payout, watch for cuts"
    return "Dividend exceeds earnings, unsustainable"


def _year_axis(frame: pd.DataFrame) -> list[str]:
    """Return short fiscal year labels to prevent long axis text."""
    if "period" in frame.columns:
        labels = frame["period"].dropna()
        if not labels.empty:
            return frame["period"].fillna("").astype(str).str.split().str[:2].str.join(" ").tolist()
    if "year" in frame.columns:
        years = pd.to_numeric(frame["year"], errors="coerce")
        return [
            f"FY{int(year)}" if pd.notna(year) else str(frame.iloc[index].get("period", ""))
            for index, year in enumerate(years)
        ]
    return frame["year"].astype(str).tolist()


def _period_value_columns(frame: pd.DataFrame, value_column: str) -> list[str]:
    """Return existing period columns plus the requested value column."""
    columns = ["year", value_column]
    if "period" in frame.columns:
        columns.insert(1, "period")
    return columns


def _empty_chart(title: str) -> go.Figure:
    """Return an empty chart with a helpful annotation."""
    fig = go.Figure()
    fig.add_annotation(
        text="No data available",
        x=0.5,
        y=0.5,
        showarrow=False,
        font={"size": 16, "color": TEXT_TERTIARY},
    )
    return apply_chart_theme(fig, title)


def create_sparkline(frame: pd.DataFrame, column: str, color: str = PRIMARY_COLOR) -> go.Figure:
    """Create a tiny KPI sparkline."""
    if frame.empty or column not in frame.columns:
        return go.Figure()

    chart_data = frame[["year", column]].copy()
    chart_data[column] = pd.to_numeric(chart_data[column], errors="coerce")
    chart_data = chart_data.dropna(subset=[column])

    fig = go.Figure()
    if not chart_data.empty:
        fig.add_trace(
            go.Scatter(
                x=_year_axis(chart_data),
                y=chart_data[column],
                mode="lines",
                line={"color": color, "width": 2.5},
                hoverinfo="skip",
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        height=70,
        margin={"l": 0, "r": 0, "t": 2, "b": 0},
        xaxis={"visible": False},
        yaxis={"visible": False},
        showlegend=False,
    )
    return fig


def create_revenue_chart(
    income_metrics: pd.DataFrame,
    currency_code: str = "reported currency",
    sector_growth_median: float | None = None,
) -> go.Figure:
    """Create a revenue development bar and trend chart."""
    if income_metrics.empty or "revenue" not in income_metrics:
        return _empty_chart("Revenue development")

    chart_data = income_metrics[_period_value_columns(income_metrics, "revenue")].copy()
    chart_data["revenue"] = pd.to_numeric(chart_data["revenue"], errors="coerce")
    chart_data = chart_data.dropna(subset=["revenue"])
    if chart_data.empty:
        return _empty_chart("Revenue development")

    years = _year_axis(chart_data)
    revenue = pd.to_numeric(chart_data["revenue"], errors="coerce")
    yoy = revenue.pct_change() * 100
    cagr = _cagr(revenue)
    latest_yoy = _latest_yoy(revenue)
    subtitle = f"{years[0]}-{years[-1]} CAGR: {_fmt_pct(cagr)} | Latest YoY: {_fmt_pct(latest_yoy)}"
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=revenue.tolist(),
            name="Revenue",
            marker={"color": TEAL, "line": {"width": 0}},
            hovertemplate=f"%{{x}}<br>Revenue: %{{y:,.1f}} M {currency_code}<extra></extra>",
        )
    )
    for index, (year, value, growth) in enumerate(zip(years, revenue, yoy)):
        if index == 0 or pd.isna(growth):
            continue
        if sector_growth_median is None:
            color = TEXT_TERTIARY
        elif growth > sector_growth_median + 1:
            color = SUCCESS_GREEN
        elif growth < sector_growth_median - 1:
            color = NEGATIVE_RED
        else:
            color = TEXT_TERTIARY
        fig.add_annotation(
            x=year,
            y=value,
            text=_fmt_pct(float(growth)),
            showarrow=False,
            yshift=10,
            font={"color": color, "size": 11},
            xanchor="center",
            yanchor="bottom",
        )
    fig.update_layout(showlegend=False)
    fig.update_yaxes(rangemode="tozero")
    if len(revenue.dropna()) > 0:
        fig.update_yaxes(range=[0, float(revenue.max()) * 1.16])
    return apply_chart_theme(fig, revenue_growth_headline(cagr), subtitle=subtitle, height=420)


def create_margin_chart(
    income_metrics: pd.DataFrame,
    industry_medians: dict[str, float] | None = None,
) -> go.Figure:
    """Create a line chart for key margins."""
    margin_columns = {
        "gross_margin": ("Gross margin", TEXT_SECONDARY),
        "ebitda_margin": ("EBITDA margin", SUCCESS_GREEN),
        "ebit_margin": ("EBIT margin", SLATE_BLUE),
        "net_margin": ("Net margin", TEXT_TERTIARY),
    }
    if income_metrics.empty:
        return _empty_chart("Margins")

    fig = go.Figure()
    latest_labels = []
    for column, (label, color) in margin_columns.items():
        if column not in income_metrics:
            continue

        trace_data = income_metrics[["year", column]].copy()
        trace_data[column] = pd.to_numeric(trace_data[column], errors="coerce")
        trace_data[column] = trace_data[column].where(trace_data[column].abs() <= 200)
        trace_data = trace_data.dropna(subset=[column])
        if trace_data.empty:
            continue
        trace_years = _year_axis(trace_data)
        values = trace_data[column]
        fig.add_trace(
            go.Scatter(
                x=trace_years,
                y=values.tolist(),
                mode="lines+markers",
                name=label,
                line={"color": color, "width": 3},
                marker={"size": 8, "color": color},
                hovertemplate=f"%{{x}}<br>{label}: %{{y:.1f}}%<extra></extra>",
            )
        )
        latest_labels.append((trace_years[-1], float(values.iloc[-1]), label.split()[0], color))

    sorted_labels = sorted(latest_labels, key=lambda item: item[1])
    middle = (len(sorted_labels) - 1) / 2 if sorted_labels else 0
    offset_by_label = {
        label: int((index - middle) * 12)
        for index, (_x, _value, label, _color) in enumerate(sorted_labels)
    }
    for latest_x, latest_value, label, color in latest_labels:
        fig.add_annotation(
            x=latest_x,
            y=latest_value,
            text=f"{label} {latest_value:.1f}%",
            showarrow=False,
            xshift=34,
            yshift=offset_by_label.get(label, 0),
            font={"color": color, "size": 11},
            xanchor="left",
        )

    if industry_medians:
        benchmark = industry_medians.get("ebitda_margin") or industry_medians.get("ebit_margin")
        if benchmark is not None:
            fig.add_hline(
                y=benchmark,
                line={"color": TEXT_TERTIARY, "dash": "dash", "width": 1},
                annotation_text=f"Industry median: {benchmark:.1f}%",
                annotation_position="right",
                annotation_font={"color": TEXT_TERTIARY, "size": 11},
            )

    fig.update_yaxes(ticksuffix="%", rangemode="normal")
    subtitle_parts = []
    for column, (label, _color) in margin_columns.items():
        values = _numeric_series(income_metrics, column)
        if not values.empty:
            subtitle_parts.append(f"{label}: {values.iloc[-1]:.1f}%")
    fig.update_layout(showlegend=False)
    themed = apply_chart_theme(
        fig,
        margin_trajectory_headline(income_metrics),
        subtitle=" | ".join(subtitle_parts[:3]),
        height=420,
    )
    themed.update_layout(showlegend=False, margin={**themed.layout.margin.to_plotly_json(), "r": 90})
    return themed


def create_balance_structure_chart(
    balance_metrics: pd.DataFrame,
    income_metrics: pd.DataFrame | None = None,
    currency_code: str = "reported currency",
) -> go.Figure:
    """Create a leverage trend chart using net debt / EBITDA."""
    if (
        balance_metrics.empty
        or income_metrics is None
        or income_metrics.empty
        or "net_debt" not in balance_metrics.columns
        or "ebitda" not in income_metrics.columns
    ):
        return _empty_chart("Leverage trend")

    chart_data = balance_metrics[["year", "net_debt"]].merge(
        income_metrics[["year", "ebitda"]],
        on="year",
        how="inner",
    )
    chart_data["net_debt_to_ebitda"] = (
        pd.to_numeric(chart_data["net_debt"], errors="coerce")
        / pd.to_numeric(chart_data["ebitda"], errors="coerce")
    )
    chart_data = chart_data.replace([float("inf"), float("-inf")], pd.NA)
    chart_data = chart_data.dropna(subset=["net_debt_to_ebitda"])
    if chart_data.empty:
        return _empty_chart("Leverage trend")

    years = _year_axis(chart_data)
    values = pd.to_numeric(chart_data["net_debt_to_ebitda"], errors="coerce")
    latest = float(values.iloc[-1])
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=years,
            y=values,
            name="Net debt / EBITDA",
            mode="lines+markers",
            line={"color": TEAL, "width": 2.5},
            marker={"size": 7, "color": TEAL},
            hovertemplate="%{x}<br>Net debt / EBITDA: %{y:.2f}x<extra></extra>",
        )
    )
    fig.add_hline(
        y=2.0,
        line={"color": TEXT_TERTIARY, "dash": "dash", "width": 1},
        annotation_text="Reference limit: 2.0x",
        annotation_position="right",
        annotation_font={"color": TEXT_TERTIARY, "size": 11},
    )
    fig.add_annotation(
        x=years[-1],
        y=latest,
        text=f"{latest:.2f}x",
        showarrow=False,
        xshift=28,
        font={"color": TEAL, "size": 11},
        xanchor="left",
    )
    fig.update_yaxes(ticksuffix="x")
    return apply_chart_theme(
        fig,
        leverage_headline(latest),
        subtitle=f"Latest net debt / EBITDA: {latest:.2f}x | Reference limit: 2.0x",
        height=460,
    )


def create_cash_flow_chart(
    cash_flow_metrics: pd.DataFrame,
    income_metrics: pd.DataFrame | None = None,
    currency_code: str = "reported currency",
) -> go.Figure:
    """Create a grouped bar chart for operating cash flow, capex, and FCF."""
    if cash_flow_metrics.empty:
        return _empty_chart("Cash flow")

    chart_data = cash_flow_metrics.copy()
    needed = ["operating_cash_flow", "capital_expenditure", "free_cash_flow"]
    chart_data = chart_data.dropna(subset=[column for column in needed if column in chart_data.columns], how="all")
    if chart_data.empty:
        return _empty_chart("Cash flow")

    if income_metrics is not None and not income_metrics.empty and "net_income" in income_metrics.columns:
        chart_data = chart_data.merge(income_metrics[["year", "net_income"]], on="year", how="left")
        chart_data["fcf_conversion"] = (
            pd.to_numeric(chart_data["free_cash_flow"], errors="coerce")
            / pd.to_numeric(chart_data["net_income"], errors="coerce")
            * 100
        )

    years = _year_axis(chart_data)
    fig = go.Figure()
    series = [
        ("operating_cash_flow", "Operating cash flow", TEAL),
        ("capital_expenditure", "Capital expenditure", "rgba(239,68,68,0.6)"),
        ("free_cash_flow", "Free cash flow", "rgba(59,155,138,0.75)"),
    ]
    for column, label, color in series:
        if column in chart_data:
            fig.add_trace(
                go.Bar(
                    x=years,
                    y=chart_data[column],
                    name=label,
                    marker_color=color,
                    hovertemplate=f"%{{x}}<br>{label}: %{{y:,.1f}} M {currency_code}<extra></extra>",
                )
            )

    latest_conversion = None
    if "fcf_conversion" in chart_data.columns:
        conversion_values = pd.to_numeric(chart_data["fcf_conversion"], errors="coerce")
        clean_conversion = conversion_values.dropna()
        if not clean_conversion.empty:
            latest_conversion = float(clean_conversion.iloc[-1])
            conversion_color = SUCCESS_GREEN if latest_conversion >= 80 else "#f59e0b" if latest_conversion >= 50 else NEGATIVE_RED
            fig.add_trace(
                go.Scatter(
                    x=years,
                    y=conversion_values,
                    name="FCF conversion",
                    mode="lines+markers",
                    yaxis="y2",
                    line={"color": conversion_color, "width": 2},
                    marker={"size": 5, "color": conversion_color},
                    hovertemplate="%{x}<br>FCF conversion: %{y:.1f}%<extra></extra>",
                )
            )
            fig.update_layout(
                yaxis2={
                    "overlaying": "y",
                    "side": "right",
                    "ticksuffix": "%",
                    "gridcolor": "rgba(0,0,0,0)",
                    "title_text": None,
                    "tickfont": {"color": TEXT_SECONDARY, "size": 12},
                }
            )

    fig.add_hline(y=0, line_color=GRID_SUBTLE, line_width=1)
    fig.update_layout(barmode="group")
    subtitle = ""
    if latest_conversion is not None:
        subtitle = f"Latest FCF conversion: {latest_conversion:.1f}% | FCF / net income"
    return apply_chart_theme(
        fig,
        fcf_conversion_headline(latest_conversion),
        subtitle=subtitle,
        height=460,
    )


def create_dividend_chart(dividend_metrics: pd.DataFrame, currency_code: str = "reported currency") -> go.Figure:
    """Create dividend per share and payout ratio chart."""
    if dividend_metrics.empty:
        return _empty_chart("Dividend history")

    chart_data = dividend_metrics.dropna(subset=["dividend_per_share"], how="all").copy()
    if chart_data.empty:
        return _empty_chart("Dividend history")

    years = _year_axis(chart_data)
    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=years,
            y=chart_data["dividend_per_share"],
            name="Dividend per share",
            marker_color=SLATE_BLUE,
            hovertemplate=f"%{{x}}<br>DPS: %{{y:.2f}} {currency_code}<br>%{{customdata}}<extra></extra>",
            customdata=[
                "Current-year dividend is year-to-date" if "YTD" in str(period) else "Annual dividend"
                for period in chart_data.get("period", pd.Series([""] * len(chart_data)))
            ],
        )
    )
    latest_payout = None
    if "payout_ratio" in chart_data.columns:
        payout = pd.to_numeric(chart_data["payout_ratio"], errors="coerce")
        clean_payout = payout.dropna()
        if not clean_payout.empty:
            latest_payout = float(clean_payout.iloc[-1])
        fig.add_trace(
            go.Scatter(
                x=years,
                y=payout,
                name="Payout ratio",
                mode="lines+markers",
                yaxis="y2",
                line={"color": SUCCESS_GREEN, "width": 2},
                marker={"size": 5, "color": SUCCESS_GREEN},
                hovertemplate="%{x}<br>Payout ratio: %{y:.1f}%<extra></extra>",
            )
        )

    fig.update_layout(
        yaxis2={
            "overlaying": "y",
            "side": "right",
            "ticksuffix": "%",
            "gridcolor": "rgba(0,0,0,0)",
            "title_text": None,
            "tickfont": {"color": TEXT_SECONDARY, "size": 12},
        }
    )
    fig.update_yaxes(title_text=None)
    latest_dps = _numeric_series(chart_data, "dividend_per_share")
    subtitle_parts = []
    if not latest_dps.empty:
        subtitle_parts.append(f"Latest DPS: {latest_dps.iloc[-1]:.2f} {currency_code}")
    if latest_payout is not None:
        subtitle_parts.append(f"Latest payout ratio: {latest_payout:.1f}%")
    return apply_chart_theme(
        fig,
        dividend_headline(latest_payout),
        subtitle=" | ".join(subtitle_parts),
        height=460,
    )


def create_earnings_surprise_chart(surprise_metrics: pd.DataFrame) -> go.Figure:
    """Create EPS estimate vs actual and surprise chart."""
    if surprise_metrics.empty:
        return _empty_chart("Revenue and earnings surprise")

    fig = go.Figure()
    colors = [
        SUCCESS_GREEN if value >= 0 else NEGATIVE_RED
        for value in surprise_metrics["surprise_pct"].fillna(0)
    ]
    fig.add_trace(
        go.Bar(
            x=surprise_metrics["period"],
            y=surprise_metrics["surprise_pct"],
            name="EPS surprise",
            marker_color=colors,
            hovertemplate="%{x}<br>Surprise: %{y:.1f}%<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_color=GRID_SUBTLE, line_width=1)
    fig.update_yaxes(ticksuffix="%")
    return apply_chart_theme(fig, "Earnings surprise vs analyst EPS estimate", height=420)


def create_radar_comparison_chart(comparison_frame: pd.DataFrame) -> go.Figure:
    """Create a radar chart comparing six normalized metrics."""
    if comparison_frame.empty or len(comparison_frame) < 2:
        return _empty_chart("Radar comparison")

    metrics = {
        "roe": "ROE",
        "roce": "ROCE",
        "pe_ratio": "P/E",
        "ev_to_ebitda": "EV/EBITDA",
        "ebit_margin": "EBIT margin",
        "leverage": "Leverage",
    }
    available = [metric for metric in metrics if metric in comparison_frame.columns]
    if not available:
        return _empty_chart("Radar comparison")

    normalized = comparison_frame.copy()
    for metric in available:
        values = pd.to_numeric(normalized[metric], errors="coerce")
        if values.dropna().empty or values.max() == values.min():
            normalized[metric] = 50
            continue
        if metric in {"pe_ratio", "ev_to_ebitda", "leverage"}:
            normalized[metric] = (values.max() - values) / (values.max() - values.min()) * 100
        else:
            normalized[metric] = (values - values.min()) / (values.max() - values.min()) * 100

    fig = go.Figure()
    theta = [metrics[metric] for metric in available]
    theta.append(theta[0])
    colors = [TEAL, SLATE_BLUE, PRIMARY_BLUE]
    for index, row in normalized.iterrows():
        values = [row.get(metric) for metric in available]
        values.append(values[0])
        fig.add_trace(
            go.Scatterpolar(
                r=values,
                theta=theta,
                fill="toself",
                name=row.get("ticker", f"Company {index + 1}"),
                line_color=colors[index % len(colors)],
            )
        )

    fig.update_layout(
        polar={
            "bgcolor": TRANSPARENT,
            "radialaxis": {
                "visible": True,
                "range": [0, 100],
                "gridcolor": GRID_SUBTLE,
                "tickfont": {"color": TEXT_SECONDARY},
            },
            "angularaxis": {"gridcolor": GRID_SUBTLE, "tickfont": {"color": TEXT_PRIMARY}},
        }
    )
    return apply_chart_theme(fig, "Normalized peer radar comparison", height=520)
