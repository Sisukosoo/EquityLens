"""Unit tests for valuation formulas."""

import pytest

from utils.valuation import (
    calculate_capital_weights,
    calculate_capm,
    calculate_cost_of_debt,
    calculate_effective_tax_rate,
    calculate_wacc,
    present_value,
    relever_beta,
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
