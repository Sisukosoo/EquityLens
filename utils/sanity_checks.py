"""Sanity checks for valuation outputs."""

from __future__ import annotations

from typing import Any

import pandas as pd


COUNTRY_STATUTORY_TAX_RATES = {
    "united states": 0.21,
    "finland": 0.20,
    "germany": 0.30,
    "sweden": 0.206,
    "denmark": 0.22,
    "norway": 0.22,
    "france": 0.25,
    "italy": 0.24,
    "netherlands": 0.258,
    "switzerland": 0.19,
    "japan": 0.30,
    "united kingdom": 0.25,
    "canada": 0.265,
}

INCOMPATIBLE_BUSINESS_MODEL_SECTOR_FRAGMENTS = (
    "bank",
    "brokerage",
    "insurance (life)",
    "insurance (prop/cas)",
    "insurance (general)",
    "reinsurance",
    "investments & asset management",
    "r.e.i.t.",
    "real estate (general/diversified)",
    "real estate (operations & services)",
    "real estate (development)",
    "financial svcs.",
    "securitized",
)

RUNTIME_EXCEL_SANITY_CATEGORIES = {
    "Business Model Compatibility",
    "Default assumptions",
    "Risk-free rate currency",
}


def run_sanity_checks(valuation: dict[str, Any]) -> list[dict[str, str]]:
    """
    Run valuation sanity checks before report generation.

    Formula: rule-based thresholds from the user requirements.
    Source: corporate finance reasonableness checks and user-specified limits.
    Example: WACC > 20% creates a warning.
    Required inputs: valuation result dict.
    Limitation: warnings are diagnostic and do not replace analyst judgment.
    """
    warnings = []
    _check_business_model_compatibility(valuation, warnings)
    _check_default_assumptions(valuation, warnings)
    _check_beta(valuation, warnings)
    _check_risk_free_currency_match(valuation, warnings)
    _check_costs(valuation, warnings)
    _check_dcf(valuation, warnings)
    _check_tax(valuation, warnings)
    return warnings


def _add(warnings: list[dict[str, str]], severity: str, message: str, category: str | None = None) -> None:
    """Add one sanity-check warning."""
    row = {"severity": severity, "message": message}
    if category:
        row["category"] = category
    warnings.append(row)


def runtime_sanity_checks_for_excel(sanity_warnings: list[dict[str, str]]) -> list[dict[str, str]]:
    """Return runtime sanity checks that should also appear in the Excel Validation tab."""
    rows = [
        {
            "severity": warning.get("severity", "info"),
            "category": warning.get("category", "Runtime sanity check"),
            "message": warning.get("message", ""),
        }
        for warning in sanity_warnings or []
        if warning.get("category") in RUNTIME_EXCEL_SANITY_CATEGORIES
    ]
    return sorted(rows, key=lambda row: {"critical": 0, "warning_high": 1, "warning": 1, "info": 2}.get(row["severity"], 3))


