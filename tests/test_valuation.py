"""Unit tests for valuation formulas."""

from types import SimpleNamespace

import pandas as pd
import pytest
import utils.valuation as valuation_module

from utils.valuation import (
    DCF_MARGIN_URLS,
    MULTIPLE_EV_EBITDA_URLS,
    MULTIPLE_EV_SALES_URLS,
    MULTIPLE_PB_URLS,
    _build_dcf_tier_results,
    _build_multiples_tier,
    _historical_revenue_growth_assumption,
    _historical_working_capital_assumption,
    _lookup_damodaran_sector_metric,
    build_dcf_forecast,
    build_reverse_dcf_analysis,
    calculate_capital_weights,
    calculate_capm,
    calculate_cost_of_debt,
    calculate_effective_tax_rate,
    calculate_wacc,
    present_value,
    relever_beta,
    solve_reverse_dcf_growth,
    terminal_value,
)


def test_capm_basic():
    rf = 0.04
    beta = 1.2
    erp = 0.055
    expected = 0.04 + 1.2 * 0.055
    assert abs(calculate_capm(rf, beta, erp) - expected) < 0.0001


def test_relever_beta():
    unlevered = 0.8
    de_ratio = 0.5
    tax = 0.25
    expected = 0.8 * (1 + (1 - 0.25) * 0.5)
    assert abs(relever_beta(unlevered, de_ratio, tax) - expected) < 0.0001


def test_wacc():
    e_weight = 0.6
    d_weight = 0.4
    re = 0.10
    rd = 0.05
    tax = 0.25
    expected = 0.6 * 0.10 + 0.4 * 0.05 * (1 - 0.25)
    assert abs(calculate_wacc(e_weight, d_weight, re, rd, tax) - expected) < 0.0001


def test_terminal_value():
    fcf = 100
    g = 0.025
    wacc = 0.08
    expected = 100 * (1 + 0.025) / (0.08 - 0.025)
    assert abs(terminal_value(fcf, g, wacc) - expected) < 0.01


def test_present_value():
    assert abs(present_value(100, 0.08, 2) - 85.7339) < 0.01


def test_capital_weights():
    weights = calculate_capital_weights(600, 400)
    assert abs(weights["equity_weight"] - 0.6) < 0.0001
    assert abs(weights["debt_weight"] - 0.4) < 0.0001


def test_cost_of_debt():
    rd, estimated = calculate_cost_of_debt(50, 1000)
    assert abs(rd - 0.05) < 0.0001
    assert estimated is False


def test_cost_of_debt_fallback():
    rd, estimated = calculate_cost_of_debt(None, 1000, fallback=0.045)
    assert rd == 0.045
    assert estimated is True


def test_cost_of_debt_missing_without_fallback_raises():
    with pytest.raises(ValueError):
        calculate_cost_of_debt(None, 1000)


def test_effective_tax_rate():
    tax, estimated = calculate_effective_tax_rate(25, 100)
    assert abs(tax - 0.25) < 0.0001
    assert estimated is False


def test_effective_tax_rate_fallback():
    tax, estimated = calculate_effective_tax_rate(-10, -100, fallback=0.21)
    assert abs(tax - 0.10) < 0.0001
    assert estimated is False


def test_working_capital_assumption_uses_current_assets_history():
    income = pd.DataFrame(
        {
            "year": [2022, 2023, 2024],
            "revenue": [1000.0, 1100.0, 1200.0],
        }
    )
    balance = pd.DataFrame(
        {
            "year": [2022, 2023, 2024],
            "current_assets": [300.0, 330.0, 360.0],
            "current_liabilities": [200.0, 220.0, 240.0],
        }
    )

    value, source = _historical_working_capital_assumption(income, balance)

    assert abs(value - 0.10) < 0.0001
    assert source == "3-year historical average"


def test_working_capital_assumption_marks_default_when_current_assets_missing():
    income = pd.DataFrame({"year": [2024], "revenue": [1200.0]})
    balance = pd.DataFrame({"year": [2024], "current_liabilities": [240.0]})

    value, source = _historical_working_capital_assumption(income, balance)

    assert value == 0.02
    assert source == "Default 2% (current assets data not available)"


