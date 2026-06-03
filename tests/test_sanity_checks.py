"""Tests for Excel-only analyst sanity checks."""

import pandas as pd

from utils.sanity_checks import (
    _check_beta,
    _check_business_model_compatibility,
    _check_default_assumptions,
    _check_beta_methodology_gap,
    _check_cost_of_debt_context,
    _check_ebit_margin_outlier,
    _check_effective_tax_context,
    _check_implied_price_vs_market,
    _check_risk_free_currency_match,
    _check_tier_price_gap,
    build_excel_sanity_checks,
    run_sanity_checks,
    runtime_sanity_checks_for_excel,
)


def test_excel_sanity_check_flags_ebit_margin_outlier():
    rows = []
    income = pd.DataFrame({"ebit_margin": [20.0, 20.0, 35.6]})

    _check_ebit_margin_outlier(income, rows)

    assert rows[0]["severity"] == "warning"
    assert rows[0]["category"] == "Margin volatility"
    assert "Latest FY EBIT margin (35.6%)" in rows[0]["message"]
    assert "3-year average" in rows[0]["message"]


def test_excel_sanity_check_flags_cost_of_debt_context():
    rows = []
    validation_result = {
        "rows": [
            {
                "Metric": "Cost of Debt",
                "Calculated": 0.02,
                "Damodaran (industry avg)": 0.06,
            }
        ]
    }

    _check_cost_of_debt_context({}, validation_result, rows)

    assert rows[0]["severity"] == "info"
    assert rows[0]["category"] == "Cost of debt context"
    assert "Company cost of debt (2.00%)" in rows[0]["message"]
    assert "sector average (6.00%)" in rows[0]["message"]
    assert "Below-sector" in rows[0]["message"]


def test_excel_sanity_check_flags_effective_tax_context():
    rows = []

    _check_effective_tax_context(
        {"tax_rate": 0.15},
        {"info": {"country": "United States"}},
        rows,
    )

    assert rows[0]["severity"] == "info"
    assert rows[0]["category"] == "Tax structure"
    assert "Effective tax rate (15.0%)" in rows[0]["message"]
    assert "United States statutory rate (21.0%)" in rows[0]["message"]
    assert "Lower effective rate" in rows[0]["message"]


def test_excel_sanity_check_flags_yfinance_beta_gap():
    rows = []

    _check_beta_methodology_gap({"yfinance_beta": 0.26, "levered_beta": 0.98}, rows)

    assert rows[0]["severity"] == "info"
    assert rows[0]["category"] == "Beta methodology"
    assert "Yahoo Finance beta (0.26)" in rows[0]["message"]
    assert "Damodaran-relevered beta (0.98)" in rows[0]["message"]


def test_excel_sanity_check_flags_tier1_tier2_price_gap():
    rows = []
    valuation = {
        "currency": "USD",
        "dcf_tiers": [
            {"tier": 1, "dcf": {"implied_price": 204.0}},
            {"tier": 2, "dcf": {"implied_price": 144.0}},
        ],
    }

    _check_tier_price_gap(valuation, rows)

    assert rows[0]["severity"] == "warning"
    assert rows[0]["category"] == "Margin assumption sensitivity"
    assert "Tier 1 implied price (204.00 USD)" in rows[0]["message"]
    assert "Tier 2 (smoothed) implied price (144.00 USD)" in rows[0]["message"]
    assert "29.4%" in rows[0]["message"]


def test_excel_sanity_check_keeps_implied_price_vs_market_check():
    rows = []

    _check_implied_price_vs_market({"dcf": {"upside": -0.10}}, rows)

    assert rows == [
        {
            "severity": "info",
            "category": "Implied price vs market",
            "message": "Implied price is within 20% of market price.",
        }
    ]


def test_excel_sanity_checks_returns_pass_row_when_nothing_triggers():
    rows = build_excel_sanity_checks(
        valuation={"tax_rate": 0.21, "yfinance_beta": 1.0, "levered_beta": 1.1},
        income_metrics=pd.DataFrame({"ebit_margin": [20.0, 20.5, 21.0]}),
        validation_result=None,
        data={"info": {"country": "United States"}},
    )

    assert rows == [{"severity": "info", "category": "Overall", "message": "All sanity checks passed."}]


