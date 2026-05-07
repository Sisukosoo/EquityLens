"""Financial ratio and statement calculations."""

from __future__ import annotations

import math
import re
from datetime import datetime
from typing import Iterable

import numpy as np
import pandas as pd


def _safe_divide(numerator: float | None, denominator: float | None) -> float | None:
    """Divide values safely and return None when the denominator is unusable."""
    if numerator is None or denominator in (None, 0):
        return None
    try:
        if pd.isna(numerator) or pd.isna(denominator):
            return None
        return float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _to_millions(value: float | int | None) -> float | None:
    """Convert a raw financial statement value to millions."""
    if value is None or pd.isna(value):
        return None
    return float(value) / 1_000_000


def _find_line(statement: pd.DataFrame, candidates: Iterable[str]) -> pd.Series:
    """Find the first matching line item in a financial statement."""
    if statement is None or statement.empty:
        return pd.Series(dtype=float)

    normalized_index = {
        _normalize_statement_label(str(index)): index for index in statement.index
    }
    for candidate in candidates:
        key = _normalize_statement_label(candidate)
        if key in normalized_index:
            return statement.loc[normalized_index[key]]

    return pd.Series(index=statement.columns, data=np.nan, dtype=float)


def _normalize_statement_label(label: str) -> str:
    """Normalize statement labels from Yahoo Finance for resilient matching."""
    return re.sub(r"[^a-z0-9]", "", label.lower())


def _series_value(series: pd.Series, column) -> float | None:
    """Read one value from a statement row."""
    if series is None or series.empty or column not in series.index:
        return None
    value = series.loc[column]
    if pd.isna(value):
        return None
    return float(value)


def _statement_years(statement: pd.DataFrame) -> list:
    """Return available statement columns sorted from oldest to newest."""
    if statement is None or statement.empty:
        return []
    return sorted(statement.columns)


def _period_metadata(period_end: pd.Timestamp) -> dict:
    """Return fiscal period labels from a statement column date."""
    timestamp = pd.Timestamp(period_end)
    month_label = timestamp.strftime("%b %Y")
    fiscal_year = f"FY{timestamp.year}"
    return {
        "year": timestamp.year,
        "period": f"{fiscal_year} (ended {month_label})",
        "period_end": timestamp.strftime("%Y-%m-%d"),
        "period_type": "FY",
    }


def _percentage(numerator: float | None, denominator: float | None) -> float | None:
    """Return a percentage ratio."""
    ratio = _safe_divide(numerator, denominator)
    if ratio is None:
        return None

    # Yahoo Finance sometimes mixes units for individual line items. Try common
    # scale corrections before accepting an impossible percentage.
    if abs(ratio * 100) > 200 and numerator is not None and denominator is not None:
        for scale in (1_000, 1_000_000):
            corrected = _safe_divide(float(numerator) / scale, denominator)
            if corrected is not None and abs(corrected * 100) <= 200:
                ratio = corrected
                break

    return ratio * 100


def _clean_frame(rows: list[dict]) -> pd.DataFrame:
    """Create a clean DataFrame with numeric None values preserved."""
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return frame.replace({math.nan: None})