@pytest.mark.parametrize(
    ("years", "expected_source"),
    [
        ([2024, 2025], "1-year growth rate (FY2024-FY2025)"),
        ([2023, 2024, 2025], "2-year CAGR (FY2023-FY2025, 2 growth periods)"),
        ([2022, 2023, 2024, 2025], "3-year CAGR (FY2022-FY2025, 3 growth periods)"),
        ([2021, 2022, 2023, 2024, 2025], "4-year CAGR (FY2021-FY2025, 4 growth periods)"),
    ],
)
def test_revenue_growth_source_labels_growth_periods(years, expected_source):
    income = pd.DataFrame(
        {
            "year": years,
            "period": [f"FY{year}" for year in years],
            "revenue": [100.0 + idx * 10.0 for idx, _ in enumerate(years)],
        }
    )

    growth, source = _historical_revenue_growth_assumption(income)

    assert growth is not None
    assert source == expected_source


def test_revenue_growth_source_marks_insufficient_history():
    income = pd.DataFrame({"year": [2025], "period": ["FY2025"], "revenue": [100.0]})

    growth, source = _historical_revenue_growth_assumption(income)

    assert growth is None
    assert source == "Insufficient historical data - using sector benchmark fallback"


def test_dcf_tier_selection_uses_standard_when_sanity_checks_pass(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "_load_dcf_sector_benchmarks",
        lambda _beta_match: {"ebit_margin": 0.12, "ebit_margin_source": "test", "capex_pct_revenue": 0.04, "capex_source": "test"},
    )
    income = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [100.0, 103.0, 106.0, 109.0, 112.0],
            "ebit_margin": [12.0, 12.0, 12.0, 12.0, 12.0],
            "ebitda": [15.0, 15.45, 15.9, 16.35, 16.8],
            "ebit": [12.0, 12.36, 12.72, 13.08, 13.44],
        }
    )
    cash = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "capital_expenditure": [-4.0, -4.1, -4.2, -4.3, -4.4],
        }
    )
    beta_match = SimpleNamespace(row_data={}, matched_industry="Test Industry")

    tiers, selected = _build_dcf_tier_results(
        income_metrics=income,
        cash_flow_metrics=cash,
        latest_revenue=112.0,
        latest_ebit_margin=0.12,
        latest_fcf=8.0,
        wacc=0.08,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=170.0,
        terminal_growth=0.025,
        tax_rate=0.25,
        working_capital_pct_revenue=0.02,
        working_capital_source="3-year historical average",
        latest_ebitda=16.8,
        total_equity=120.0,
        standard_revenue_growth=0.03,
        standard_revenue_growth_source="5-year historical CAGR",
        standard_depreciation_pct_revenue=0.03,
        standard_capex_pct_revenue=0.04,
        beta_match=beta_match,
    )

    assert len(tiers) == 3
    assert selected["tier"] == 1
    assert selected["accepted"] is True
    assert selected["acceptance_reason"]


def test_dcf_tier_selection_falls_back_to_sector_benchmark(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "_load_dcf_sector_benchmarks",
        lambda _beta_match: {
            "ebit_margin": 0.10,
            "ebit_margin_source": "Damodaran sector benchmark: Sector Benchmark",
            "capex_pct_revenue": 0.04,
            "capex_source": "Damodaran sector benchmark: Sector Benchmark",
        },
    )
    income = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [100.0, 100.0, 100.0, 100.0, 100.0],
            "ebit_margin": [2.0, 2.0, 2.0, 2.0, -5.0],
            "ebitda": [5.0, 5.0, 5.0, 5.0, -2.0],
            "ebit": [2.0, 2.0, 2.0, 2.0, -5.0],
        }
    )
    cash = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "capital_expenditure": [-4.0, -4.0, -4.0, -4.0, -4.0],
        }
    )
    beta_match = SimpleNamespace(
        row_data={"EBIT Margin": 10.0, "Capital Expenditures/Sales": 4.0},
        matched_industry="Sector Benchmark",
    )

    tiers, selected = _build_dcf_tier_results(
        income_metrics=income,
        cash_flow_metrics=cash,
        latest_revenue=100.0,
        latest_ebit_margin=-0.05,
        latest_fcf=-3.0,
        wacc=0.08,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=120.0,
        terminal_growth=0.025,
        tax_rate=0.25,
        working_capital_pct_revenue=0.02,
        working_capital_source="3-year historical average",
        latest_ebitda=-2.0,
        total_equity=50.0,
        standard_revenue_growth=0.0,
        standard_revenue_growth_source="5-year historical CAGR",
        standard_depreciation_pct_revenue=0.03,
        standard_capex_pct_revenue=0.04,
        beta_match=beta_match,
    )

    assert tiers[0]["accepted"] is False
    assert tiers[1]["accepted"] is False
    assert selected["tier"] == 3
    assert selected["accepted"] is True
    assert selected["confidence"] == "LOW"