def build_excel_sanity_checks(
    valuation: dict[str, Any],
    income_metrics: pd.DataFrame,
    validation_result: dict[str, Any] | None,
    data: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    """
    Build analyst-level sanity checks for the Excel Validation tab only.

    Formula: rule-based thresholds for margin volatility, cost of debt context, tax context,
    beta methodology differences, DCF tier sensitivity, and implied price vs market.
    Source: valuation package, yfinance-derived statement metrics, and Damodaran validation rows.
    Example: a latest EBIT margin far above the 3-year average creates a warning row.
    Required inputs: valuation result, income metrics, optional Damodaran validation result, company data.
    Limitation: diagnostic only; does not alter tier selection or assumptions.
    """
    rows: list[dict[str, str]] = []
    _check_ebit_margin_outlier(income_metrics, rows)
    _check_cost_of_debt_context(valuation, validation_result, rows)
    _check_effective_tax_context(valuation, data or {}, rows)
    _check_beta_methodology_gap(valuation, rows)
    _check_tier_price_gap(valuation, rows)
    _check_implied_price_vs_market(valuation, rows)
    if not rows:
        return [{"severity": "info", "category": "Overall", "message": "All sanity checks passed."}]
    return sorted(rows, key=lambda row: {"critical": 0, "warning": 1, "info": 2}.get(row["severity"], 3))


def _add_excel_check(rows: list[dict[str, str]], severity: str, category: str, message: str) -> None:
    """Add one categorized Excel sanity-check row."""
    rows.append({"severity": severity, "category": category, "message": message})


def _check_ebit_margin_outlier(income_metrics: pd.DataFrame, rows: list[dict[str, str]]) -> None:
    """Flag latest FY EBIT margin when it is materially away from the 3-year average."""
    if income_metrics.empty or "ebit_margin" not in income_metrics.columns:
        return
    margins = pd.to_numeric(income_metrics["ebit_margin"], errors="coerce").dropna().tail(3)
    if len(margins) < 3:
        return
    latest = _ratio_value(margins.iloc[-1])
    average = float(margins.map(_ratio_value).mean())
    diff = latest - average
    if abs(diff) <= 0.05:
        return
    _add_excel_check(
        rows,
        "warning",
        "Margin volatility",
        (
            f"Latest FY EBIT margin ({latest:.1%}) deviates {abs(diff) * 100:.1f}pp from 3-year average ({average:.1%}). "
            "Investigate possible non-recurring items in the latest fiscal year (impairments, gains on sale, "
            "restructuring charges, divestiture effects). Tier 1 DCF assumes the latest margin will persist - "
            "if non-recurring, consider Tier 2 result as a more representative base case."
        ),
    )


def _check_cost_of_debt_context(
    valuation: dict[str, Any],
    validation_result: dict[str, Any] | None,
    rows: list[dict[str, str]],
) -> None:
    """Flag company cost of debt when it is materially different from Damodaran sector cost of debt."""
    metric = _validation_metric(validation_result, "Cost of Debt")
    company = _to_float(metric.get("Calculated") if metric else valuation.get("cost_of_debt"))
    sector = _to_float(metric.get("Damodaran (industry avg)") if metric else None)
    if company is None or sector is None:
        return
    diff = company - sector
    if abs(diff) <= 0.02:
        return
    direction_note = (
        "Below-sector cost of debt typically reflects strong credit rating (investment-grade or higher). "
        "Verify against current credit ratings (S&P/Moody's)."
        if company < sector
        else "Above-sector cost of debt may reflect lower credit rating, higher leverage, or sector-specific debt structures. "
        "Investigate balance sheet for distressed indicators."
    )
    _add_excel_check(
        rows,
        "info",
        "Cost of debt context",
        (
            f"Company cost of debt ({company:.2%}) differs from sector average ({sector:.2%}) by {abs(diff) * 100:.1f}pp. "
            f"{direction_note}"
        ),
    )


def _check_effective_tax_context(
    valuation: dict[str, Any],
    data: dict[str, Any],
    rows: list[dict[str, str]],
) -> None:
    """Flag company effective tax rate when it is materially away from country statutory rate."""
    effective = _to_float(valuation.get("tax_rate"))
    if effective is None:
        return
    country = ((data.get("info") or {}).get("country") or data.get("country") or "Unknown market")
    statutory = _statutory_tax_rate(country)
    diff = effective - statutory
    if abs(diff) <= 0.05:
        return
    direction_note = (
        "Lower effective rate often reflects multinational tax structures, R&D credits, or use of deferred tax assets. "
        "Verify sustainability of current rate."
        if effective < statutory
        else "Higher effective rate may reflect non-deductible items, withholding on foreign income, or one-time tax events."
    )
    _add_excel_check(
        rows,
        "info",
        "Tax structure",
        (
            f"Effective tax rate ({effective:.1%}) deviates from {country} statutory rate ({statutory:.1%}) "
            f"by {abs(diff) * 100:.1f}pp. {direction_note}"
        ),
    )


def _check_beta_methodology_gap(valuation: dict[str, Any], rows: list[dict[str, str]]) -> None:
    """Flag large differences between yfinance regression beta and Damodaran sector-relevered beta."""
    yfinance_beta = _to_float(valuation.get("yfinance_beta"))
    calculated_beta = _to_float(valuation.get("levered_beta"))
    if yfinance_beta is None or calculated_beta is None:
        return
    diff = abs(yfinance_beta - calculated_beta)
    if diff <= 0.30:
        return
    _add_excel_check(
        rows,
        "info",
        "Beta methodology",
        (
            f"Yahoo Finance beta ({yfinance_beta:.2f}) differs from Damodaran-relevered beta ({calculated_beta:.2f}) "
            f"by {diff:.2f}. This reflects different methodologies (recent regression vs sector-normalized). "
            "Damodaran approach is used for DCF; this is informational only."
        ),
    )


def _check_tier_price_gap(valuation: dict[str, Any], rows: list[dict[str, str]]) -> None:
    """Flag large sensitivity between Tier 1 and Tier 2 implied share prices."""
    tiers = valuation.get("dcf_tiers") or []
    tier1 = next((tier for tier in tiers if tier.get("tier") == 1), None)
    tier2 = next((tier for tier in tiers if tier.get("tier") == 2), None)
    tier1_price = _to_float((tier1 or {}).get("dcf", {}).get("implied_price"))
    tier2_price = _to_float((tier2 or {}).get("dcf", {}).get("implied_price"))
    if tier1_price is None or tier2_price is None or tier1_price == 0:
        return
    gap = abs(tier1_price - tier2_price) / abs(tier1_price)
    if gap <= 0.20:
        return
    currency = valuation.get("currency", "")
    _add_excel_check(
        rows,
        "warning",
        "Margin assumption sensitivity",
        (
            f"Tier 1 implied price ({_format_price(tier1_price, currency)}) differs from Tier 2 (smoothed) "
            f"implied price ({_format_price(tier2_price, currency)}) by {gap:.1%}. Tier 1 uses latest FY actuals "
            "while Tier 2 uses 3-5 year averages. A large gap indicates the valuation is sensitive to recent margin "
            "levels - consider whether the latest margin is sustainable."
        ),
    )


def _check_implied_price_vs_market(valuation: dict[str, Any], rows: list[dict[str, str]]) -> None:
    """Keep the existing implied price vs market diagnostic in the Excel sanity-check table."""
    upside = _to_float((valuation.get("dcf") or {}).get("upside"))
    if upside is None:
        return
    abs_upside = abs(upside)
    if abs_upside < 0.20:
        severity = "info"
        message = "Implied price is within 20% of market price."
    elif abs_upside <= 1.00:
        severity = "warning"
        message = _diagnostic_implied_price_message(upside)
        if abs_upside > 0.60:
            message += " Review the data-driven DCF assumptions before relying on the result."
    else:
        severity = "critical"
        message = (
            "Implied price differs from market price by more than 100%; check ticker, source data, "
            "and assumptions before relying on the report."
        )
    _add_excel_check(rows, severity, "Implied price vs market", message)


def _validation_metric(validation_result: dict[str, Any] | None, metric_name: str) -> dict[str, Any] | None:
    """Return a validation result row by metric name."""
    if not validation_result:
        return None
    for row in validation_result.get("rows", []) or []:
        if row.get("Metric") == metric_name:
            return row
    return None


def _ratio_value(value: Any) -> float:
    """Normalize decimal or percent-like ratio values to decimals."""
    number = float(value)
    return number / 100 if abs(number) > 1 else number


def _to_float(value: Any) -> float | None:
    """Coerce a numeric-like value to float, returning None for missing values."""
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _statutory_tax_rate(country: str) -> float:
    """Return a country statutory tax rate with a conservative default."""
    key = str(country or "").strip().lower()
    return COUNTRY_STATUTORY_TAX_RATES.get(key, 0.25)


def _format_price(value: float, currency: str) -> str:
    """Format an implied share price for sanity-check messages."""
    suffix = f" {currency}" if currency else ""
    return f"{value:.2f}{suffix}"


def _check_business_model_compatibility(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Block operating-company DCF reports for structurally incompatible business models."""
    sector_name = str(valuation.get("damodaran_sector") or "").strip()
    if not sector_name:
        return
    normalized = sector_name.lower()
    if not any(fragment in normalized for fragment in INCOMPATIBLE_BUSINESS_MODEL_SECTOR_FRAGMENTS):
        return
    _add(
        warnings,
        "critical",
        (
            f"DCF model is not appropriate for {sector_name} businesses. Operating-company DCF assumes revenue "
            "from product/service sales with predictable CapEx and working capital, which does not apply to "
            "financial institutions, asset managers, or real estate vehicles. The implied price shown should be "
            "ignored. For these businesses, use sector-specific approaches: residual income or P/B for banks, "
            "dividend discount or P/AFFO for REITs, embedded value for insurance. The 5-tier fallback structure "
            "is not designed for these company types."
        ),
        "Business Model Compatibility",
    )


def _check_default_assumptions(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Flag when Tier 1 substitutes default assumptions because source data is unavailable."""
    tier1 = _tier_by_number(valuation, 1)
    assumptions = (tier1 or {}).get("assumptions") or {}
    defaults_used: list[str] = []
    for label, source_key in (
        ("CapEx", "capex_source"),
        ("working capital", "working_capital_source"),
    ):
        source = assumptions.get(source_key) or valuation.get(source_key)
        if isinstance(source, str) and source.lower().startswith("default"):
            defaults_used.append(f"{label} ({source})")
    if not defaults_used:
        return
    _add(
        warnings,
        "info",
        (
            "Tier 1 used default assumption(s) because underlying data was unavailable: "
            f"{', '.join(defaults_used)}. Common reasons: company reports under industry-specific accounting "
            "(banking, insurance, REITs) where these line items don't apply. Verify that DCF is appropriate "
            "for this business type."
        ),
        "Default assumptions",
    )


def _tier_by_number(valuation: dict[str, Any], tier_number: int) -> dict[str, Any] | None:
    """Return one DCF tier by number from a valuation result."""
    for tier in valuation.get("dcf_tiers") or []:
        if tier.get("tier") == tier_number:
            return tier
    return None


def _check_beta(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Validate beta and D/E ratio."""
    beta = valuation.get("levered_beta")
    de_ratio = valuation.get("de_ratio")
    if beta is not None and (beta < 0 or beta > 3):
        _add(warnings, "warning", "Levered beta is outside the usual 0-3 range.")
    if de_ratio is not None and de_ratio > 5:
        _add(warnings, "warning", "D/E ratio is above 5.0, indicating unusually high leverage.")


def _check_costs(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Validate cost of equity, cost of debt, and WACC ranges."""
    rf = valuation.get("risk_free_rate")
    re = valuation.get("cost_of_equity")
    wacc = valuation.get("wacc")
    rd = valuation.get("cost_of_debt")
    if rf is not None and (rf < -0.01 or rf > 0.15):
        _add(warnings, "critical", "Risk-free rate is outside the required -1%-15% range.")
    if rf is not None and re is not None and re < rf:
        _add(warnings, "critical", "Cost of equity is below the risk-free rate, which is not economically sensible.")
    if re is not None and re > 0.25:
        _add(warnings, "warning", "Cost of equity is above 25%, which is unusually high.")
    if wacc is not None and (wacc < 0.03 or wacc > 0.20):
        _add(warnings, "critical", "WACC is outside the required 3%-20% range.")
    if rd is not None and (rd < 0.01 or rd > 0.15):
        _add(warnings, "critical", "Cost of debt is outside the required 1%-15% range.")
    if wacc is not None and re is not None and wacc > re:
        _add(warnings, "critical", "WACC is above cost of equity; check debt cost, weights, and tax shield assumptions.")


def _check_risk_free_currency_match(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Flag cases where the risk-free rate currency had to fall back away from reporting currency."""
    if not valuation.get("risk_free_currency_mismatch"):
        return
    source_currency = valuation.get("risk_free_currency") or "unknown"
    target_currency = valuation.get("risk_free_target_currency") or valuation.get("currency") or "reported currency"
    source = valuation.get("risk_free_source") or "fallback source"
    _add(
        warnings,
        "info",
        (
            f"Risk-free rate source currency ({source_currency}) does not match reporting currency "
            f"({target_currency}). {source} was used because a {target_currency} risk-free rate could not be loaded. "
            "Review WACC before relying on the valuation."
        ),
        "Risk-free rate currency",
    )


def _check_dcf(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Validate DCF terminal growth and implied price."""
    wacc = valuation.get("wacc")
    terminal_growth = valuation.get("terminal_growth")
    upside = (valuation.get("dcf") or {}).get("upside")
    if wacc is not None and terminal_growth is not None and terminal_growth >= wacc:
        _add(warnings, "critical", "Terminal growth is greater than or equal to WACC.")
    if terminal_growth is not None and terminal_growth > 0.04:
        _add(warnings, "warning", "Terminal growth is above 4%, which may exceed long-term GDP growth.")
    if upside is None:
        return

    abs_upside = abs(upside)
    if abs_upside < 0.20:
        _add(warnings, "info", "Implied price is within 20% of market price.")
    elif abs_upside < 0.40:
        _add(
            warnings,
            "warning",
            _diagnostic_implied_price_message(upside),
        )
    elif abs_upside <= 0.60:
        _add(warnings, "warning", _diagnostic_implied_price_message(upside))
    elif abs_upside <= 1.00:
        _add(
            warnings,
            "warning",
            _diagnostic_implied_price_message(upside)
            + " Review the data-driven DCF assumptions in the Scenario tab before relying on the result.",
        )
    else:
        _add(
            warnings,
            "critical",
            "Implied price differs from market price by more than 100%; check ticker, source data, and assumptions before generating the report.",
        )


def _implied_price_direction_message(upside: float) -> str:
    """Explain DCF implied price direction in plain language."""
    magnitude = abs(upside)
    if upside > 0:
        return (
            f"Implied price suggests UPSIDE of {magnitude:.1%}. DCF model views the stock as undervalued. "
            "Common for value/turnaround cases. Sensitive to growth assumptions."
        )
    return (
        f"Implied price suggests DOWNSIDE of {magnitude:.1%}. DCF model views the stock as overvalued. "
        "Common for quality companies trading at premium. Sensitive to terminal value assumptions."
    )


def _diagnostic_implied_price_message(upside: float) -> str:
    """Explain large DCF gaps as diagnostics rather than a definitive valuation call."""
    magnitude = abs(upside)
    direction = "upside" if upside > 0 else "downside"
    return (
        f"Implied price differs significantly from market price ({magnitude:.1%} {direction}). "
        "Possible explanations: DCF assumptions may not reflect market expectations "
        "(revenue growth, margins, terminal growth); company may trade at a premium/discount that historical financials do not capture; "
        "or the simplified DCF may miss business-specific factors."
    )


def _check_tax(valuation: dict[str, Any], warnings: list[dict[str, str]]) -> None:
    """Validate tax-rate assumption."""
    tax = valuation.get("tax_rate")
    if tax is not None and (tax < 0 or tax > 0.40):
        _add(warnings, "warning", "Tax rate is outside the 0%-40% range; use Damodaran industry benchmark fallback.")