def build_income_statement_metrics(income_statement: pd.DataFrame) -> pd.DataFrame:
    """Build yearly income statement metrics in millions."""
    revenue = _find_line(income_statement, ["Total Revenue", "Operating Revenue"])
    gross_profit = _find_line(income_statement, ["Gross Profit"])
    ebitda = _find_line(income_statement, ["EBITDA", "Normalized EBITDA"])
    ebit = _find_line(
        income_statement,
        ["EBIT", "Operating Income", "Operating Income Loss", "Normalized Income"],
    )
    net_income = _find_line(
        income_statement,
        ["Net Income", "Net Income Common Stockholders", "Net Income From Continuing Operation Net Minority Interest"],
    )
    pretax_income = _find_line(
        income_statement,
        ["Pretax Income", "Pretax Income Loss", "Income Before Tax"],
    )
    income_tax = _find_line(
        income_statement,
        ["Tax Provision", "Income Tax Expense", "Income Tax Expense Benefit"],
    )
    interest_expense = _find_line(
        income_statement,
        ["Interest Expense", "Interest Expense Non Operating", "Net Interest Income"],
    )

    rows = []
    for year in _statement_years(income_statement):
        period = _period_metadata(year)
        revenue_raw = _series_value(revenue, year)
        gross_profit_raw = _series_value(gross_profit, year)
        ebitda_raw = _series_value(ebitda, year)
        ebit_raw = _series_value(ebit, year)
        net_income_raw = _series_value(net_income, year)
        pretax_income_raw = _series_value(pretax_income, year)
        income_tax_raw = _series_value(income_tax, year)
        interest_expense_raw = _series_value(interest_expense, year)

        rows.append(
            {
                **period,
                "revenue": _to_millions(revenue_raw),
                "gross_profit": _to_millions(gross_profit_raw),
                "ebitda": _to_millions(ebitda_raw),
                "ebit": _to_millions(ebit_raw),
                "net_income": _to_millions(net_income_raw),
                "pretax_income": _to_millions(pretax_income_raw),
                "income_tax_expense": _to_millions(income_tax_raw),
                "interest_expense": _to_millions(interest_expense_raw),
                "gross_margin": _percentage(gross_profit_raw, revenue_raw),
                "ebitda_margin": _percentage(ebitda_raw, revenue_raw),
                "ebit_margin": _percentage(ebit_raw, revenue_raw),
                "net_margin": _percentage(net_income_raw, revenue_raw),
            }
        )

    return _clean_frame(rows)


def build_balance_sheet_metrics(balance_sheet: pd.DataFrame) -> pd.DataFrame:
    """Build yearly balance sheet metrics in millions."""
    total_assets = _find_line(balance_sheet, ["Total Assets"])
    total_liabilities = _find_line(
        balance_sheet,
        ["Total Liabilities Net Minority Interest", "Total Liabilities"],
    )
    total_equity = _find_line(
        balance_sheet,
        ["Stockholders Equity", "Total Equity Gross Minority Interest", "Common Stock Equity"],
    )
    cash = _find_line(
        balance_sheet,
        ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"],
    )
    debt = _find_line(balance_sheet, ["Total Debt", "Long Term Debt And Capital Lease Obligation"])
    current_assets = _find_line(
        balance_sheet,
        ["Current Assets", "Total Current Assets"],
    )
    current_liabilities = _find_line(
        balance_sheet,
        ["Current Liabilities", "Total Current Liabilities"],
    )

    rows = []
    for year in _statement_years(balance_sheet):
        period = _period_metadata(year)
        assets_raw = _series_value(total_assets, year)
        liabilities_raw = _series_value(total_liabilities, year)
        equity_raw = _series_value(total_equity, year)
        cash_raw = _series_value(cash, year) or 0
        debt_raw = _series_value(debt, year) or 0
        current_assets_raw = _series_value(current_assets, year)
        current_liabilities_raw = _series_value(current_liabilities, year)

        rows.append(
            {
                **period,
                "total_assets": _to_millions(assets_raw),
                "total_liabilities": _to_millions(liabilities_raw),
                "total_equity": _to_millions(equity_raw),
                "cash": _to_millions(cash_raw),
                "debt": _to_millions(debt_raw),
                "net_debt": _to_millions(debt_raw - cash_raw),
                "current_assets": _to_millions(current_assets_raw),
                "current_liabilities": _to_millions(current_liabilities_raw),
                "equity_ratio": _percentage(equity_raw, assets_raw),
            }
        )

    return _clean_frame(rows)


