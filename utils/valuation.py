"""CAPM, WACC, and DCF valuation calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf

from utils.logger import log_event


# Equity risk premium: hardcoded constant (Damodaran's ERP estimate, Jan 2026).
# This is NOT loaded from a live Damodaran file; update manually when the source changes.
MARKET_RISK_PREMIUM = 0.055
DEFAULT_TERMINAL_GROWTH = 0.025
STANDARD_DCF_MAX_DEVIATION = 0.70
FALLBACK_DCF_MAX_DEVIATION = 0.70
DCF_MARGIN_URLS = {
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/marginEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/margin.xls",
}
DCF_CAPEX_URLS = {
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/capexEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/capex.xls",
}
MULTIPLE_EV_EBITDA_URLS = {
    # 2026-05-07: Damodaran Europe filenames are explicit and inconsistent;
    # EV/EBITDA uses vebitEurope.xls, not a generated *dataEurope suffix.
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/vebitEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/vebitda.xls",
}
MULTIPLE_EV_SALES_URLS = {
    # 2026-05-07: psdataEurope.xls returns 404; official Europe file is psEurope.xls.
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/psEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/psdata.xls",
}
MULTIPLE_PB_URLS = {
    # 2026-05-07: pbvdataEurope.xls returns 404; official Europe file is pbvEurope.xls.
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/pbvEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/pbvdata.xls",
}
RISK_FREE_CURRENCY_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/currencyriskfree2026.xls"
USD_RISK_FREE_SOURCE = "Yahoo Finance ^TNX"
DAMODARAN_RISK_FREE_SOURCE = "Damodaran currency risk-free rates"
TICKER_SUFFIX_CURRENCY_MAP = {
    ".HE": "EUR",
    ".DE": "EUR",
    ".PA": "EUR",
    ".AS": "EUR",
    ".MI": "EUR",
    ".SW": "CHF",
    ".L": "GBP",
    ".ST": "SEK",
    ".OL": "NOK",
    ".CO": "DKK",
    ".T": "JPY",
}
COUNTRY_CURRENCY_MAP = {
    "united states": "USD",
    "finland": "EUR",
    "germany": "EUR",
    "france": "EUR",
    "italy": "EUR",
    "netherlands": "EUR",
    "switzerland": "CHF",
    "united kingdom": "GBP",
    "sweden": "SEK",
    "norway": "NOK",
    "denmark": "DKK",
    "japan": "JPY",
}
CURRENCY_LOOKUP_ALIASES = {
    "USD": ("USD", "US", "US Dollar", "United States Dollar", "Dollar"),
    "EUR": ("EUR", "Euro", "Euros"),
    "CHF": ("CHF", "Swiss Franc", "Swiss Francs"),
    "GBP": ("GBP", "British Pound", "Pound Sterling", "Sterling"),
    "SEK": ("SEK", "Swedish Krona"),
    "NOK": ("NOK", "Norwegian Krone"),
    "DKK": ("DKK", "Danish Krone"),
    "JPY": ("JPY", "Japanese Yen", "Yen"),
}


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
    if rate < 0.005 or rate > 0.15:
        log_event(f"Risk-free rate sanity warning: raw_close={close}, parsed_rate={rate}", "valuation_warning")
        raise ValueError(f"Risk-free rate outside 0.5%-15% sanity range: raw={close}, scaled={rate}")
    return {
        "rate": rate,
        "date": latest.name.strftime("%Y-%m-%d") if hasattr(latest.name, "strftime") else str(latest.name),
        "raw_close": close,
        "currency": "USD",
        "target_currency": "USD",
        "source": USD_RISK_FREE_SOURCE,
        "source_detail": "^TNX latest close over the last 7 trading days",
        "source_ticker": "^TNX",
        "currency_mismatch": False,
    }


def detect_risk_free_currency(data: dict[str, Any]) -> str:
    """
    Determine the currency that should drive the risk-free rate.

    Formula: prefer reporting currency, then market currency, then ticker/country fallback.
    Source: yfinance info fields and exchange suffix conventions.
    Example: NESN.SW -> CHF when financialCurrency is unavailable.
    Required inputs: fetched company data.
    Limitation: multi-currency reporters can still require analyst review.
    """
    info = data.get("info", {}) if isinstance(data, dict) else {}
    for key in ("financialCurrency", "currency"):
        value = info.get(key)
        if value:
            return str(value).strip().upper()
    ticker = str(data.get("ticker", "") if isinstance(data, dict) else "").upper().strip()
    for suffix, currency in TICKER_SUFFIX_CURRENCY_MAP.items():
        if ticker.endswith(suffix):
            return currency
    country = str(info.get("country") or "").strip().lower()
    return COUNTRY_CURRENCY_MAP.get(country, "USD")


def fetch_risk_free_rate_for_currency(currency: str) -> dict[str, Any]:
    """
    Fetch a risk-free rate aligned with the valuation currency.

    Formula: USD uses ^TNX; non-USD uses Damodaran currency risk-free rate by currency.
    Source: Yahoo Finance for USD and Damodaran currencyriskfree2026.xls for non-USD.
    Example: EUR -> Damodaran EUR risk-free rate.
    Required inputs: ISO-like currency code.
    Limitation: Damodaran currency table is updated periodically, not intraday.
    """
    normalized = str(currency or "USD").strip().upper()
    if normalized == "USD":
        return fetch_risk_free_rate()
    return fetch_damodaran_currency_risk_free_rate(normalized)


def fetch_damodaran_currency_risk_free_rate(currency: str) -> dict[str, Any]:
    """
    Fetch a non-USD risk-free rate from Damodaran's currency risk-free table.

    Formula: lookup risk-free rate by currency code and convert percent-like values to decimals.
    Source: Damodaran currencyriskfree2026.xls.
    Example: CHF row risk-free rate -> CAPM Rf for CHF reporters.
    Required inputs: currency code.
    Limitation: workbook header labels can change; parser uses loose column matching.
    """
    normalized = str(currency or "").strip().upper()
    if not normalized:
        raise ValueError("Currency is required for Damodaran risk-free lookup.")
    frame = _load_currency_risk_free_table(RISK_FREE_CURRENCY_URL)
    currency_col = _find_risk_free_currency_column(frame)
    rate_col = _find_risk_free_rate_column(frame)
    if currency_col is None or rate_col is None:
        raise ValueError(
            "Damodaran currency risk-free table did not expose required currency/risk-free columns."
        )
    aliases = {_normalized_label(alias) for alias in CURRENCY_LOOKUP_ALIASES.get(normalized, (normalized,))}
    matches = frame[frame[currency_col].map(lambda item: _normalized_label(item) in aliases)]
    if matches.empty:
        raise ValueError(f"Risk-free rate for {normalized} was not found in Damodaran currency table.")
    value = _risk_free_rate_to_decimal(matches.iloc[0].get(rate_col))
    if value is None:
        raise ValueError(f"Risk-free rate for {normalized} is not numeric in Damodaran currency table.")
    if value < -0.01 or value > 0.15:
        log_event(
            f"Currency risk-free rate sanity warning: currency={normalized}, parsed_rate={value}",
            "valuation_warning",
        )
        raise ValueError(f"Risk-free rate outside -1%-15% sanity range for {normalized}: {value}")
    return {
        "rate": value,
        "date": "January 2026",
        "raw_close": matches.iloc[0].get(rate_col),
        "currency": normalized,
        "target_currency": normalized,
        "source": DAMODARAN_RISK_FREE_SOURCE,
        "source_detail": f"{_source_filename(RISK_FREE_CURRENCY_URL)} {normalized} risk-free rate",
        "source_url": RISK_FREE_CURRENCY_URL,
        "currency_mismatch": False,
    }


def _load_currency_risk_free_table(url: str) -> pd.DataFrame:
    """Load Damodaran's currency risk-free table with a currency-specific header heuristic."""
    try:
        workbook = pd.read_excel(url, sheet_name=None, header=None)
    except Exception as exc:
        log_event(f"Damodaran currency risk-free URL failed: {url} | {exc}", "damodaran_error")
        raise RuntimeError(f"Could not load Damodaran currency risk-free dataset: {url}") from exc
    best_raw = None
    best_header = 0
    best_score = -1
    for raw in workbook.values():
        for idx, row in raw.head(30).iterrows():
            values = [str(value).strip().lower() for value in row.dropna().tolist()]
            text = " ".join(values)
            score = 0
            if "currency" in text:
                score += 20
            if "risk" in text and "free" in text:
                score += 20
            if "rate" in text:
                score += 5
            if score > best_score:
                best_score = score
                best_header = int(idx)
                best_raw = raw
    if best_raw is None or best_score < 20:
        raise RuntimeError("No readable currency risk-free table header was found.")
    headers = _make_unique_labels(best_raw.iloc[best_header].tolist())
    frame = best_raw.iloc[best_header + 1 :].copy()
    frame.columns = headers
    frame = frame.dropna(how="all").reset_index(drop=True)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _make_unique_labels(values: list[Any]) -> list[str]:
    """Build unique DataFrame labels from a raw header row."""
    labels = []
    counts: dict[str, int] = {}
    for index, value in enumerate(values):
        base = f"unnamed_{index + 1}" if pd.isna(value) or str(value).strip() == "" else str(value).strip()
        count = counts.get(base, 0)
        counts[base] = count + 1
        labels.append(base if count == 0 else f"{base}_{count + 1}")
    return labels