def test_tier3_non_positive_sector_margin_is_skipped(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "_load_dcf_sector_benchmarks",
        lambda _beta_match: {
            "ebit_margin": -0.002,
            "ebit_margin_source": "Damodaran sector benchmark: Electronics (Consumer & Office)",
            "ebit_margin_matched_industry": "Electronics (Consumer & Office)",
            "capex_pct_revenue": 0.04,
            "capex_source": "Damodaran sector benchmark: Electronics (Consumer & Office)",
        },
    )
    monkeypatch.setattr(
        valuation_module,
        "_load_sector_multiples",
        lambda _beta_match: {"ev_ebitda": None, "ev_sales": None, "price_book": None},
    )
    income = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [100.0, 100.0, 100.0, 100.0, 100.0],
            "ebit_margin": [-5.0, -5.0, -5.0, -5.0, -5.0],
            "ebitda": [-2.0, -2.0, -2.0, -2.0, -2.0],
            "ebit": [-5.0, -5.0, -5.0, -5.0, -5.0],
        }
    )
    cash = pd.DataFrame({"year": [2024], "capital_expenditure": [-4.0]})

    tiers, selected = _build_dcf_tier_results(
        income_metrics=income,
        cash_flow_metrics=cash,
        latest_revenue=100.0,
        latest_ebit_margin=-0.05,
        latest_fcf=-3.0,
        wacc=0.08,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=100.0,
        terminal_growth=0.025,
        tax_rate=0.25,
        working_capital_pct_revenue=0.02,
        working_capital_source="3-year historical average",
        latest_ebitda=-2.0,
        total_equity=80.0,
        standard_revenue_growth=0.0,
        standard_revenue_growth_source="5-year historical CAGR",
        standard_depreciation_pct_revenue=0.03,
        standard_capex_pct_revenue=0.04,
        beta_match=SimpleNamespace(row_data={}, matched_industry="Electronics (Consumer & Office)"),
    )

    tier3 = next(tier for tier in tiers if tier["tier"] == 3)
    assert tier3["status"] == "SKIPPED"
    assert tier3["rejection_reason"] == "sector benchmark not applicable"
    assert "non-positive" in tier3["skip_message"]
    assert tier3["dcf"] == {}
    assert selected["tier"] == 5


def test_dcf_pipeline_uses_multiples_when_all_dcf_tiers_fail(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "_load_dcf_sector_benchmarks",
        lambda _beta_match: {"ebit_margin": -0.05, "ebit_margin_source": "test", "capex_pct_revenue": 0.04, "capex_source": "test"},
    )
    monkeypatch.setattr(
        valuation_module,
        "_load_sector_multiples",
        lambda _beta_match: {
            "ev_ebitda": 5.0,
            "ev_ebitda_source": "Damodaran sector benchmark: Test",
            "ev_sales": 1.0,
            "ev_sales_source": "Damodaran sector benchmark: Test",
            "price_book": 1.2,
            "price_book_source": "Damodaran sector benchmark: Test",
        },
    )
    income = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [100.0, 100.0, 100.0, 100.0, 100.0],
            "ebit_margin": [-5.0, -5.0, -5.0, -5.0, -5.0],
            "ebitda": [-5.0, -5.0, -5.0, -5.0, -5.0],
            "ebit": [-5.0, -5.0, -5.0, -5.0, -5.0],
        }
    )
    cash = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "capital_expenditure": [-4.0, -4.0, -4.0, -4.0, -4.0],
        }
    )
    beta_match = SimpleNamespace(row_data={}, matched_industry="Test")

    tiers, selected = _build_dcf_tier_results(
        income_metrics=income,
        cash_flow_metrics=cash,
        latest_revenue=100.0,
        latest_ebit_margin=-0.05,
        latest_fcf=-3.0,
        wacc=0.08,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=100.0,
        terminal_growth=0.025,
        tax_rate=0.25,
        working_capital_pct_revenue=0.02,
        working_capital_source="3-year historical average",
        latest_ebitda=10.0,
        total_equity=80.0,
        standard_revenue_growth=0.0,
        standard_revenue_growth_source="5-year historical CAGR",
        standard_depreciation_pct_revenue=0.03,
        standard_capex_pct_revenue=0.04,
        beta_match=beta_match,
    )

    assert [tier["tier"] for tier in tiers] == [1, 2, 3, 4, 5]
    assert selected["tier"] == 4
    assert selected["accepted"] is True
    assert abs(selected["dcf"]["implied_price"] - 96.0) < 0.0001
    assert [row["method"] for row in selected["multiples"]] == ["EV/EBITDA", "EV/Sales", "P/Book"]
    assert selected["detail_status"] == "Full multiples set (3/3 available)"


