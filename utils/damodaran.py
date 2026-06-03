"""Damodaran industry data loading, matching, and beta re-levering."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse
from typing import Any

import pandas as pd

try:
    from rapidfuzz import fuzz, process
except ImportError:  # pragma: no cover - runtime fallback if dependency is missing
    fuzz = None
    process = None

try:
    import streamlit as st
except ImportError:  # pragma: no cover - allows tests without Streamlit
    st = None

from utils.logger import log_event
from utils.valuation import relever_beta


BETA_URLS = {
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betaEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betas.xls",
    "global": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betaGlobal.xls",
    "emerging": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/betaemerg.xls",
}

EUROPE_SUFFIXES = (".HE", ".ST", ".CO", ".OL", ".DE", ".PA", ".AS", ".MI")
DAMODARAN_UPDATED = "January 2026"
PARSER_VERSION = "damodaran-parser-v3"
INDUSTRY_WHITELIST = {
    "communication equipment": "Telecom. Equipment",
    "wireless communications": "Telecom (Wireless)",
    "internet content": "Software (Internet)",
    "internet content & information": "Software (Internet)",
    "specialty industrial machinery": ("Machinery (Industrial)", "Machinery"),
    "industrial machinery": ("Machinery (Industrial)", "Machinery"),
    "software application": "Software (System & Application)",
    "software infrastructure": "Software (System & Application)",
    "consumer electronics": "Electronics (Consumer & Office)",
    "semiconductors": "Semiconductor",
    "drug manufacturers - general": "Drugs (Pharmaceutical)",
    "drug manufacturers - specialty & generic": "Drugs (Pharmaceutical)",
    "banks - diversified": "Bank (Money Center)",
}


@dataclass
class DamodaranMatch:
    """Matched Damodaran industry row."""

    source_url: str
    source_region: str
    source_updated: str
    company_industry: str
    matched_industry: str
    confidence: float
    unlevered_beta: float | None
    industry_de_ratio: float | None
    industry_tax_rate: float | None
    industry_cost_of_debt: float | None
    row_data: dict[str, Any]
    source_filename: str = ""
    loaded_at: str = ""
    load_success: bool = True
    load_warnings: list[str] = field(default_factory=list)
    damodaran_row_count: int = 0
    source_row: int | None = None
    matching_method: str = "unknown"
    top_matches: list[dict[str, Any]] = field(default_factory=list)


def _cache_data(ttl: int):
    """
    Apply Streamlit caching when Streamlit is available.

    Formula: not applicable.
    Source: Streamlit cache_data behavior.
    Example: @_cache_data(ttl=86400).
    Required inputs: TTL seconds.
    Limitation: falls back to no caching in non-Streamlit contexts.
    """
    if st is None:
        return lambda func: func
    return st.cache_data(ttl=ttl, show_spinner=False)


def select_beta_source(ticker: str) -> tuple[str, str]:
    """
    Select the Damodaran beta dataset based on ticker suffix.

    Formula: suffix mapping from user requirements.
    Source: Damodaran NYU Stern datasets supplied in the prompt.
    Example: KNEBV.HE -> betaEurope.xls, AAPL -> betas.xls.
    Required inputs: ticker string.
    Limitation: exchange suffix mapping is simplified; unknown suffixes use global data.
    """
    normalized = ticker.upper().strip()
    if normalized.endswith(EUROPE_SUFFIXES):
        return "europe", BETA_URLS["europe"]
    if "." not in normalized:
        return "us", BETA_URLS["us"]
    return "global", BETA_URLS["global"]


def _source_filename(url: str) -> str:
    """Return the workbook filename from a Damodaran source URL."""
    return urlparse(url).path.rsplit("/", 1)[-1] or url


def _match_processor(value: Any) -> str:
    """Normalize fuzzy-match inputs without changing displayed choices."""
    return str(value).strip().lower()


@_cache_data(ttl=24 * 60 * 60)
def load_damodaran_table(url: str, parser_version: str = PARSER_VERSION) -> pd.DataFrame:
    """
    Load a Damodaran Excel dataset from NYU Stern.

    Formula: not applicable.
    Source: Aswath Damodaran, NYU Stern public datasets.
    Example: load_damodaran_table(betaEurope.xls).
    Required inputs: URL to a Damodaran .xls file. parser_version busts stale Streamlit cache.
    Limitation: depends on NYU Stern availability and xlrd for legacy .xls parsing.
    """
    try:
        workbook = pd.read_excel(url, sheet_name=None, header=None)
    except Exception as exc:
        log_event(f"Damodaran URL failed: {url} | {exc}", "damodaran_error")
        raise RuntimeError(f"Could not load Damodaran dataset: {url}") from exc

    raw = _select_best_sheet(workbook)
    header_row = _find_header_row(raw)
    headers = _make_unique_columns(raw.iloc[header_row].tolist())
    frame = raw.iloc[header_row + 1 :].copy()
    frame.columns = headers
    frame = frame.dropna(how="all").reset_index(drop=True)
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _select_best_sheet(workbook: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Select the workbook sheet most likely to contain Damodaran industry data.

    Formula: highest header-row score across sheets.
    Source: Damodaran workbook layouts can include title/notes sheets.
    Example: picks the sheet containing Industry Name and Unlevered beta.
    Required inputs: dict of sheet name to raw DataFrame.
    Limitation: heuristic, but avoids assuming the first sheet is always the data sheet.
    """
    best_sheet = None
    best_score = -1
    for raw in workbook.values():
        _row, score = _find_header_row_with_score(raw)
        if score > best_score:
            best_score = score
            best_sheet = raw
    if best_sheet is None:
        raise RuntimeError("No readable sheet was found in the Damodaran workbook.")
    return best_sheet