def _find_risk_free_currency_column(frame: pd.DataFrame) -> str | None:
    """Find the currency-code column in Damodaran's currency risk-free workbook."""
    for column in frame.columns:
        key = _normalized_label(column)
        if key in {"currency", "currencycode"} or "currency" in key:
            return str(column)
    return None


def _find_risk_free_rate_column(frame: pd.DataFrame) -> str | None:
    """Find the risk-free-rate column, preferring explicit risk-free labels over bond rates."""
    scored: list[tuple[int, str]] = []
    for column in frame.columns:
        key = _normalized_label(column)
        if "riskfree" not in key and not ("risk" in key and "free" in key):
            continue
        score = 100
        if "rate" in key:
            score += 20
        if "government" in key or "bond" in key:
            score -= 40
        scored.append((score, str(column)))
    if not scored:
        return None
    scored.sort(reverse=True, key=lambda item: item[0])
    return scored[0][1]


def _risk_free_rate_to_decimal(value: Any) -> float | None:
    """Convert risk-free-rate values such as 2.5, 0.025, or -0.2 into decimals."""
    number = _value_or_none(value)
    if number is None:
        return None
    if abs(number) > 0.15:
        return number / 100
    return number


def _normalized_label(value: Any) -> str:
    """Normalize labels for loose column matching."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _source_filename(url: str) -> str:
    """Return the filename portion of a source URL."""
    return str(url).rsplit("/", 1)[-1]


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
    ebitda = _value_or_none(latest_income.get("ebitda"))
    total_equity = _value_or_none(latest_balance.get("total_equity"))
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

    unlevered_beta_estimated = beta_match.unlevered_beta is None
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

    revenue_growth, revenue_growth_source = _historical_revenue_growth_assumption(income_metrics)
    terminal_cagr = _historical_revenue_cagr(income_metrics, years=5)
    terminal_cagr_source = _historical_revenue_cagr_source(income_metrics, years=5)
    working_capital_pct_revenue, working_capital_source = _historical_working_capital_assumption(income_metrics, balance_metrics)
    terminal_growth = max(min(terminal_cagr, DEFAULT_TERMINAL_GROWTH), 0.015) if terminal_cagr is not None else DEFAULT_TERMINAL_GROWTH
    terminal_growth_source = (
        f"{terminal_cagr_source}; capped to 1.5%-2.5% terminal range"
        if terminal_cagr is not None
        else "Default terminal growth assumption"
    )
    depreciation_pct_revenue, depreciation_source = _historical_depreciation_assumption(income_metrics)
    capex_pct_revenue, capex_source = _historical_capex_assumption(income_metrics, cash_flow_metrics)
    dcf_tiers = []
    dcf = {}
    selected_tier = None
    reverse_dcf = _build_unavailable_reverse_dcf(info, "Tier 1 Standard DCF inputs are unavailable.")
    if revenue is not None and ebit_margin is not None and shares_outstanding:
        dcf_tiers, selected_tier = _build_dcf_tier_results(
            income_metrics=income_metrics,
            cash_flow_metrics=cash_flow_metrics,
            latest_revenue=revenue,
            latest_ebit_margin=ebit_margin,
            latest_fcf=fcf,
            wacc=wacc,
            net_debt=net_debt,
            shares_outstanding=float(shares_outstanding),
            current_price=current_price,
            terminal_growth=terminal_growth,
            tax_rate=tax_rate,
            working_capital_pct_revenue=working_capital_pct_revenue,
            working_capital_source=working_capital_source,
            latest_ebitda=ebitda,
            total_equity=total_equity,
            standard_revenue_growth=revenue_growth,
            standard_revenue_growth_source=revenue_growth_source,
            standard_depreciation_pct_revenue=depreciation_pct_revenue,
            standard_depreciation_source=depreciation_source,
            standard_capex_pct_revenue=capex_pct_revenue,
            standard_capex_source=capex_source,
            beta_match=beta_match,
        )
        dcf = selected_tier.get("dcf", {}) if selected_tier else {}
        tier1 = next((tier for tier in dcf_tiers if tier.get("tier") == 1), None)
        if tier1:
            reverse_dcf = build_reverse_dcf_analysis(
                info=info,
                tier1=tier1,
                latest_revenue=revenue,
                latest_fcf=fcf,
                wacc=wacc,
                net_debt=net_debt,
                shares_outstanding=float(shares_outstanding),
                current_price=current_price,
                terminal_growth=terminal_growth,
                tax_rate=tax_rate,
                historical_ebit_margin_average=_reverse_dcf_historical_margin_average(income_metrics),
            )
    selected_assumptions = (selected_tier or {}).get("assumptions", {})

    return {
        "currency": currency,
        "market_cap": market_cap,
        "total_debt": total_debt,
        "total_equity": total_equity,
        "cash": cash,
        "net_debt": net_debt,
        "de_ratio": de_ratio,
        "de_estimated": de_estimated,
        "tax_rate": tax_rate,
        "tax_estimated": tax_estimated,
        "cost_of_debt": cost_of_debt,
        "cost_of_debt_estimated": debt_estimated,
        "interest_expense_used": interest_expense,
        "depreciation_pct_revenue": selected_assumptions.get("depreciation_pct_revenue", depreciation_pct_revenue),
        "depreciation_source": selected_assumptions.get("depreciation_source", depreciation_source),
        "capex_pct_revenue": selected_assumptions.get("capex_pct_revenue", capex_pct_revenue),
        "capex_source": selected_assumptions.get("capex_source", capex_source),
        "revenue_growth": selected_assumptions.get("revenue_growth", revenue_growth),
        "revenue_growth_source": selected_assumptions.get("revenue_growth_source", revenue_growth_source),
        "terminal_growth_cagr": terminal_cagr,
        "terminal_growth_source": terminal_growth_source,
        "working_capital_pct_revenue": selected_assumptions.get("working_capital_pct_revenue", working_capital_pct_revenue),
        "working_capital_source": selected_assumptions.get("working_capital_source", working_capital_source),
        "risk_free_rate": rf,
        "risk_free_date": risk_free.get("date"),
        "risk_free_currency": risk_free.get("currency", "USD"),
        "risk_free_target_currency": risk_free.get("target_currency", currency),
        "risk_free_source": risk_free.get("source", USD_RISK_FREE_SOURCE),
        "risk_free_source_detail": risk_free.get("source_detail", ""),
        "risk_free_source_url": risk_free.get("source_url"),
        "risk_free_currency_mismatch": bool(risk_free.get("currency_mismatch")),
        "risk_free_warning": risk_free.get("warning"),
        "market_risk_premium": MARKET_RISK_PREMIUM,
        "unlevered_beta": unlevered_beta,
        "unlevered_beta_estimated": unlevered_beta_estimated,
        "levered_beta": levered_beta,
        "yfinance_beta": info.get("beta"),
        "damodaran_sector": getattr(beta_match, "matched_industry", None),
        "cost_of_equity": cost_of_equity,
        "equity_weight": weights["equity_weight"],
        "debt_weight": weights["debt_weight"],
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
        "dcf": dcf,
        "dcf_tiers": dcf_tiers,
        "selected_dcf_tier": selected_tier,
        "dcf_tier": (selected_tier or {}).get("tier"),
        "dcf_tier_name": (selected_tier or {}).get("name"),
        "dcf_confidence": (selected_tier or {}).get("confidence"),
        "dcf_selection_reason": (selected_tier or {}).get("selection_reason"),
        "dcf_model_not_appropriate": bool((selected_tier or {}).get("model_not_appropriate")),
        "reverse_dcf": reverse_dcf,
    }


def _build_dcf_tier_results(
    income_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    latest_revenue: float,
    latest_ebit_margin: float,
    latest_fcf: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    terminal_growth: float,
    tax_rate: float,
    working_capital_pct_revenue: float,
    working_capital_source: str,
    latest_ebitda: float | None,
    total_equity: float | None,
    standard_revenue_growth: float | None,
    standard_revenue_growth_source: str,
    standard_depreciation_pct_revenue: float,
    standard_capex_pct_revenue: float,
    beta_match: Any,
    standard_capex_source: str = "3-year historical average",
    standard_depreciation_source: str = "recent historical average",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Run the three DCF tiers and choose the first result that passes sanity gates."""
    smoothed_margin, smoothed_margin_source = _historical_margin_assumption(income_metrics, "ebit_margin")
    smoothed_growth = max(_historical_revenue_cagr(income_metrics, years=5, fallback=0.0) or 0.0, 0.0)
    smoothed_growth_source = f"{_historical_revenue_cagr_source(income_metrics, years=5)}; floored at 0%"
    smoothed_depreciation = _historical_depreciation_pct_revenue(income_metrics, years=5)
    smoothed_capex = _historical_capex_pct_revenue(income_metrics, cash_flow_metrics, years=5)
    sector_benchmarks = _load_dcf_sector_benchmarks(beta_match)
    sector_margin = sector_benchmarks.get("ebit_margin")
    sector_margin_source = sector_benchmarks.get("ebit_margin_source")
    if sector_margin is None:
        sector_margin = smoothed_margin
        sector_margin_source = "company long-term average; sector EBIT margin unavailable"
    sector_capex = sector_benchmarks.get("capex_pct_revenue")
    sector_capex_source = sector_benchmarks.get("capex_source")
    if sector_capex is None:
        sector_capex = smoothed_capex
        sector_capex_source = "company long-term average; sector CapEx benchmark unavailable"
    sector_capex = abs(sector_capex)

    tier_inputs = [
        {
            "tier": 1,
            "name": "Standard DCF",
            "method": "Tier 1 - standard",
            "confidence": "NORMAL",
            "max_deviation": STANDARD_DCF_MAX_DEVIATION,
            "assumptions": {
                "revenue_growth": standard_revenue_growth if standard_revenue_growth is not None else 0.05,
                "revenue_growth_source": standard_revenue_growth_source,
                "ebit_margin": latest_ebit_margin,
                "ebit_margin_source": "latest FY actual",
                "depreciation_pct_revenue": standard_depreciation_pct_revenue,
                "depreciation_source": standard_depreciation_source,
                "capex_pct_revenue": standard_capex_pct_revenue,
                "capex_source": standard_capex_source,
                "working_capital_pct_revenue": working_capital_pct_revenue,
                "working_capital_source": working_capital_source,
            },
        },
        {
            "tier": 2,
            "name": "Smoothed DCF",
            "method": "Tier 2 - smoothed long-term averages",
            "confidence": "MODERATE",
            "max_deviation": FALLBACK_DCF_MAX_DEVIATION,
            "assumptions": {
                "revenue_growth": smoothed_growth,
                "revenue_growth_source": smoothed_growth_source,
                "ebit_margin": smoothed_margin,
                "ebit_margin_source": smoothed_margin_source,
                "depreciation_pct_revenue": smoothed_depreciation,
                "depreciation_source": "5-year historical average",
                "capex_pct_revenue": smoothed_capex,
                "capex_source": "5-year historical average",
                "working_capital_pct_revenue": working_capital_pct_revenue,
                "working_capital_source": working_capital_source,
            },
        },
        {
            "tier": 3,
            "name": "Sector Benchmark DCF",
            "method": "Tier 3 - sector benchmark",
            "confidence": "LOW",
            "max_deviation": FALLBACK_DCF_MAX_DEVIATION,
            "assumptions": {
                "revenue_growth": DEFAULT_TERMINAL_GROWTH,
                "revenue_growth_source": "terminal-level 2.5% benchmark assumption",
                "ebit_margin": sector_margin,
                "ebit_margin_source": sector_margin_source,
                "ebit_margin_matched_industry": sector_benchmarks.get("ebit_margin_matched_industry"),
                "ebit_margin_source_url": sector_benchmarks.get("ebit_margin_source_url"),
                "ebit_margin_source_file": sector_benchmarks.get("ebit_margin_source_file"),
                "ebit_margin_source_row": sector_benchmarks.get("ebit_margin_source_row"),
                "depreciation_pct_revenue": smoothed_depreciation,
                "depreciation_source": "company 5-year historical average",
                "capex_pct_revenue": sector_capex,
                "capex_source": sector_capex_source,
                "capex_source_url": sector_benchmarks.get("capex_source_url"),
                "capex_source_file": sector_benchmarks.get("capex_source_file"),
                "capex_source_row": sector_benchmarks.get("capex_source_row"),
                "working_capital_pct_revenue": working_capital_pct_revenue,
                "working_capital_source": working_capital_source,
            },
        },
    ]

    tiers = []
    selected = None
    for tier_input in tier_inputs:
        if _should_skip_tier3_for_non_positive_sector_margin(tier_input):
            tier = _build_skipped_tier3(tier_input)
        else:
            tier = _run_dcf_tier(
                tier_input,
                latest_revenue=latest_revenue,
                latest_fcf=latest_fcf,
                wacc=wacc,
                net_debt=net_debt,
                shares_outstanding=shares_outstanding,
                current_price=current_price,
                terminal_growth=terminal_growth,
                tax_rate=tax_rate,
            )
        tiers.append(tier)
        if selected is None and tier["accepted"]:
            selected = tier

    if selected is None:
        tier4 = _build_multiples_tier(
            beta_match=beta_match,
            latest_revenue=latest_revenue,
            latest_ebitda=latest_ebitda,
            net_debt=net_debt,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
            total_equity=total_equity,
        )
        tiers.append(tier4)
        if tier4["accepted"]:
            selected = tier4
        tier5 = _build_tangible_book_tier(
            total_equity=total_equity,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        )
        tiers.append(tier5)
        if selected is None:
            selected = tier5

    if selected is not None and selected.get("tier") == 5:
        selected["selected"] = True
        selected["selection_reason"] = "Cannot determine fair value with available methods; tangible book value is used as a theoretical floor."
    elif selected is not None:
        selected["selected"] = True
        selected["selection_reason"] = _dcf_selection_reason(selected, tiers)

    if selected:
        selected["explanation"] = _dcf_tier_explanation(selected, tiers)
    return tiers, selected or {}


