"""Tests for yfinance-to-Damodaran industry matching."""

import pandas as pd

from utils.damodaran import match_industry


def _industry_table() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "industry": [
                "Advertising",
                "Machinery (Industrial)",
                "Telecom. Equipment",
                "Software (Internet)",
            ],
            "unlevered_beta": [0.9, 0.95, 1.05, 1.2],
        }
    )


def test_kone_maps_to_machinery():
    matched, confidence = match_industry("Specialty Industrial Machinery", _industry_table())

    assert matched == "Machinery (Industrial)"
    assert confidence >= 70


def test_unknown_industry_handled():
    matched, confidence = match_industry("Totally Unknown Moon Business", _industry_table())

    assert isinstance(matched, str)
    assert isinstance(confidence, float)


def test_case_insensitive_matching():
    upper_match, _upper_confidence = match_industry("MACHINERY", _industry_table())
    lower_match, _lower_confidence = match_industry("machinery", _industry_table())

    assert upper_match == lower_match