def test_european_tier4_multiples_use_correct_damodaran_urls_and_parse(monkeypatch):
    import utils.damodaran as damodaran_module

    calls = []

    def fake_load_damodaran_table(url):
        calls.append(url)
        if url.endswith("vebitEurope.xls"):
            return pd.DataFrame(
                {
                    "Industry Name": ["Oil/Gas (Integrated)"],
                    "EV/EBITDAR&D": [99.0],
                    "EV/EBITDA": [5.5],
                }
            )
        if url.endswith("psEurope.xls"):
            return pd.DataFrame(
                {
                    "Industry Name": ["Oil/Gas (Integrated)"],
                    "Price/Sales": [1.2],
                    "EV/Sales": [0.9],
                }
            )
        if url.endswith("pbvEurope.xls"):
            return pd.DataFrame(
                {
                    "Industry Name": ["Oil/Gas (Integrated)"],
                    "PBV": [1.3],
                }
            )
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(damodaran_module, "load_damodaran_table", fake_load_damodaran_table)

    tier = _build_multiples_tier(
        beta_match=SimpleNamespace(
            row_data={},
            source_region="europe",
            matched_industry="Oil/Gas (Integrated)",
            company_industry="Oil/Gas (Integrated)",
        ),
        latest_revenue=100.0,
        latest_ebitda=10.0,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=100.0,
        total_equity=80.0,
    )

    assert calls == [
        MULTIPLE_EV_EBITDA_URLS["europe"],
        MULTIPLE_EV_SALES_URLS["europe"],
        MULTIPLE_PB_URLS["europe"],
    ]
    assert [row["status"] for row in tier["multiples"]] == ["AVAILABLE", "AVAILABLE", "AVAILABLE"]
    assert [row["source_file"] for row in tier["multiples"]] == ["vebitEurope.xls", "psEurope.xls", "pbvEurope.xls"]
    assert [row["implied_price"] for row in tier["multiples"]] == [55.0, 90.0, 104.0]
    assert tier["detail_status"] == "Full multiples set (3/3 available)"
    assert tier["dcf"]["implied_price"] == 90.0


def test_multiples_tier_allows_limited_one_of_three_available(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "_load_sector_multiples",
        lambda _beta_match: {
            "ev_ebitda": 5.0,
            "ev_ebitda_source": "Damodaran sector benchmark: Test",
            "ev_ebitda_source_file": "vebitEurope.xls",
            "ev_sales": None,
            "ev_sales_error": "load failed for psEurope.xls: test",
            "price_book": None,
            "price_book_error": "load failed for pbvEurope.xls: test",
        },
    )

    tier = _build_multiples_tier(
        beta_match=SimpleNamespace(row_data={}, matched_industry="Test"),
        latest_revenue=100.0,
        latest_ebitda=10.0,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=60.0,
        total_equity=80.0,
    )

    assert tier["accepted"] is True
    assert tier["available_multiples"] == 1
    assert tier["detail_status"] == "Limited multiples (only 1/3 available)"
    assert abs(tier["dcf"]["implied_price"] - 50.0) < 0.0001
    assert [row["status"] for row in tier["multiples"]] == ["AVAILABLE", "UNAVAILABLE", "UNAVAILABLE"]


def test_dcf_pipeline_uses_tangible_book_when_multiples_fail(monkeypatch):
    monkeypatch.setattr(
        valuation_module,
        "_load_dcf_sector_benchmarks",
        lambda _beta_match: {"ebit_margin": -0.05, "ebit_margin_source": "test", "capex_pct_revenue": 0.04, "capex_source": "test"},
    )
    monkeypatch.setattr(
        valuation_module,
        "_load_sector_multiples",
        lambda _beta_match: {"ev_ebitda": None, "ev_sales": None, "price_book": None},
    )
    income = pd.DataFrame(
        {
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [100.0, 100.0, 100.0, 100.0, 100.0],
            "ebit_margin": [-5.0, -5.0, -5.0, -5.0, -5.0],
            "ebitda": [-2.0, -2.0, -2.0, -2.0, -2.0],
            "ebit": [-5.0, -5.0, -5.0, -5.0, -5.0],
        }
    )
    cash = pd.DataFrame({"year": [2024], "capital_expenditure": [-4.0]})
    beta_match = SimpleNamespace(row_data={}, matched_industry="Test")

    tiers, selected = _build_dcf_tier_results(
        income_metrics=income,
        cash_flow_metrics=cash,
        latest_revenue=100.0,
        latest_ebit_margin=-0.05,
        latest_fcf=-3.0,
        wacc=0.08,
        net_debt=0.0,
        shares_outstanding=1_000_000.0,
        current_price=100.0,
        terminal_growth=0.025,
        tax_rate=0.25,
        working_capital_pct_revenue=0.02,
        working_capital_source="3-year historical average",
        latest_ebitda=-2.0,
        total_equity=80.0,
        standard_revenue_growth=0.0,
        standard_revenue_growth_source="5-year historical CAGR",
        standard_depreciation_pct_revenue=0.03,
        standard_capex_pct_revenue=0.04,
        beta_match=beta_match,
    )

    assert [tier["tier"] for tier in tiers] == [1, 2, 3, 4, 5]
    assert tiers[3]["accepted"] is False
    assert selected["tier"] == 5
    assert selected["confidence"] == "VERY LOW"
    assert abs(selected["dcf"]["implied_price"] - 80.0) < 0.0001