def _should_skip_tier3_for_non_positive_sector_margin(tier_input: dict[str, Any]) -> bool:
    """Return True when Tier 3 has a non-positive Damodaran sector EBIT margin."""
    if tier_input.get("tier") != 3:
        return False
    assumptions = tier_input.get("assumptions") or {}
    margin = _value_or_none(assumptions.get("ebit_margin"))
    source = assumptions.get("ebit_margin_source") or ""
    return margin is not None and margin <= 0 and source.startswith("Damodaran sector benchmark")


def _build_skipped_tier3(tier_input: dict[str, Any]) -> dict[str, Any]:
    """Build a skipped Tier 3 result when sector benchmark margins are not applicable."""
    assumptions = tier_input["assumptions"]
    margin = _value_or_none(assumptions.get("ebit_margin"))
    sector_name = assumptions.get("ebit_margin_matched_industry") or assumptions.get("ebit_margin_source") or "sector benchmark"
    margin_text = f"{margin:.2%}" if margin is not None else "N/A"
    message = (
        "Tier 3 not applicable - Damodaran sector benchmark EBIT margin is non-positive "
        f"({sector_name}: {margin_text}). This typically occurs in fragmented sectors with many "
        "unprofitable small companies. A profitable target company is unlikely to be valued at sector-bottom margins."
    )
    return {
        "tier": tier_input["tier"],
        "name": tier_input["name"],
        "method": tier_input["method"],
        "confidence": tier_input["confidence"],
        "assumptions": assumptions,
        "dcf": {},
        "accepted": False,
        "selected": False,
        "status": "SKIPPED",
        "rejection_reason": "sector benchmark not applicable",
        "acceptance_reason": "",
        "skip_message": message,
        "model_not_appropriate": False,
    }


