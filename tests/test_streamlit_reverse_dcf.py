"""Tests for Streamlit Reverse DCF display-state handling."""

from app import reverse_dcf_display_model


def test_reverse_dcf_display_model_hides_when_valuation_not_computed():
    assert reverse_dcf_display_model(None) == {"case": "hidden"}
    assert reverse_dcf_display_model({}) == {"case": "hidden"}


def test_reverse_dcf_display_model_renders_success_case_cards():
    display = reverse_dcf_display_model(
        {
            "reverse_dcf": {
                "implied_growth": 0.074,
                "tier1_growth": 0.056,
                "analyst_consensus_growth": 0.099,
                "interpretation": "Market pricing is consistent with model assumptions.",
            }
        }
    )

    assert display["case"] == "success"
    assert display["cards"] == [
        ("Market implied growth", "7.4%"),
        ("Model assumed growth", "5.6%"),
        ("Yahoo revenue growth estimate", "9.9%"),
    ]
    assert display["interpretation"] == "Market pricing is consistent with model assumptions."


def test_reverse_dcf_display_model_renders_neste_failure_case():
    message = (
        "Reverse DCF could not solve. Current Tier 1 EBIT margin (1.8%) is significantly below "
        "the 5-year average (4.6%), suggesting the market is pricing margin recovery rather than revenue growth. "
        "Standard reverse DCF holds margins constant and cannot capture this scenario."
    )

    display = reverse_dcf_display_model(
        {
            "reverse_dcf": {
                "implied_growth": None,
                "tier1_growth": -0.0956,
                "analyst_consensus_growth": 0.029,
                "interpretation": message,
            }
        }
    )

    assert display["case"] == "failure"
    assert display["body"] == message
    assert display["meta"] == "Tier 1 assumed growth: -9.6% | Yahoo revenue growth estimate: 2.9%"
