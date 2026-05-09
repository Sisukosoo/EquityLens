"""Application configuration, theme, and shared constants."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


APP_TITLE = "EquityLens"
APP_TAGLINE = "Built by Sisu Kosonen | Laskentatoimi & Yritysrahoitus"
DISCLAIMER = "Tämä on opiskelutarkoituksiin tehty työkalu, ei sijoitusneuvonta."
DATA_SOURCES = "Data sources: Yahoo Finance via yfinance. Market and analyst data availability varies by ticker."
TIMEZONE = "Europe/Helsinki"
DAMODARAN_MARGINAL_TAX_RATE_USA = 0.25
DAMODARAN_MARGINAL_TAX_RATE_EUROPE = 0.25

COLORS = {
    "navy": "#1a1a2e",
    "blue": "#16213e",
    "blue_soft": "#22345d",
    "gold": "#f0a500",
    "gold_soft": "#ffd166",
    "white": "#f7f7ff",
    "muted": "#a9b3c9",
    "green": "#2ecc71",
    "red": "#ff5c5c",
    "border": "rgba(255,255,255,0.14)",
    "panel": "rgba(22,33,62,0.78)",
    "panel_deep": "rgba(26,26,46,0.96)",
}

PLOTLY_CONFIG = {
    "displaylogo": False,
    "modeBarButtonsToAdd": ["toImage"],
    "toImageButtonOptions": {
        "format": "png",
        "filename": "financial_analyzer_chart",
        "height": 720,
        "width": 1200,
        "scale": 2,
    },
}


def current_timestamp() -> str:
    """Return the current local timestamp for the UI."""
    return datetime.now(ZoneInfo(TIMEZONE)).strftime("%d.%m.%Y %H:%M")