def _run_dcf_tier(
    tier_input: dict[str, Any],
    latest_revenue: float,
    latest_fcf: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    terminal_growth: float,
    tax_rate: float,
) -> dict[str, Any]:
    """Calculate one DCF tier and attach acceptance diagnostics."""
    assumptions = tier_input["assumptions"]
    tier = {
        "tier": tier_input["tier"],
        "name": tier_input["name"],
        "method": tier_input["method"],
        "confidence": tier_input["confidence"],
        "assumptions": assumptions,
        "selected": False,
        "model_not_appropriate": False,
    }
    try:
        dcf = build_dcf_forecast(
            latest_revenue=latest_revenue,
            latest_ebit_margin=assumptions["ebit_margin"],
            latest_fcf=latest_fcf,
            wacc=wacc,
            net_debt=net_debt,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
            revenue_growth=assumptions["revenue_growth"],
            terminal_growth=terminal_growth,
            tax_rate=tax_rate,
            capex_pct_revenue=assumptions["capex_pct_revenue"],
            depreciation_pct_revenue=assumptions["depreciation_pct_revenue"],
            working_capital_pct_revenue=assumptions["working_capital_pct_revenue"],
        )
        tier["dcf"] = dcf
        accepted, status, reason = _assess_dcf_result(dcf, current_price, tier_input["max_deviation"])
    except Exception as exc:
        tier["dcf"] = {}
        accepted, status, reason = False, "REJECTED", f"calculation failed: {exc}"
    tier["accepted"] = accepted
    tier["status"] = "ACCEPTED" if accepted else status
    tier["rejection_reason"] = "" if accepted else reason
    tier["acceptance_reason"] = reason if accepted else ""
    return tier


def _assess_dcf_result(
    dcf: dict[str, Any],
    current_price: float | None,
    max_deviation: float,
) -> tuple[bool, str, str]:
    """Return whether a DCF result passes the tier-specific sanity gate."""
    implied_price = _value_or_none(dcf.get("implied_price"))
    if implied_price is None:
        return False, "REJECTED", "missing implied price"
    if implied_price <= 0:
        return False, "REJECTED", "negative or zero implied price"
    if current_price in (None, 0) or pd.isna(current_price):
        return True, "ACCEPTED", "accepted; market price unavailable for deviation check"
    upside = implied_price / float(current_price) - 1
    if abs(upside) > max_deviation:
        direction = "downside" if upside < 0 else "upside"
        return False, "REJECTED", f"{abs(upside):.1%} {direction} exceeds {max_deviation:.0%} tier limit"
    return True, "ACCEPTED", f"within {max_deviation:.0%} of market price"


def build_reverse_dcf_analysis(
    info: dict[str, Any],
    tier1: dict[str, Any],
    latest_revenue: float,
    latest_fcf: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    terminal_growth: float,
    tax_rate: float,
    historical_ebit_margin_average: float | None = None,
) -> dict[str, Any]:
    """Build Reverse DCF diagnostics from Tier 1 assumptions; this is not a valuation tier."""
    assumptions = tier1.get("assumptions") or {}
    tier1_growth = assumptions.get("revenue_growth")
    analyst_growth, analyst_source = _analyst_consensus_growth(info)
    solved = solve_reverse_dcf_growth(
        latest_revenue=latest_revenue,
        latest_ebit_margin=assumptions.get("ebit_margin"),
        latest_fcf=latest_fcf,
        wacc=wacc,
        net_debt=net_debt,
        shares_outstanding=shares_outstanding,
        current_price=current_price,
        terminal_growth=terminal_growth,
        tax_rate=tax_rate,
        capex_pct_revenue=assumptions.get("capex_pct_revenue"),
        depreciation_pct_revenue=assumptions.get("depreciation_pct_revenue"),
        working_capital_pct_revenue=assumptions.get("working_capital_pct_revenue"),
    )
    implied_growth = solved.get("implied_growth")
    gap = implied_growth - tier1_growth if implied_growth is not None and tier1_growth is not None else None
    failure_message = _reverse_dcf_failure_message(
        solved,
        assumptions.get("ebit_margin"),
        historical_ebit_margin_average,
    )
    message = failure_message or solved.get("message")
    interpretation = _reverse_dcf_interpretation(implied_growth, tier1_growth, message)
    return {
        "implied_growth": implied_growth,
        "tier1_growth": tier1_growth,
        "tier1_growth_source": assumptions.get("revenue_growth_source"),
        "analyst_consensus_growth": analyst_growth,
        "analyst_consensus_source": analyst_source,
        "growth_gap": gap,
        "status": solved.get("status"),
        "message": message,
        "interpretation": interpretation,
        "source": "Reverse DCF (solved from market price)",
        "target_price": current_price,
        "low_growth": solved.get("low_growth"),
        "high_growth": solved.get("high_growth"),
        "low_price": solved.get("low_price"),
        "high_price": solved.get("high_price"),
    }


