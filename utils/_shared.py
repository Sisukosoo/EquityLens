"""Shared low-level helpers used across the utils modules.

These were previously duplicated (with small drifting variations) in valuation,
damodaran, validation, and sanity_checks. Keeping one implementation here avoids
fixing a bug in one copy and missing the others.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import pandas as pd


def to_float(value: Any) -> float | None:
    """Convert a pandas/numeric scalar to float, returning None for missing or non-numeric values."""
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def normalize_label(value: Any) -> str:
    """Lower-case a label and drop every non-alphanumeric character for loose matching."""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


def source_filename(url: str) -> str:
    """Return the filename portion of a source URL."""
    return urlparse(str(url)).path.rsplit("/", 1)[-1] or str(url)


def make_unique_labels(values: list[Any]) -> list[str]:
    """Build unique, cleaned labels from a raw header row (blank -> unnamed_N, duplicates suffixed)."""
    labels: list[str] = []
    counts: dict[str, int] = {}
    for index, value in enumerate(values):
        base = f"unnamed_{index + 1}" if pd.isna(value) or str(value).strip() == "" else str(value).strip()
        count = counts.get(base, 0)
        counts[base] = count + 1
        labels.append(base if count == 0 else f"{base}_{count + 1}")
    return labels
