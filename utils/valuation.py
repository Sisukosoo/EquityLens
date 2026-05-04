"""CAPM, WACC, and DCF valuation calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf

from utils.logger import log_event


MARKET_RISK_PREMIUM = 0.055
DEFAULT_TERMINAL_GROWTH = 0.025


@dataclass
class ValuationInputs:
    """Container for automatically fetched valuation inputs."""

    market_cap: float | None
    total_debt: float | None
    cash: float | None
    interest_expense: float | None
    pretax_income: float | None
    income_tax: float | None
    shares_outstanding: float | None
    current_price: float | None
    currency: str


def calculate_capm(rf: float, beta: float, erp: float = MARKET_RISK_PREMIUM) -> float:
    """
    Calculate cost of equity using CAPM.

    Formula: Re = Rf + beta x ERP
    Source: CFA Institute Curriculum, Equity Valuation; Damodaran, Investment Valuation.
    Example: Rf=4%, beta=1.2, ERP=5.5% -> Re = 10.6%.
    Required inputs: rf, beta, erp as decimals. If an input is missing, caller should stop.
    Limitation: CAPM assumes one systematic risk factor and a stable beta.
    """
    return rf + beta * erp


def relever_beta(unlevered_beta: float, de_ratio: float, tax_rate: float) -> float:
    """
    Re-lever an industry asset beta using the Hamada equation.

    Formula: beta_L = beta_U x (1 + (1 - tax) x D/E)
    Source: Damodaran, Investment Valuation, cost of capital framework.
    Example: beta_U=0.8, D/E=0.5, tax=25% -> beta_L=1.10.
    Required inputs: unlevered beta, D/E ratio, tax rate as decimal.
    Limitation: Assumes debt beta is approximately zero and capital structure is stable.
    """
    return unlevered_beta * (1 + (1 - tax_rate) * de_ratio)


def calculate_wacc(e_weight: float, d_weight: float, re: float, rd: float, tax: float) -> float:
    """
    Calculate Weighted Average Cost of Capital.

    Formula: WACC = (E/V x Re) + (D/V x Rd x (1-T))
    Source: Damodaran, Investment Valuation; CFA Institute Corporate Issuers.
    Example: E/V=60%, D/V=40%, Re=10%, Rd=5%, T=25% -> WACC=7.5%.
    Required inputs: capital weights, cost of equity, pre-tax cost of debt, tax rate.
    Limitation: Uses market value of equity and book debt when market debt is unavailable.
    """
    return (e_weight * re) + (d_weight * rd * (1 - tax))


def terminal_value(fcf: float, g: float, wacc: float) -> float:
    """
    Calculate Gordon Growth terminal value.

    Formula: TV = FCF_n x (1 + g) / (WACC - g)
    Source: Damodaran, Investment Valuation, DCF terminal value framework.
    Example: FCF=100, g=2.5%, WACC=8% -> TV=1863.64.
    Required inputs: final forecast FCF, terminal growth, WACC.
    Limitation: Terminal growth must be below WACC and should be conservative.
    """
    if wacc <= g:
        raise ValueError("WACC must be greater than terminal growth.")
    return fcf * (1 + g) / (wacc - g)


def calculate_cost_of_debt(interest_expense: float | None, total_debt: float | None, fallback: float | None = None) -> tuple[float, bool]:
    """
    Estimate pre-tax cost of debt from interest expense and total debt.

    Formula: Rd = Interest expense / Total debt
    Source: Damodaran, Investment Valuation, WACC input estimation.
    Example: Interest=50, Debt=1000 -> Rd=5%.
    Required inputs: interest expense and total debt; Damodaran fallback is used when unavailable.
    Limitation: Book interest expense may lag current refinancing rates.
    """
    if interest_expense is None or total_debt in (None, 0) or pd.isna(interest_expense) or pd.isna(total_debt):
        if fallback is None:
            raise ValueError("Cost of debt cannot be calculated: interest expense or total debt is missing.")
        return fallback, True
    rd = abs(float(interest_expense)) / abs(float(total_debt))
    if rd < 0.01 or rd > 0.15:
        if fallback is None:
            raise ValueError(f"Cost of debt outside 1%-15% range and no Damodaran fallback is available: {rd:.4f}")
        return fallback, True
    return rd, False


def calculate_effective_tax_rate(income_tax: float | None, pretax_income: float | None, fallback: float = 0.25) -> tuple[float, bool]:
    """
    Estimate effective tax rate from income tax and pre-tax income.

    Formula: Tax rate = Income tax expense / Pretax income
    Source: CFA Institute Financial Statement Analysis; Damodaran WACC inputs.
    Example: Tax=25, Pretax=100 -> T=25%.
    Required inputs: income tax expense and pretax income; fallback used if invalid.
    Limitation: One-year tax rates can be distorted by losses and one-offs.
    """
    if income_tax is None or pretax_income in (None, 0) or pd.isna(income_tax) or pd.isna(pretax_income):
        return fallback, True
    tax = abs(float(income_tax)) / abs(float(pretax_income))
    if tax < 0 or tax > 0.4:
        return fallback, True
    return tax, False


def calculate_capital_weights(equity_value: float | None, debt_value: float | None) -> dict[str, float]:
    """
    Calculate market-value capital structure weights.

    Formula: E/V = E/(E+D), D/V = D/(E+D)
    Source: Damodaran, Investment Valuation, cost of capital.
    Example: E=600, D=400 -> E/V=60%, D/V=40%.
    Required inputs: market cap and total debt.
    Limitation: Uses book debt as debt market value proxy.
    """
    equity = max(float(equity_value or 0), 0)
    debt = max(float(debt_value or 0), 0)
    total = equity + debt
    if total == 0:
        return {"equity_weight": 1.0, "debt_weight": 0.0, "enterprise_capital": 0.0}
    return {
        "equity_weight": equity / total,
        "debt_weight": debt / total,
        "enterprise_capital": total,
    }


def present_value(value: float, discount_rate: float, period: int) -> float:
    """
    Discount a future cash flow to present value.

    Formula: PV = CF_t / (1 + r)^t
    Source: CFA Institute Quantitative Methods; Damodaran DCF framework.
    Example: CF=100, r=8%, t=2 -> PV=85.73.
    Required inputs: value, discount rate, period number.
    Limitation: Assumes annual period spacing.
    """
    return value / ((1 + discount_rate) ** period)


def build_dcf_forecast(
    latest_revenue: float,
    latest_ebit_margin: float,
    latest_fcf: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    revenue_growth: float = 0.05,
    terminal_growth: float = DEFAULT_TERMINAL_GROWTH,
    tax_rate: float = 0.25,
    capex_pct_revenue: float = 0.04,
    depreciation_pct_revenue: float = 0.03,
    working_capital_pct_revenue: float = 0.02,
) -> dict[str, Any]:
    """
    Build a five-year simplified DCF forecast.

    Formula: FCF = EBIT x (1-T) + D&A - CapEx - Delta WC; TV = FCF_n x (1+g)/(WACC-g)
    Source: Damodaran, Investment Valuation, free cash flow to firm model.
    Example: The function projects revenue, FCF, terminal value, EV and implied price.
    Required inputs: latest revenue, margin, WACC, net debt, shares outstanding.
    Limitation: D&A uses historical EBITDA-EBIT percentage when available; otherwise a conservative fallback.
    """
    if wacc <= terminal_growth:
        raise ValueError("WACC must be greater than terminal growth.")
    rows = []
    previous_revenue = latest_revenue
    for year in range(1, 6):
        revenue = previous_revenue * (1 + revenue_growth)
        ebit = revenue * latest_ebit_margin
        nopat = ebit * (1 - tax_rate)
        depreciation = revenue * depreciation_pct_revenue
        capex = revenue * capex_pct_revenue
        delta_wc = (revenue - previous_revenue) * working_capital_pct_revenue
        fcf = nopat + depreciation - capex - delta_wc
        pv_fcf = present_value(fcf, wacc, year)
        rows.append(
            {
                "year": year,
                "revenue": revenue,
                "ebit": ebit,
                "fcf": fcf,
                "pv_fcf": pv_fcf,
            }
        )
        previous_revenue = revenue

    tv = terminal_value(rows[-1]["fcf"], terminal_growth, wacc)
    pv_tv = present_value(tv, wacc, 5)
    enterprise_value = sum(row["pv_fcf"] for row in rows) + pv_tv
    equity_value = enterprise_value - net_debt
    implied_price = equity_value * 1_000_000 / shares_outstanding if shares_outstanding else None
    upside = None
    if implied_price is not None and current_price not in (None, 0):
        upside = implied_price / current_price - 1
    return {
        "forecast": rows,
        "terminal_value": tv,
        "pv_terminal_value": pv_tv,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "implied_price": implied_price,
        "upside": upside,
        "latest_fcf": latest_fcf,
    }


def fetch_risk_free_rate() -> dict[str, Any]:
    """
    Fetch the 10-year US Treasury yield from Yahoo Finance.

    Formula: Risk-free rate = latest ^TNX close / 100 when quote is above 1.
    Source: Yahoo Finance ^TNX; CAPM/WACC convention.
    Example: ^TNX close 4.378 -> 4.378%; close 0.04378 -> 4.378%.
    Required inputs: network access through yfinance.
    Limitation: If Yahoo is unavailable, caller must use a cached fallback and warn the user.
    """
    history = yf.Ticker("^TNX").history(period="7d")
    if history.empty:
        raise ValueError("No ^TNX data available.")
    latest = history.dropna(subset=["Close"]).iloc[-1]
    close = float(latest["Close"])
    rate = close / 100 if close > 1 else close
    print(f"Risk-free rate raw={close}, scaled={rate}")
    if rate < 0.005 or rate > 0.15:
        log_event(f"Risk-free rate sanity warning: raw_close={close}, parsed_rate={rate}", "valuation_warning")
        raise ValueError(f"Risk-free rate outside 0.5%-15% sanity range: raw={close}, scaled={rate}")
    return {
        "rate": rate,
        "date": latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, "strftime") else str(latest.name),
        "raw_close": close,
    }


def build_valuation_result(
    data: dict,
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    beta_match: Any,
    risk_free: dict[str, Any],
) -> dict[str, Any]:
    """
    Build the complete CAPM, WACC, and DCF valuation result package.

    Formula: CAPM, re-levered beta, WACC, and FCFF DCF formulas are combined.
    Source: Damodaran valuation framework and Yahoo Finance company data.
    Example: takes one ticker's financial statements and returns WACC plus implied price.
    Required inputs: yfinance data, calculated statements, Damodaran beta match, risk-free rate.
    Limitation: uses automated assumptions; Excel highlights estimated inputs for review.
    """
    info = data.get("info", {})
    currency = info.get("financialCurrency") or info.get("currency") or "reported currency"
    latest_income = income_metrics.iloc[-1] if not income_metrics.empty else pd.Series(dtype=float)
    latest_balance = balance_metrics.iloc[-1] if not balance_metrics.empty else pd.Series(dtype=float)
    latest_cash = cash_flow_metrics.iloc[-1] if not cash_flow_metrics.empty else pd.Series(dtype=float)

    market_cap = _to_millions_safe(info.get("marketCap"))
    total_debt = _value_or_none(latest_balance.get("debt"))
    cash = _value_or_none(latest_balance.get("cash"))
    net_debt = _value_or_none(latest_balance.get("net_debt")) or 0
    interest_expense = _latest_available_value(income_metrics, "interest_expense")
    pretax_income = _value_or_none(latest_income.get("pretax_income"))
    income_tax = _value_or_none(latest_income.get("income_tax_expense"))
    revenue = _value_or_none(latest_income.get("revenue"))
    ebit_margin = _ratio_from_percent(latest_income.get("ebit_margin"))
    fcf = _value_or_none(latest_cash.get("free_cash_flow")) or 0
    shares_outstanding = info.get("sharesOutstanding")
    current_price = info.get("currentPrice") or info.get("regularMarketPrice")

    fallback_tax = beta_match.industry_tax_rate if beta_match.industry_tax_rate is not None else 0.25
    tax_rate, tax_estimated = calculate_effective_tax_rate(income_tax, pretax_income, fallback=fallback_tax)
    if tax_rate < 0:
        tax_rate = fallback_tax
        tax_estimated = True

    if market_cap not in (None, 0) and total_debt is not None:
        de_ratio = total_debt / market_cap
        de_estimated = False
    elif beta_match.industry_de_ratio is not None:
        de_ratio = beta_match.industry_de_ratio
        de_estimated = True
    else:
        de_ratio = 0.25
        de_estimated = True

    unlevered_beta = beta_match.unlevered_beta if beta_match.unlevered_beta is not None else 1.0
    levered_beta = relever_beta(unlevered_beta, de_ratio, tax_rate)
    rf = risk_free["rate"]
    cost_of_equity = calculate_capm(rf, levered_beta, MARKET_RISK_PREMIUM)
    damodaran_debt_fallback = getattr(beta_match, "industry_cost_of_debt", None)
    cost_of_debt, debt_estimated = calculate_cost_of_debt(interest_expense, total_debt, fallback=damodaran_debt_fallback)
    weights = calculate_capital_weights(market_cap, total_debt)
    wacc = calculate_wacc(
        weights["equity_weight"],
        weights["debt_weight"],
        cost_of_equity,
        cost_of_debt,
        tax_rate,
    )

    dcf = {}
    revenue_growth, revenue_growth_source = _historical_revenue_growth_assumption(income_metrics)
    terminal_cagr = _historical_revenue_cagr(income_metrics, years=5)
    working_capital_pct_revenue = _historical_working_capital_pct_revenue(income_metrics, balance_metrics)
    terminal_growth = max(min(terminal_cagr, DEFAULT_TERMINAL_GROWTH), 0.015) if terminal_cagr is not None else DEFAULT_TERMINAL_GROWTH
    depreciation_pct_revenue = _historical_depreciation_pct_revenue(income_metrics)
    capex_pct_revenue = _historical_capex_pct_revenue(income_metrics, cash_flow_metrics)
    if revenue is not None and ebit_margin is not None and shares_outstanding:
        dcf = build_dcf_forecast(
            latest_revenue=revenue,
            latest_ebit_margin=ebit_margin,
            latest_fcf=fcf,
            wacc=wacc,
            net_debt=net_debt,
            shares_outstanding=float(shares_outstanding),
            current_price=current_price,
            revenue_growth=revenue_growth if revenue_growth is not None else 0.05,
            terminal_growth=terminal_growth,
            tax_rate=tax_rate,
            depreciation_pct_revenue=depreciation_pct_revenue,
            capex_pct_revenue=capex_pct_revenue,
            working_capital_pct_revenue=working_capital_pct_revenue,
        )
        print(
            "DCF debug "
            f"implied_price_streamlit={dcf.get('implied_price')}, "
            f"current_price={current_price}, "
            f"upside={dcf.get('upside')}, "
            f"wacc={wacc}"
        )

    return {
        "currency": currency,
        "market_cap": market_cap,
        "total_debt": total_debt,
        "cash": cash,
        "net_debt": net_debt,
        "de_ratio": de_ratio,
        "de_estimated": de_estimated,
        "tax_rate": tax_rate,
        "tax_estimated": tax_estimated,
        "cost_of_debt": cost_of_debt,
        "cost_of_debt_estimated": debt_estimated,
        "interest_expense_used": interest_expense,
        "depreciation_pct_revenue": depreciation_pct_revenue,
        "capex_pct_revenue": capex_pct_revenue,
        "revenue_growth": revenue_growth,
        "revenue_growth_source": revenue_growth_source,
        "terminal_growth_cagr": terminal_cagr,
        "working_capital_pct_revenue": working_capital_pct_revenue,
        "risk_free_rate": rf,
        "risk_free_date": risk_free.get("date"),
        "market_risk_premium": MARKET_RISK_PREMIUM,
        "unlevered_beta": unlevered_beta,
        "levered_beta": levered_beta,
        "yfinance_beta": info.get("beta"),
        "cost_of_equity": cost_of_equity,
        "equity_weight": weights["equity_weight"],
        "debt_weight": weights["debt_weight"],
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
        "dcf": dcf,
    }


def _value_or_none(value: Any) -> float | None:
    """
    Convert a pandas/numeric value to float or None.

    Formula: not applicable.
    Source: internal data cleaning.
    Example: pd.NA -> None, 100 -> 100.0.
    Required inputs: any scalar.
    Limitation: non-numeric strings return None.
    """
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_millions_safe(value: Any) -> float | None:
    """
    Convert raw currency units to millions.

    Formula: value / 1,000,000.
    Source: Yahoo Finance raw market cap fields.
    Example: 1,000,000,000 -> 1000.0.
    Required inputs: raw numeric value.
    Limitation: assumes yfinance returns raw currency units.
    """
    number = _value_or_none(value)
    if number is None:
        return None
    return number / 1_000_000


def _ratio_from_percent(value: Any) -> float | None:
    """
    Convert percent-form metrics to decimal ratios.

    Formula: decimal = percent / 100.
    Source: internal conversion for margin fields.
    Example: 12.5 -> 0.125.
    Required inputs: percent value.
    Limitation: assumes input metric is stored as percent.
    """
    number = _value_or_none(value)
    if number is None:
        return None
    return number / 100


def _latest_available_value(frame: pd.DataFrame, column: str) -> float | None:
    """
    Return the latest non-empty numeric value from a DataFrame column.

    Formula: latest available value, not necessarily latest fiscal year.
    Source: yfinance financial statement history.
    Example: use latest available interest expense when the newest year is blank.
    Required inputs: DataFrame and column name.
    Limitation: assumes all rows are annual periods sorted oldest to newest.
    """
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    if values.empty:
        return None
    return float(values.iloc[-1])


def _historical_depreciation_pct_revenue(income_metrics: pd.DataFrame, fallback: float = 0.03) -> float:
    """
    Estimate D&A as a percentage of revenue using EBITDA minus EBIT.

    Formula: D&A % revenue = average((EBITDA - EBIT) / revenue) over available recent years.
    Source: yfinance income statement metrics; Damodaran FCFF model convention.
    Example: Apple FY2025 D&A = 144,748 - 133,050 = 11,698M = 2.81% of revenue.
    Required inputs: income_metrics with revenue, EBITDA, and EBIT.
    Limitation: falls back to 3% if EBITDA/EBIT data is missing or invalid.
    """
    required = {"revenue", "ebitda", "ebit"}
    if income_metrics.empty or not required.issubset(income_metrics.columns):
        return fallback
    frame = income_metrics.tail(3).copy()
    revenue = pd.to_numeric(frame["revenue"], errors="coerce")
    ebitda = pd.to_numeric(frame["ebitda"], errors="coerce")
    ebit = pd.to_numeric(frame["ebit"], errors="coerce")
    ratios = ((ebitda - ebit) / revenue).replace([float("inf"), -float("inf")], pd.NA).dropna()
    ratios = ratios[(ratios >= 0) & (ratios <= 0.2)]
    if ratios.empty:
        return fallback
    return float(ratios.mean())


def _historical_capex_pct_revenue(income_metrics: pd.DataFrame, cash_flow_metrics: pd.DataFrame, fallback: float = 0.04) -> float:
    """
    Estimate CapEx as a percentage of revenue from the latest three fiscal years.

    Formula: CapEx % revenue = average(abs(Capital Expenditure) / Revenue).
    Source: yfinance cash flow and income statement metrics.
    Example: Apple FY2023-FY2025 average is roughly 2.78% of revenue.
    Required inputs: income_metrics revenue and cash_flow_metrics capital_expenditure.
    Limitation: falls back to 4% when cash flow line items are missing.
    """
    if income_metrics.empty or cash_flow_metrics.empty:
        return fallback
    required_income = {"year", "revenue"}
    required_cash = {"year", "capital_expenditure"}
    if not required_income.issubset(income_metrics.columns) or not required_cash.issubset(cash_flow_metrics.columns):
        return fallback
    merged = (
        income_metrics[["year", "revenue"]]
        .merge(cash_flow_metrics[["year", "capital_expenditure"]], on="year", how="inner")
        .tail(3)
    )
    revenue = pd.to_numeric(merged["revenue"], errors="coerce")
    capex = pd.to_numeric(merged["capital_expenditure"], errors="coerce").abs()
    ratios = (capex / revenue).replace([float("inf"), -float("inf")], pd.NA).dropna()
    ratios = ratios[(ratios >= 0) & (ratios <= 0.3)]
    if ratios.empty:
        return fallback
    return float(ratios.mean())


def _historical_revenue_cagr(income_metrics: pd.DataFrame, years: int = 3, fallback: float | None = None) -> float | None:
    """
    Estimate revenue growth from the latest three-year historical CAGR.

    Formula: CAGR = (latest revenue / first revenue)^(1 / periods) - 1.
    Source: yfinance income statement revenue history.
    Example: FY2023-FY2025 revenue CAGR becomes the default DCF revenue growth.
    Required inputs: income metrics with annual revenue.
    Limitation: returns fallback when fewer than two valid revenue observations exist.
    """
    if income_metrics.empty or "revenue" not in income_metrics.columns:
        return fallback
    values = pd.to_numeric(income_metrics["revenue"], errors="coerce").dropna().tail(years)
    if len(values) < 2 or values.iloc[0] <= 0:
        return fallback
    periods = len(values) - 1
    return float((values.iloc[-1] / values.iloc[0]) ** (1 / periods) - 1)


def _historical_revenue_growth_assumption(income_metrics: pd.DataFrame) -> tuple[float | None, str]:
    """
    Choose a robust revenue-growth default for the DCF assumption.

    Formula: prefer five-year CAGR; fall back to three-year CAGR when five-year data is unavailable.
    Source: yfinance income statement revenue history.
    Example: Apple uses FY2021-FY2025 when available instead of being dominated by one weak FY2023.
    Required inputs: income metrics with annual revenue.
    Limitation: CAGR still simplifies cyclical revenue patterns into one annualized number.
    """
    if income_metrics.empty or "revenue" not in income_metrics.columns:
        return None, "Fallback assumption (historical revenue data unavailable)"

    frame = income_metrics.copy()
    frame["revenue"] = pd.to_numeric(frame["revenue"], errors="coerce")
    frame = frame.dropna(subset=["revenue"])
    frame = frame[frame["revenue"] > 0]
    if len(frame) >= 5:
        window = frame.tail(5)
        return _cagr_from_window(window), f"5-year historical CAGR ({_period_range(window)})"
    if len(frame) >= 3:
        window = frame.tail(3)
        return _cagr_from_window(window), f"3-year historical CAGR ({_period_range(window)}) - 5-year data not available"
    if len(frame) >= 2:
        window = frame.tail(2)
        return _cagr_from_window(window), f"2-year historical CAGR ({_period_range(window)}) - limited history available"
    return None, "Fallback assumption (historical revenue data unavailable)"


def _cagr_from_window(frame: pd.DataFrame) -> float | None:
    """Calculate CAGR from a preselected revenue window."""
    values = pd.to_numeric(frame["revenue"], errors="coerce").dropna()
    if len(values) < 2 or values.iloc[0] <= 0:
        return None
    periods = len(values) - 1
    return float((values.iloc[-1] / values.iloc[0]) ** (1 / periods) - 1)


def _period_range(frame: pd.DataFrame) -> str:
    """Return compact FY range for valuation source labels."""
    labels = []
    for _, row in frame.iterrows():
        if "period" in frame.columns and pd.notna(row.get("period")):
            labels.append(str(row.get("period")).split(" ")[0])
        elif "year" in frame.columns and pd.notna(row.get("year")):
            labels.append(f"FY{int(row.get('year'))}")
    if len(labels) >= 2:
        return f"{labels[0]}-{labels[-1]}"
    return labels[0] if labels else "available FY history"


def _historical_working_capital_pct_revenue(
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    fallback: float = 0.02,
) -> float:
    """
    Estimate working capital as a percentage of revenue from recent fiscal years.

    Formula: WC % revenue = average((current assets - current liabilities) / revenue).
    Source: yfinance balance sheet and income statement metrics.
    Example: latest three valid fiscal years become the DCF working-capital assumption.
    Required inputs: current assets, current liabilities, revenue.
    Limitation: falls back to 2% when balance-sheet detail is unavailable.
    """
    required_income = {"year", "revenue"}
    required_balance = {"year", "current_assets", "current_liabilities"}
    if (
        income_metrics.empty
        or balance_metrics.empty
        or not required_income.issubset(income_metrics.columns)
        or not required_balance.issubset(balance_metrics.columns)
    ):
        return fallback
    merged = (
        income_metrics[["year", "revenue"]]
        .merge(balance_metrics[["year", "current_assets", "current_liabilities"]], on="year", how="inner")
        .tail(3)
    )
    revenue = pd.to_numeric(merged["revenue"], errors="coerce")
    current_assets = pd.to_numeric(merged["current_assets"], errors="coerce")
    current_liabilities = pd.to_numeric(merged["current_liabilities"], errors="coerce")
    ratios = ((current_assets - current_liabilities) / revenue).replace([float("inf"), -float("inf")], pd.NA).dropna()
    ratios = ratios[(ratios >= -0.5) & (ratios <= 0.8)]
    if ratios.empty:
        return fallback
    return float(ratios.mean())