def build_cash_flow_metrics(cash_flow: pd.DataFrame) -> pd.DataFrame:
    """Build yearly cash flow metrics in millions."""
    operating_cash_flow = _find_line(
        cash_flow,
        ["Operating Cash Flow", "Total Cash From Operating Activities"],
    )
    capital_expenditure = _find_line(
        cash_flow,
        ["Capital Expenditure", "Capital Expenditures"],
    )
    free_cash_flow = _find_line(cash_flow, ["Free Cash Flow"])

    rows = []
    for year in _statement_years(cash_flow):
        period = _period_metadata(year)
        operating_raw = _series_value(operating_cash_flow, year)
        capex_raw = _series_value(capital_expenditure, year)
        free_cash_flow_raw = _series_value(free_cash_flow, year)

        if free_cash_flow_raw is None and operating_raw is not None:
            free_cash_flow_raw = operating_raw + (capex_raw or 0)

        rows.append(
            {
                **period,
                "operating_cash_flow": _to_millions(operating_raw),
                "capital_expenditure": _to_millions(capex_raw),
                "free_cash_flow": _to_millions(free_cash_flow_raw),
            }
        )

    return _clean_frame(rows)


def _latest_value(frame: pd.DataFrame, column: str) -> float | None:
    """Return latest non-empty value from a calculated metric frame."""
    if frame.empty or column not in frame.columns:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])


def _first_value(frame: pd.DataFrame, column: str) -> float | None:
    """Return earliest non-empty value from a calculated metric frame."""
    if frame.empty or column not in frame.columns:
        return None
    values = frame[column].dropna()
    if values.empty:
        return None
    return float(values.iloc[0])


def _cagr(start_value: float | None, end_value: float | None, periods: int) -> float | None:
    """Calculate compound annual growth rate as a percentage."""
    if start_value is None or end_value is None or periods <= 0:
        return None
    if start_value <= 0 or end_value <= 0:
        return None
    return ((end_value / start_value) ** (1 / periods) - 1) * 100


def _year_span(frame: pd.DataFrame) -> int:
    """Return the number of periods between the first and latest year."""
    if frame.empty or "year" not in frame.columns:
        return 0
    years = pd.to_numeric(frame["year"], errors="coerce").dropna()
    if len(years) < 2:
        return 0
    return int(years.iloc[-1] - years.iloc[0])


def _metric_status(value: float | None, good: float, watch: float, higher_is_better: bool = True) -> str:
    """Classify a metric into a simple professional status label."""
    if value is None:
        return "No data"
    if higher_is_better:
        if value >= good:
            return "Strong"
        if value >= watch:
            return "Watch"
        return "Weak"
    if value <= good:
        return "Strong"
    if value <= watch:
        return "Watch"
    return "Weak"


def _change_text(metric_name: str, value: float | None, unit: str) -> str:
    """Create a short sentence for one analysis metric."""
    if value is None:
        return f"{metric_name}: not enough data available."
    direction = "positive" if value >= 0 else "negative"
    return f"{metric_name}: {value:.1f}{unit}, which is {direction} over the available period."