def _find_header_row(raw: pd.DataFrame) -> int:
    """
    Find the likely header row in Damodaran's workbook.

    Formula: row scoring based on keyword presence.
    Source: Damodaran workbook layout conventions.
    Example: a row containing 'Industry Name' and 'Unlevered beta' receives high score.
    Required inputs: raw headerless DataFrame.
    Limitation: heuristic, but robust to blank title rows.
    """
    best_row, _score = _find_header_row_with_score(raw)
    return best_row


def _find_header_row_with_score(raw: pd.DataFrame) -> tuple[int, int]:
    """
    Find the likely header row and return its score.

    Formula: row scoring based on industry and beta/cost keyword co-occurrence.
    Source: Damodaran workbook layout conventions.
    Example: 'Industry Name' + 'Unlevered beta' scores higher than title rows.
    Required inputs: raw headerless DataFrame.
    Limitation: heuristic for changing public spreadsheet layouts.
    """
    best_row = 0
    best_score = -1
    keywords = ("industry", "industry name", "beta", "unlevered", "debt", "equity", "tax", "wacc", "cost")
    for idx, row in raw.head(30).iterrows():
        values = [str(value).strip().lower() for value in row.dropna().tolist()]
        text = " ".join(values)
        normalized_values = {_norm(value) for value in values}
        has_industry = "industry" in text
        has_industry_name = "industryname" in normalized_values or any(value.startswith("industry") for value in normalized_values)
        has_beta_or_cost = any(keyword in text for keyword in ("beta", "cost of capital", "cost of equity", "wacc"))
        score = sum(keyword in text for keyword in keywords)
        if has_industry_name:
            score += 20
        if has_industry and has_beta_or_cost:
            score += 10
        if score > best_score:
            best_score = score
            best_row = idx
    return int(best_row), int(best_score)


def _make_unique_columns(values: list[Any]) -> list[str]:
    """
    Build unique cleaned DataFrame column names from a raw Damodaran header row.

    Formula: not applicable.
    Source: internal Excel parsing helper.
    Example: blank headers become 'unnamed_1', duplicate headers get suffixes.
    Required inputs: raw header row values.
    Limitation: keeps only one header row; multi-row labels are not combined.
    """
    columns = []
    counts: dict[str, int] = {}
    for index, value in enumerate(values):
        if pd.isna(value) or str(value).strip() == "":
            base = f"unnamed_{index + 1}"
        else:
            base = str(value).strip()
        count = counts.get(base, 0)
        counts[base] = count + 1
        columns.append(base if count == 0 else f"{base}_{count + 1}")
    return columns


