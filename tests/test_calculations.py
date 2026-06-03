"""Tests for statement metric calculations."""

import pandas as pd

from utils.calculations import build_balance_sheet_metrics


def _balance_sheet(items: dict) -> pd.DataFrame:
    """Build a one-period raw balance sheet frame indexed by line item."""
    return pd.DataFrame({pd.Timestamp("2024-12-31"): items})


def test_tangible_equity_subtracts_goodwill_and_intangibles():
    frame = build_balance_sheet_metrics(
        _balance_sheet(
            {
                "Total Assets": 1_000e6,
                "Stockholders Equity": 400e6,
                "Goodwill": 120e6,
                "Other Intangible Assets": 30e6,
            }
        )
    )
    row = frame.iloc[-1]
    assert row["total_equity"] == 400.0
    assert row["goodwill_and_intangibles"] == 150.0
    assert row["tangible_equity"] == 250.0  # 400 - 120 - 30


def test_tangible_equity_prefers_combined_line_without_double_counting():
    frame = build_balance_sheet_metrics(
        _balance_sheet(
            {
                "Total Assets": 1_000e6,
                "Stockholders Equity": 400e6,
                "Goodwill And Other Intangible Assets": 150e6,
                # A separate Goodwill line must be ignored when the combined line exists.
                "Goodwill": 120e6,
            }
        )
    )
    assert frame.iloc[-1]["tangible_equity"] == 250.0


def test_tangible_equity_falls_back_to_book_equity_when_no_intangibles():
    frame = build_balance_sheet_metrics(
        _balance_sheet(
            {
                "Total Assets": 1_000e6,
                "Stockholders Equity": 400e6,
            }
        )
    )
    row = frame.iloc[-1]
    assert row["goodwill_and_intangibles"] == 0.0
    assert row["tangible_equity"] == 400.0


def test_tangible_equity_is_none_when_equity_missing():
    frame = build_balance_sheet_metrics(
        _balance_sheet(
            {
                "Total Assets": 1_000e6,
                "Goodwill": 120e6,
            }
        )
    )
    assert frame.iloc[-1]["tangible_equity"] is None
