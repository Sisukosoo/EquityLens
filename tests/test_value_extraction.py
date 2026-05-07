"""Tests for Damodaran value extraction and unit normalization."""

import pandas as pd

from utils.calculations import build_dividend_metrics
from utils.damodaran import _ratio_to_decimal, match_industry, normalize_damodaran_beta_table


def _raw_beta_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Industry Name": ["Machinery (Industrial)", "Advertising"],
            "Unlevered beta corrected for cash": [0.92, 1.1],
            "Debt/Equity": [25.0, 40.0],
            "Effective Tax Rate": [22.0, 18.0],
            "Net Margin": [12.0, 8.0],
        }
    )


def test_beta_within_reasonable_range():
    normalized = normalize_damodaran_beta_table(_raw_beta_table())
    matched, _confidence = match_industry("Specialty Industrial Machinery", normalized)
    beta = normalized.loc[normalized["industry"] == matched, "unlevered_beta"].iloc[0]

    assert 0.5 <= beta <= 2.0


def test_margin_in_percent_not_decimal():
    assert abs(_ratio_to_decimal(12.0) - 0.12) < 0.0001
    assert abs(_ratio_to_decimal(0.12) - 0.12) < 0.0001


def test_dividend_metrics_explain_missing_payout_ratio_and_mark_ytd(monkeypatch):
    class FakeDateTime:
        @classmethod
        def now(cls):
            return type("Date", (), {"year": 2026})()

    import utils.calculations as calculations_module

    monkeypatch.setattr(calculations_module, "datetime", FakeDateTime)
    data = {
        "dividends": pd.Series({2021: 1.0, 2025: 2.0, 2026: 0.5}),
        "info": {"sharesOutstanding": 1_000_000, "currentPrice": 100.0},
    }
    income = pd.DataFrame({"year": [2025], "net_income": [10.0]})

    result = build_dividend_metrics(data, income)

    assert result.loc[result["year"].eq(2021), "payout_ratio"].iloc[0] is None
    assert "matching net income" in result.loc[result["year"].eq(2021), "payout_ratio_note"].iloc[0]
    assert result.loc[result["year"].eq(2025), "payout_ratio"].iloc[0] == 20.0
    assert result.loc[result["year"].eq(2025), "period"].iloc[0] == "FY2025"
    assert result.loc[result["year"].eq(2026), "period"].iloc[0] == "FY2026 YTD"
    assert "year-to-date" in result.loc[result["year"].eq(2026), "payout_ratio_note"].iloc[0]