def _norm(text: str) -> str:
    """
    Normalize column names for fuzzy lookup.

    Formula: lower-case and remove non-alphanumeric characters.
    Source: internal normalization.
    Example: 'Unlevered beta corrected for cash' -> 'unleveredbetacorrectedforcash'.
    Required inputs: text.
    Limitation: may collapse distinct labels with similar names.
    """
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def _find_column(frame: pd.DataFrame, candidates: tuple[str, ...]) -> str | None:
    """
    Find a Damodaran column by normalized candidate fragments.

    Formula: first normalized candidate substring match.
    Source: internal column matching.
    Example: candidates ('unleveredbeta',) matches 'Unlevered beta'.
    Required inputs: DataFrame and candidate fragments.
    Limitation: returns first match, not necessarily semantically perfect.
    """
    normalized = {_norm(column): column for column in frame.columns}
    for fragment in candidates:
        normalized_fragment = _norm(fragment)
        for key, column in normalized.items():
            if normalized_fragment in key:
                return column
    return None


def normalize_damodaran_beta_table(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize Damodaran beta data into stable columns.

    Formula: column mapping only; no financial formula.
    Source: Damodaran beta datasets.
    Example: creates industry, unlevered_beta, industry_de_ratio, industry_tax_rate.
    Required inputs: raw Damodaran DataFrame.
    Limitation: unusual workbook label changes can require new candidate fragments.
    """
    industry_col = _find_column(frame, ("industry name", "industry group", "industry"))
    beta_col = _find_column(frame, ("unlevered beta corrected for cash", "unlevered beta", "asset beta"))
    de_col = _find_column(frame, ("debt/equity", "debt to equity", "d/e", "de ratio"))
    tax_col = _find_column(frame, ("taxrate", "effectivetaxrate"))
    cost_of_debt_col = _find_column(frame, ("cost of debt", "pre-tax cost of debt", "pretax cost of debt"))
    if industry_col is None:
        industry_col = _fallback_industry_column(frame)
    if industry_col is None:
        preview = ", ".join(str(column) for column in list(frame.columns)[:12])
        raise RuntimeError(f"Damodaran industry column was not found. Parsed columns: {preview}")

    normalized = pd.DataFrame()
    normalized["industry"] = frame[industry_col].astype(str).str.strip()
    normalized = normalized[~normalized["industry"].str.lower().isin({"nan", "industry", "industry name"})]
    normalized["unlevered_beta"] = pd.to_numeric(frame[beta_col], errors="coerce") if beta_col else pd.NA
    normalized["industry_de_ratio"] = pd.to_numeric(frame[de_col], errors="coerce") if de_col else pd.NA
    normalized["industry_tax_rate"] = pd.to_numeric(frame[tax_col], errors="coerce") if tax_col else pd.NA
    normalized["industry_cost_of_debt"] = pd.to_numeric(frame[cost_of_debt_col], errors="coerce") if cost_of_debt_col else pd.NA
    normalized["raw_index"] = frame.index
    normalized = normalized[normalized["industry"].str.len() > 0]
    normalized = normalized.dropna(subset=["unlevered_beta"], how="all")
    return normalized.reset_index(drop=True)


def _fallback_industry_column(frame: pd.DataFrame) -> str | None:
    """
    Infer an industry column when the header label is missing or malformed.

    Formula: choose the text column with the most non-empty non-numeric values.
    Source: internal parser fallback for Damodaran workbook layout variations.
    Example: first column containing 'Advertising', 'Aerospace/Defense', etc. is selected.
    Required inputs: parsed DataFrame.
    Limitation: only used when explicit industry labels are missing.
    """
    best_column = None
    best_score = 0
    for column in frame.columns:
        values = frame[column].dropna().astype(str).str.strip()
        non_numeric = 0
        for value in values.head(80):
            try:
                float(value)
            except ValueError:
                if len(value) > 2 and value.lower() not in {"nan", "none"}:
                    non_numeric += 1
        if non_numeric > best_score:
            best_score = non_numeric
            best_column = column
    return best_column if best_score >= 5 else None


def match_industry(company_industry: str, damodaran_frame: pd.DataFrame) -> tuple[str, float]:
    """
    Fuzzy-match a yfinance industry to Damodaran industry names.

    Formula: token-set fuzzy score.
    Source: rapidfuzz token_set_ratio.
    Example: 'Specialty Industrial Machinery' -> closest Damodaran industry.
    Required inputs: company industry string and normalized Damodaran table.
    Limitation: if score < 70%, user approval is required in the Streamlit UI.
    """
    details = match_industry_details(company_industry, damodaran_frame)
    return details["matched_industry"], details["confidence"]


def match_industry_details(company_industry: str, damodaran_frame: pd.DataFrame) -> dict[str, Any]:
    """
    Return full debug details for the yfinance-to-Damodaran industry match.

    Formula: curated mapping first, then rapidfuzz token_set_ratio.
    Source: yfinance industry label and Damodaran industry list.
    Example: Communication Equipment -> Telecom. Equipment via manual mapping.
    Required inputs: company industry string and normalized Damodaran table.
    Limitation: low confidence still requires user confirmation in the UI.
    """
    choices = damodaran_frame["industry"].dropna().astype(str).tolist()
    details = {
        "matched_industry": "",
        "confidence": 0.0,
        "matching_method": "unavailable",
        "top_matches": [],
    }
    if not company_industry or not choices:
        return details

    details["top_matches"] = _top_matches(company_industry, choices)

    whitelist_match = _whitelist_industry_match(company_industry, choices)
    if whitelist_match:
        details.update(
            {
                "matched_industry": whitelist_match[0],
                "confidence": whitelist_match[1],
                "matching_method": "manual mapping",
            }
        )
        return details

    if process is not None and fuzz is not None:
        result = process.extractOne(
            company_industry,
            choices,
            scorer=fuzz.token_set_ratio,
            processor=_match_processor,
        )
        if result is None:
            return details
        details.update(
            {
                "matched_industry": str(result[0]),
                "confidence": float(result[1]),
                "matching_method": "fuzzy token_set_ratio",
            }
        )
        return details

    # Minimal fallback without rapidfuzz.
    import difflib

    match = difflib.get_close_matches(company_industry, choices, n=1)
    if not match:
        return details
    score = difflib.SequenceMatcher(None, company_industry.lower(), match[0].lower()).ratio() * 100
    details.update(
        {
            "matched_industry": match[0],
            "confidence": score,
            "matching_method": "difflib fallback",
        }
    )
    return details


def _top_matches(company_industry: str, choices: list[str]) -> list[dict[str, Any]]:
    """Return top industry match candidates for debug display."""
    if process is not None and fuzz is not None:
        return [
            {"industry": str(match), "score": float(score)}
            for match, score, _index in process.extract(
                company_industry,
                choices,
                scorer=fuzz.token_set_ratio,
                processor=_match_processor,
                limit=5,
            )
        ]

    import difflib

    scored = [
        {
            "industry": choice,
            "score": difflib.SequenceMatcher(None, company_industry.lower(), choice.lower()).ratio() * 100,
        }
        for choice in choices
    ]
    return sorted(scored, key=lambda item: item["score"], reverse=True)[:5]


def _whitelist_industry_match(company_industry: str, choices: list[str]) -> tuple[str, float] | None:
    """
    Return a curated Damodaran industry for known yfinance industry labels.

    Formula: normalized exact lookup from yfinance label to Damodaran label.
    Source: manual mapping for common industries where fuzzy matching is ambiguous.
    Example: Communication Equipment -> Telecom. Equipment.
    Required inputs: company industry and valid Damodaran choices.
    Limitation: only covers known high-value mappings.
    """
    normalized_industry = str(company_industry).strip().lower()
    targets = INDUSTRY_WHITELIST.get(normalized_industry)
    if not targets:
        return None
    if isinstance(targets, str):
        targets = (targets,)
    normalized_choices = {choice.strip().lower(): choice for choice in choices}
    for target in targets:
        matched_choice = normalized_choices.get(target.lower())
        if matched_choice:
            return matched_choice, 95.0
    return None


def build_beta_match(data: dict, selected_industry: str | None = None) -> tuple[DamodaranMatch, pd.DataFrame]:
    """
    Build a matched beta record for the current ticker.

    Formula: match industry, then retrieve Damodaran asset beta and benchmark fields.
    Source: yfinance industry + Damodaran beta dataset.
    Example: KNEBV.HE loads betaEurope.xls and matches yfinance industry.
    Required inputs: fetched company data; optional user-selected Damodaran industry.
    Limitation: low-confidence automatic matches must be user-confirmed before Excel generation.
    """
    ticker = data["ticker"]
    region, url = select_beta_source(ticker)
    raw = load_damodaran_table(url)
    table = normalize_damodaran_beta_table(raw)
    info = data.get("info", {})
    company_industry = info.get("industry") or info.get("sector") or ""

    match_details = match_industry_details(company_industry, table)
    matched_industry = match_details["matched_industry"]
    confidence = match_details["confidence"]
    matching_method = match_details["matching_method"]
    if selected_industry:
        matched_industry = selected_industry
        confidence = 100.0
        matching_method = "user selected"

    row = table[table["industry"] == matched_industry]
    if row.empty:
        raise RuntimeError("Selected Damodaran industry was not found in the dataset.")
    row_data = row.iloc[0].to_dict()
    load_warnings = []
    if row_data.get("unlevered_beta") is None or pd.isna(row_data.get("unlevered_beta")):
        load_warnings.append("Unlevered beta value is missing from matched row.")
    if row_data.get("industry_de_ratio") is None or pd.isna(row_data.get("industry_de_ratio")):
        load_warnings.append("Industry D/E value is missing from matched row.")
    if row_data.get("industry_tax_rate") is None or pd.isna(row_data.get("industry_tax_rate")):
        load_warnings.append("Industry tax-rate value is missing from matched row.")

    raw_index = row_data.get("raw_index")
    match = DamodaranMatch(
        source_url=url,
        source_region=region,
        source_updated=DAMODARAN_UPDATED,
        company_industry=company_industry,
        matched_industry=matched_industry,
        confidence=confidence,
        unlevered_beta=_to_float(row_data.get("unlevered_beta")),
        industry_de_ratio=_ratio_to_decimal(row_data.get("industry_de_ratio")),
        industry_tax_rate=_ratio_to_decimal(row_data.get("industry_tax_rate")),
        industry_cost_of_debt=_ratio_to_decimal(row_data.get("industry_cost_of_debt")),
        row_data=row_data,
        source_filename=_source_filename(url),
        loaded_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        load_success=True,
        load_warnings=load_warnings,
        damodaran_row_count=len(table),
        source_row=int(raw_index) if raw_index is not None and not pd.isna(raw_index) else None,
        matching_method=matching_method,
        top_matches=match_details.get("top_matches", []),
    )
    return match, table


def _to_float(value: Any) -> float | None:
    """
    Convert a value to float safely.

    Formula: not applicable.
    Source: internal data cleaning.
    Example: '1.05' -> 1.05.
    Required inputs: any value.
    Limitation: non-numeric strings return None.
    """
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio_to_decimal(value: Any) -> float | None:
    """
    Convert Damodaran percentage-like values to decimals.

    Formula: if value > 3, divide by 100; else keep as decimal.
    Source: Damodaran tables mix decimal and percent-looking fields depending on file.
    Example: 25 -> 0.25, 0.25 -> 0.25.
    Required inputs: value.
    Limitation: heuristic for legacy Excel formatting.
    """
    number = _to_float(value)
    if number is None:
        return None
    if abs(number) > 3:
        return number / 100
    return number


def calculate_damodaran_levered_beta(unlevered_beta: float, de_ratio: float, tax_rate: float) -> float:
    """
    Calculate levered beta from a Damodaran unlevered industry beta.

    Formula: beta_L = beta_U x (1 + (1 - tax) x D/E)
    Source: Damodaran industry beta methodology.
    Example: beta_U=0.8, D/E=0.5, tax=25% -> 1.10.
    Required inputs: unlevered beta, company D/E, tax rate.
    Limitation: debt beta ignored; use industry fallback if company D/E or tax is unavailable.
    """
    return relever_beta(unlevered_beta, de_ratio, tax_rate)
