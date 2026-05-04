"""Tests for Damodaran workbook loading and normalization."""

import pandas as pd

from utils.damodaran import load_damodaran_table, normalize_damodaran_beta_table


def _mock_beta_workbook(row_count: int = 95) -> dict[str, pd.DataFrame]:
    """Build a Damodaran-like workbook with title rows and a real header row."""
    industries = ["Machinery (Industrial)", "Telecom. Equipment", "Software (Internet)"]
    industries.extend(f"Industry {index}" for index in range(row_count - len(industries)))
    rows = [
        ["Created by Aswath Damodaran", None, None, None, None, None],
        ["Updated January 2026", None, None, None, None, None],
        ["Industry Name", "Beta", "Unlevered beta corrected for cash", "Debt/Equity", "Effective Tax Rate", "Net Margin"],
    ]
    for index, industry in enumerate(industries):
        rows.append([industry, 1.0 + index * 0.001, 0.85 + index * 0.001, 0.25, 0.22, 0.12])
    return {"Industry Averages": pd.DataFrame(rows)}


def _mock_margin_workbook(row_count: int = 95) -> dict[str, pd.DataFrame]:
    """Build a Damodaran-like margin workbook fixture."""
    industries = ["Machinery (Industrial)", "Telecom. Equipment", "Software (Internet)"]
    industries.extend(f"Industry {index}" for index in range(row_count - len(industries)))
    rows = [
        ["Margin data", None, None, None],
        ["Industry Name", "Gross Margin", "EBITDA Margin", "Net Margin"],
    ]
    for industry in industries:
        rows.append([industry, 0.35, 0.18, 0.12])
    return {"Margins": pd.DataFrame(rows)}


def test_loads_betas_excel(monkeypatch):
    def fake_read_excel(_url, sheet_name=None, header=None):
        return _mock_beta_workbook()

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    frame = load_damodaran_table("mock://betas.xls", parser_version="test-loads-betas")

    assert isinstance(frame, pd.DataFrame)
    assert len(frame) >= 90


def test_loads_margins_excel(monkeypatch):
    def fake_read_excel(_url, sheet_name=None, header=None):
        return _mock_margin_workbook()

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    frame = load_damodaran_table("mock://margin.xls", parser_version="test-loads-margins")

    assert isinstance(frame, pd.DataFrame)
    assert len(frame) >= 90


def test_required_columns_exist(monkeypatch):
    def fake_read_excel(_url, sheet_name=None, header=None):
        return _mock_beta_workbook()

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    frame = load_damodaran_table("mock://required-columns.xls", parser_version="test-required-columns")

    assert "Industry Name" in frame.columns
    assert "Beta" in frame.columns
    assert "Net Margin" in frame.columns
    assert "Unlevered beta corrected for cash" in frame.columns


def test_no_empty_critical_values(monkeypatch):
    def fake_read_excel(_url, sheet_name=None, header=None):
        return _mock_beta_workbook()

    monkeypatch.setattr(pd, "read_excel", fake_read_excel)

    raw = load_damodaran_table("mock://critical-values.xls", parser_version="test-critical-values")
    normalized = normalize_damodaran_beta_table(raw)
    key_row = normalized[normalized["industry"] == "Machinery (Industrial)"].iloc[0]

    assert pd.notna(key_row["unlevered_beta"])
    assert pd.notna(key_row["industry_de_ratio"])
    assert pd.notna(key_row["industry_tax_rate"])