def solve_reverse_dcf_growth(
    latest_revenue: float,
    latest_ebit_margin: float | None,
    latest_fcf: float,
    wacc: float,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    terminal_growth: float,
    tax_rate: float,
    capex_pct_revenue: float | None,
    depreciation_pct_revenue: float | None,
    working_capital_pct_revenue: float | None,
    low_growth: float = -0.10,
    high_growth: float = 0.50,
) -> dict[str, Any]:
    """
    Solve the revenue growth rate implied by the current market price.

    This reverse DCF holds Tier 1 Standard DCF inputs constant and solves only
    the year 1-5 revenue growth rate. It is a diagnostic interpretation tool,
    not a valuation tier and not a calibration of the existing 5-tier model.
    """
    required = {
        "latest_revenue": latest_revenue,
        "latest_ebit_margin": latest_ebit_margin,
        "wacc": wacc,
        "shares_outstanding": shares_outstanding,
        "current_price": current_price,
        "capex_pct_revenue": capex_pct_revenue,
        "depreciation_pct_revenue": depreciation_pct_revenue,
        "working_capital_pct_revenue": working_capital_pct_revenue,
    }
    missing = [key for key, value in required.items() if value is None or pd.isna(value)]
    if missing:
        return {
            "implied_growth": None,
            "status": "UNAVAILABLE",
            "message": f"Reverse DCF unavailable: missing {', '.join(missing)}.",
            "low_growth": low_growth,
            "high_growth": high_growth,
            "low_price": None,
            "high_price": None,
        }
    if current_price <= 0 or shares_outstanding <= 0 or latest_revenue <= 0:
        return {
            "implied_growth": None,
            "status": "UNAVAILABLE",
            "message": "Reverse DCF unavailable: market price, shares, and revenue must be positive.",
            "low_growth": low_growth,
            "high_growth": high_growth,
            "low_price": None,
            "high_price": None,
        }

    def price_at_growth(growth: float) -> float:
        return build_dcf_forecast(
            latest_revenue=latest_revenue,
            latest_ebit_margin=float(latest_ebit_margin),
            latest_fcf=latest_fcf,
            wacc=wacc,
            net_debt=net_debt,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
            revenue_growth=growth,
            terminal_growth=terminal_growth,
            tax_rate=tax_rate,
            capex_pct_revenue=float(capex_pct_revenue),
            depreciation_pct_revenue=float(depreciation_pct_revenue),
            working_capital_pct_revenue=float(working_capital_pct_revenue),
        )["implied_price"]

    try:
        low_price = price_at_growth(low_growth)
        high_price = price_at_growth(high_growth)
        low_gap = low_price - current_price
        high_gap = high_price - current_price
        if abs(low_gap) < 1e-7:
            implied_growth = low_growth
        elif abs(high_gap) < 1e-7:
            implied_growth = high_growth
        elif low_gap * high_gap > 0:
            if low_price > current_price and high_price > current_price:
                message = (
                    "Reverse DCF could not solve within the search range (-10% to +50% revenue growth); "
                    "market price is below the modeled range."
                )
            else:
                message = (
                    "Reverse DCF could not solve within the search range (-10% to +50% revenue growth); "
                    "market price is above the modeled range."
                )
            return {
                "implied_growth": None,
                "status": "UNREACHABLE",
                "message": message,
                "low_growth": low_growth,
                "high_growth": high_growth,
                "low_price": low_price,
                "high_price": high_price,
            }
        else:
            implied_growth = _solve_brentq(lambda growth: price_at_growth(growth) - current_price, low_growth, high_growth)
    except Exception as exc:
        return {
            "implied_growth": None,
            "status": "FAILED",
            "message": f"Reverse DCF solver failed to converge: {exc}",
            "low_growth": low_growth,
            "high_growth": high_growth,
            "low_price": None,
            "high_price": None,
        }

    return {
        "implied_growth": implied_growth,
        "status": "OK",
        "message": "Reverse DCF solved successfully.",
        "low_growth": low_growth,
        "high_growth": high_growth,
        "low_price": low_price,
        "high_price": high_price,
    }


def _reverse_dcf_failure_message(
    solved: dict[str, Any],
    tier1_ebit_margin: float | None,
    historical_ebit_margin_average: float | None,
) -> str | None:
    """Return context-aware Reverse DCF failure messaging without changing the solver."""
    status = solved.get("status")
    if status == "OK":
        return None
    if status == "UNREACHABLE":
        margin = _value_or_none(tier1_ebit_margin)
        average = _value_or_none(historical_ebit_margin_average)
        if margin is not None and average is not None and average > 0 and margin < 0.5 * average:
            return (
                f"Reverse DCF could not solve. Current Tier 1 EBIT margin ({margin:.1%}) is significantly below "
                f"the 5-year average ({average:.1%}), suggesting the market is pricing margin recovery rather "
                "than revenue growth. Standard reverse DCF holds margins constant and cannot capture this scenario."
            )
        return (
            "Reverse DCF could not solve within the search range (-10% to +50% revenue growth). This may indicate "
            "the market is pricing factors not captured by the model (acquisition premium, breakup value, takeover "
            "speculation, etc)."
        )
    if status in {"UNAVAILABLE", "FAILED"}:
        return (
            "Reverse DCF could not solve due to model input issues. Verify that Tier 1 inputs are valid "
            "(positive WACC, positive shares outstanding, etc)."
        )
    return None


def _reverse_dcf_historical_margin_average(income_metrics: pd.DataFrame) -> float | None:
    """Return the available trailing 5-year EBIT margin average for Reverse DCF diagnostics."""
    if income_metrics.empty or "ebit_margin" not in income_metrics.columns:
        return None
    values = pd.to_numeric(income_metrics["ebit_margin"], errors="coerce").dropna().tail(5)
    values = values[(values >= -50.0) & (values <= 80.0)]
    if values.empty:
        return None
    return float((values / 100).mean())


def _solve_brentq(function, low: float, high: float) -> float:
    """Use scipy brentq when available, otherwise fall back to a deterministic bisection solver."""
    try:
        from scipy.optimize import brentq

        return float(brentq(function, low, high, xtol=1e-6, maxiter=100))
    except ImportError:
        return _bisect_root(function, low, high)


def _bisect_root(function, low: float, high: float, tolerance: float = 1e-6, max_iterations: int = 100) -> float:
    """Small local fallback for environments where scipy is not installed."""
    low_value = function(low)
    high_value = function(high)
    if low_value * high_value > 0:
        raise ValueError("root is not bracketed")
    for _ in range(max_iterations):
        midpoint = (low + high) / 2
        midpoint_value = function(midpoint)
        if abs(midpoint_value) < tolerance or (high - low) / 2 < tolerance:
            return float(midpoint)
        if low_value * midpoint_value <= 0:
            high = midpoint
            high_value = midpoint_value
        else:
            low = midpoint
            low_value = midpoint_value
    raise ValueError("bisection did not converge")


def _analyst_consensus_growth(info: dict[str, Any]) -> tuple[float | None, str]:
    """Return yfinance revenueGrowth if available, without fabricating missing estimates."""
    value = _ratio_like_to_decimal((info or {}).get("revenueGrowth"))
    if value is not None:
        return value, "yfinance revenueGrowth"
    recommendation = (info or {}).get("recommendationKey")
    if recommendation:
        return None, f"N/A - yfinance revenueGrowth unavailable; recommendationKey={recommendation}"
    return None, "N/A - yfinance revenueGrowth unavailable"


def _reverse_dcf_interpretation(implied_growth: float | None, tier1_growth: float | None, failure_message: str | None) -> str:
    """Create the user-facing Reverse DCF interpretation."""
    if implied_growth is None or tier1_growth is None:
        return failure_message or "Reverse DCF could not solve an implied growth rate from the available inputs."
    gap = implied_growth - tier1_growth
    if abs(gap) <= 0.02:
        return "Market pricing is consistent with model assumptions."
    if gap > 0.02:
        return "Market is pricing in higher growth than the model assumes - this explains the negative valuation gap."
    return "Market is pricing in lower growth than the model assumes - the model may be overoptimistic."


def _build_unavailable_reverse_dcf(info: dict[str, Any], message: str) -> dict[str, Any]:
    """Return a complete Reverse DCF object when the diagnostic cannot be calculated."""
    analyst_growth, analyst_source = _analyst_consensus_growth(info)
    return {
        "implied_growth": None,
        "tier1_growth": None,
        "tier1_growth_source": "N/A",
        "analyst_consensus_growth": analyst_growth,
        "analyst_consensus_source": analyst_source,
        "growth_gap": None,
        "status": "UNAVAILABLE",
        "message": message,
        "interpretation": message,
        "source": "Reverse DCF (solved from market price)",
        "target_price": None,
        "low_growth": -0.10,
        "high_growth": 0.50,
        "low_price": None,
        "high_price": None,
    }


def _dcf_selection_reason(selected: dict[str, Any], tiers: list[dict[str, Any]]) -> str:
    """Explain why the selected DCF tier became the primary estimate."""
    tier = selected.get("tier")
    if tier == 1:
        return "Standard DCF passed the primary sanity checks."
    failed = [item for item in tiers if item.get("tier", 0) < tier]
    failed_text = "; ".join(
        f"Tier {item['tier']} {_tier_failure_verb(item)} ({item.get('rejection_reason', 'failed sanity check')})"
        for item in failed
    )
    if tier == 2:
        return f"Smoothed DCF selected because {failed_text}."
    if tier == 3:
        return f"Sector Benchmark DCF selected because {failed_text}."
    if tier == 4:
        return f"Multiples valuation selected because {failed_text}."
    return selected.get("selection_reason", "")


def _tier_failure_verb(tier: dict[str, Any]) -> str:
    """Return a precise verb for non-selected tier diagnostics."""
    return "skipped" if tier.get("status") == "SKIPPED" else "rejected"


