"""Damodaran benchmark validation for CAPM, WACC, and tax assumptions."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import pandas as pd

try:
    import streamlit as st
except ImportError:  # pragma: no cover
    st = None

from config import DAMODARAN_MARGINAL_TAX_RATE_EUROPE, DAMODARAN_MARGINAL_TAX_RATE_USA
from utils.damodaran import DAMODARAN_UPDATED, _find_column, _ratio_to_decimal, _to_float, load_damodaran_table, match_industry
from utils.logger import append_log, log_event


WACC_URLS = {
    "europe": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/waccEurope.xls",
    "us": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/wacc.xls",
    "global": "https://pages.stern.nyu.edu/~adamodar/pc/datasets/waccGlobal.xls",
}
COE_GLOBAL_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/coeglobal.xls"
TAX_RATE_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/taxrate.xls"
COUNTRY_PREMIUM_URL = "https://pages.stern.nyu.edu/~adamodar/pc/datasets/ctryprem.xls"
COUNTRY_TAX_RATES = {
    "finland": 0.20,
    "united states": 0.21,
    "sweden": 0.206,
    "denmark": 0.22,
    "norway": 0.22,
    "germany": 0.30,
    "france": 0.25,
    "italy": 0.24,
    "netherlands": 0.258,
    "switzerland": 0.19,
    "japan": 0.30,
}


def _cache_data(ttl: int):
    """
    Apply Streamlit cache_data when Streamlit is available.

    Formula: not applicable.
    Source: Streamlit caching.
    Example: @_cache_data(86400).
    Required inputs: TTL seconds.
    Limitation: falls back to no caching outside Streamlit.
    """
    if st is None:
        return lambda func: func
    return st.cache_data(ttl=ttl, show_spinner=False)


@_cache_data(ttl=24 * 60 * 60)
def load_benchmark_table(url: str) -> pd.DataFrame:
    """
    Load a Damodaran validation benchmark table.

    Formula: not applicable.
    Source: Aswath Damodaran, NYU Stern industry datasets.
    Example: load_benchmark_table(waccEurope.xls).
    Required inputs: URL.
    Limitation: depends on Damodaran site availability and workbook layout.
    """
    return load_damodaran_table(url)


def normalize_wacc_table(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize Damodaran WACC-like benchmark columns.

    Formula: column mapping only.
    Source: Damodaran WACC, cost of equity, and tax rate tables.
    Example: maps 'Cost of Capital' to benchmark_wacc.
    Required inputs: raw Damodaran table.
    Limitation: changing Damodaran headers can require candidate updates.
    """
    industry_col = _find_column(frame, ("industryname", "industry"))
    wacc_col = _find_column(frame, ("costofcapital", "wacc"))
    coe_col = _find_column(frame, ("costofequity", "costofequity"))
    cod_col = _find_column(frame, ("costofdebt", "pretaxtcostofdebt"))
    tax_col = _find_best_tax_column(frame)
    print(f"Damodaran columns: {frame.columns.tolist()}")
    print(f"Tax rate columns found: {[c for c in frame.columns if 'tax' in str(c).lower()]}")
    if tax_col:
        print(f"Tax rate values found: {frame[tax_col].head()}")
    log_event(
        "Damodaran validation columns found: "
        f"industry={industry_col}, wacc={wacc_col}, coe={coe_col}, cod={cod_col}, tax={tax_col}; "
        f"all_columns={list(frame.columns)}",
        "validation_debug",
    )
    if industry_col is None:
        raise RuntimeError("Damodaran benchmark industry column was not found.")

    normalized = pd.DataFrame()
    normalized["industry"] = frame[industry_col].astype(str).str.strip()
    normalized["benchmark_wacc"] = frame[wacc_col].map(_ratio_to_decimal) if wacc_col else pd.NA
    normalized["benchmark_cost_of_equity"] = frame[coe_col].map(_ratio_to_decimal) if coe_col else pd.NA
    normalized["benchmark_cost_of_debt"] = frame[cod_col].map(_ratio_to_decimal) if cod_col else pd.NA
    normalized["benchmark_tax_rate"] = frame[tax_col].map(_ratio_to_decimal) if tax_col else pd.NA
    normalized["raw_effective_tax_rate"] = normalized["benchmark_tax_rate"]
    normalized["raw_index"] = frame.index
    if tax_col:
        tax_values = pd.to_numeric(normalized["benchmark_tax_rate"], errors="coerce").dropna()
        unusual = tax_values[(tax_values < 0.05) | (tax_values > 0.50)]
        if not unusual.empty:
            log_event(
                f"Damodaran tax-rate parsing warning: column={tax_col}, unusual_count={len(unusual)}, "
                f"sample={unusual.head(5).tolist()}",
                "validation_warning",
            )
    normalized = normalized[normalized["industry"].str.len() > 0]
    return normalized.reset_index(drop=True)


