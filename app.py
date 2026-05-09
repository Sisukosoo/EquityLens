"""Streamlit application for financial statement analysis."""

from __future__ import annotations

from html import escape
import pandas as pd
import streamlit as st
import subprocess
import sys
from pathlib import Path

from config import (
    APP_TAGLINE,
    APP_TITLE,
    COLORS,
    DAMODARAN_MARGINAL_TAX_RATE_EUROPE,
    DAMODARAN_MARGINAL_TAX_RATE_USA,
    DATA_SOURCES,
    DISCLAIMER,
    PLOTLY_CONFIG,
    current_timestamp,
)
from utils.calculations import (
    build_analysis_summary,
    build_balance_sheet_metrics,
    build_cash_flow_metrics,
    build_dividend_metrics,
    build_earnings_surprise_metrics,
    build_income_statement_metrics,
    build_kpi_history,
    build_kpi_metrics,
    build_scenario_projection,
    compare_companies,
)
from utils.fetcher import FinancialDataError, fetch_company_financials
from utils.damodaran import BETA_URLS, INDUSTRY_WHITELIST, build_beta_match
from utils.excel_report import build_valuation_excel_report
from utils.sanity_checks import INCOMPATIBLE_BUSINESS_MODEL_SECTOR_FRAGMENTS, run_sanity_checks
from utils.validation import (
    COE_GLOBAL_URL,
    COUNTRY_PREMIUM_URL,
    TAX_RATE_URL,
    WACC_URLS,
    get_damodaran_industry_cost_of_debt,
    get_damodaran_industry_cost_of_debt_details,
    validate_against_damodaran,
)
from utils.valuation import (
    DEFAULT_TERMINAL_GROWTH,
    DCF_CAPEX_URLS,
    DCF_MARGIN_URLS,
    FALLBACK_DCF_MAX_DEVIATION,
    MARKET_RISK_PREMIUM,
    MULTIPLE_EV_EBITDA_URLS,
    MULTIPLE_EV_SALES_URLS,
    MULTIPLE_PB_URLS,
    STANDARD_DCF_MAX_DEVIATION,
    build_valuation_result,
    fetch_risk_free_rate,
)
from utils.reporting import build_pdf_report
from utils.visualizations import (
    create_balance_structure_chart,
    create_cash_flow_chart,
    create_comparison_chart,
    create_dividend_chart,
    create_earnings_surprise_chart,
    create_margin_chart,
    create_radar_comparison_chart,
    create_revenue_chart,
)