def _dcf_tier_explanation(selected: dict[str, Any], tiers: list[dict[str, Any]]) -> str:
    """Build a concise user-facing explanation for fallback tiers."""
    if selected.get("tier") == 1:
        return "Standard DCF uses current company financials and passed sanity checks."
    if selected.get("tier") == 4:
        return "DCF model was not applicable; selected estimate uses the median of sector EV/EBITDA, EV/Sales, and P/Book valuation outputs."
    if selected.get("tier") == 5:
        return "Cannot determine fair value with available methods. Tangible book value provides a theoretical floor; market price reflects expectations not captured here."
    tier1 = next((item for item in tiers if item.get("tier") == 1), {})
    tier2 = next((item for item in tiers if item.get("tier") == 2), {})
    latest_margin = (tier1.get("assumptions") or {}).get("ebit_margin")
    smoothed_margin = (tier2.get("assumptions") or {}).get("ebit_margin")
    selected_margin = (selected.get("assumptions") or {}).get("ebit_margin")
    parts = []
    if latest_margin is not None and smoothed_margin is not None:
        parts.append(f"recent EBIT margin ({latest_margin:.2%}) vs long-term average ({smoothed_margin:.2%})")
    if selected.get("tier") == 3 and selected_margin is not None:
        parts.append(f"selected sector/benchmark margin ({selected_margin:.2%})")
    if not parts:
        return selected.get("selection_reason", "")
    return (
        "Fallback selected because "
        + " and ".join(parts)
        + "; company-specific recent financials appear distorted for point-in-time DCF."
    )


def _historical_margin_assumption(
    income_metrics: pd.DataFrame,
    column: str,
    fallback: float | None = None,
) -> tuple[float, str]:
    """Return a 5-year margin average, falling back to 3-year and then latest margin."""
    if fallback is None:
        fallback = _ratio_from_percent(_latest_available_value(income_metrics, column)) or 0.12
    if income_metrics.empty or column not in income_metrics.columns:
        return fallback, "fallback margin assumption"
    values = pd.to_numeric(income_metrics[column], errors="coerce").dropna() / 100
    values = values[(values >= -0.5) & (values <= 0.8)]
    if len(values) >= 5:
        return float(values.tail(5).mean()), "5-year historical average"
    if len(values) >= 3:
        return float(values.tail(3).mean()), "3-year historical average"
    if not values.empty:
        return float(values.iloc[-1]), "latest available FY actual"
    return fallback, "fallback margin assumption"


def _load_dcf_sector_benchmarks(beta_match: Any) -> dict[str, Any]:
    """
    Load Damodaran margin and CapEx sector benchmarks for Tier 3 DCF.

    Uses the same Damodaran workbook parser as beta loading; Streamlit gives
    that parser a one-day cache.
    """
    margin = _lookup_damodaran_sector_metric(
        beta_match,
        DCF_MARGIN_URLS,
        (
            ("operating", "margin"),
            ("pre", "tax", "operating", "margin"),
            ("pretax", "operating", "margin"),
        ),
    )
    capex = _lookup_damodaran_sector_metric(
        beta_match,
        DCF_CAPEX_URLS,
        (
            ("net", "cap", "ex", "sales"),
            ("cap", "ex", "sales"),
            ("capital", "expenditures", "sales"),
            ("capex", "sales"),
        ),
    )
    return {
        "ebit_margin": margin.get("value"),
        "ebit_margin_source": margin.get("source"),
        "ebit_margin_source_url": margin.get("source_url"),
        "ebit_margin_source_file": margin.get("source_file"),
        "ebit_margin_source_row": margin.get("source_row"),
        "ebit_margin_matched_industry": margin.get("matched_industry"),
        "capex_pct_revenue": capex.get("value"),
        "capex_source": capex.get("source"),
        "capex_source_url": capex.get("source_url"),
        "capex_source_file": capex.get("source_file"),
        "capex_source_row": capex.get("source_row"),
        "capex_matched_industry": capex.get("matched_industry"),
    }


def _build_multiples_tier(
    beta_match: Any,
    latest_revenue: float,
    latest_ebitda: float | None,
    net_debt: float,
    shares_outstanding: float,
    current_price: float | None,
    total_equity: float | None,
) -> dict[str, Any]:
    """Build Tier 4 using Damodaran sector multiples."""
    multiples = _load_sector_multiples(beta_match)
    detail_rows = []
    ev_ebitda = multiples.get("ev_ebitda")
    ev_ebitda_error = multiples.get("ev_ebitda_error")
    ev_ebitda_price = None
    if ev_ebitda is not None and latest_ebitda is not None and latest_ebitda > 0:
        enterprise_value = ev_ebitda * latest_ebitda
        ev_ebitda_price = _equity_value_to_price(enterprise_value - net_debt, shares_outstanding)
    elif ev_ebitda is not None:
        ev_ebitda_error = "company TTM EBITDA unavailable or non-positive"
    detail_rows.append(
        _multiples_detail_row(
            "EV/EBITDA",
            ev_ebitda,
            ev_ebitda_price,
            multiples.get("ev_ebitda_source"),
            multiples.get("ev_ebitda_source_file"),
            ev_ebitda_error,
        )
    )

    ev_sales = multiples.get("ev_sales")
    ev_sales_error = multiples.get("ev_sales_error")
    ev_sales_price = None
    if ev_sales is not None and latest_revenue > 0:
        enterprise_value = ev_sales * latest_revenue
        ev_sales_price = _equity_value_to_price(enterprise_value - net_debt, shares_outstanding)
    elif ev_sales is not None:
        ev_sales_error = "company TTM revenue unavailable or non-positive"
    detail_rows.append(
        _multiples_detail_row(
            "EV/Sales",
            ev_sales,
            ev_sales_price,
            multiples.get("ev_sales_source"),
            multiples.get("ev_sales_source_file"),
            ev_sales_error,
        )
    )

    pb = multiples.get("price_book")
    pb_error = multiples.get("price_book_error")
    tangible_book_price = _tangible_book_per_share(total_equity, shares_outstanding)
    pb_price = None
    if pb is not None and tangible_book_price is not None and tangible_book_price > 0:
        pb_price = pb * tangible_book_price
    elif pb is not None:
        pb_error = "book value per share unavailable or non-positive"
    detail_rows.append(
        _multiples_detail_row(
            "P/Book",
            pb,
            pb_price,
            multiples.get("price_book_source"),
            multiples.get("price_book_source_file"),
            pb_error,
        )
    )

    clean_estimates = sorted(
        float(item["implied_price"])
        for item in detail_rows
        if item.get("implied_price") is not None and not pd.isna(item.get("implied_price")) and float(item["implied_price"]) > 0
    )
    implied_price = _median(clean_estimates) if clean_estimates else None
    dcf_like = _valuation_output(implied_price, current_price)
    accepted, status, reason = _assess_dcf_result(dcf_like, current_price, FALLBACK_DCF_MAX_DEVIATION)
    available_count = len(clean_estimates)
    if available_count == 0:
        accepted = False
        status = "REJECTED"
        reason = "data unavailable"
    if accepted and tangible_book_price is not None and implied_price is not None and implied_price <= 0.5 * tangible_book_price:
        accepted = False
        status = "REJECTED"
        reason = "multiples estimate is below 50% of tangible book value"
    detail_status = _multiples_detail_status(available_count)
    tier = {
        "tier": 4,
        "name": "Multiples-Based Valuation",
        "method": "Tier 4 - multiples valuation",
        "confidence": "LOW",
        "selected": False,
        "accepted": accepted,
        "status": "ACCEPTED" if accepted else status,
        "rejection_reason": "" if accepted else reason,
        "detail_status": detail_status,
        "available_multiples": available_count,
        "assumptions": {
            "source": "Sector multiples (median of EV/EBITDA, EV/Sales, P/Book)",
            "tangible_book_per_share": tangible_book_price,
            **multiples,
        },
        "multiples": detail_rows,
        "dcf": dcf_like,
    }
    return tier