def test_damodaran_sector_metric_lookup_uses_margin_dataset(monkeypatch):
    import utils.damodaran as damodaran_module

    frame = pd.DataFrame(
        {
            "Industry Name": ["Oil/Gas Integrated", "Software"],
            "Operating Margin": [8.7, 20.0],
        }
    )
    monkeypatch.setattr(damodaran_module, "load_damodaran_table", lambda _url: frame)
    beta_match = SimpleNamespace(
        source_region="europe",
        matched_industry="Oil/Gas Integrated",
        company_industry="Oil/Gas Integrated",
    )

    result = _lookup_damodaran_sector_metric(
        beta_match,
        DCF_MARGIN_URLS,
        (("operating", "margin"), ("pre", "tax", "operating", "margin")),
    )

    assert abs(result["value"] - 0.087) < 0.0001
    assert result["source"] == "Damodaran sector benchmark: Oil/Gas Integrated"
    assert result["source_file"] == "marginEurope.xls"


def test_reverse_dcf_recovers_original_growth_rate():
    target = build_dcf_forecast(
        latest_revenue=100.0,
        latest_ebit_margin=0.20,
        latest_fcf=12.0,
        wacc=0.08,
        net_debt=10.0,
        shares_outstanding=1_000_000.0,
        current_price=1.0,
        revenue_growth=0.08,
        terminal_growth=0.025,
        tax_rate=0.25,
        capex_pct_revenue=0.04,
        depreciation_pct_revenue=0.03,
        working_capital_pct_revenue=0.02,
    )

    result = solve_reverse_dcf_growth(
        latest_revenue=100.0,
        latest_ebit_margin=0.20,
        latest_fcf=12.0,
        wacc=0.08,
        net_debt=10.0,
        shares_outstanding=1_000_000.0,
        current_price=target["implied_price"],
        terminal_growth=0.025,
        tax_rate=0.25,
        capex_pct_revenue=0.04,
        depreciation_pct_revenue=0.03,
        working_capital_pct_revenue=0.02,
    )

    assert result["status"] == "OK"
    assert abs(result["implied_growth"] - 0.08) < 0.0001


def test_reverse_dcf_handles_unreachable_market_price():
    result = solve_reverse_dcf_growth(
        latest_revenue=100.0,
        latest_ebit_margin=0.20,
        latest_fcf=12.0,
        wacc=0.08,
        net_debt=10.0,
        shares_outstanding=1_000_000.0,
        current_price=10_000.0,
        terminal_growth=0.025,
        tax_rate=0.25,
        capex_pct_revenue=0.04,
        depreciation_pct_revenue=0.03,
        working_capital_pct_revenue=0.02,
    )

    assert result["implied_growth"] is None
    assert result["status"] == "UNREACHABLE"
    assert "beyond 50%" in result["message"]


def test_reverse_dcf_marks_missing_analyst_consensus_as_na():
    tier1 = {
        "assumptions": {
            "revenue_growth": 0.03,
            "revenue_growth_source": "5-year historical CAGR",
            "ebit_margin": 0.20,
            "capex_pct_revenue": 0.04,
            "depreciation_pct_revenue": 0.03,
            "working_capital_pct_revenue": 0.02,
        }
    }

    result = build_reverse_dcf_analysis(
        info={},
        tier1=tier1,
        latest_revenue=100.0,
        latest_fcf=12.0,
        wacc=0.08,
        net_debt=10.0,
        shares_outstanding=1_000_000.0,
        current_price=200.0,
        terminal_growth=0.025,
        tax_rate=0.25,
    )

    assert result["analyst_consensus_growth"] is None
    assert result["analyst_consensus_source"] == "N/A - yfinance revenueGrowth/earningsGrowth unavailable"