def build_analysis_summary(
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    kpis: dict,
) -> dict:
    """Build higher-level financial analysis for the overview tab."""
    latest_revenue = _latest_value(income_metrics, "revenue")
    first_revenue = _first_value(income_metrics, "revenue")
    latest_ebitda = _latest_value(income_metrics, "ebitda")
    latest_net_income = _latest_value(income_metrics, "net_income")
    latest_fcf = _latest_value(cash_flow_metrics, "free_cash_flow")
    latest_net_debt = _latest_value(balance_metrics, "net_debt")
    latest_net_margin = _latest_value(income_metrics, "net_margin")
    first_net_margin = _first_value(income_metrics, "net_margin")
    latest_ebit_margin = _latest_value(income_metrics, "ebit_margin")
    first_ebit_margin = _first_value(income_metrics, "ebit_margin")
    latest_equity_ratio = _latest_value(balance_metrics, "equity_ratio")

    periods = _year_span(income_metrics)
    revenue_cagr = _cagr(first_revenue, latest_revenue, periods)
    ebit_margin_change = None
    if latest_ebit_margin is not None and first_ebit_margin is not None:
        ebit_margin_change = latest_ebit_margin - first_ebit_margin

    net_margin_change = None
    if latest_net_margin is not None and first_net_margin is not None:
        net_margin_change = latest_net_margin - first_net_margin

    fcf_conversion = None
    if latest_fcf is not None and latest_net_income not in (None, 0):
        fcf_conversion = latest_fcf / latest_net_income * 100

    net_debt_to_ebitda = None
    if latest_net_debt is not None and latest_ebitda not in (None, 0):
        net_debt_to_ebitda = latest_net_debt / latest_ebitda

    overview = {
        "revenue_cagr": revenue_cagr,
        "ebit_margin_change": ebit_margin_change,
        "net_margin_change": net_margin_change,
        "fcf_conversion": fcf_conversion,
        "net_debt_to_ebitda": net_debt_to_ebitda,
        "equity_ratio": latest_equity_ratio,
        "roe": kpis.get("roe"),
        "roce": kpis.get("roce"),
    }

    scorecard = [
        {
            "area": "Growth",
            "metric": "Revenue CAGR",
            "value": revenue_cagr,
            "unit": "%",
            "status": _metric_status(revenue_cagr, good=5, watch=0),
        },
        {
            "area": "Profitability",
            "metric": "EBIT margin",
            "value": latest_ebit_margin,
            "unit": "%",
            "status": _metric_status(latest_ebit_margin, good=15, watch=8),
        },
        {
            "area": "Cash quality",
            "metric": "FCF conversion",
            "value": fcf_conversion,
            "unit": "%",
            "status": _metric_status(fcf_conversion, good=80, watch=40),
        },
        {
            "area": "Leverage",
            "metric": "Net debt / EBITDA",
            "value": net_debt_to_ebitda,
            "unit": "x",
            "status": _metric_status(net_debt_to_ebitda, good=1.5, watch=3.0, higher_is_better=False),
        },
        {
            "area": "Solvency",
            "metric": "Equity ratio",
            "value": latest_equity_ratio,
            "unit": "%",
            "status": _metric_status(latest_equity_ratio, good=40, watch=25),
        },
    ]

    insights = [
        _change_text("Revenue CAGR", revenue_cagr, "%"),
        _change_text("EBIT margin change", ebit_margin_change, " percentage points"),
        _change_text("Net margin change", net_margin_change, " percentage points"),
    ]

    if fcf_conversion is not None:
        if fcf_conversion >= 80:
            insights.append("Cash conversion is strong: free cash flow covers most of reported earnings.")
        elif fcf_conversion >= 40:
            insights.append("Cash conversion is moderate: earnings quality should be monitored.")
        else:
            insights.append("Cash conversion is weak: reported profit is not translating strongly into free cash flow.")

    if net_debt_to_ebitda is not None:
        if net_debt_to_ebitda < 0:
            insights.append("The company has net cash, which gives balance sheet flexibility.")
        elif net_debt_to_ebitda <= 1.5:
            insights.append("Leverage appears conservative relative to EBITDA.")
        elif net_debt_to_ebitda <= 3:
            insights.append("Leverage is moderate and should be compared with sector norms.")
        else:
            insights.append("Leverage is elevated and deserves closer review.")

    return {
        "overview": overview,
        "scorecard": pd.DataFrame(scorecard),
        "insights": insights,
    }