def _multiples_detail_row(
    method: str,
    multiple: float | None,
    implied_price: float | None,
    source: str | None,
    source_file: str | None,
    error: str | None,
) -> dict[str, Any]:
    """Return one Tier 4 row, including unavailable-data diagnostics."""
    row_error = error
    if multiple is None and not row_error:
        row_error = "Damodaran multiple unavailable"
    if implied_price is not None and (pd.isna(implied_price) or float(implied_price) <= 0):
        row_error = "implied price is non-positive"
    row_status = "AVAILABLE" if multiple is not None and implied_price is not None and not pd.isna(implied_price) and float(implied_price) > 0 else "UNAVAILABLE"
    return {
        "method": method,
        "multiple": multiple,
        "implied_price": implied_price,
        "source": source or ("Unavailable" if row_error else None),
        "source_file": source_file,
        "status": row_status,
        "error": row_error or "",
    }


def _multiples_detail_status(available_count: int) -> str:
    """Return the user-facing Tier 4 data coverage status."""
    if available_count == 3:
        return "Full multiples set (3/3 available)"
    if available_count == 2:
        return "Limited multiples (2/3 available)"
    if available_count == 1:
        return "Limited multiples (only 1/3 available)"
    return "REJECTED (data unavailable)"


def _build_tangible_book_tier(
    total_equity: float | None,
    shares_outstanding: float,
    current_price: float | None,
) -> dict[str, Any]:
    """Build Tier 5 tangible book value floor."""
    implied_price = _tangible_book_per_share(total_equity, shares_outstanding)
    dcf_like = _valuation_output(implied_price, current_price)
    return {
        "tier": 5,
        "name": "Tangible Book Value Floor",
        "method": "Tier 5 - tangible book floor",
        "confidence": "VERY LOW",
        "selected": False,
        "accepted": implied_price is not None and implied_price > 0,
        "status": "REFERENCE",
        "rejection_reason": "",
        "assumptions": {
            "source": "Tangible book value per share (liquidation floor)",
            "total_equity": total_equity,
            "shares_outstanding": shares_outstanding,
        },
        "dcf": dcf_like,
    }


def _load_sector_multiples(beta_match: Any) -> dict[str, Any]:
    """Load Damodaran sector EV/EBITDA, EV/Sales, and P/Book multiples."""
    ev_ebitda = _lookup_damodaran_sector_metric(
        beta_match,
        MULTIPLE_EV_EBITDA_URLS,
        (
            ("ev", "ebitda"),
            ("enterprise", "value", "ebitda"),
            ("value", "ebitda"),
        ),
        ratio=False,
    )
    ev_sales = _lookup_damodaran_sector_metric(
        beta_match,
        MULTIPLE_EV_SALES_URLS,
        (
            ("ev", "sales"),
            ("enterprise", "value", "sales"),
            ("value", "sales"),
            ("price", "sales"),
            ("p", "sales"),
        ),
        ratio=False,
    )
    price_book = _lookup_damodaran_sector_metric(
        beta_match,
        MULTIPLE_PB_URLS,
        (
            ("price", "book"),
            ("price", "book", "value"),
            ("pbv",),
            ("p", "bv"),
            ("p", "book"),
            ("market", "book"),
        ),
        ratio=False,
    )
    return {
        "ev_ebitda": ev_ebitda.get("value"),
        "ev_ebitda_source": ev_ebitda.get("source"),
        "ev_ebitda_source_file": ev_ebitda.get("source_file"),
        "ev_ebitda_source_url": ev_ebitda.get("source_url"),
        "ev_ebitda_error": ev_ebitda.get("error"),
        "ev_sales": ev_sales.get("value"),
        "ev_sales_source": ev_sales.get("source"),
        "ev_sales_source_file": ev_sales.get("source_file"),
        "ev_sales_source_url": ev_sales.get("source_url"),
        "ev_sales_error": ev_sales.get("error"),
        "price_book": price_book.get("value"),
        "price_book_source": price_book.get("source"),
        "price_book_source_file": price_book.get("source_file"),
        "price_book_source_url": price_book.get("source_url"),
        "price_book_error": price_book.get("error"),
    }


def _lookup_damodaran_sector_metric(
    beta_match: Any,
    urls: dict[str, str],
    column_fragment_sets: tuple[tuple[str, ...], ...],
    ratio: bool = True,
) -> dict[str, Any]:
    """Look up one DCF sector benchmark from a Damodaran dataset."""
    from utils.damodaran import _source_filename, load_damodaran_table, match_industry

    region = "europe" if getattr(beta_match, "source_region", "") == "europe" else "us"
    url = urls[region]
    source_file = _source_filename(url)
    try:
        raw = load_damodaran_table(url)
        industry_col = _find_damodaran_column(raw, (("industry", "name"), ("industry",)))
        value_col = _find_damodaran_column(raw, column_fragment_sets)
        if industry_col is None:
            return {"error": f"industry column unavailable in {source_file}", "source_url": url, "source_file": source_file}
        if value_col is None:
            return {"error": f"target metric column unavailable in {source_file}", "source_url": url, "source_file": source_file}
        table = pd.DataFrame()
        table["industry"] = raw[industry_col].astype(str).str.strip()
        converter = _ratio_like_to_decimal if ratio else _value_or_none
        table["value"] = raw[value_col].map(converter)
        table["raw_index"] = raw.index
        table = table.dropna(subset=["value"])
        table = table[table["industry"].str.len() > 0]
        table = table[~table["industry"].str.lower().isin({"nan", "industry", "industry name"})]
        if table.empty:
            return {"error": f"no usable sector rows in {source_file}", "source_url": url, "source_file": source_file}
        lookup_industry = getattr(beta_match, "matched_industry", "") or getattr(beta_match, "company_industry", "")
        matched_industry, confidence = match_industry(lookup_industry, table)
        row = table[table["industry"] == matched_industry]
        if row.empty:
            return {"error": f"sector match unavailable in {source_file}: {lookup_industry}", "source_url": url, "source_file": source_file}
        row_data = row.iloc[0].to_dict()
        source_label = f"Damodaran sector benchmark: {matched_industry}"
        raw_index = row_data.get("raw_index")
        return {
            "value": float(row_data["value"]),
            "source": source_label,
            "source_url": url,
            "source_file": source_file,
            "source_row": int(raw_index) if raw_index is not None and not pd.isna(raw_index) else None,
            "matched_industry": matched_industry,
            "confidence": confidence,
            "column": str(value_col),
            "error": "",
        }
    except Exception as exc:
        log_event(f"DCF sector benchmark lookup failed: url={url} | {exc}", "valuation_warning")
        return {"error": f"load failed for {source_file}: {exc}", "source_url": url, "source_file": source_file}


def _find_damodaran_column(frame: pd.DataFrame, fragment_sets: tuple[tuple[str, ...], ...]) -> str | None:
    """Find a Damodaran column whose normalized name contains every fragment in one set."""
    normalized_columns = {str(column): _normalize_text(column) for column in frame.columns}
    for fragments in fragment_sets:
        normalized_fragments = [_normalize_text(fragment) for fragment in fragments]
        matches = []
        for column, key in normalized_columns.items():
            if all(fragment in key for fragment in normalized_fragments):
                matches.append((len(key), column))
        if matches:
            matches.sort(key=lambda item: item[0])
            return matches[0][1]
    return None


