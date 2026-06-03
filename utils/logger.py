"""Lightweight file logging for valuation and validation workflows."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


LOG_DIR = Path(__file__).resolve().parents[1] / "logs"


def log_event(message: str, category: str = "valuation") -> Path:
    """
    Append one valuation workflow event to a per-day, per-category log file.

    Formula: not applicable.
    Source: internal audit trail.
    Example: log_event("WACC validation warning", "validation").
    Required inputs: message string; optional category.
    Limitation: local file logging only, no remote telemetry.

    Appends to logs/<category>_<YYYYMMDD>.log. A previous version wrote one file
    per second and overwrote events that shared a timestamp; appending keeps the
    full trail and avoids spawning a file per call.
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.now().strftime("%Y%m%d")
    path = LOG_DIR / f"{category}_{day}.log"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat()} | {message}\n")
    return path


def append_log(path: Path, message: str) -> None:
    """
    Append one line to an existing validation log.

    Formula: not applicable.
    Source: internal audit trail.
    Example: append_log(path, "CAPM OK").
    Required inputs: log path and message.
    Limitation: assumes the path is writable inside the project.
    """
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{datetime.now().isoformat()} | {message}\n")
