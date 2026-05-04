"""Tests for Damodaran value extraction and unit normalization."""

import pandas as pd

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