def build_kpi_history(
    data: dict,
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Build historical KPI series for card deltas and sparklines."""
    if income_metrics.empty:
        return pd.DataFrame()

    frame = income_metrics.merge(balance_metrics, on="year", how="left")

    rows = []
    for _, row in frame.iterrows():
        capital_employed = None
        if pd.notna(row.get("total_assets")) and pd.notna(row.get("current_liabilities")):
            capital_employed = row.get("total_assets") - row.get("current_liabilities")

        rows.append(
            {
                "year": row.get("year"),
                "period": row.get("period"),
                "roe": _percentage(row.get("net_income"), row.get("total_equity")),
                "roce": _percentage(row.get("ebit"), capital_employed),
            }
        )

    return _clean_frame(rows)


def build_dividend_metrics(
    data: dict,
    income_metrics: pd.DataFrame,
) -> pd.DataFrame:
    """Build annual dividend, yield, and payout ratio metrics."""
    dividends = data.get("dividends")
    if dividends is None or dividends.empty:
        return pd.DataFrame()

    info = data.get("info", {})
    shares_outstanding = info.get("sharesOutstanding")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")
    current_year = datetime.now().year

    rows = []
    for year, dividend_per_share in dividends.items():
        year_int = int(year)
        net_income = None
        payout_ratio_note = "Payout ratio unavailable - matching net income data not available from Yahoo Finance"
        if not income_metrics.empty and "year" in income_metrics.columns:
            year_rows = income_metrics[income_metrics["year"] == year_int]
            if not year_rows.empty:
                net_income = year_rows.iloc[-1].get("net_income")
                payout_ratio_note = "Payout ratio unavailable - net income is missing or zero"

        payout_ratio = None
        if shares_outstanding and net_income not in (None, 0):
            total_dividends_millions = float(dividend_per_share) * shares_outstanding / 1_000_000
            payout_ratio = total_dividends_millions / float(net_income) * 100
            payout_ratio_note = "Calculated from annual dividends, shares outstanding, and same-year net income"
        elif year_int == current_year:
            payout_ratio_note = "Payout ratio unavailable - current-year dividend is year-to-date and FY net income is not available yet"

        dividend_yield = None
        if current_price not in (None, 0):
            dividend_yield = float(dividend_per_share) / float(current_price) * 100

        rows.append(
            {
                "year": year_int,
                "period": f"FY{year_int} YTD" if year_int == current_year else f"FY{year_int}",
                "dividend_per_share": float(dividend_per_share),
                "payout_ratio": payout_ratio,
                "dividend_yield": dividend_yield,
                "payout_ratio_note": payout_ratio_note,
            }
        )

    frame = _clean_frame(rows)
    if not frame.empty and "dividend_yield" in frame.columns:
        frame["historical_avg_yield"] = pd.to_numeric(
            frame["dividend_yield"], errors="coerce"
        ).mean()
    return frame


def build_earnings_surprise_metrics(data: dict) -> pd.DataFrame:
    """Normalize yfinance earnings surprise data for visualization."""
    raw_frame = data.get("earnings_surprises")
    if raw_frame is None or raw_frame.empty:
        return pd.DataFrame()

    column_map = {}
    for column in raw_frame.columns:
        normalized = _normalize_statement_label(column)
        if normalized in {"earningsdate", "index"}:
            column_map[column] = "date"
        elif normalized == "epsestimate":
            column_map[column] = "eps_estimate"
        elif normalized == "reportedeps":
            column_map[column] = "reported_eps"
        elif normalized in {"surprise", "surprisepercent"}:
            column_map[column] = "surprise_pct"

    frame = raw_frame.rename(columns=column_map)
    required = {"date", "eps_estimate", "reported_eps"}
    if not required.issubset(frame.columns):
        return pd.DataFrame()

    frame = frame[list(required | {"surprise_pct"}.intersection(frame.columns))].copy()
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["eps_estimate"] = pd.to_numeric(frame["eps_estimate"], errors="coerce")
    frame["reported_eps"] = pd.to_numeric(frame["reported_eps"], errors="coerce")
    if "surprise_pct" in frame.columns:
        frame["surprise_pct"] = pd.to_numeric(frame["surprise_pct"], errors="coerce")
    else:
        frame["surprise_pct"] = (
            (frame["reported_eps"] - frame["eps_estimate"]) / frame["eps_estimate"].abs() * 100
        )

    frame = frame.dropna(subset=["date", "eps_estimate", "reported_eps"])
    if frame.empty:
        return pd.DataFrame()

    frame["period"] = frame["date"].dt.strftime("%Y-%m-%d")
    return frame.sort_values("date").tail(8)


def build_scenario_projection(
    income_metrics: pd.DataFrame,
    shares_outstanding: int | float | None,
    revenue_growth_pct: float,
    margin_change_pp: float,
) -> dict:
    """Project revenue, net income, and EPS from simple user assumptions."""
    latest_revenue = _latest_value(income_metrics, "revenue")
    latest_net_margin = _latest_value(income_metrics, "net_margin")
    if latest_revenue is None or latest_net_margin is None:
        return {}

    projected_revenue = latest_revenue * (1 + revenue_growth_pct / 100)
    projected_margin = latest_net_margin + margin_change_pp
    projected_net_income = projected_revenue * projected_margin / 100

    projected_eps = None
    if shares_outstanding:
        projected_eps = projected_net_income * 1_000_000 / float(shares_outstanding)

    return {
        "base_revenue": latest_revenue,
        "base_net_margin": latest_net_margin,
        "projected_revenue": projected_revenue,
        "projected_net_margin": projected_margin,
        "projected_net_income": projected_net_income,
        "projected_eps": projected_eps,
    }


def build_kpi_metrics(
    data: dict,
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
) -> dict:
    """Calculate dashboard KPIs from statements and Yahoo Finance metadata."""
    info = data.get("info", {})

    net_income = _latest_value(income_metrics, "net_income")
    ebit = _latest_value(income_metrics, "ebit")
    ebitda = _latest_value(income_metrics, "ebitda")
    equity = _latest_value(balance_metrics, "total_equity")
    total_assets = _latest_value(balance_metrics, "total_assets")
    current_liabilities = _latest_value(balance_metrics, "current_liabilities")
    net_debt = _latest_value(balance_metrics, "net_debt")
    market_cap = _to_millions(info.get("marketCap"))
    enterprise_value = _to_millions(info.get("enterpriseValue"))

    capital_employed = None
    if total_assets is not None and current_liabilities is not None:
        capital_employed = total_assets - current_liabilities

    return {
        "roe": _percentage(net_income, equity),
        "roce": _percentage(ebit, capital_employed),
        "pe_ratio": info.get("trailingPE"),
        "ev_to_ebitda": info.get("enterpriseToEbitda"),
        "net_debt_to_ebitda": _safe_divide(net_debt, ebitda),
        "latest_free_cash_flow": _latest_value(cash_flow_metrics, "free_cash_flow"),
    }


def compare_companies(
    primary_data: dict,
    primary_income: pd.DataFrame,
    primary_balance: pd.DataFrame,
    primary_cash: pd.DataFrame,
    primary_kpis: dict,
    comparison_data: dict,
    comparison_income: pd.DataFrame,
    comparison_balance: pd.DataFrame,
    comparison_cash: pd.DataFrame,
    comparison_kpis: dict,
) -> pd.DataFrame:
    """Create a compact comparison frame for two companies."""
    rows = []
    companies = [
        (primary_data, primary_income, primary_balance, primary_cash, primary_kpis),
        (comparison_data, comparison_income, comparison_balance, comparison_cash, comparison_kpis),
    ]

    for data, income, balance, cash, kpis in companies:
        info = data.get("info", {})
        rows.append(
            {
                "company": info.get("shortName") or info.get("longName") or data["ticker"],
                "ticker": data["ticker"],
                "currency": info.get("financialCurrency") or info.get("currency"),
                "revenue": _latest_value(income, "revenue"),
                "ebit_margin": _latest_value(income, "ebit_margin"),
                "net_margin": _latest_value(income, "net_margin"),
                "equity_ratio": _latest_value(balance, "equity_ratio"),
                "net_debt": _latest_value(balance, "net_debt"),
                "free_cash_flow": _latest_value(cash, "free_cash_flow"),
                "roe": kpis.get("roe"),
                "roce": kpis.get("roce"),
                "pe_ratio": kpis.get("pe_ratio"),
                "ev_to_ebitda": kpis.get("ev_to_ebitda"),
                "leverage": kpis.get("net_debt_to_ebitda"),
            }
        )

    return _clean_frame(rows)