st.set_page_config(
    page_title=APP_TITLE,
    page_icon=":bar_chart:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def format_large_number(value: float | int | None, suffix: str = "M") -> str:
    """Format large monetary values in millions for display."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return "N/A"
    if numeric_value == 0:
        return "0"
    return f"{numeric_value:,.1f} {suffix}".replace(",", " ")


def reporting_currency(data: dict) -> str:
    """Return the company's reported financial currency code."""
    info = data.get("info", {})
    return info.get("financialCurrency") or info.get("currency") or "reported currency"


def money_suffix(currency_code: str) -> str:
    """Return the suffix used for financial statement values in millions."""
    return f"M {currency_code}"


def latest_fy_label(frame: pd.DataFrame) -> str:
    """Return the latest fiscal year label from a metric frame."""
    if frame.empty:
        return "latest FY"
    if "period" in frame.columns and pd.notna(frame.iloc[-1].get("period")):
        return str(frame.iloc[-1]["period"]).split(" ")[0]
    if "year" in frame.columns and pd.notna(frame.iloc[-1].get("year")):
        return f"FY{int(frame.iloc[-1]['year'])}"
    return "latest FY"


def latest_period_label(frame: pd.DataFrame) -> str:
    """Return the latest detailed fiscal period label from a metric frame."""
    if frame.empty:
        return "latest FY"
    if "period" in frame.columns and pd.notna(frame.iloc[-1].get("period")):
        return str(frame.iloc[-1]["period"])
    return latest_fy_label(frame)


def format_percentage(value: float | int | None) -> str:
    """Format a ratio value as a percentage."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "N/A"


def format_percentage_points(value: float | int | None) -> str:
    """Format a percentage point change."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):+.1f} pp"
    except (TypeError, ValueError):
        return "N/A"


def format_multiple(value: float | int | None) -> str:
    """Format valuation multiples."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):.1f}x"
    except (TypeError, ValueError):
        return "N/A"


def format_share_price(value: float | int | None, currency_code: str) -> str:
    """Format a per-share valuation output."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):.2f} {currency_code}"
    except (TypeError, ValueError):
        return "N/A"


def clamped_implied_price(raw_value: float | int | None) -> tuple[float | None, bool]:
    """Return visible implied price clamped at zero plus whether clamping occurred."""
    if raw_value is None or pd.isna(raw_value):
        return None, False
    numeric_value = float(raw_value)
    return max(0.0, numeric_value), numeric_value < 0


def _coerce_benchmark_percent(value) -> float | None:
    """Normalize benchmark-like values to display percentages."""
    if value is None or pd.isna(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if abs(number) <= 1:
        return number * 100
    return number


def _find_row_benchmark(row_data: dict, fragments: list[str]) -> float | None:
    """Find a benchmark value from a Damodaran row by loose column-name fragments."""
    normalized_fragments = [fragment.lower() for fragment in fragments]
    for key, value in (row_data or {}).items():
        key_text = str(key).lower()
        if all(fragment in key_text for fragment in normalized_fragments):
            return _coerce_benchmark_percent(value)
    return None


def extract_chart_benchmarks(beta_match) -> dict[str, float]:
    """Extract optional chart benchmark values from the matched Damodaran row."""
    if beta_match is None:
        return {}
    row_data = getattr(beta_match, "row_data", {}) or {}
    candidates = {
        "revenue_growth": [["revenue", "growth"], ["sales", "growth"]],
        "ebitda_margin": [["ebitda", "margin"], ["ebitda", "sales"]],
        "ebit_margin": [["operating", "margin"], ["ebit", "margin"]],
        "net_margin": [["net", "margin"]],
        "roe": [["roe"], ["return", "equity"]],
    }
    benchmarks = {}
    for name, fragment_sets in candidates.items():
        for fragments in fragment_sets:
            value = _find_row_benchmark(row_data, fragments)
            if value is not None and abs(value) <= 200:
                benchmarks[name] = value
                break
    return benchmarks


def _find_row_benchmark_with_key(row_data: dict, fragments: list[str]) -> tuple[str | None, float | None]:
    """Find a benchmark value and the Damodaran source column that supplied it."""
    normalized_fragments = [fragment.lower() for fragment in fragments]
    for key, value in (row_data or {}).items():
        key_text = str(key).lower()
        if all(fragment in key_text for fragment in normalized_fragments):
            normalized_value = _coerce_benchmark_percent(value)
            if normalized_value is not None:
                return str(key), normalized_value
    return None, None


def trailing_cagr(frame: pd.DataFrame, column: str, years: int = 3) -> float | None:
    """Calculate a small UI-only trailing CAGR from an existing metric frame."""
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna().tail(years + 1)
    if len(values) < 2 or values.iloc[0] <= 0:
        return None
    periods = len(values) - 1
    return ((values.iloc[-1] / values.iloc[0]) ** (1 / periods) - 1) * 100


def net_debt_display(value: float | int | None, suffix: str) -> tuple[str, str, str | None]:
    """Return a clear net debt/net cash label, formatted value, and tooltip."""
    if value is None or pd.isna(value):
        return "Net debt", "N/A", None
    numeric_value = float(value)
    if numeric_value < 0:
        return (
            "Net cash",
            format_large_number(abs(numeric_value), suffix),
            "Negative net debt indicates net cash position",
        )
    return "Net debt", format_large_number(numeric_value, suffix), None


def net_debt_to_ebitda_display(value: float | int | None, fy_label: str) -> tuple[str, str, str | None]:
    """Return a clear net debt/net cash to EBITDA metric label and formatted value."""
    if value is None or pd.isna(value):
        return f"Net debt / EBITDA ({fy_label})", "N/A", None
    numeric_value = float(value)
    if numeric_value < 0:
        return (
            f"Net cash / EBITDA ({fy_label})",
            format_multiple(abs(numeric_value)),
            "Negative net debt indicates net cash position",
        )
    return f"Net debt / EBITDA ({fy_label})", format_multiple(numeric_value), None


def format_plain_number(value: float | int | None) -> str:
    """Format plain numeric analysis values."""
    if value is None or pd.isna(value):
        return "N/A"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return "N/A"


def info_icon(tooltip: str) -> str:
    """Return a Lucide-style info icon with a custom tooltip."""
    return (
        '<span class="info-wrap" aria-label="Info">'
        '<svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="2">'
        '<circle cx="12" cy="12" r="10"></circle><path d="M12 16v-4"></path><path d="M12 8h.01"></path>'
        f'</svg><span class="tooltip-panel">{escape(tooltip)}</span></span>'
    )


def _sparkline_svg(values: list[float], positive: bool = True) -> str:
    """Render a compact inline SVG sparkline with subtle gradient fill."""
    clean_values = [float(value) for value in values if value is not None and not pd.isna(value)]
    color = "#10b981" if positive else "#ef4444"
    if len(clean_values) < 2:
        return f'<svg class="sparkline" viewBox="0 0 160 40" preserveAspectRatio="none"><line x1="0" y1="28" x2="160" y2="28" stroke="{color}" stroke-width="2" opacity="0.35"/></svg>'
    min_value = min(clean_values)
    max_value = max(clean_values)
    spread = max(max_value - min_value, 1e-9)
    points = []
    for index, value in enumerate(clean_values):
        x = index / (len(clean_values) - 1) * 160
        y = 34 - ((value - min_value) / spread * 28)
        points.append((x, y))
    line_points = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    area_points = f"0,40 {line_points} 160,40"
    gradient_id = f"g{abs(hash(tuple(round(value, 4) for value in clean_values))) % 1_000_000}"
    return (
        f'<svg class="sparkline" viewBox="0 0 160 40" preserveAspectRatio="none">'
        f'<defs><linearGradient id="{gradient_id}" x1="0" x2="0" y1="0" y2="1">'
        f'<stop offset="0%" stop-color="{color}" stop-opacity="0.15"/>'
        f'<stop offset="100%" stop-color="{color}" stop-opacity="0"/></linearGradient></defs>'
        f'<polygon points="{area_points}" fill="url(#{gradient_id})"/>'
        f'<polyline points="{line_points}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>'
        '</svg>'
    )


def _status_pill(status: str) -> str:
    """Render a restrained status pill."""
    status_text = escape(str(status))
    status_lower = str(status).lower()
    class_name = "pill"
    if "strong" in status_lower or "ok" in status_lower:
        class_name += " pill-green"
    elif "watch" in status_lower or "review" in status_lower:
        class_name += " pill-amber"
    elif "weak" in status_lower or "check" in status_lower:
        class_name += " pill-red"
    return f'<span class="{class_name}">{status_text}</span>'


@st.cache_data(ttl=60 * 60)
def load_financial_data(ticker: str) -> dict:
    """Fetch and cache financial data for one ticker."""
    return fetch_company_financials(ticker)


def apply_custom_theme() -> None:
    """Apply a restrained professional finance dashboard theme."""
    st.markdown(
        f"""
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

            :root {{
                --page: #0a0a0f;
                --card: #1a1a24;
                --card-soft: rgba(26,26,36,0.72);
                --border-subtle: rgba(255,255,255,0.06);
                --border-strong: rgba(255,255,255,0.12);
                --text: #ededf0;
                --secondary: #a1a1aa;
                --tertiary: #71717a;
                --green: #10b981;
                --amber: #f59e0b;
                --red: #ef4444;
                --brand: #3b82f6;
            }}

            html, body, [class*="css"] {{
                font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-variant-numeric: tabular-nums;
            }}

            .stApp {{
                background: var(--page);
                color: var(--text);
            }}

            [data-testid="stMainBlockContainer"] {{
                max-width: 1400px;
                padding: 48px 32px 32px;
            }}

            h1 {{
                font-size: 36px;
                line-height: 1.1;
                font-weight: 600;
                letter-spacing: 0;
                color: var(--text);
            }}

            h2, h3 {{
                color: var(--text);
                font-size: 20px;
                line-height: 1.25;
                font-weight: 600;
                letter-spacing: 0;
                margin-top: 32px;
            }}

            p, .stCaption, [data-testid="stCaptionContainer"] {{
                color: var(--secondary);
            }}

            [data-testid="stSidebar"] {{
                background: #0d0d14;
                border-right: 1px solid var(--border-subtle);
                width: 280px !important;
                min-width: 280px !important;
            }}

            [data-testid="stSidebar"] [data-testid="stSidebarContent"] {{
                padding: 28px 18px;
            }}

            [data-testid="stSidebar"] h2,
            [data-testid="stSidebar"] h3 {{
                font-size: 13px;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                color: var(--tertiary);
                margin-bottom: 12px;
            }}

            [data-testid="stSidebar"] input,
            [data-testid="stSidebar"] [data-baseweb="select"] > div {{
                background: #111119;
                color: var(--text);
                border: 1px solid var(--border-strong);
                border-radius: 6px;
                min-height: 40px;
            }}

            [data-testid="stSidebar"] .stButton > button {{
                width: 100%;
                min-height: 50px;
                height: auto;
                padding: 8px 12px;
                border-radius: 6px;
                border: 1px solid rgba(59,130,246,0.72) !important;
                background: #3b82f6 !important;
                color: #ffffff !important;
                font-weight: 600 !important;
                line-height: 1.25 !important;
                box-shadow: none !important;
                opacity: 1 !important;
            }}

            [data-testid="stSidebar"] .stButton > button p,
            [data-testid="stSidebar"] .stButton > button span,
            [data-testid="stSidebar"] .stButton > button div {{
                color: #ffffff !important;
                font-weight: 600 !important;
                line-height: 1.25 !important;
                opacity: 1 !important;
            }}

            [data-testid="stSidebar"] .stButton > button:hover {{
                background: #2563eb !important;
                border-color: rgba(59,130,246,0.92) !important;
                color: #ffffff !important;
            }}

            [data-testid="stSidebar"] .stButton > button:disabled {{
                background: rgba(59,130,246,0.18) !important;
                color: var(--tertiary) !important;
                border-color: var(--border-subtle) !important;
            }}

            div[data-testid="stDownloadButton"] > button {{
                min-height: 40px;
                border-radius: 6px;
                border: 1px solid rgba(59,130,246,0.72) !important;
                background: #3b82f6 !important;
                color: #ffffff !important;
                font-weight: 600 !important;
                box-shadow: none !important;
                opacity: 1 !important;
            }}

            div[data-testid="stDownloadButton"] > button p,
            div[data-testid="stDownloadButton"] > button span,
            div[data-testid="stDownloadButton"] > button div {{
                color: #ffffff !important;
                font-weight: 600 !important;
                opacity: 1 !important;
            }}

            div[data-testid="stDownloadButton"] > button:hover {{
                background: #2563eb !important;
                border-color: rgba(59,130,246,0.92) !important;
                color: #ffffff !important;
            }}

            [data-testid="stMetric"] {{
                background: var(--card);
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                padding: 16px;
                min-height: 112px;
                box-shadow: none;
            }}

            [data-testid="stMetricLabel"] {{
                color: var(--tertiary);
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.06em;
            }}

            [data-testid="stMetricValue"] {{
                color: var(--text);
                font-size: 32px;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                white-space: normal;
                overflow: visible;
                text-overflow: clip;
                word-break: normal;
                overflow-wrap: normal;
                line-height: 1.18;
            }}

            [data-testid="stMetricValue"] > div {{
                white-space: normal;
                overflow: visible;
                text-overflow: clip;
                word-break: normal;
                overflow-wrap: normal;
            }}

            div[data-testid="stExpander"] {{
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                background: var(--card-soft);
            }}

            button[data-baseweb="tab"] {{
                color: var(--secondary) !important;
                min-height: 48px;
                padding: 12px 20px;
                border-radius: 6px 6px 0 0;
                font-weight: 500;
            }}

            button[data-baseweb="tab"][aria-selected="true"] {{
                color: #fafafa !important;
                border-bottom-color: var(--brand);
                background: rgba(59,130,246,0.08);
                font-weight: 600;
            }}

            button[data-baseweb="tab"] p {{
                font-size: 15px;
                line-height: 1.2;
                font-weight: inherit;
                color: inherit;
            }}

            [data-baseweb="tab-list"] {{
                gap: 8px;
                border-bottom: 1px solid var(--border-subtle);
            }}

            div[data-baseweb="tab-highlight"] {{
                height: 3px !important;
                background-color: var(--brand) !important;
            }}

            div[data-baseweb="slider"] [role="slider"] {{
                background-color: var(--brand) !important;
                border-color: var(--brand) !important;
                box-shadow: 0 0 0 4px rgba(59,130,246,0.16) !important;
            }}

            div[data-baseweb="slider"] div[style*="rgb(255, 75, 75)"],
            div[data-baseweb="slider"] div[style*="#ff4b4b"] {{
                background: var(--brand) !important;
                background-color: var(--brand) !important;
            }}

            div[data-testid="stSlider"] [role="slider"] {{
                background-color: var(--brand) !important;
                border-color: var(--brand) !important;
                box-shadow: 0 0 0 4px rgba(59,130,246,0.16) !important;
            }}

            div[data-testid="stSlider"] > div > div > div > div {{
                background-color: var(--brand) !important;
            }}

            .stAlert {{
                border-radius: 8px;
                border: 1px solid var(--border-subtle);
            }}

            .beta-banner {{
                min-height: 32px;
                display: flex;
                align-items: center;
                gap: 8px;
                padding: 7px 10px;
                margin: 8px 0 24px;
                border-left: 2px solid var(--brand);
                border-top: 1px solid rgba(59,130,246,0.14);
                border-right: 1px solid rgba(59,130,246,0.14);
                border-bottom: 1px solid rgba(59,130,246,0.14);
                border-radius: 6px;
                background: rgba(59,130,246,0.08);
                color: var(--secondary);
                font-size: 12px;
            }}

            .company-info-grid {{
                display: grid;
                grid-template-columns: repeat(5, minmax(0, 1fr));
                grid-auto-rows: 1fr;
                gap: 16px;
                margin: 16px 0 18px;
            }}

            .company-info-card {{
                height: 100%;
                min-height: 88px;
                background: var(--card);
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                padding: 18px 20px;
                display: flex;
                flex-direction: column;
                justify-content: flex-start;
            }}

            .company-info-label {{
                margin-bottom: 10px;
                color: var(--tertiary);
                font-size: 11px;
                line-height: 1.2;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 600;
            }}

            .company-info-value {{
                color: var(--text);
                font-size: 28px;
                line-height: 1.12;
                font-weight: 600;
                letter-spacing: 0;
                font-variant-numeric: tabular-nums;
                white-space: normal;
                overflow: visible;
                text-overflow: clip;
                word-break: normal;
                overflow-wrap: normal;
            }}

            @media (max-width: 1279px) {{
                .company-info-grid {{
                    grid-template-columns: repeat(3, minmax(0, 1fr));
                }}
            }}

            @media (max-width: 767px) {{
                .company-info-grid {{
                    grid-template-columns: repeat(2, minmax(0, 1fr));
                }}
            }}

            @media (max-width: 420px) {{
                .company-info-card {{
                    padding: 14px 14px;
                }}

                .company-info-value {{
                    font-size: 22px;
                }}
            }}

            .kpi-card {{
                background: var(--card);
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                padding: 20px;
                min-height: 214px;
                transition: border-color 160ms ease;
            }}

            .kpi-card:hover {{
                border-color: var(--border-strong);
            }}

            .kpi-label-row {{
                display: flex;
                align-items: center;
                justify-content: space-between;
                gap: 8px;
                margin-bottom: 10px;
            }}

            .kpi-label {{
                color: var(--tertiary);
                font-size: 11px;
                line-height: 1.2;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 600;
            }}

            .kpi-value {{
                color: var(--text);
                font-size: 36px;
                line-height: 1.05;
                font-weight: 600;
                letter-spacing: 0;
                font-variant-numeric: tabular-nums;
                margin-bottom: 10px;
            }}

            .valuation-result-grid {{
                display: grid;
                grid-template-columns: repeat(3, minmax(0, 1fr));
                gap: 16px;
                margin: 16px 0;
            }}

            .valuation-result-card {{
                min-height: 112px;
                background: var(--card);
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                padding: 16px;
            }}

            .valuation-result-label {{
                color: var(--tertiary);
                font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 11px;
                line-height: 1.2;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 600;
                margin-bottom: 10px;
            }}

            .valuation-result-value {{
                color: var(--text);
                font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 32px;
                line-height: 1.18;
                font-weight: 600;
                font-variant-numeric: tabular-nums;
                white-space: normal;
                overflow-wrap: anywhere;
            }}

            .reverse-dcf-failure {{
                margin: 12px 0 18px;
                padding: 16px 18px;
                border-left: 2px solid var(--brand);
                border-top: 1px solid rgba(59,130,246,0.14);
                border-right: 1px solid rgba(59,130,246,0.14);
                border-bottom: 1px solid rgba(59,130,246,0.14);
                border-radius: 6px;
                background: rgba(59,130,246,0.08);
            }}

            .reverse-dcf-failure-title {{
                color: var(--text);
                font-family: "Inter", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                font-size: 15px;
                line-height: 1.3;
                font-weight: 600;
                margin-bottom: 8px;
            }}

            .reverse-dcf-failure-body {{
                color: var(--secondary);
                font-size: 13px;
                line-height: 1.5;
                margin-bottom: 10px;
            }}

            .reverse-dcf-failure-meta {{
                color: var(--tertiary);
                font-size: 12px;
                line-height: 1.4;
            }}

            @media (max-width: 900px) {{
                .valuation-result-grid {{
                    grid-template-columns: 1fr;
                }}
            }}

            .pill {{
                display: inline-flex;
                align-items: center;
                min-height: 22px;
                padding: 4px 12px;
                border-radius: 6px;
                font-size: 11px;
                line-height: 1;
                font-weight: 500;
                font-variant-numeric: tabular-nums;
                border: 1px solid var(--border-subtle);
                background: rgba(255,255,255,0.04);
                color: var(--secondary);
            }}

            .pill-green {{
                background: rgba(16,185,129,0.12);
                border-color: rgba(16,185,129,0.25);
                color: #34d399;
            }}

            .pill-red {{
                background: rgba(239,68,68,0.12);
                border-color: rgba(239,68,68,0.25);
                color: #f87171;
            }}

            .pill-amber {{
                background: rgba(245,158,11,0.12);
                border-color: rgba(245,158,11,0.25);
                color: #fbbf24;
            }}

            .kpi-card .pill {{
                min-height: 22px;
                padding: 2px 8px;
                border-radius: 999px;
                font-weight: 600;
            }}

            .sparkline {{
                height: 40px;
                width: 100%;
                margin: 14px 0 10px;
            }}

            .sparkline-empty {{
                height: 40px;
                width: 100%;
                margin: 14px 0 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                color: var(--tertiary);
                font-size: 11px;
                line-height: 1;
                border-top: 1px dashed rgba(113,113,122,0.42);
                border-bottom: 1px dashed rgba(113,113,122,0.12);
            }}

            .benchmark {{
                color: var(--tertiary);
                font-size: 12px;
                line-height: 1.25;
            }}

            .info-wrap {{
                position: relative;
                display: inline-flex;
                color: var(--tertiary);
            }}

            .info-wrap svg {{
                width: 14px;
                height: 14px;
                stroke: currentColor;
            }}

            .tooltip-panel {{
                visibility: hidden;
                opacity: 0;
                position: absolute;
                z-index: 999;
                top: 20px;
                right: 0;
                width: 220px;
                padding: 10px 12px;
                border-radius: 8px;
                border: 1px solid var(--border-strong);
                background: #111119;
                color: var(--secondary);
                font-size: 12px;
                line-height: 1.35;
                box-shadow: 0 16px 40px rgba(0,0,0,0.32);
                text-transform: none;
                letter-spacing: 0;
                font-weight: 400;
            }}

            .info-wrap:hover .tooltip-panel {{
                visibility: visible;
                opacity: 1;
            }}

            .fa-table {{
                width: 100%;
                border-collapse: collapse;
                background: var(--card);
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                overflow: hidden;
                font-size: 13px;
            }}

            .fa-table th {{
                text-align: left;
                color: var(--tertiary);
                background: #13131a;
                font-size: 11px;
                text-transform: uppercase;
                letter-spacing: 0.06em;
                font-weight: 600;
                padding: 12px 16px;
                border-bottom: 1px solid var(--border-strong);
            }}

            .fa-table td {{
                color: var(--secondary);
                min-height: 48px;
                padding: 14px 16px;
                border-bottom: 1px solid var(--border-subtle);
                font-variant-numeric: tabular-nums;
                vertical-align: middle;
            }}

            .fa-table tbody tr:hover td {{
                background: rgba(255,255,255,0.02);
            }}

            .fa-table tr:last-child td {{
                border-bottom: 0;
            }}

            .fa-table .num {{
                text-align: right;
                color: #fafafa;
                font-weight: 600;
            }}

            .fa-table .unit {{
                color: var(--secondary);
                text-align: left;
                white-space: nowrap;
            }}

            .fa-table .period {{
                color: var(--secondary);
                font-size: 12px;
                white-space: nowrap;
            }}

            .fa-table .area {{
                color: var(--secondary);
                font-weight: 400;
            }}

            .fa-table .metric-cell {{
                display: inline-flex;
                align-items: center;
                gap: 6px;
                color: var(--text);
                font-weight: 500;
            }}

            div[data-testid="stDataFrame"] {{
                border: 1px solid var(--border-subtle);
                border-radius: 8px;
                overflow: hidden;
            }}

            [data-testid="stCaptionContainer"] {{
                color: var(--tertiary);
                font-size: 12px;
            }}

            .skeleton-card {{
                height: 88px;
                border-radius: 8px;
                background: linear-gradient(90deg, rgba(255,255,255,0.04), rgba(255,255,255,0.09), rgba(255,255,255,0.04));
                background-size: 240% 100%;
                animation: shimmer 1.2s infinite;
                border: 1px solid var(--border-subtle);
            }}

            .skeleton-title {{
                width: 320px;
                height: 36px;
                margin-bottom: 18px;
            }}

            @keyframes shimmer {{
                0% {{ background-position: 220% 0; }}
                100% {{ background-position: -220% 0; }}
            }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def chart_config(filename: str) -> dict:
    """Return Plotly config with a chart-specific PNG filename."""
    config = dict(PLOTLY_CONFIG)
    config["displayModeBar"] = False
    config["toImageButtonOptions"] = dict(PLOTLY_CONFIG["toImageButtonOptions"])
    config["toImageButtonOptions"]["filename"] = filename
    return config


def run_pytest_before_excel() -> tuple[bool, str]:
    """Run valuation unit tests before Excel report generation."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "tests/"],
            cwd=Path(__file__).resolve().parent,
            capture_output=True,
            text=True,
            timeout=60,
        )
    except Exception as exc:
        return False, f"Could not run pytest: {exc}"
    output = (result.stdout or "") + "\n" + (result.stderr or "")
    return result.returncode == 0, output[-3000:]


def fetch_risk_free_with_fallback() -> tuple[dict | None, str | None]:
    """Fetch ^TNX risk-free rate, using session cached value if live fetch fails."""
    try:
        risk_free = fetch_risk_free_rate()
        st.session_state["last_risk_free"] = risk_free
        return risk_free, None
    except Exception as exc:
        if "Risk-free rate outside" in str(exc):
            return None, str(exc)
        cached = st.session_state.get("last_risk_free")
        if cached:
            return cached, f"Risk-free rate live fetch failed; using cached ^TNX value from {cached.get('date')}."
        return None, f"Risk-free rate could not be loaded and no cached value exists: {exc}"


def render_beta_source_box(beta_match) -> None:
    """Show Damodaran beta source information on the main page."""
    if beta_match is None:
        return
    st.markdown(
        f"""
        <div class="beta-banner">
            <strong>Beta source</strong>
            <span>Damodaran industry: {escape(str(beta_match.matched_industry))}</span>
            <span>Confidence: {beta_match.confidence:.1f}%</span>
            <span>Updated: {escape(str(beta_match.source_updated))}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def prepare_damodaran_match(data: dict):
    """Load Damodaran match and require user approval for low-confidence matches."""
    skeleton = st.empty()
    try:
        skeleton.markdown('<div class="skeleton-card"></div>', unsafe_allow_html=True)
        beta_match, damodaran_table = build_beta_match(data)
    except Exception as exc:
        skeleton.empty()
        st.error(f"Damodaran beta data could not be loaded: {exc}")
        return None, None
    skeleton.empty()

    if beta_match.confidence < 70:
        with st.sidebar:
            st.warning("Damodaran industry match confidence is below 70%. Please select the correct industry.")
            placeholder = "-- Select industry --"
            options = [placeholder] + damodaran_table["industry"].dropna().astype(str).tolist()
            selected = st.selectbox(
                "Damodaran industry",
                options,
                index=0,
            )
        if selected != placeholder:
            beta_match, damodaran_table = build_beta_match(data, selected_industry=selected)
    return beta_match, damodaran_table


def render_validation_view(validation_result: dict | None) -> None:
    """Render optional Damodaran benchmark validation table."""
    if not validation_result:
        return
    st.subheader("Calculation validation")
    st.info(
        "Validointi varmistaa että kaavat tuottavat järkeviä tuloksia verrattuna "
        "Aswath Damodaranin (NYU Stern) julkaisemiin toimialakeskiarvoihin. "
        "Pienet poikkeamat ovat normaaleja, suuret poikkeamat voivat johtua yrityksen "
        "poikkeavasta pääomarakenteesta tai erityisluonteesta."
    )
    frame = pd.DataFrame(validation_result["rows"])
    display = frame.copy()
    for column in ["Calculated", "Damodaran (industry avg)", "Difference"]:
        display[column] = pd.to_numeric(display[column], errors="coerce").map(
            lambda value: "" if pd.isna(value) else f"{value:.2%}"
        )
    st.dataframe(display, use_container_width=True, hide_index=True)


def render_dcf_result_summary(valuation: dict, currency_code: str) -> None:
    """Render selected DCF tier and all attempted tier outputs."""
    dcf = valuation.get("dcf") or {}
    selected_tier = valuation.get("selected_dcf_tier") or {}
    raw_implied = dcf.get("implied_price")

    valuation_rows = [
        ("Selected implied share price", format_share_price(raw_implied, currency_code)),
        ("Valuation method", selected_tier.get("method") or "N/A"),
        ("Upside / downside", format_percentage(dcf.get("upside") * 100 if dcf.get("upside") is not None else None)),
    ]
    cards_html = "".join(
        (
            '<div class="valuation-result-card">'
            f'<div class="valuation-result-label">{escape(label)}</div>'
            f'<div class="valuation-result-value">{escape(str(value))}</div>'
            '</div>'
        )
        for label, value in valuation_rows
    )
    st.markdown(f'<div class="valuation-result-grid">{cards_html}</div>', unsafe_allow_html=True)
    render_dcf_tier_notice(valuation)
    render_reverse_dcf_analysis(valuation)

    with st.expander("Show all valuation tier attempts", expanded=False):
        tier_rows = []
        for tier in valuation.get("dcf_tiers", []) or []:
            tier_dcf = tier.get("dcf") or {}
            tier_rows.append(
                {
                    "Tier": f"Tier {tier.get('tier')}",
                    "Method": tier.get("name", ""),
                    "Implied price": format_share_price(tier_dcf.get("implied_price"), currency_code),
                    "Upside / downside": format_percentage(tier_dcf.get("upside") * 100 if tier_dcf.get("upside") is not None else None),
                    "Status": "Used as primary result" if tier.get("selected") else tier.get("status", ""),
                    "Reason": tier.get("selection_reason") or tier.get("rejection_reason") or "Passed sanity check",
                }
            )
        if tier_rows:
            st.dataframe(pd.DataFrame(tier_rows), use_container_width=True, hide_index=True)
        else:
            st.info("DCF tier diagnostics are not available for this run.")


def render_dcf_tier_notice(valuation: dict | None) -> None:
    """Show a prominent note for the selected valuation tier."""
    if not valuation:
        return
    tier = valuation.get("dcf_tier")
    if tier == 2:
        st.warning(
            "⚠ DCF model uses smoothed long-term averages because recent financials show cyclical distortion. "
            "Implied price has moderate confidence."
        )
    elif tier == 3:
        st.error(
            "🚨 DCF model uses sector benchmark assumptions because company-specific data is not reliable for valuation. "
            "Implied price has LOW confidence — review alternative valuation methods."
        )
    elif tier == 4:
        st.warning(
            "This company's recent financials don't support a standard DCF valuation. The estimate above uses "
            "multiples comparison as an alternative method. Consider this estimate alongside the current market price, "
            "which may reflect expectations not captured by historical data."
        )
    elif tier == 5:
        st.error(
            "This company's recent financials don't support a standard DCF valuation. The estimate above uses tangible "
            "book value as an alternative floor. Consider this estimate alongside the current market price, which may "
            "reflect expectations not captured by historical data."
        )


def render_reverse_dcf_analysis(valuation: dict | None) -> None:
    """Render Reverse DCF implied growth diagnostics in the overview tab."""
    display = reverse_dcf_display_model(valuation)
    if display["case"] == "hidden":
        return
    st.markdown("#### Reverse DCF - Implied Growth Analysis")
    # Reverse DCF is a diagnostic interpretation tool, not a valuation tier.
    if display["case"] == "success":
        cards_html = "".join(
            (
                '<div class="valuation-result-card">'
                f'<div class="valuation-result-label">{escape(label)}</div>'
                f'<div class="valuation-result-value">{escape(value)}</div>'
                '</div>'
            )
            for label, value in display["cards"]
        )
        st.markdown(f'<div class="valuation-result-grid">{cards_html}</div>', unsafe_allow_html=True)
        st.caption(display["interpretation"])
        return
    st.markdown(
        (
            '<div class="reverse-dcf-failure">'
            '<div class="reverse-dcf-failure-title">Reverse DCF &mdash; Could not solve</div>'
            f'<div class="reverse-dcf-failure-body">{escape(str(display["body"]))}</div>'
            f'<div class="reverse-dcf-failure-meta">{escape(display["meta"])}</div>'
            '</div>'
        ),
        unsafe_allow_html=True,
    )


def reverse_dcf_display_model(valuation: dict | None) -> dict:
    """Return the display model for Reverse DCF diagnostics."""
    reverse = (valuation or {}).get("reverse_dcf") or {}
    if not reverse:
        return {"case": "hidden"}
    if _is_number(reverse.get("implied_growth")):
        return {
            "case": "success",
            "cards": [
                ("Market implied growth", _format_growth_rate(reverse.get("implied_growth"))),
                ("Model assumed growth", _format_growth_rate(reverse.get("tier1_growth"))),
                ("Yahoo revenue growth estimate", _format_growth_rate(reverse.get("analyst_consensus_growth"))),
            ],
            "interpretation": reverse.get("interpretation") or reverse.get("message") or "Reverse DCF diagnostic unavailable.",
        }
    return {
        "case": "failure",
        "body": reverse.get("interpretation") or reverse.get("message") or "Reverse DCF diagnostic unavailable.",
        "meta": (
            f"Tier 1 assumed growth: {_format_growth_rate(reverse.get('tier1_growth'))} | "
            f"Yahoo revenue growth estimate: {_format_growth_rate(reverse.get('analyst_consensus_growth'))}"
        ),
    }


def _is_number(value: float | int | None) -> bool:
    """Return True for finite displayable numeric values."""
    return value is not None and not pd.isna(value)


def _format_growth_rate(value: float | int | None) -> str:
    """Format a decimal growth rate for UI display."""
    return format_percentage(float(value) * 100 if value is not None and not pd.isna(value) else None)


def _format_growth_gap(value: float | int | None) -> str:
    """Format a decimal growth-rate difference as percentage points."""
    return format_percentage_points(float(value) * 100 if value is not None and not pd.isna(value) else None)


def render_valuation_sidebar(
    data: dict,
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    beta_match,
    show_validation: bool,
) -> None:
    """Render sidebar controls for Excel valuation report generation."""
    with st.sidebar:
        st.divider()
        st.header("Valuation")
        allow_sanity_override = st.checkbox(
            "Allow report despite high/critical sanity-check warnings",
            key="allow_sanity_override",
        )
        allow_validation_override = st.checkbox(
            "Allow report despite Damodaran validation failures",
            key="allow_validation_override",
        )
        match_not_approved = beta_match is None or beta_match.confidence < 70
        if match_not_approved:
            st.caption("Select a Damodaran industry before generating the valuation report.")
        generate = st.button(
            "Generate Excel Report (CAPM + WACC + DCF)",
            use_container_width=True,
            type="primary",
            disabled=match_not_approved,
        )

    if not generate:
        return
    if beta_match is None:
        st.error("Excel report cannot be generated because Damodaran beta data is unavailable.")
        return
    if beta_match.confidence < 70:
        st.error("Select and approve a Damodaran industry before generating the Excel report.")
        return

    progress = st.progress(0)
    status = st.empty()
    status.info("Running unit tests...")
    tests_ok, test_output = run_pytest_before_excel()
    if not tests_ok:
        st.error("Unit tests failed. Excel report generation stopped.")
        st.code(test_output)
        return
    progress.progress(20)

    status.info("Loading risk-free rate...")
    risk_free, rf_warning = fetch_risk_free_with_fallback()
    if rf_warning:
        st.warning(rf_warning)
    if risk_free is None:
        st.error("Risk-free rate is required for CAPM. Report generation stopped.")
        return
    progress.progress(35)

    status.info("Calculating WACC...")
    try:
        valuation = build_valuation_result(data, income_metrics, balance_metrics, cash_flow_metrics, beta_match, risk_free)
    except ValueError as exc:
        if "Cost of debt" not in str(exc) or getattr(beta_match, "industry_cost_of_debt", None) is not None:
            st.error(f"Valuation calculation stopped: {exc}")
            return
        status.info("Loading Damodaran cost-of-debt fallback...")
        beta_match.industry_cost_of_debt = get_damodaran_industry_cost_of_debt(
            beta_match.company_industry,
            beta_match.source_region,
        )
        if beta_match.industry_cost_of_debt is None:
            st.error(f"Valuation calculation stopped: {exc} Damodaran industry cost of debt was not found.")
            return
        try:
            valuation = build_valuation_result(data, income_metrics, balance_metrics, cash_flow_metrics, beta_match, risk_free)
        except ValueError as retry_exc:
            st.error(f"Valuation calculation stopped: {retry_exc}")
            return
    except Exception as exc:
        st.error(f"Could not load required Damodaran cost-of-debt benchmark: {exc}")
        return
    st.session_state["last_valuation"] = valuation
    st.session_state["last_valuation_ticker"] = data.get("ticker")
    sanity_warnings = run_sanity_checks(valuation)
    critical = [warning for warning in sanity_warnings if warning["severity"] == "critical"]
    high_warnings = [warning for warning in sanity_warnings if warning["severity"] == "warning_high"]
    for warning in sanity_warnings:
        if warning["severity"] == "critical":
            st.error(f"Critical: {warning['message']}")
        elif warning["severity"] == "warning_high":
            st.warning(f"High warning: {warning['message']}")
        elif warning["severity"] == "info":
            st.info(warning["message"])
        else:
            st.warning(warning["message"])
    if high_warnings and not critical:
        st.warning("High sanity-check warnings found. Confirm before generating the report.")
        if not allow_sanity_override:
            st.info("Tick the sidebar override checkbox, then click Generate Excel Report again.")
            return
    if critical:
        st.error("Critical sanity-check warnings found. Review assumptions before relying on the report.")
        if not allow_sanity_override:
            st.info("Tick the sidebar override checkbox, then click Generate Excel Report again.")
            return
    progress.progress(55)

    status.info("Validating against Damodaran benchmarks...")
    validation_result = None
    try:
        validation_result = validate_against_damodaran(
            valuation,
            beta_match.company_industry,
            beta_match.source_region,
            (data.get("info", {}) or {}).get("country"),
        )
    except Exception as exc:
        st.warning(f"Damodaran benchmark validation could not be completed: {exc}")
    if show_validation:
        render_validation_view(validation_result)
    validation_failures = []
    if validation_result:
        validation_failures = [
            row for row in validation_result.get("rows", [])
            if "Check" in str(row.get("Status", ""))
        ]
    if validation_failures:
        st.error("Damodaran validation found one or more critical deviations above 5 percentage points.")
        if not allow_validation_override:
            st.info("Tick the sidebar override checkbox, then click Generate Excel Report again.")
            return
    progress.progress(75)

    status.info("Building Excel...")
    xlsx_bytes = build_valuation_excel_report(
        data,
        income_metrics,
        balance_metrics,
        cash_flow_metrics,
        beta_match,
        valuation,
        validation_result,
        sanity_warnings,
    )
    progress.progress(100)
    status.success("Excel report ready.")
    render_dcf_result_summary(valuation, reporting_currency(data))
    filename = f"{data['ticker'].replace('.', '_')}_valuation_{pd.Timestamp.today().strftime('%Y%m%d')}.xlsx"
    st.download_button(
        "Download valuation Excel",
        data=xlsx_bytes,
        file_name=filename,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )


def render_company_header(data: dict) -> None:
    """Render basic company information with logo support."""
    info = data["info"]
    market_cap = info.get("marketCap")
    share_price = info.get("currentPrice") or info.get("regularMarketPrice")
    logo_url = info.get("logo_url")
    currency_code = reporting_currency(data)

    header_left, header_right = st.columns([0.86, 0.14])
    with header_left:
        st.subheader(info.get("longName") or info.get("shortName") or data["ticker"])
        st.markdown(
            f"""
            <span title="FY means fiscal year: audited annual statement period. TTM means trailing twelve months: rolling 12-month market or earnings data. This app keeps FY statement data and TTM market multiples labelled separately.">
                Reported in: <b>{currency_code}</b> &nbsp; | &nbsp; hover for FY vs TTM explanation
            </span>
            """,
            unsafe_allow_html=True,
        )
    with header_right:
        if logo_url:
            st.image(logo_url, width=86)

    header_cards = [
        ("Ticker", data["ticker"]),
        ("Industry", info.get("industry") or "N/A"),
        ("Country", info.get("country") or "N/A"),
        ("Share price", format_share_price(share_price, currency_code)),
        (
            "Market cap",
            format_large_number(
                market_cap / 1_000_000 if market_cap else None,
                money_suffix(currency_code),
            ),
        ),
    ]
    cards_html = "".join(
        (
            '<div class="company-info-card">'
            f'<div class="company-info-label">{escape(label)}</div>'
            f'<div class="company-info-value">{escape(str(value))}</div>'
            '</div>'
        )
        for label, value in header_cards
    )
    st.markdown(f'<div class="company-info-grid">{cards_html}</div>', unsafe_allow_html=True)

    summary = info.get("longBusinessSummary")
    if summary:
        with st.expander("Company description", expanded=False):
            st.write(summary)


def _latest_and_delta(frame: pd.DataFrame, column: str) -> tuple[float | None, float | None]:
    """Return latest KPI and change from previous year."""
    if frame.empty or column not in frame.columns:
        return None, None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None, None
    latest = float(values.iloc[-1])
    previous = float(values.iloc[-2]) if len(values) >= 2 else None
    delta = latest - previous if previous is not None else None
    return latest, delta


KPI_TOOLTIPS = {
    "roe": "ROE = Net Income / Equity. Measures return generated on shareholders' equity.",
    "roce": "ROCE = EBIT / (Total Assets - Current Liabilities). Measures operating return on capital employed.",
    "pe_ratio": "P/E TTM = current market price divided by trailing twelve month earnings per share.",
    "ev_to_ebitda": "EV/EBITDA = enterprise value divided by trailing EBITDA. Uses Yahoo Finance TTM market data when available.",
}

METRIC_TOOLTIPS = {
    "Revenue": "Total fiscal-year revenue reported by the company.",
    "EBIT": "Earnings before interest and taxes from fiscal-year statements.",
    "Net income": "Profit attributable to shareholders in the fiscal year.",
    "EBIT margin": "EBIT margin = EBIT / Revenue.",
    "Total assets": "Total assets from the latest fiscal-year balance sheet.",
    "Equity ratio": "Equity ratio = Shareholders' equity / Total assets.",
    "Net debt": "Net debt = Total debt - cash and cash equivalents.",
    "Net cash": "Negative net debt indicates net cash position.",
    "Free cash flow": "Free cash flow = Operating cash flow + capital expenditure.",
    "Revenue CAGR": "Revenue CAGR = annualized growth rate from first to latest available fiscal year.",
    "FCF conversion": "FCF conversion = Free cash flow / Net income.",
    "Net debt / EBITDA": "Net debt / EBITDA measures leverage relative to EBITDA.",
    "Net cash / EBITDA": "Net cash / EBITDA shows cash surplus relative to EBITDA.",
}


def _render_financial_table(headers: list[str], rows: list[dict[str, str]]) -> None:
    """Render a compact professional HTML table."""
    header_html = "".join(f"<th>{escape(header)}</th>" for header in headers)
    body_html = []
    for row in rows:
        cells = []
        for header in headers:
            value = row.get(header, "")
            class_name = "num" if header in {"Value", "Calculated", "Damodaran", "Difference"} else ""
            if header == "Unit":
                class_name = "unit"
            elif header == "Period":
                class_name = "period"
            elif header == "Area":
                class_name = "area"
            if header == "Metric":
                tooltip = METRIC_TOOLTIPS.get(str(value), "")
                icon = info_icon(tooltip) if tooltip else ""
                value = f'<span class="metric-cell">{escape(str(value))}{icon}</span>'
            elif header == "Status":
                value = _status_pill(str(value))
            else:
                value = escape(str(value))
            cells.append(f'<td class="{class_name}">{value}</td>')
        body_html.append("<tr>" + "".join(cells) + "</tr>")
    st.markdown(
        f'<table class="fa-table"><thead><tr>{header_html}</tr></thead><tbody>{"".join(body_html)}</tbody></table>',
        unsafe_allow_html=True,
    )


def _format_scorecard_value(value: float | int | None, unit: str) -> str:
    """Format scorecard values by unit."""
    if value is None or pd.isna(value):
        return "N/A"
    if unit == "%":
        return format_percentage(value)
    if unit == "x":
        return format_multiple(value)
    return format_plain_number(value)


def render_kpi_dashboard(kpis: dict, kpi_history: pd.DataFrame, fy_label: str) -> None:
    """Render KPI cards with deltas and sparklines."""
    st.subheader("KPI dashboard")
    cards = [
        (f"ROE ({fy_label})", "roe", format_percentage, True),
        (f"ROCE ({fy_label})", "roce", format_percentage, True),
        ("P/E (TTM)", "pe_ratio", format_multiple, False),
        ("EV/EBITDA (TTM)", "ev_to_ebitda", format_multiple, False),
    ]
    cols = st.columns(4)
    for index, (label, column, formatter, use_history) in enumerate(cards):
        latest, delta = _latest_and_delta(kpi_history, column) if use_history else (kpis.get(column), None)
        delta_text = "n/a"
        delta_class = "pill"
        if delta is not None:
            delta_text = f"{delta:+.1f}{' pp' if column in {'roe', 'roce'} else 'x'} vs last year"
            delta_class = "pill pill-green" if delta >= 0 else "pill pill-red"
        values = []
        if use_history and column in kpi_history.columns:
            values = pd.to_numeric(kpi_history[column], errors="coerce").dropna().tail(5).tolist()
        positive = True if delta is None else delta >= 0
        sparkline_html = (
            _sparkline_svg(values, positive)
            if len(values) >= 2
            else '<div class="sparkline-empty">Insufficient history</div>'
        )
        benchmark = "Industry avg: n/a"
        with cols[index]:
            card_html = (
                '<div class="kpi-card">'
                '<div class="kpi-label-row">'
                f'<div class="kpi-label">{escape(label)}</div>'
                f'{info_icon(KPI_TOOLTIPS.get(column, "Financial ratio from Yahoo Finance and financial statements."))}'
                '</div>'
                f'<div class="kpi-value">{escape(formatter(latest))}</div>'
                f'<span class="{delta_class}">{escape(delta_text)}</span>'
                f'{sparkline_html}'
                f'<div class="benchmark">{benchmark}</div>'
                '</div>'
            )
            st.markdown(
                card_html,
                unsafe_allow_html=True,
            )


def render_latest_financials(income: pd.DataFrame, balance: pd.DataFrame, cash: pd.DataFrame, currency_code: str) -> None:
    """Render latest fiscal year financials without TTM values."""
    if income.empty and balance.empty and cash.empty:
        return

    period = latest_period_label(income if not income.empty else balance if not balance.empty else cash)
    rows = []
    if not income.empty:
        latest = income.iloc[-1]
        rows.extend(
            [
                {
                    "Metric": "Revenue",
                    "Value": format_large_number(latest.get("revenue"), money_suffix(currency_code)),
                    "Unit": money_suffix(currency_code),
                    "Period": period,
                },
                {
                    "Metric": "EBIT",
                    "Value": format_large_number(latest.get("ebit"), money_suffix(currency_code)),
                    "Unit": money_suffix(currency_code),
                    "Period": period,
                },
                {
                    "Metric": "Net income",
                    "Value": format_large_number(latest.get("net_income"), money_suffix(currency_code)),
                    "Unit": money_suffix(currency_code),
                    "Period": period,
                },
                {
                    "Metric": "EBIT margin",
                    "Value": format_percentage(latest.get("ebit_margin")),
                    "Unit": "%",
                    "Period": period,
                },
            ]
        )
    if not balance.empty:
        latest = balance.iloc[-1]
        net_debt_label, net_debt_value, _net_debt_help = net_debt_display(latest.get("net_debt"), money_suffix(currency_code))
        rows.extend(
            [
                {
                    "Metric": "Total assets",
                    "Value": format_large_number(latest.get("total_assets"), money_suffix(currency_code)),
                    "Unit": money_suffix(currency_code),
                    "Period": period,
                },
                {
                    "Metric": "Equity ratio",
                    "Value": format_percentage(latest.get("equity_ratio")),
                    "Unit": "%",
                    "Period": period,
                },
                {
                    "Metric": net_debt_label,
                    "Value": net_debt_value,
                    "Unit": money_suffix(currency_code),
                    "Period": period,
                },
            ]
        )
    if not cash.empty:
        latest = cash.iloc[-1]
        rows.append(
            {
                "Metric": "Free cash flow",
                "Value": format_large_number(latest.get("free_cash_flow"), money_suffix(currency_code)),
                "Unit": money_suffix(currency_code),
                "Period": period,
            }
        )
    st.markdown(f"#### Latest Financials - {period}")
    st.caption("This table uses the latest fiscal-year statement data only. It does not include TTM market multiples.")
    _render_financial_table(["Metric", "Value", "Unit", "Period"], rows)


def render_analysis_overview(
    analysis: dict,
    income: pd.DataFrame,
    balance: pd.DataFrame,
    cash: pd.DataFrame,
    currency_code: str,
    valuation: dict | None = None,
) -> None:
    """Render professional analyst-style summary."""
    overview = analysis["overview"]
    scorecard = analysis["scorecard"]

    st.subheader("Analyst overview")
    fy_label = latest_fy_label(income)
    top_cols = st.columns(4)
    top_cols[0].metric("Revenue CAGR (FY)", format_percentage(overview.get("revenue_cagr")))
    top_cols[1].metric("EBIT margin change (FY)", format_percentage_points(overview.get("ebit_margin_change")))
    top_cols[2].metric(f"FCF conversion ({fy_label})", format_percentage(overview.get("fcf_conversion")))
    leverage_label, leverage_value, leverage_help = net_debt_to_ebitda_display(overview.get("net_debt_to_ebitda"), fy_label)
    top_cols[3].metric(leverage_label, leverage_value, help=leverage_help)

    st.markdown("#### Key takeaways")
    for insight in analysis["insights"]:
        st.write(f"- {insight}")

    st.markdown("#### Financial quality scorecard")
    scorecard = scorecard.copy()
    net_debt_mask = scorecard["metric"].eq("Net debt / EBITDA") & pd.to_numeric(scorecard["value"], errors="coerce").lt(0)
    scorecard.loc[net_debt_mask, "metric"] = "Net cash / EBITDA"
    scorecard.loc[net_debt_mask, "value"] = pd.to_numeric(scorecard.loc[net_debt_mask, "value"], errors="coerce").abs()
    scorecard_rows = []
    for _, row in scorecard.iterrows():
        scorecard_rows.append(
            {
                "Area": row.get("area", ""),
                "Metric": row.get("metric", ""),
                "Value": _format_scorecard_value(row.get("value"), row.get("unit")),
                "Unit": row.get("unit", ""),
                "Status": row.get("status", ""),
            }
        )
    _render_financial_table(
        ["Area", "Metric", "Value", "Unit", "Status"],
        scorecard_rows,
    )
    render_reverse_dcf_analysis(valuation)
    render_latest_financials(income, balance, cash, currency_code)


def _scorecard_style(row: pd.Series) -> list[str]:
    """Color scorecard rows by status."""
    status = row.get("status")
    color = {
        "Strong": "rgba(46,204,113,0.22)",
        "Watch": "rgba(240,165,0,0.22)",
        "Weak": "rgba(255,92,92,0.22)",
    }.get(status, "rgba(255,255,255,0.04)")
    return [f"background-color: {color}" for _ in row]


def render_pdf_export(data: dict, kpis: dict, analysis: dict, income: pd.DataFrame, balance: pd.DataFrame, cash: pd.DataFrame) -> None:
    """Render a PDF export button."""
    try:
        pdf_bytes = build_pdf_report(data, kpis, analysis, income, balance, cash)
    except RuntimeError as exc:
        st.warning(str(exc))
        return

    st.download_button(
        "Export to PDF",
        data=pdf_bytes,
        file_name=f"{data['ticker']}_financial_report.pdf",
        mime="application/pdf",
    )


def render_dividends(dividend_metrics: pd.DataFrame, currency_code: str) -> None:
    """Render dividend history analysis."""
    if dividend_metrics.empty:
        st.info("Dividend history is not available for this ticker in Yahoo Finance.")
        return

    st.plotly_chart(
        create_dividend_chart(dividend_metrics, currency_code),
        use_container_width=True,
        config=chart_config("dividend_history"),
    )
    st.caption(
        "Payout ratio is shown only for years where Yahoo Finance provides both dividend data and same-year net income. "
        "Current-year dividends are year-to-date, so the payout ratio is hidden until full-year net income is available."
    )
    st.dataframe(dividend_metrics, use_container_width=True, hide_index=True)


def render_statement_dataframe(frame: pd.DataFrame, statement_name: str) -> None:
    """Render a historical statement table while hiding wholly incomplete display rows."""
    display, excluded_periods = filter_incomplete_display_rows(frame)
    if excluded_periods:
        earliest = excluded_periods[0]
        note = (
            f"Earlier fiscal years ({earliest} and prior) excluded due to incomplete data from Yahoo Finance."
            if len(excluded_periods) == 1
            else f"Earlier fiscal years ({earliest}-{excluded_periods[-1]}) excluded due to incomplete data from Yahoo Finance."
        )
        st.caption(note)
    st.dataframe(display, use_container_width=True, hide_index=True)


def filter_incomplete_display_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    """Hide rows whose non-metadata numeric fields are entirely empty for display only."""
    if frame.empty:
        return frame, []
    metadata_columns = {"year", "period", "period_end", "period_type"}
    value_columns = [column for column in frame.columns if column not in metadata_columns]
    if not value_columns:
        return frame, []
    numeric_values = frame[value_columns].apply(pd.to_numeric, errors="coerce")
    empty_rows = numeric_values.isna().all(axis=1)
    excluded = [
        _display_period_label(row)
        for _, row in frame.loc[empty_rows].iterrows()
    ]
    return frame.loc[~empty_rows].copy(), excluded


def _display_period_label(row: pd.Series) -> str:
    """Return a compact FY label for hidden-row notes."""
    if pd.notna(row.get("period")):
        return str(row.get("period")).split()[0]
    if pd.notna(row.get("year")):
        return f"FY{int(row.get('year'))}"
    return "earlier FY"


def render_surprises(surprise_metrics: pd.DataFrame) -> None:
    """Render earnings surprise analysis."""
    st.caption("Yahoo Finance usually exposes EPS surprise data more consistently than revenue consensus data.")
    if surprise_metrics.empty:
        st.info("Analyst EPS surprise data is not available for this ticker.")
        return

    st.plotly_chart(
        create_earnings_surprise_chart(surprise_metrics),
        use_container_width=True,
        config=chart_config("earnings_surprise"),
    )
    st.dataframe(surprise_metrics, use_container_width=True, hide_index=True)


def render_scenario_analysis(
    data: dict,
    income_metrics: pd.DataFrame,
    chart_benchmarks: dict[str, float] | None = None,
) -> None:
    """Render a simple revenue and EPS scenario calculator."""
    st.subheader("Scenario analysis")
    currency_code = reporting_currency(data)
    latest_income = income_metrics.iloc[-1] if not income_metrics.empty else {}
    latest_revenue = latest_income.get("revenue") if not income_metrics.empty else None
    latest_net_income = latest_income.get("net_income") if not income_metrics.empty else None
    latest_net_margin = latest_income.get("net_margin") if not income_metrics.empty else None
    revenue_cagr = trailing_cagr(income_metrics, "revenue", years=3)
    sector_growth = (chart_benchmarks or {}).get("revenue_growth", 4.0)
    sector_margin = (chart_benchmarks or {}).get("net_margin", 6.0)
    left, right = st.columns([0.55, 0.45])
    with left:
        revenue_growth = st.slider("Revenue growth assumption", -20.0, 30.0, 10.0, 0.5)
        st.caption(
            f"Last 3Y CAGR: {format_percentage(revenue_cagr)} | Sector median: ~{sector_growth:.1f}%"
        )
        margin_change = st.slider("Net margin change", -10.0, 10.0, 0.0, 0.25)
        st.caption(
            f"Current net margin: {format_percentage(latest_net_margin)} | Sector median: ~{sector_margin:.1f}%"
        )

    projection = build_scenario_projection(
        income_metrics,
        data.get("info", {}).get("sharesOutstanding"),
        revenue_growth,
        margin_change,
    )

    with right:
        if not projection:
            st.info("Scenario analysis needs revenue, net margin, and shares outstanding data.")
            return
        cols = st.columns(2)
        revenue_delta = None
        if latest_revenue not in (None, 0) and projection.get("projected_revenue") is not None:
            revenue_delta = (projection.get("projected_revenue") / latest_revenue - 1) * 100
        income_delta = None
        if latest_net_income not in (None, 0) and projection.get("projected_net_income") is not None:
            income_delta = (projection.get("projected_net_income") / latest_net_income - 1) * 100
        cols[0].metric(
            "Projected revenue",
            format_large_number(projection.get("projected_revenue"), money_suffix(currency_code)),
            delta=f"{revenue_delta:+.1f}% vs latest FY" if revenue_delta is not None else None,
        )
        cols[1].metric(
            "Projected net income",
            format_large_number(projection.get("projected_net_income"), money_suffix(currency_code)),
            delta=f"{income_delta:+.1f}% vs latest FY" if income_delta is not None else None,
        )
        margin_delta = None
        if latest_net_margin is not None and projection.get("projected_net_margin") is not None:
            margin_delta = projection.get("projected_net_margin") - latest_net_margin
        cols[0].metric(
            "Projected net margin",
            format_percentage(projection.get("projected_net_margin")),
            delta=f"{margin_delta:+.1f} pp vs latest FY" if margin_delta is not None else None,
        )
        eps = projection.get("projected_eps")
        cols[1].metric(f"Projected EPS ({currency_code})", f"{eps:.2f}" if eps is not None else "N/A")


def render_methodology() -> None:
    """Render ratio methodology explanations."""
    st.subheader("Methodology")
    st.info(
        "FY = fiscal year, based on annual financial statements. TTM = trailing twelve months, "
        "usually used for current market multiples such as trailing P/E. FY statement tables and TTM multiples are labelled separately."
    )
    rows = [
        {"Metric": "Revenue CAGR", "Formula": "(Latest revenue / first revenue)^(1 / years) - 1"},
        {"Metric": "Gross margin", "Formula": "Gross profit / revenue"},
        {"Metric": "EBITDA margin", "Formula": "EBITDA / revenue"},
        {"Metric": "EBIT margin", "Formula": "EBIT / revenue"},
        {"Metric": "Net margin", "Formula": "Net income / revenue"},
        {"Metric": "ROE", "Formula": "Net income / shareholders' equity"},
        {"Metric": "ROCE", "Formula": "EBIT / (total assets - current liabilities)"},
        {"Metric": "P/E (TTM)", "Formula": "Yahoo Finance trailing P/E based on trailing twelve months data"},
        {"Metric": "EV/EBITDA (TTM)", "Formula": "Yahoo Finance enterprise value to EBITDA based on trailing data when available"},
        {"Metric": "Equity ratio", "Formula": "Shareholders' equity / total assets"},
        {"Metric": "Net debt", "Formula": "Total debt - cash and cash equivalents"},
        {"Metric": "Free cash flow", "Formula": "Operating cash flow + capital expenditure"},
        {"Metric": "FCF conversion", "Formula": "Free cash flow / net income"},
        {"Metric": "Net debt / EBITDA", "Formula": "Net debt / EBITDA"},
        {"Metric": "Dividend payout ratio", "Formula": "Dividend per share * shares outstanding / net income"},
        {"Metric": "Dividend yield", "Formula": "Dividend per share / current share price"},
    ]
    _render_financial_table(["Metric", "Formula"], rows)
    st.markdown("### Valuation Framework: 5-Tier Fallback")
    _render_financial_table(["Tier", "Method", "Inputs", "Skip condition", "Acceptance"], methodology_tier_rows())
    st.markdown("### CAPM and WACC")
    st.markdown("#### CAPM")
    _render_financial_table(["Component", "Formula / source"], methodology_capm_rows())
    st.markdown("#### WACC and DCF Horizon")
    _render_financial_table(["Component", "Formula / source"], methodology_wacc_rows())
    st.markdown("### Damodaran Sector Matching")
    for paragraph in methodology_sector_matching_paragraphs():
        st.caption(paragraph)
    st.markdown("### Reverse DCF")
    for paragraph in methodology_reverse_dcf_paragraphs():
        st.caption(paragraph)
    st.markdown("### Sanity Checks: Two Parallel Pipelines")
    _render_financial_table(["Pipeline", "Code check", "Displayed category / message"], methodology_sanity_check_rows())
    st.markdown("### Business Model Compatibility Check")
    st.caption(
        "The operating-company DCF is flagged as structurally inappropriate for financial institutions, "
        "asset managers, real estate vehicles, and similar business models when the matched Damodaran sector "
        "contains one of the trigger fragments below."
    )
    _render_financial_table(["Trigger fragment"], methodology_business_model_rows())
    st.caption(
        "When triggered, Streamlit displays a critical warning and blocks Excel generation until the sidebar "
        "override is checked. The Excel Summary tab shows a red critical banner, changes Confidence to "
        "'CRITICAL - DCF model not appropriate for this business type. See Validation tab. Result should not be "
        "used as a fair value estimate.', and changes the selected tier status to 'Computed but flagged - critical "
        "sanity check applies. See Validation tab.'"
    )
    st.markdown("### Damodaran Excel Datasets Used")
    st.caption("These NYU Stern Damodaran workbooks are loaded by the app for beta, WACC validation, DCF fallback assumptions, and sector multiples.")
    _render_financial_table(["Purpose", "Region", "File", "URL"], damodaran_dataset_rows())
    st.markdown("### DCF Model Limitations")
    limitation_rows = [
        {
            "Category": "Companies in transition",
            "Description": "Recent capex booms, such as AI-driven datacenter buildouts, or temporary margin shocks can distort 3-5 year averages.",
        },
        {
            "Category": "Cyclical industries",
            "Description": "Point-in-time assumptions struggle with cyclical sectors such as oil/gas, semiconductors, and paper.",
        },
        {
            "Category": "Negative or near-zero profitability",
            "Description": "DCF can produce mathematically negative equity values; the user-facing implied price is clamped to zero while the raw result remains visible.",
        },
        {
            "Category": "Growth companies",
            "Description": "Historical CAGR may understate future growth for AI, cloud, or other transition stories.",
        },
        {
            "Category": "Quality premium",
            "Description": "Markets may price brand strength, switching costs, and network effects that historical financials do not capture.",
        },
    ]
    _render_financial_table(["Category", "Description"], limitation_rows)
    st.caption(DATA_SOURCES)


def methodology_tier_rows() -> list[dict[str, str]]:
    """Return DCF tier methodology rows from code constants and tier definitions."""
    standard_acceptance = _methodology_acceptance_text(STANDARD_DCF_MAX_DEVIATION)
    fallback_acceptance = _methodology_acceptance_text(FALLBACK_DCF_MAX_DEVIATION)
    return [
        {
            "Tier": "Tier 1",
            "Method": "Standard DCF",
            "Inputs": "Revenue growth from historical revenue CAGR; EBIT margin from latest FY actual; D&A from recent historical average; CapEx from historical CapEx/revenue or default source; working capital from historical current assets/current liabilities or default source.",
            "Skip condition": "Not run when latest revenue, latest EBIT margin, or shares outstanding are unavailable.",
            "Acceptance": standard_acceptance,
        },
        {
            "Tier": "Tier 2",
            "Method": "Smoothed DCF",
            "Inputs": "Revenue growth from 5-year historical CAGR floored at 0%; EBIT margin from 5-year average when available otherwise 3-year; D&A and CapEx from 5-year historical averages; same working-capital assumption as Tier 1.",
            "Skip condition": "Same availability gate as Tier 1; attempted only if no earlier tier has been selected.",
            "Acceptance": fallback_acceptance,
        },
        {
            "Tier": "Tier 3",
            "Method": "Sector Benchmark DCF",
            "Inputs": f"Revenue growth uses DEFAULT_TERMINAL_GROWTH ({DEFAULT_TERMINAL_GROWTH:.1%}); EBIT margin and CapEx/revenue use Damodaran sector benchmarks when available; D&A uses company 5-year historical average; same working-capital assumption as Tier 1.",
            "Skip condition": "Skipped when Damodaran sector EBIT margin is non-positive and its source starts with 'Damodaran sector benchmark'.",
            "Acceptance": fallback_acceptance,
        },
        {
            "Tier": "Tier 4",
            "Method": "Multiples-Based Valuation",
            "Inputs": "Damodaran sector EV/EBITDA, EV/Sales, and P/Book multiples. EV multiples convert enterprise value to equity value by subtracting net debt; P/Book multiplies tangible book value per share. Selected estimate is the median of positive available implied prices.",
            "Skip condition": "Rejected when no positive multiple-based implied prices are available, or when an accepted estimate is less than or equal to 50% of tangible book value per share.",
            "Acceptance": f"{fallback_acceptance}; additionally must be above 50% of tangible book value per share when tangible book value is available.",
        },
        {
            "Tier": "Tier 5",
            "Method": "Tangible Book Value Floor",
            "Inputs": "Total equity divided by shares outstanding.",
            "Skip condition": "No skip condition in the fallback path; used as the final reference floor when Tiers 1-4 do not produce an accepted result.",
            "Acceptance": "Reference floor only; accepted field is positive tangible book value per share, but Tier 5 is selected only when no earlier tier is accepted.",
        },
    ]


def _methodology_acceptance_text(max_deviation: float) -> str:
    """Describe the tier acceptance gate using source-code threshold constants."""
    return f"Implied price must be positive; if market price is available, |implied / market - 1| must be <= {max_deviation:.0%}."


def methodology_capm_rows() -> list[dict[str, str]]:
    """Return CAPM methodology rows based on valuation.py sources."""
    return [
        {"Component": "CAPM formula", "Formula / source": f"Cost of equity = risk-free rate + levered beta x market risk premium. MARKET_RISK_PREMIUM = {MARKET_RISK_PREMIUM:.1%}."},
        {"Component": "Risk-free rate", "Formula / source": "Yahoo Finance ^TNX latest close over the last 7 days; close is divided by 100 when the quote is above 1. Sanity range is 0.5%-15%."},
        {"Component": "Beta source", "Formula / source": "Damodaran industry unlevered beta from the matched beta workbook, re-levered with beta_L = beta_U x (1 + (1 - tax rate) x D/E)."},
        {"Component": "Equity risk premium", "Formula / source": f"Fixed source-code constant MARKET_RISK_PREMIUM = {MARKET_RISK_PREMIUM:.1%}."},
    ]


def methodology_wacc_rows() -> list[dict[str, str]]:
    """Return WACC and DCF horizon methodology rows based on valuation.py sources."""
    return [
        {"Component": "WACC formula", "Formula / source": "WACC = (E/V x cost of equity) + (D/V x cost of debt x (1 - tax rate))."},
        {"Component": "Cost of debt", "Formula / source": "abs(interest expense) / abs(total debt). If missing or outside the 1%-15% range, Damodaran industry cost of debt is used when available."},
        {"Component": "Tax rate", "Formula / source": "abs(income tax expense) / abs(pretax income), with fallback to Damodaran industry tax rate or 25%. Values outside 0%-40% use the fallback."},
        {"Component": "Capital structure", "Formula / source": "Equity weight = market cap / (market cap + total debt); debt weight = total debt / (market cap + total debt). Book debt is used when market debt is unavailable."},
        {"Component": "Projection horizon", "Formula / source": "Five annual forecast years: build_dcf_forecast iterates year 1 through year 5."},
        {"Component": "Terminal growth", "Formula / source": f"Historical revenue CAGR over the latest available 5-year window, capped to the 1.5%-{DEFAULT_TERMINAL_GROWTH:.1%} terminal range. If unavailable, DEFAULT_TERMINAL_GROWTH = {DEFAULT_TERMINAL_GROWTH:.1%}."},
    ]


def methodology_sector_matching_paragraphs() -> list[str]:
    """Return Damodaran matching explanation based on damodaran.py."""
    whitelist_items = ", ".join(f"{source} -> {target}" for source, target in sorted(INDUSTRY_WHITELIST.items()))
    return [
        "The app loads the Damodaran beta workbook selected by ticker region and normalizes the Damodaran industry table before matching.",
        "Matching first checks a curated exact mapping table for known ambiguous yfinance industry labels. Current mappings are: " + whitelist_items + ".",
        "If no curated mapping applies, the app uses rapidfuzz token_set_ratio against Damodaran industry choices, with a difflib fallback when rapidfuzz is unavailable. The top five candidates are retained for debug display.",
        "If match confidence is below 70%, the sidebar asks the user to select a Damodaran industry manually. Selecting an override calls build_beta_match with selected_industry, sets confidence to 100%, and uses the selected Damodaran row for beta and benchmark fields.",
    ]


def methodology_reverse_dcf_paragraphs() -> list[str]:
    """Return Reverse DCF explanation based on valuation.py and app.py rendering."""
    return [
        "Reverse DCF is a diagnostic tool, not a valuation tier. It holds Tier 1 Standard DCF inputs constant and solves only the year 1-5 revenue growth rate that would make the DCF implied share price equal the current market price.",
        "The solver searches from -10% to +50% revenue growth. It uses scipy.optimize.brentq with xtol=1e-6 and maxiter=100 when scipy is available, otherwise a deterministic bisection fallback with tolerance 1e-6 and max_iterations=100.",
        "Case A in the Streamlit UI is a successful solve with numeric implied growth, model assumed growth, and Yahoo revenue growth estimate cards. Case B is a failed or unreachable solve, shown as a 'Reverse DCF - Could not solve' box with Tier 1 growth and Yahoo revenue growth estimate context. Case C hides the section before valuation has been computed.",
        "For cyclical companies, the failure message can explicitly state that current Tier 1 EBIT margin is below 50% of the 5-year average, suggesting the market is pricing margin recovery rather than revenue growth.",
    ]


def methodology_sanity_check_rows() -> list[dict[str, str]]:
    """Return the two sanity-check pipelines from sanity_checks.py."""
    return [
        {"Pipeline": "run_sanity_checks()", "Code check": "_check_business_model_compatibility", "Displayed category / message": "Business Model Compatibility"},
        {"Pipeline": "run_sanity_checks()", "Code check": "_check_default_assumptions", "Displayed category / message": "Default assumptions"},
        {"Pipeline": "run_sanity_checks()", "Code check": "_check_beta", "Displayed category / message": "Levered beta is outside the usual 0-3 range; D/E ratio is above 5.0"},
        {"Pipeline": "run_sanity_checks()", "Code check": "_check_costs", "Displayed category / message": "Risk-free rate outside 0.5%-15%; cost of equity below risk-free rate; cost of equity above 25%; WACC outside 3%-20%; cost of debt outside 1%-15%; WACC above cost of equity"},
        {"Pipeline": "run_sanity_checks()", "Code check": "_check_dcf", "Displayed category / message": "Terminal growth >= WACC; terminal growth above 4%; implied price vs market sanity messages"},
        {"Pipeline": "run_sanity_checks()", "Code check": "_check_tax", "Displayed category / message": "Tax rate is outside the 0%-40% range"},
        {"Pipeline": "Excel-only analyst checks (build_excel_sanity_checks)", "Code check": "_check_ebit_margin_outlier", "Displayed category / message": "Margin volatility"},
        {"Pipeline": "Excel-only analyst checks (build_excel_sanity_checks)", "Code check": "_check_cost_of_debt_context", "Displayed category / message": "Cost of debt context"},
        {"Pipeline": "Excel-only analyst checks (build_excel_sanity_checks)", "Code check": "_check_effective_tax_context", "Displayed category / message": "Tax structure"},
        {"Pipeline": "Excel-only analyst checks (build_excel_sanity_checks)", "Code check": "_check_beta_methodology_gap", "Displayed category / message": "Beta methodology"},
        {"Pipeline": "Excel-only analyst checks (build_excel_sanity_checks)", "Code check": "_check_tier_price_gap", "Displayed category / message": "Margin assumption sensitivity"},
        {"Pipeline": "Excel-only analyst checks (build_excel_sanity_checks)", "Code check": "_check_implied_price_vs_market", "Displayed category / message": "Implied price vs market"},
    ]


def methodology_business_model_rows() -> list[dict[str, str]]:
    """Return exact business-model incompatibility trigger fragments from sanity_checks.py."""
    return [{"Trigger fragment": fragment} for fragment in INCOMPATIBLE_BUSINESS_MODEL_SECTOR_FRAGMENTS]


def damodaran_dataset_rows() -> list[dict[str, str]]:
    """Return all Damodaran workbook URLs used by the application."""
    rows: list[dict[str, str]] = []
    dataset_groups = [
        ("Industry beta / D/E / tax / cost of debt", BETA_URLS),
        ("WACC validation and cost of debt fallback", WACC_URLS),
        ("Tier 3 EBIT margin benchmark", DCF_MARGIN_URLS),
        ("Tier 3 CapEx / sales benchmark", DCF_CAPEX_URLS),
        ("Tier 4 EV/EBITDA multiple", MULTIPLE_EV_EBITDA_URLS),
        ("Tier 4 EV/Sales multiple", MULTIPLE_EV_SALES_URLS),
        ("Tier 4 P/Book multiple", MULTIPLE_PB_URLS),
    ]
    for purpose, mapping in dataset_groups:
        for region, url in mapping.items():
            rows.append({"Purpose": purpose, "Region": region, "File": _url_filename(url), "URL": url})
    supplemental = [
        ("Supplemental cost of equity validation", "global", COE_GLOBAL_URL),
        ("Supplemental industry tax-rate validation", "global", TAX_RATE_URL),
        ("Country risk premium lookup", "global", COUNTRY_PREMIUM_URL),
    ]
    for purpose, region, url in supplemental:
        rows.append({"Purpose": purpose, "Region": region, "File": _url_filename(url), "URL": url})
    return rows


def _url_filename(url: str) -> str:
    """Return a short filename from a URL for Methodology display."""
    return str(url).rstrip("/").rsplit("/", 1)[-1]


def render_debug_view(data: dict, beta_match, damodaran_table: pd.DataFrame | None) -> None:
    """Render hidden developer diagnostics for Damodaran loading and industry matching."""
    st.subheader("Debug")
    st.caption("Developer diagnostics for checking Damodaran source data and matching decisions.")

    if beta_match is None:
        st.error("Damodaran match is unavailable. Check the Streamlit console and logs for the original load error.")
        return

    load_rows = [
        {"Metric": "File", "Value": getattr(beta_match, "source_filename", "") or "N/A"},
        {"Metric": "Source path", "Value": getattr(beta_match, "source_url", "") or "N/A"},
        {"Metric": "Loaded at", "Value": getattr(beta_match, "loaded_at", "") or "N/A"},
        {"Metric": "Load status", "Value": "success" if getattr(beta_match, "load_success", False) else "failed"},
        {
            "Metric": "Rows parsed",
            "Value": str(getattr(beta_match, "damodaran_row_count", None) or (len(damodaran_table) if damodaran_table is not None else 0)),
        },
    ]
    _render_financial_table(["Metric", "Value"], load_rows)

    warnings = getattr(beta_match, "load_warnings", []) or []
    if warnings:
        st.warning("\n".join(str(warning) for warning in warnings))
    else:
        st.success("No Damodaran load warnings were recorded for the matched row.")
    st.info(
        "Damodaran provides effective tax rates that are often near zero for sectors with widespread tax shields. "
        "We use the marginal tax rate (25%) for comparison purposes as recommended in Damodaran's methodology."
    )

    info = data.get("info", {}) or {}
    matching_rows = [
        {"Metric": "Ticker", "Value": data.get("ticker", "N/A")},
        {"Metric": "Yahoo Finance industry", "Value": getattr(beta_match, "company_industry", "") or info.get("industry", "N/A")},
        {"Metric": "Damodaran industry", "Value": getattr(beta_match, "matched_industry", "N/A")},
        {"Metric": "Match confidence", "Value": f"{getattr(beta_match, 'confidence', 0):.1f}%"},
        {"Metric": "Matching logic", "Value": getattr(beta_match, "matching_method", "unknown")},
    ]
    st.markdown("#### Industry matching")
    _render_financial_table(["Metric", "Value"], matching_rows)

    top_matches = getattr(beta_match, "top_matches", []) or []
    if top_matches:
        st.caption("Top fuzzy match candidates")
        top_rows = [
            {"Metric": item.get("industry", ""), "Value": f"{float(item.get('score', 0)):.1f}%"}
            for item in top_matches
        ]
        _render_financial_table(["Metric", "Value"], top_rows)

    source_file = getattr(beta_match, "source_filename", "") or "N/A"
    source_row = getattr(beta_match, "source_row", None)
    row_label = str(source_row) if source_row is not None else "N/A"
    marginal_tax = DAMODARAN_MARGINAL_TAX_RATE_USA if getattr(beta_match, "source_region", "") == "us" else DAMODARAN_MARGINAL_TAX_RATE_EUROPE
    cost_of_debt_details = get_damodaran_industry_cost_of_debt_details(
        getattr(beta_match, "company_industry", ""),
        getattr(beta_match, "source_region", "global"),
    )
    cost_source_file = cost_of_debt_details.get("source_file") or source_file
    cost_source_row = cost_of_debt_details.get("source_row")
    used_rows = [
        {
            "Metric": "Industry beta",
            "Value": "" if beta_match.unlevered_beta is None else f"{beta_match.unlevered_beta:.4f}",
            "Source file": source_file,
            "Source row": row_label,
        },
        {
            "Metric": "Industry D/E",
            "Value": format_percentage(beta_match.industry_de_ratio * 100 if beta_match.industry_de_ratio is not None else None),
            "Source file": source_file,
            "Source row": row_label,
        },
        {
            "Metric": "Industry effective tax rate (Damodaran raw)",
            "Value": format_percentage(beta_match.industry_tax_rate * 100 if beta_match.industry_tax_rate is not None else None),
            "Source file": source_file,
            "Source row": row_label,
        },
        {
            "Metric": "Industry marginal tax rate (used in validation calc)",
            "Value": format_percentage(marginal_tax * 100),
            "Source file": "Damodaran methodology recommendation",
            "Source row": "workbook top rows",
        },
        {
            "Metric": "Industry cost of debt",
            "Value": format_percentage(cost_of_debt_details.get("value") * 100 if cost_of_debt_details.get("value") is not None else None),
            "Source file": cost_source_file,
            "Source row": str(cost_source_row) if cost_source_row is not None else "N/A",
        },
    ]

    row_data = getattr(beta_match, "row_data", {}) or {}
    extra_metrics = {
        "Industry net margin": [["net", "margin"]],
        "Industry ROE": [["roe"], ["return", "equity"]],
        "Industry EBITDA margin": [["ebitda", "margin"], ["ebitda", "sales"]],
        "Industry EBIT margin": [["operating", "margin"], ["ebit", "margin"]],
        "Industry revenue growth": [["revenue", "growth"], ["sales", "growth"]],
    }
    for metric, fragment_sets in extra_metrics.items():
        for fragments in fragment_sets:
            _column, value = _find_row_benchmark_with_key(row_data, fragments)
            if value is not None:
                used_rows.append(
                    {
                        "Metric": metric,
                        "Value": format_percentage(value),
                        "Source file": source_file,
                        "Source row": row_label,
                    }
                )
                break

    st.markdown("#### Used Damodaran values")
    _render_financial_table(["Metric", "Value", "Source file", "Source row"], used_rows)

    valuation = st.session_state.get("last_valuation")
    if st.session_state.get("last_valuation_ticker") == data.get("ticker") and valuation:
        currency_code = reporting_currency(data)
        dcf_rows = []
        for tier in valuation.get("dcf_tiers", []) or []:
            tier_dcf = tier.get("dcf") or {}
            assumptions = tier.get("assumptions") or {}
            reason = tier.get("selection_reason") or tier.get("rejection_reason") or "passed sanity check"
            dcf_rows.append(
                {
                    "Metric": f"Tier {tier.get('tier')} attempted",
                    "Value": (
                        f"{format_share_price(tier_dcf.get('implied_price'), currency_code)} -> "
                        f"{'ACCEPTED' if tier.get('selected') else tier.get('status', 'REJECTED')} ({reason})"
                    ),
                }
            )
            if tier.get("tier") == 3:
                dcf_rows.extend(
                    [
                        {
                            "Metric": "Tier 3 EBIT margin source",
                            "Value": (
                                f"{format_percentage((assumptions.get('ebit_margin') or 0) * 100)} | "
                                f"{assumptions.get('ebit_margin_source') or 'N/A'} | "
                                f"{assumptions.get('ebit_margin_source_file') or 'N/A'}"
                            ),
                        },
                        {
                            "Metric": "Tier 3 CapEx source",
                            "Value": (
                                f"{format_percentage((assumptions.get('capex_pct_revenue') or 0) * 100)} | "
                                f"{assumptions.get('capex_source') or 'N/A'} | "
                                f"{assumptions.get('capex_source_file') or 'N/A'}"
                            ),
                        },
                    ]
                )
            if tier.get("tier") == 4:
                dcf_rows.append(
                    {
                        "Metric": "Tier 4 data coverage",
                        "Value": tier.get("detail_status") or "N/A",
                    }
                )
                for item in tier.get("multiples", []) or []:
                    source_parts = [
                        format_multiple(item.get("multiple")),
                        format_share_price(item.get("implied_price"), currency_code),
                        item.get("source_file") or "N/A",
                    ]
                    if item.get("error"):
                        source_parts.append(item.get("error"))
                    else:
                        source_parts.append(item.get("source") or "N/A")
                    dcf_rows.append(
                        {
                            "Metric": f"Tier 4 {item.get('method')}",
                            "Value": " | ".join(source_parts),
                        }
                    )
        selected = valuation.get("selected_dcf_tier") or {}
        if selected:
            dcf_rows.append({"Metric": "Final", "Value": f"Tier {selected.get('tier')} ({selected.get('name')})"})
        if dcf_rows:
            st.markdown("#### DCF Tier Selection")
            _render_financial_table(["Metric", "Value"], dcf_rows)

    with st.expander("Matched Damodaran row data"):
        st.json({str(key): str(value) for key, value in row_data.items()})


def render_single_company_analysis(data: dict, beta_match=None, damodaran_table: pd.DataFrame | None = None) -> None:
    """Render all analysis tabs for one company."""
    income_metrics = build_income_statement_metrics(data["income_statement"])
    balance_metrics = build_balance_sheet_metrics(data["balance_sheet"])
    cash_flow_metrics = build_cash_flow_metrics(data["cash_flow"])
    kpis = build_kpi_metrics(data, income_metrics, balance_metrics, cash_flow_metrics)
    kpi_history = build_kpi_history(data, income_metrics, balance_metrics)
    analysis = build_analysis_summary(income_metrics, balance_metrics, cash_flow_metrics, kpis)
    dividend_metrics = build_dividend_metrics(data, income_metrics)
    surprise_metrics = build_earnings_surprise_metrics(data)
    currency_code = reporting_currency(data)
    fy_label = latest_fy_label(income_metrics)
    chart_benchmarks = extract_chart_benchmarks(beta_match)

    render_company_header(data)
    if st.session_state.get("last_valuation_ticker") == data.get("ticker"):
        render_dcf_tier_notice(st.session_state.get("last_valuation"))
    render_kpi_dashboard(kpis, kpi_history, fy_label)

    tab_names = [
        "Analysis overview",
        "Income statement",
        "Balance sheet",
        "Cash flow",
        "Dividends",
        "Surprises",
        "Scenario",
        "Methodology",
    ]
    show_debug = bool(st.session_state.get("show_debug", False))
    if show_debug:
        tab_names.append("Debug")
    tabs = st.tabs(tab_names)
    overview_valuation = (
        st.session_state.get("last_valuation")
        if st.session_state.get("last_valuation_ticker") == data.get("ticker")
        else None
    )

    with tabs[0]:
        render_analysis_overview(analysis, income_metrics, balance_metrics, cash_flow_metrics, currency_code, overview_valuation)
        render_pdf_export(data, kpis, analysis, income_metrics, balance_metrics, cash_flow_metrics)

    with tabs[1]:
        left, right = st.columns(2)
        with left:
            st.plotly_chart(
                create_revenue_chart(
                    income_metrics,
                    currency_code,
                    sector_growth_median=chart_benchmarks.get("revenue_growth"),
                ),
                use_container_width=True,
                config=chart_config("revenue"),
            )
        with right:
            st.plotly_chart(
                create_margin_chart(income_metrics, industry_medians=chart_benchmarks),
                use_container_width=True,
                config=chart_config("margins"),
            )
        render_statement_dataframe(income_metrics, "Income Statement")

    with tabs[2]:
        left, right = st.columns([2, 1])
        with left:
            st.plotly_chart(
                create_balance_structure_chart(balance_metrics, income_metrics, currency_code),
                use_container_width=True,
                config=chart_config("balance_sheet"),
            )
        with right:
            latest = balance_metrics.iloc[-1].to_dict() if not balance_metrics.empty else {}
            st.metric("Equity ratio", format_percentage(latest.get("equity_ratio")))
            net_label, net_value, net_help = net_debt_display(latest.get("net_debt"), money_suffix(currency_code))
            st.metric(f"{net_label} ({latest_fy_label(balance_metrics)})", net_value, help=net_help)
        render_statement_dataframe(balance_metrics, "Balance Sheet")

    with tabs[3]:
        st.plotly_chart(
            create_cash_flow_chart(cash_flow_metrics, income_metrics, currency_code),
            use_container_width=True,
            config=chart_config("cash_flow"),
        )
        render_statement_dataframe(cash_flow_metrics, "Cash Flow")

    with tabs[4]:
        render_dividends(dividend_metrics, currency_code)

    with tabs[5]:
        render_surprises(surprise_metrics)

    with tabs[6]:
        render_scenario_analysis(data, income_metrics, chart_benchmarks)

    with tabs[7]:
        render_methodology()

    if show_debug:
        with tabs[8]:
            render_debug_view(data, beta_match, damodaran_table)


def _style_comparison_table(frame: pd.DataFrame):
    """Apply simple green-red coloring to comparison metrics."""
    higher_better = {"revenue", "roe", "roce", "ebit_margin", "equity_ratio", "free_cash_flow"}
    lower_better = {"pe_ratio", "ev_to_ebitda", "leverage", "net_debt"}

    def style_column(column: pd.Series) -> list[str]:
        if column.name not in higher_better | lower_better:
            return ["" for _ in column]
        values = pd.to_numeric(column, errors="coerce")
        if values.dropna().empty or values.max() == values.min():
            return ["" for _ in column]
        styles = []
        for value in values:
            if pd.isna(value):
                styles.append("")
            elif column.name in higher_better:
                styles.append(f"background-color: {'rgba(46,204,113,0.22)' if value == values.max() else 'rgba(255,92,92,0.16)'}")
            else:
                styles.append(f"background-color: {'rgba(46,204,113,0.22)' if value == values.min() else 'rgba(255,92,92,0.16)'}")
        return styles

    return frame.style.apply(style_column, axis=0)


def render_comparison(primary_data: dict, comparison_ticker: str) -> None:
    """Render side-by-side comparison for two companies."""
    if not comparison_ticker:
        return

    skeleton = st.empty()
    try:
        skeleton.markdown('<div class="skeleton-card"></div>', unsafe_allow_html=True)
        comparison_data = load_financial_data(comparison_ticker)
    except FinancialDataError as exc:
        skeleton.empty()
        st.warning(str(exc))
        return
    skeleton.empty()

    primary_income = build_income_statement_metrics(primary_data["income_statement"])
    primary_balance = build_balance_sheet_metrics(primary_data["balance_sheet"])
    primary_cash = build_cash_flow_metrics(primary_data["cash_flow"])
    primary_kpis = build_kpi_metrics(primary_data, primary_income, primary_balance, primary_cash)

    comparison_income = build_income_statement_metrics(comparison_data["income_statement"])
    comparison_balance = build_balance_sheet_metrics(comparison_data["balance_sheet"])
    comparison_cash = build_cash_flow_metrics(comparison_data["cash_flow"])
    comparison_kpis = build_kpi_metrics(
        comparison_data, comparison_income, comparison_balance, comparison_cash
    )

    comparison_frame = compare_companies(
        primary_data,
        primary_income,
        primary_balance,
        primary_cash,
        primary_kpis,
        comparison_data,
        comparison_income,
        comparison_balance,
        comparison_cash,
        comparison_kpis,
    )

    st.subheader("Company comparison")
    currencies = comparison_frame.get("currency", pd.Series(dtype=object)).dropna().unique()
    if len(currencies) > 1:
        st.warning(
            "Comparison companies report in different currencies. Monetary statement values are not converted; "
            "use margin and ratio metrics for cleaner peer comparison."
        )
    left, right = st.columns([0.48, 0.52])
    with left:
        st.plotly_chart(
            create_radar_comparison_chart(comparison_frame),
            use_container_width=True,
            config=chart_config("peer_radar"),
        )
    with right:
        st.plotly_chart(
            create_comparison_chart(comparison_frame),
            use_container_width=True,
            config=chart_config("peer_comparison"),
        )
    fy_columns = [
        "company",
        "ticker",
        "currency",
        "revenue",
        "ebit_margin",
        "net_margin",
        "equity_ratio",
        "net_debt",
        "free_cash_flow",
        "roe",
        "roce",
        "leverage",
    ]
    ttm_columns = ["company", "ticker", "currency", "pe_ratio", "ev_to_ebitda"]
    st.markdown("#### FY peer metrics")
    st.caption("Fiscal-year statement metrics only. Monetary values are reported in each company's original currency.")
    st.dataframe(
        _style_comparison_table(comparison_frame[[column for column in fy_columns if column in comparison_frame.columns]]),
        use_container_width=True,
        hide_index=True,
    )
    st.markdown("#### TTM market multiples")
    st.caption("Trailing twelve months market multiples from Yahoo Finance. These are not mixed into FY statement tables.")
    st.dataframe(
        _style_comparison_table(comparison_frame[[column for column in ttm_columns if column in comparison_frame.columns]]),
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    """Run the Streamlit application."""
    apply_custom_theme()
    st.title(APP_TITLE)
    st.caption(APP_TAGLINE)

    with st.sidebar:
        st.header("Search")
        ticker = st.text_input(
            "Ticker symbol",
            value="KNEBV.HE",
            placeholder="Examples: KNEBV.HE, AAPL, MSFT",
        )
        comparison_ticker = st.text_input(
            "Comparison ticker",
            value="",
            placeholder="Example: 6484.T",
        )
        st.info("For Nasdaq Helsinki, use the .HE suffix, for example KNEBV.HE.")
        show_validation = st.toggle("Show validation against Damodaran benchmarks", value=False)
        st.toggle("Show debug info", value=False, key="show_debug")
        st.caption(f"Last updated: {current_timestamp()}")

    if not ticker:
        st.warning("Enter a ticker symbol to start.")
        return

    skeleton = st.empty()
    try:
        skeleton.markdown(
            '<div class="skeleton-card skeleton-title"></div><div class="skeleton-card"></div><br><div class="skeleton-card"></div>',
            unsafe_allow_html=True,
        )
        data = load_financial_data(ticker)
    except FinancialDataError as exc:
        skeleton.empty()
        st.error(str(exc))
        st.stop()
    skeleton.empty()

    income_metrics = build_income_statement_metrics(data["income_statement"])
    balance_metrics = build_balance_sheet_metrics(data["balance_sheet"])
    cash_flow_metrics = build_cash_flow_metrics(data["cash_flow"])
    beta_match, damodaran_table = prepare_damodaran_match(data)
    render_beta_source_box(beta_match)

    render_single_company_analysis(data, beta_match, damodaran_table)
    render_comparison(data, comparison_ticker.strip())
    render_valuation_sidebar(
        data,
        income_metrics,
        balance_metrics,
        cash_flow_metrics,
        beta_match,
        show_validation,
    )

    st.divider()
    st.caption(f"{DATA_SOURCES} | Generated: {current_timestamp()} | {DISCLAIMER}")


if __name__ == "__main__":
    main()