def _find_best_tax_column(frame: pd.DataFrame) -> str | None:
    """
    Find the most plausible Damodaran effective tax-rate column.

    Formula: prefer columns containing effective tax rate or tax rate, excluding tax benefit/noise columns.
    Source: Damodaran WACC and tax-rate workbook labels.
    Example: chooses 'Effective Tax Rate' over unrelated tax columns.
    Required inputs: raw benchmark DataFrame.
    Limitation: still logs selected columns for debugging when Damodaran changes layout.
    """
    candidates = []
    for column in frame.columns:
        raw_name = str(column).strip().lower()
        key = "".join(ch for ch in raw_name if ch.isalnum())
        if "tax" not in key:
            continue
        score = 0
        if "effectivetaxrate" in key:
            score += 200
        elif "effective" in key and "tax" in key:
            score += 160
        if key == "aggregatetaxrate" and "_2" not in raw_name:
            score += 170
        elif key.startswith("aggregatetaxrate"):
            score += 60
        if "averageacrossonlymoneymakingcompanies" in key and "_2" not in raw_name:
            score += 130
        if key == "taxrate" or key.endswith("taxrate"):
            score += 80
        if "marginal" in key:
            score -= 30
        if "cash" in key or "_2" in raw_name:
            score -= 100
        if "benefit" in key or "savings" in key:
            score -= 50
        values = pd.to_numeric(frame[column], errors="coerce").dropna()
        converted = values.map(_ratio_to_decimal).dropna()
        plausible = converted[(converted >= 0.05) & (converted <= 0.50)]
        score += min(len(plausible), 20)
        candidates.append((score, column))
    if not candidates:
        return None
    candidates.sort(reverse=True, key=lambda item: item[0])
    return candidates[0][1] if candidates[0][0] > 0 else None


def validate_against_damodaran(
    valuation: dict[str, Any],
    company_industry: str,
    region: str,
    country: str | None = None,
) -> dict[str, Any]:
    """
    Compare calculated valuation metrics against Damodaran industry benchmarks.

    Formula: difference = calculated metric - industry benchmark.
    Source: Damodaran WACC/cost benchmark tables, January 2026 URLs from prompt.
    Example: calculated WACC 7.30% vs industry 7.15% -> +0.15pp OK.
    Required inputs: valuation result dict, company industry, source region.
    Limitation: benchmarks are industry averages and may differ for firm-specific reasons.
    """
    url = WACC_URLS.get(region, WACC_URLS["global"])
    raw = load_benchmark_table(url)
    table = normalize_wacc_table(raw)
    matched_industry, confidence = match_industry(company_industry, table)
    row = table[table["industry"] == matched_industry]
    if row.empty:
        raise RuntimeError("Validation benchmark industry was not found.")
    benchmark = row.iloc[0].to_dict()
    raw_effective_tax_rate = _to_float(benchmark.get("raw_effective_tax_rate"))
    benchmark = _enrich_missing_benchmarks(benchmark, company_industry)
    country_tax = _country_tax_rate(country)
    marginal_tax_rate = _marginal_tax_rate(region)
    benchmark["benchmark_tax_rate"] = marginal_tax_rate

    metrics = [
        ("Cost of Equity", valuation.get("cost_of_equity"), benchmark.get("benchmark_cost_of_equity")),
        ("Cost of Debt", valuation.get("cost_of_debt"), benchmark.get("benchmark_cost_of_debt")),
        ("WACC", valuation.get("wacc"), benchmark.get("benchmark_wacc")),
        ("Tax rate", valuation.get("tax_rate"), benchmark.get("benchmark_tax_rate")),
    ]
    rows = []
    explanations = []
    for name, calculated, benchmark_value in metrics:
        calc = _to_float(calculated)
        bench = _to_float(benchmark_value)
        difference = None if calc is None or bench is None else calc - bench
        note = ""
        if name == "Tax rate":
            status, note = _tax_validation_status(calc, bench, country_tax, country)
        elif name == "Cost of Debt":
            status, note = _cost_of_debt_validation_status(difference)
        else:
            status = _validation_status(difference)
        if "Check" in status:
            explanations.extend(
                [
                    "Yrityksen pääomarakenne poikkeaa toimialan keskiarvosta.",
                    "Yrityksen tehollinen veroaste eroaa toimialakeskiarvosta.",
                    "Yrityksen koko tai riskiprofiili voi vaikuttaa tuottovaatimukseen.",
                ]
            )
        rows.append(
            {
                "Metric": name,
                "Calculated": calc,
                "Damodaran (industry avg)": bench,
                "Difference": difference,
                "Status": status,
                "Note": note,
            }
        )

    log_path = log_event(f"Validation run for industry={company_industry}, matched={matched_industry}", "validation")
    for row_data in rows:
        append_log(log_path, str(row_data))

    return {
        "source_url": url,
        "source_updated": DAMODARAN_UPDATED,
        "matched_industry": matched_industry,
        "confidence": confidence,
        "rows": rows,
        "explanations": list(dict.fromkeys(explanations)),
        "log_path": str(log_path),
        "country_tax_rate": country_tax,
        "marginal_tax_rate": marginal_tax_rate,
        "raw_effective_tax_rate": raw_effective_tax_rate,
        "tax_note": (
            "Tax rate comparison uses Damodaran's marginal tax-rate convention, because industry effective tax rates "
            "can be near zero when sectors have widespread tax shields, NOLs, or offshore structures."
        ),
        "tax_effective_note": (
            f"Industry effective tax rate (Damodaran raw): {_format_pct(raw_effective_tax_rate)}, "
            "indicating widespread tax shield use in this sector."
        ),
    }


