"""Sanity checks for valuation outputs."""

from __future__ import annotations

from typing import Any


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
    _check_beta(valuation, warnings)
    _check_costs(valuation, warnings)
    _check_dcf(valuation, warnings)
    _check_tax(valuation, warnings)
    return warnings


def _add(warnings: list[dict[str, str]], severity: str, message: str) -> None:
    """Add one sanity-check warning."""
    warnings.append({"severity": severity, "message": message})


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
    if rf is not None and (rf < 0.005 or rf > 0.15):
        _add(warnings, "critical", "Risk-free rate is outside the required 0.5%-15% range.")
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