def _normalize_text(value: Any) -> str:
    """Normalize loose Damodaran labels for column matching."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def _equity_value_to_price(equity_value_millions: float | None, shares_outstanding: float | None) -> float | None:
    """Convert equity value in millions to per-share price."""
    if equity_value_millions is None or shares_outstanding in (None, 0):
        return None
    return float(equity_value_millions) * 1_000_000 / float(shares_outstanding)


def _tangible_book_per_share(total_equity: float | None, shares_outstanding: float | None) -> float | None:
    """Return book value per share from latest balance-sheet equity."""
    return _equity_value_to_price(total_equity, shares_outstanding)


def _valuation_output(implied_price: float | None, current_price: float | None) -> dict[str, Any]:
    """Return a valuation result with the same key shape used by DCF outputs."""
    upside = None
    if implied_price is not None and current_price not in (None, 0) and not pd.isna(current_price):
        upside = implied_price / float(current_price) - 1
    return {
        "forecast": [],
        "terminal_value": None,
        "pv_terminal_value": None,
        "enterprise_value": None,
        "equity_value": None,
        "implied_price": implied_price,
        "upside": upside,
        "latest_fcf": None,
    }


def _median(values: list[float]) -> float | None:
    """Return median for a non-empty numeric list."""
    if not values:
        return None
    midpoint = len(values) // 2
    if len(values) % 2 == 1:
        return float(values[midpoint])
    return float((values[midpoint - 1] + values[midpoint]) / 2)


def _find_row_ratio(row_data: dict[str, Any], fragments: tuple[str, ...]) -> float | None:
    """Find a ratio-like value from a Damodaran row by loose column fragments."""
    normalized_fragments = [fragment.lower() for fragment in fragments]
    for key, value in row_data.items():
        key_text = str(key).lower()
        if all(fragment in key_text for fragment in normalized_fragments):
            ratio = _ratio_like_to_decimal(value)
            if ratio is not None and -0.5 <= ratio <= 0.8:
                return ratio
    return None


def _ratio_like_to_decimal(value: Any) -> float | None:
    """Convert ratio values that may appear as 8.7, 8.7%, or 0.087 into decimals."""
    number = _value_or_none(value)
    if number is None:
        return None
    if abs(number) > 3:
        return number / 100
    return number


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


def _historical_depreciation_pct_revenue(income_metrics: pd.DataFrame, fallback: float = 0.03, years: int = 3) -> float:
    """Return D&A as a revenue percentage (value only; see _historical_depreciation_assumption)."""
    value, _source = _historical_depreciation_assumption(income_metrics, fallback, years)
    return value


def _historical_depreciation_assumption(income_metrics: pd.DataFrame, fallback: float = 0.03, years: int = 3) -> tuple[float, str]:
    """
    Estimate D&A as a percentage of revenue using EBITDA minus EBIT, plus a source label.

    Formula: D&A % revenue = average((EBITDA - EBIT) / revenue) over available recent years.
    Source: yfinance income statement metrics; Damodaran FCFF model convention.
    Example: Apple FY2025 D&A = 144,748 - 133,050 = 11,698M = 2.81% of revenue.
    Required inputs: income_metrics with revenue, EBITDA, and EBIT.
    Limitation: falls back to 3% (clearly labelled) if EBITDA/EBIT data is missing or invalid.
    """
    fallback_source = "Default 3% (depreciation/amortization data not available)"
    required = {"revenue", "ebitda", "ebit"}
    if income_metrics.empty or not required.issubset(income_metrics.columns):
        return fallback, fallback_source
    frame = income_metrics.tail(years).copy()
    revenue = pd.to_numeric(frame["revenue"], errors="coerce")
    ebitda = pd.to_numeric(frame["ebitda"], errors="coerce")
    ebit = pd.to_numeric(frame["ebit"], errors="coerce")
    ratios = ((ebitda - ebit) / revenue).replace([float("inf"), -float("inf")], pd.NA).dropna()
    ratios = ratios[(ratios >= 0) & (ratios <= 0.2)]
    if ratios.empty:
        return fallback, fallback_source
    return float(ratios.mean()), f"{min(years, len(ratios))}-year historical average"


def _historical_capex_pct_revenue(
    income_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    fallback: float = 0.04,
    years: int = 3,
) -> float:
    """
    Estimate CapEx as a percentage of revenue from the latest three fiscal years.

    Formula: CapEx % revenue = average(abs(Capital Expenditure) / Revenue).
    Source: yfinance cash flow and income statement metrics.
    Example: Apple FY2023-FY2025 average is roughly 2.78% of revenue.
    Required inputs: income_metrics revenue and cash_flow_metrics capital_expenditure.
    Limitation: falls back to 4% when cash flow line items are missing.
    """
    value, _source = _historical_capex_assumption(income_metrics, cash_flow_metrics, fallback, years)
    return value


def _historical_capex_assumption(
    income_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    fallback: float = 0.04,
    years: int = 3,
) -> tuple[float, str]:
    """Return CapEx as a revenue percentage plus the source label for reports."""
    fallback_source = "Default 4% (capital expenditure data not available)"
    if income_metrics.empty or cash_flow_metrics.empty:
        return fallback, fallback_source
    required_income = {"year", "revenue"}
    required_cash = {"year", "capital_expenditure"}
    if not required_income.issubset(income_metrics.columns) or not required_cash.issubset(cash_flow_metrics.columns):
        return fallback, fallback_source
    merged = (
        income_metrics[["year", "revenue"]]
        .merge(cash_flow_metrics[["year", "capital_expenditure"]], on="year", how="inner")
        .tail(years)
    )
    revenue = pd.to_numeric(merged["revenue"], errors="coerce")
    capex = pd.to_numeric(merged["capital_expenditure"], errors="coerce").abs()
    ratios = (capex / revenue).replace([float("inf"), -float("inf")], pd.NA).dropna()
    ratios = ratios[(ratios >= 0) & (ratios <= 0.3)]
    if ratios.empty:
        return fallback, fallback_source
    return float(ratios.mean()), f"{min(years, len(ratios))}-year historical average"


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

    Formula: prefer the longest available 2-5 year CAGR window.
    Source: yfinance income statement revenue history.
    Example: Apple uses FY2021-FY2025 when available instead of being dominated by one weak FY2023.
    Required inputs: income metrics with annual revenue.
    Limitation: CAGR still simplifies cyclical revenue patterns into one annualized number.
    """
    if income_metrics.empty or "revenue" not in income_metrics.columns:
        return None, "Insufficient historical data - using sector benchmark fallback"

    frame = income_metrics.copy()
    frame["revenue"] = pd.to_numeric(frame["revenue"], errors="coerce")
    frame = frame.dropna(subset=["revenue"])
    frame = frame[frame["revenue"] > 0]
    # yfinance can return five FY columns while older line items are unavailable
    # (for example AAPL FY2021 TotalRevenue is NaN); label the usable window.
    available_years = min(len(frame), 5)
    if available_years >= 2:
        window = frame.tail(available_years)
        return _cagr_from_window(window), _cagr_source_from_window(window)
    return None, "Insufficient historical data - using sector benchmark fallback"


def _historical_revenue_cagr_source(income_metrics: pd.DataFrame, years: int = 5) -> str:
    """Return a CAGR source label using growth periods, not data-point count."""
    if income_metrics.empty or "revenue" not in income_metrics.columns:
        return "Insufficient historical data - using sector benchmark fallback"
    frame = income_metrics.copy()
    frame["revenue"] = pd.to_numeric(frame["revenue"], errors="coerce")
    frame = frame.dropna(subset=["revenue"])
    frame = frame[frame["revenue"] > 0]
    window = frame.tail(years)
    if len(window) < 2:
        return "Insufficient historical data - using sector benchmark fallback"
    return _cagr_source_from_window(window)


def _cagr_source_from_window(frame: pd.DataFrame) -> str:
    """Describe CAGR by elapsed growth periods rather than observation count."""
    periods = len(frame) - 1
    period_range = _period_range(frame)
    if periods <= 1:
        return f"1-year growth rate ({period_range})"
    return f"{periods}-year CAGR ({period_range}, {periods} growth periods)"


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
    value, _source = _historical_working_capital_assumption(income_metrics, balance_metrics, fallback)
    return value


def _historical_working_capital_assumption(
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    fallback: float = 0.02,
) -> tuple[float, str]:
    """Return working capital as a revenue percentage plus the source label for reports."""
    fallback_source = "Default 2% (current assets data not available)"
    required_income = {"year", "revenue"}
    required_balance = {"year", "current_assets", "current_liabilities"}
    if (
        income_metrics.empty
        or balance_metrics.empty
        or not required_income.issubset(income_metrics.columns)
        or not required_balance.issubset(balance_metrics.columns)
    ):
        return fallback, fallback_source
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
        return fallback, fallback_source
    return float(ratios.mean()), "3-year historical average"