def get_damodaran_industry_cost_of_debt_details(company_industry: str, region: str) -> dict[str, Any]:
    """
    Look up Damodaran industry average pre-tax cost of debt with source metadata.

    Formula: column lookup only; the value is used as Rd fallback when company interest expense is unavailable.
    Source: Damodaran WACC by industry datasets.
    Example: Consumer Electronics -> benchmark_cost_of_debt from wacc.xls.
    Required inputs: yfinance company industry and Damodaran source region.
    Limitation: fuzzy industry matching can differ from the beta-table match.
    """
    url = WACC_URLS.get(region, WACC_URLS["global"])
    raw = load_benchmark_table(url)
    table = normalize_wacc_table(raw)
    matched_industry, confidence = match_industry(company_industry, table)
    row = table[table["industry"] == matched_industry]
    if row.empty:
        return {
            "value": None,
            "source_url": url,
            "source_file": _source_filename(url),
            "matched_industry": matched_industry,
            "confidence": confidence,
            "source_row": None,
        }
    row_data = row.iloc[0].to_dict()
    cost_of_debt = _to_float(row_data.get("benchmark_cost_of_debt"))
    if cost_of_debt is not None:
        log_event(
            f"Damodaran cost of debt fallback loaded: industry={matched_industry}, "
            f"confidence={confidence:.1f}, cost_of_debt={cost_of_debt}",
            "validation_debug",
        )
    raw_index = row_data.get("raw_index")
    return {
        "value": cost_of_debt,
        "source_url": url,
        "source_file": _source_filename(url),
        "matched_industry": matched_industry,
        "confidence": confidence,
        "source_row": int(raw_index) if raw_index is not None and not pd.isna(raw_index) else None,
    }


def get_damodaran_industry_cost_of_debt(company_industry: str, region: str) -> float | None:
    """Look up Damodaran industry average pre-tax cost of debt."""
    return get_damodaran_industry_cost_of_debt_details(company_industry, region).get("value")


def _enrich_missing_benchmarks(benchmark: dict[str, Any], company_industry: str) -> dict[str, Any]:
    """
    Fill missing benchmark fields from supplemental Damodaran tables.

    Formula: not applicable; supplemental lookup only.
    Source: coeglobal.xls, taxrate.xls, and ctryprem.xls from Damodaran NYU Stern.
    Example: if WACC table lacks tax rate, taxrate.xls industry match is used.
    Required inputs: partial benchmark dict and company industry.
    Limitation: supplemental tables may use different industry taxonomies.
    """
    enriched = dict(benchmark)
    if pd.isna(enriched.get("benchmark_cost_of_equity")):
        coe = _lookup_metric(COE_GLOBAL_URL, company_industry, "benchmark_cost_of_equity")
        if coe is not None:
            enriched["benchmark_cost_of_equity"] = coe
    tax = _lookup_metric(TAX_RATE_URL, company_industry, "benchmark_tax_rate")
    if tax is not None:
        enriched["benchmark_tax_rate"] = tax
    try:
        # Loaded for audit completeness; country ERP is not substituted into the company-specific CAPM.
        load_benchmark_table(COUNTRY_PREMIUM_URL)
    except Exception:
        pass
    return enriched


