"""PDF report generation helpers."""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from config import DATA_SOURCES, DISCLAIMER


def _fmt(value: float | int | None, suffix: str = "") -> str:
    """Format a value safely for reports."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):,.1f}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def build_pdf_report(
    data: dict,
    kpis: dict,
    analysis: dict,
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
) -> bytes:
    """Build a compact PDF report for the current company."""
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        from reportlab.lib import colors
    except ImportError as exc:
        raise RuntimeError(
            "PDF export requires reportlab. Run: python -m pip install reportlab"
        ) from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=36, bottomMargin=36)
    styles = getSampleStyleSheet()
    story = []

    info = data.get("info", {})
    company_name = info.get("longName") or info.get("shortName") or data.get("ticker", "Company")
    currency_code = info.get("financialCurrency") or info.get("currency") or "reported currency"

    story.append(Paragraph(f"{company_name} Financial Analyzer Report", styles["Title"]))
    story.append(Paragraph(f"Reported in: {currency_code}", styles["Normal"]))
    story.append(Paragraph("FY = annual fiscal-year data. TTM = trailing twelve months market data.", styles["Normal"]))
    story.append(Paragraph(DATA_SOURCES, styles["Normal"]))
    story.append(Paragraph(DISCLAIMER, styles["Italic"]))
    story.append(Spacer(1, 16))

    kpi_rows = [
        ["Metric", "Value"],
        ["ROE", _fmt(kpis.get("roe"), "%")],
        ["ROCE", _fmt(kpis.get("roce"), "%")],
        ["P/E (TTM)", _fmt(kpis.get("pe_ratio"), "x")],
        ["EV/EBITDA (TTM)", _fmt(kpis.get("ev_to_ebitda"), "x")],
    ]
    story.append(Paragraph("KPI Dashboard", styles["Heading2"]))
    story.append(_styled_table(kpi_rows, colors))
    story.append(Spacer(1, 12))

    overview = analysis.get("overview", {})
    analysis_rows = [
        ["Metric", "Value"],
        ["Revenue CAGR", _fmt(overview.get("revenue_cagr"), "%")],
        ["EBIT margin change", _fmt(overview.get("ebit_margin_change"), " pp")],
        ["FCF conversion", _fmt(overview.get("fcf_conversion"), "%")],
        ["Net debt / EBITDA", _fmt(overview.get("net_debt_to_ebitda"), "x")],
    ]
    story.append(Paragraph("Analyst Overview", styles["Heading2"]))
    story.append(_styled_table(analysis_rows, colors))
    story.append(Spacer(1, 12))

    story.append(Paragraph("Key Takeaways", styles["Heading2"]))
    for insight in analysis.get("insights", []):
        story.append(Paragraph(f"- {insight}", styles["Normal"]))
    story.append(Spacer(1, 12))

    latest_rows, latest_period = _latest_statement_rows(
        income_metrics, balance_metrics, cash_flow_metrics, currency_code
    )
    if latest_rows:
        story.append(Paragraph(f"Latest Financials - {latest_period}", styles["Heading2"]))
        story.append(_styled_table([["Metric", "Value", "Period"]] + latest_rows, colors))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


def _styled_table(rows: list[list[str]], colors_module):
    """Create a consistent report table."""
    from reportlab.platypus import Table, TableStyle

    table = Table(rows, hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors_module.HexColor("#16213e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors_module.white),
                ("GRID", (0, 0), (-1, -1), 0.25, colors_module.HexColor("#cccccc")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    return table


def _latest_statement_rows(
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    currency_code: str,
) -> tuple[list[list[str]], str]:
    """Collect latest statement values for the PDF."""
    rows = []
    period_source = income_metrics if not income_metrics.empty else balance_metrics if not balance_metrics.empty else cash_flow_metrics
    latest_period = "latest FY"
    if not period_source.empty and "period" in period_source.columns:
        latest_period = str(period_source.iloc[-1].get("period") or latest_period)
    currency_suffix = f" M {currency_code}"
    if not income_metrics.empty:
        latest = income_metrics.iloc[-1]
        rows.extend(
            [
                ["Revenue", _fmt(latest.get("revenue"), currency_suffix), latest_period],
                ["EBIT", _fmt(latest.get("ebit"), currency_suffix), latest_period],
                ["Net income", _fmt(latest.get("net_income"), currency_suffix), latest_period],
            ]
        )
    if not balance_metrics.empty:
        latest = balance_metrics.iloc[-1]
        rows.extend(
            [
                ["Total assets", _fmt(latest.get("total_assets"), currency_suffix), latest_period],
                ["Equity ratio", _fmt(latest.get("equity_ratio"), "%"), latest_period],
                ["Net debt", _fmt(latest.get("net_debt"), currency_suffix), latest_period],
            ]
        )
    if not cash_flow_metrics.empty:
        latest = cash_flow_metrics.iloc[-1]
        rows.append(["Free cash flow", _fmt(latest.get("free_cash_flow"), currency_suffix), latest_period])
    return rows, latest_period