def test_business_model_compatibility_check_fires_for_structurally_incompatible_sectors():
    cases = [
        ("BAC", "Bank (Money Center)"),
        ("JPM", "Bank (Money Center)"),
        ("GS", "Brokerage & Investment Banking"),
        ("O", "R.E.I.T."),
        ("AMT", "R.E.I.T."),
        ("MET", "Insurance (Life)"),
        ("AIG", "Insurance (General)"),
    ]

    for ticker, sector in cases:
        warnings = run_sanity_checks({"ticker": ticker, "damodaran_sector": sector})

        critical = [row for row in warnings if row["severity"] == "critical"]
        assert critical, ticker
        assert critical[0]["category"] == "Business Model Compatibility"
        assert f"DCF model is not appropriate for {sector} businesses" in critical[0]["message"]


def test_business_model_compatibility_check_does_not_fire_for_operating_companies():
    cases = [
        ("JNJ", "Drugs (Pharmaceutical)"),
        ("KO", "Beverage (Soft)"),
        ("XOM", "Oil/Gas (Integrated)"),
    ]

    for ticker, sector in cases:
        warnings = run_sanity_checks({"ticker": ticker, "damodaran_sector": sector, "dcf": {"upside": 0.05}})

        assert not [
            row
            for row in warnings
            if row.get("category") == "Business Model Compatibility" and row["severity"] == "critical"
        ], ticker


def test_default_assumption_check_lists_tier1_missing_data_defaults():
    rows = []
    valuation = {
        "dcf_tiers": [
            {
                "tier": 1,
                "assumptions": {
                    "capex_source": "Default 4% (capital expenditure data not available)",
                    "working_capital_source": "Default 2% (current assets data not available)",
                    "depreciation_source": "Default 3% (depreciation/amortization data not available)",
                },
            }
        ]
    }

    _check_default_assumptions(valuation, rows)

    assert rows[0]["severity"] == "info"
    assert rows[0]["category"] == "Default assumptions"
    assert "CapEx (Default 4%" in rows[0]["message"]
    assert "working capital (Default 2%" in rows[0]["message"]
    assert "D&A (Default 3%" in rows[0]["message"]


def test_check_beta_flags_estimated_unlevered_beta_fallback():
    warnings = []

    _check_beta({"unlevered_beta_estimated": True, "levered_beta": 1.0, "de_ratio": 0.3}, warnings)

    flagged = [warning for warning in warnings if warning.get("category") == "Default assumptions"]
    assert flagged
    assert flagged[0]["severity"] == "warning"
    assert "market-average 1.0" in flagged[0]["message"]


def test_check_beta_does_not_flag_sector_derived_unlevered_beta():
    warnings = []

    _check_beta({"unlevered_beta_estimated": False, "levered_beta": 1.0, "de_ratio": 0.3}, warnings)

    assert warnings == []


def test_risk_free_currency_mismatch_check_flags_usd_fallback():
    rows = []
    valuation = {
        "currency": "CHF",
        "risk_free_currency": "USD",
        "risk_free_target_currency": "CHF",
        "risk_free_source": "Yahoo Finance ^TNX fallback",
        "risk_free_currency_mismatch": True,
    }

    _check_risk_free_currency_match(valuation, rows)

    assert rows == [
        {
            "severity": "info",
            "category": "Risk-free rate currency",
            "message": (
                "Risk-free rate source currency (USD) does not match reporting currency (CHF). "
                "Yahoo Finance ^TNX fallback was used because a CHF risk-free rate could not be loaded. "
                "Review WACC before relying on the valuation."
            ),
        }
    ]


def test_risk_free_currency_mismatch_check_does_not_flag_matching_currency():
    rows = []

    _check_risk_free_currency_match(
        {
            "currency": "EUR",
            "risk_free_currency": "EUR",
            "risk_free_target_currency": "EUR",
            "risk_free_currency_mismatch": False,
        },
        rows,
    )

    assert rows == []


def test_runtime_sanity_checks_for_excel_keeps_business_model_warning_first():
    warnings = []
    _check_business_model_compatibility({"damodaran_sector": "Bank (Money Center)"}, warnings)
    warnings.append({"severity": "warning", "message": "Other warning"})

    rows = runtime_sanity_checks_for_excel(warnings)

    assert rows == [
        {
            "severity": "critical",
            "category": "Business Model Compatibility",
            "message": warnings[0]["message"],
        }
    ]