def _lookup_metric(url: str, company_industry: str, metric: str) -> float | None:
    """
    Look up one industry benchmark metric from a supplemental Damodaran table.

    Formula: fuzzy industry match followed by metric extraction.
    Source: Damodaran supplemental validation datasets.
    Example: lookup cost of equity from coeglobal.xls.
    Required inputs: URL, company industry, metric column name.
    Limitation: returns None when the supplemental workbook does not expose the metric.
    """
    try:
        raw = load_benchmark_table(url)
        table = normalize_wacc_table(raw)
        matched, _confidence = match_industry(company_industry, table)
        row = table[table["industry"] == matched]
        if row.empty:
            return None
        value = row.iloc[0].get(metric)
        return _to_float(value)
    except Exception:
        return None


def _validation_status(difference: float | None) -> str:
    """
    Classify a benchmark difference in percentage points.

    Formula: abs(diff) thresholds <2pp OK, 2-5pp warning, >5pp fail.
    Source: user-specified validation tolerance.
    Example: 0.0102 -> OK; 0.035 -> review; 0.060 -> fail.
    Required inputs: difference as decimal.
    Limitation: ignores industry dispersion and confidence intervals.
    """
    if difference is None or pd.isna(difference):
        return "No benchmark"
    abs_diff = abs(difference)
    if abs_diff < 0.02:
        return "✓ OK"
    if abs_diff <= 0.05:
        return "⚠ Review"
    return "✗ Check"
def _tax_validation_status(
    calculated: float | None,
    benchmark: float | None,
    country_tax: float | None,
    country: str | None,
) -> tuple[str, str]:
    """Classify tax-rate reasonableness against industry and country benchmarks."""
    if calculated is None or pd.isna(calculated):
        return "No benchmark", ""
    industry_ok = benchmark is not None and not pd.isna(benchmark) and abs(calculated - benchmark) <= 0.05
    country_ok = country_tax is not None and abs(calculated - country_tax) <= 0.05
    if country_ok:
        country_name = country or "country"
        return "\u2713 OK", f"Effective tax rate consistent with {country_name}'s corporate tax rate"
    if 0.18 <= calculated <= 0.30:
        return "\u2713 OK", "Effective tax rate is within a normal 18%-30% operating range"
    if 0.10 <= calculated < 0.18 or 0.30 < calculated <= 0.35:
        return (
            "\u26a0 Review",
            "Effective tax rate below standard marginal rate may reflect tax shields, carryforwards, or favorable jurisdictions; common for global tech and pharma companies",
        )
    if calculated < 0.10 or calculated > 0.35:
        return "\u2717 Check", "Effective tax rate is outside the usual 10%-35% operating range; check for unusual tax items"
    if industry_ok:
        return "\u2713 OK", "Effective tax rate within 5pp of Damodaran industry average"
    reference = benchmark if benchmark is not None and not pd.isna(benchmark) else country_tax
    difference = None if reference is None else calculated - reference
    return _validation_status(difference), ""


def _cost_of_debt_validation_status(difference: float | None) -> tuple[str, str]:
    """Classify company cost of debt against Damodaran industry average."""
    if difference is None or pd.isna(difference):
        return "No benchmark", ""
    if abs(difference) <= 0.0205:
        return "\u2713 OK", ""
    return (
        "\u26a0 Review",
        "Difference may reflect company-specific credit rating; investment-grade firms typically enjoy below-average debt costs",
    )


def _marginal_tax_rate(region: str) -> float:
    """Return Damodaran marginal tax-rate convention by broad region."""
    if region == "us":
        return DAMODARAN_MARGINAL_TAX_RATE_USA
    return DAMODARAN_MARGINAL_TAX_RATE_EUROPE


def _format_pct(value: float | None) -> str:
    """Format a decimal percentage for validation notes."""
    if value is None or pd.isna(value):
        return "N/A"
    return f"{value:.2%}"


def _country_tax_rate(country: str | None) -> float | None:
    """Return a simple country statutory corporate tax benchmark when known."""
    if not country:
        return None
    return COUNTRY_TAX_RATES.get(str(country).strip().lower())


def _source_filename(url: str) -> str:
    """Return workbook filename from a Damodaran URL."""
    return urlparse(url).path.rsplit("/", 1)[-1] or url


def _validation_status(difference: float | None) -> str:
    """Classify a benchmark difference in percentage points."""
    if difference is None or pd.isna(difference):
        return "No benchmark"
    abs_diff = abs(difference)
    if abs_diff < 0.02:
        return "\u2713 OK"
    if abs_diff <= 0.05:
        return "\u26a0 Review"
    return "\u2717 Check"
