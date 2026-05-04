"""OpenPyXL Excel report generation for CAPM, WACC, DCF, and validation."""

from __future__ import annotations

from io import BytesIO
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.chart import PieChart, Reference
from openpyxl.comments import Comment
from openpyxl.drawing.image import Image
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from config import DATA_SOURCES, DISCLAIMER, current_timestamp


DARK_BLUE = "16213E"
WHITE = "FFFFFF"
GOLD = "F0A500"
LIGHT_BLUE = "D9EAF7"
LIGHT_GREEN = "DDEFD8"
LIGHT_YELLOW = "FFF2CC"
LIGHT_GRAY = "E7E6E6"
STATUS_GREEN = "C6EFCE"
STATUS_GREEN_TEXT = "006100"
STATUS_YELLOW = "FFEB9C"
STATUS_YELLOW_TEXT = "9C6500"
STATUS_RED = "FFC7CE"
STATUS_RED_TEXT = "9C0006"
THIN_BORDER = Border(
    left=Side(style="thin", color="A6A6A6"),
    right=Side(style="thin", color="A6A6A6"),
    top=Side(style="thin", color="A6A6A6"),
    bottom=Side(style="thin", color="A6A6A6"),
)


def build_valuation_excel_report(
    data: dict,
    income_metrics: pd.DataFrame,
    balance_metrics: pd.DataFrame,
    cash_flow_metrics: pd.DataFrame,
    beta_match: Any,
    valuation: dict[str, Any],
    validation_result: dict[str, Any] | None,
    sanity_warnings: list[dict[str, str]],
) -> bytes:
    """
    Build a complete CAPM/WACC/DCF Excel workbook.

    Formula: workbook embeds CAPM, Hamada re-levering, WACC, FCFF DCF, and validation formulas.
    Source: yfinance, Damodaran NYU Stern datasets, and valuation formulas in utils.valuation.
    Example: build_valuation_excel_report(data, statements, beta_match, valuation, validation, warnings).
    Required inputs: company data, calculated statements, matched Damodaran row, valuation dict.
    Limitation: forecasts are editable templates; automated assumptions require analyst review.
    """
    workbook = Workbook()
    default = workbook.active
    workbook.remove(default)

    sheets = {
        "Summary": workbook.create_sheet("Summary"),
        "Beta (Damodaran)": workbook.create_sheet("Beta (Damodaran)"),
        "CAPM": workbook.create_sheet("CAPM"),
        "WACC": workbook.create_sheet("WACC"),
        "DCF": workbook.create_sheet("DCF"),
        "Validation": workbook.create_sheet("Validation"),
        "Raw Data": workbook.create_sheet("Raw Data"),
    }

    _build_summary(sheets["Summary"], data, beta_match, valuation)
    _build_beta_sheet(sheets["Beta (Damodaran)"], data, beta_match, valuation)
    _build_capm_sheet(sheets["CAPM"], valuation)
    _build_wacc_sheet(sheets["WACC"], valuation)
    _build_dcf_sheet(sheets["DCF"], income_metrics, cash_flow_metrics, valuation)
    _build_validation_sheet(sheets["Validation"], validation_result, sanity_warnings)
    _build_raw_data_sheet(sheets["Raw Data"], data, income_metrics, balance_metrics, cash_flow_metrics, beta_match)

    for sheet in sheets.values():
        _autofit(sheet)
        sheet.freeze_panes = "A2"

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output.getvalue()


def _title(sheet, title: str) -> None:
    """
    Apply a worksheet title band.

    Formula: not applicable.
    Source: internal workbook styling.
    Example: _title(sheet, "CAPM").
    Required inputs: worksheet and title.
    Limitation: assumes title spans columns A:F.
    """
    sheet.merge_cells("A1:F1")
    cell = sheet["A1"]
    cell.value = title
    cell.font = Font(bold=True, size=14, color=WHITE)
    cell.fill = PatternFill("solid", fgColor=DARK_BLUE)
    cell.alignment = Alignment(horizontal="center")


def _header(row_range) -> None:
    """
    Style a header row.

    Formula: not applicable.
    Source: internal workbook styling.
    Example: _header(sheet["A3:F3"]).
    Required inputs: openpyxl row range.
    Limitation: only styles passed cells.
    """
    for cell in row_range[0]:
        cell.font = Font(bold=True, color=WHITE)
        cell.fill = PatternFill("solid", fgColor=DARK_BLUE)
        cell.border = THIN_BORDER


def _subheader(cell) -> None:
    """
    Style a section subheader.

    Formula: not applicable.
    Source: internal workbook styling.
    Example: _subheader(sheet["A5"]).
    Required inputs: openpyxl cell.
    Limitation: single-cell style only.
    """
    cell.font = Font(bold=True)
    cell.fill = PatternFill("solid", fgColor=LIGHT_GRAY)


def _input(cell) -> None:
    """
    Style a user-editable input cell.

    Formula: not applicable.
    Source: user requirement for yellow editable cells.
    Example: _input(sheet["B8"]).
    Required inputs: openpyxl cell.
    Limitation: does not lock or protect workbook.
    """
    cell.fill = PatternFill("solid", fgColor=LIGHT_YELLOW)
    cell.border = THIN_BORDER


def _formula(cell) -> None:
    """
    Style a formula cell.

    Formula: not applicable.
    Source: user requirement for light-blue formulas.
    Example: _formula(sheet["B12"]).
    Required inputs: openpyxl cell.
    Limitation: Excel recalculates formulas when opened.
    """
    cell.fill = PatternFill("solid", fgColor=LIGHT_BLUE)
    cell.border = THIN_BORDER


def _result(cell) -> None:
    """
    Style a key output cell.

    Formula: not applicable.
    Source: user requirement for green result cells.
    Example: _result(sheet["B14"]).
    Required inputs: openpyxl cell.
    Limitation: styling only.
    """
    cell.fill = PatternFill("solid", fgColor=LIGHT_GREEN)
    cell.font = Font(bold=True)
    cell.border = THIN_BORDER


def _pct(cell) -> None:
    """
    Apply percentage number format.

    Formula: not applicable.
    Source: Excel number-format convention.
    Example: _pct(sheet["B2"]).
    Required inputs: openpyxl cell.
    Limitation: assumes decimal input.
    """
    cell.number_format = "0.00%"


def _multiple(cell) -> None:
    """
    Apply multiple number format.

    Formula: not applicable.
    Source: Excel number-format convention.
    Example: _multiple(sheet["B2"]).
    Required inputs: openpyxl cell.
    Limitation: assumes numeric input.
    """
    cell.number_format = '0.00"x"'


def _money(cell, currency: str) -> None:
    """
    Apply millions currency number format.

    Formula: not applicable.
    Source: Excel number-format convention.
    Example: _money(cell, "EUR") -> #,##0.0 "M EUR".
    Required inputs: cell and currency code.
    Limitation: no FX conversion is performed.
    """
    cell.number_format = f'#,##0.0 "M {currency}"'


def _price(cell, currency: str) -> None:
    """
    Apply single-share price currency formatting.

    Formula: not applicable.
    Source: Excel number-format convention.
    Example: _price(cell, "USD") -> #,##0.00 "USD".
    Required inputs: cell and currency code.
    Limitation: no FX conversion is performed.
    """
    cell.number_format = f'#,##0.00 "{currency}"'


def _build_summary(sheet, data: dict, beta_match: Any, valuation: dict[str, Any]) -> None:
    """
    Build the Summary worksheet.

    Formula: pulls outputs from the valuation package and links to detail tabs.
    Source: yfinance + Damodaran valuation result.
    Example: first worksheet users see.
    Required inputs: company data, beta match, valuation dict.
    Limitation: summary values are snapshots at generation time.
    """
    _title(sheet, "Valuation Summary")
    info = data.get("info", {})
    rows = [
        ("Company", info.get("longName") or info.get("shortName")),
        ("Ticker", data.get("ticker")),
        ("Industry", info.get("industry")),
        ("Date", current_timestamp()),
        ("Reported currency", valuation.get("currency")),
        ("Beta", valuation.get("levered_beta")),
        ("Cost of Equity", valuation.get("cost_of_equity")),
        ("Cost of Debt", valuation.get("cost_of_debt")),
        ("Cost of Debt Estimated", "YES" if valuation.get("cost_of_debt_estimated") else "NO"),
        ("WACC", valuation.get("wacc")),
        ("Implied Share Price", "='DCF'!B34"),
        ("Current Market Price", "='Raw Data'!B8"),
        ("Upside / Downside", "='DCF'!B36"),
    ]
    sheet.append(["Field", "Value"])
    _header(sheet["A2:B2"])
    for row in rows:
        sheet.append(list(row))
    currency = valuation.get("currency", "")
    percent_rows = {"Cost of Equity", "Cost of Debt", "WACC", "Upside / Downside"}
    price_rows = {"Implied Share Price", "Current Market Price"}
    for row_idx in range(3, 3 + len(rows)):
        label = sheet[f"A{row_idx}"].value
        if label in percent_rows:
            _pct(sheet[f"B{row_idx}"])
        if label == "Beta":
            _multiple(sheet[f"B{row_idx}"])
        if label in price_rows:
            _price(sheet[f"B{row_idx}"], currency)
        if label in {"Implied Share Price", "Current Market Price", "Upside / Downside"}:
            _formula(sheet[f"B{row_idx}"])
        if label in {"WACC", "Implied Share Price"}:
            _result(sheet[f"B{row_idx}"])
    navigation_row = 3 + len(rows) + 2
    sheet[f"A{navigation_row}"] = "Workbook navigation"
    sheet[f"B{navigation_row}"] = None
    _subheader(sheet[f"A{navigation_row}"])
    for idx, name in enumerate(["Beta (Damodaran)", "CAPM", "WACC", "DCF", "Validation", "Raw Data"], start=navigation_row + 1):
        sheet[f"A{idx}"] = name
        sheet[f"A{idx}"].hyperlink = f"#'{name}'!A1"
        sheet[f"A{idx}"].style = "Hyperlink"
    sheet["D3"] = "Beta source"
    _subheader(sheet["D3"])
    sheet["D4"] = f"Damodaran industry: {beta_match.matched_industry}"
    sheet["D5"] = f"Match confidence: {beta_match.confidence:.1f}%"
    sheet["D6"] = f"Updated: {beta_match.source_updated}"


def _build_beta_sheet(sheet, data: dict, beta_match: Any, valuation: dict[str, Any]) -> None:
    """
    Build the Beta (Damodaran) worksheet.

    Formula: Levered Beta = Unlevered Beta x (1 + (1 - Tax) x D/E).
    Source: Aswath Damodaran, NYU Stern industry beta tables.
    Example: shows asset beta, D/E, tax, re-levering, and yfinance reference beta.
    Required inputs: beta match and valuation dict.
    Limitation: industry average beta may not capture company-specific operating risk.
    """
    _title(sheet, "Beta (Damodaran)")
    sheet["A3"] = f"Source: Aswath Damodaran, NYU Stern - {beta_match.source_url} - Updated {beta_match.source_updated}"
    sheet["A5"], sheet["B5"] = "Company industry (yfinance)", beta_match.company_industry
    sheet["A6"], sheet["B6"] = "Matched Damodaran industry", beta_match.matched_industry
    sheet["A7"], sheet["B7"] = "Match confidence", beta_match.confidence / 100
    sheet["A8"], sheet["B8"] = "Unlevered Beta", valuation.get("unlevered_beta")
    sheet["A9"], sheet["B9"] = "Company D/E ratio", valuation.get("de_ratio")
    sheet["A10"], sheet["B10"] = "Tax rate", valuation.get("tax_rate")
    sheet["C10"] = (
        "Company effective tax rate used in relevering. Alternative methodology would use marginal tax rate "
        "(Damodaran's recommendation); results may differ for firms with significant tax shields."
    )
    sheet["A11"], sheet["B11"] = "Levered Beta", "=B8*(1+(1-B10)*B9)"
    sheet["A12"], sheet["B12"] = "yfinance beta (reference only)", valuation.get("yfinance_beta")
    for row in (7, 9, 10):
        _pct(sheet[f"B{row}"])
    _formula(sheet["B11"])
    _multiple(sheet["B8"])
    _multiple(sheet["B11"])
    sheet["B11"].comment = Comment(
        "Damodaran industry beta is often more stable than a single-stock regression beta because it averages operating risk across comparable companies.",
        "Financial Analyzer",
    )
    if valuation.get("de_estimated"):
        sheet["C9"] = "ESTIMATED - company D/E missing, Damodaran industry average used."
        _input(sheet["C9"])
    if valuation.get("tax_estimated"):
        sheet["C10"] = (
            "ESTIMATED - company tax rate invalid/missing, Damodaran industry average used. "
            "Alternative methodology would use marginal tax rate (Damodaran's recommendation)."
        )
        _input(sheet["C10"])


def _build_capm_sheet(sheet, valuation: dict[str, Any]) -> None:
    """
    Build the CAPM worksheet.

    Formula: Re = Rf + beta x ERP.
    Source: yfinance ^TNX for Rf and Damodaran recommended 5.5% ERP.
    Example: B5 formula equals B2+B3*B4.
    Required inputs: valuation dict.
    Limitation: ERP is fixed at 5.5% per prompt.
    """
    _title(sheet, "CAPM")
    rows = [
        ("Risk-free rate", valuation.get("risk_free_rate"), f"^TNX as of {valuation.get('risk_free_date')}"),
        ("Levered Beta", "='Beta (Damodaran)'!B11", "Damodaran industry beta re-levered to company D/E"),
        ("Market Risk Premium", valuation.get("market_risk_premium"), "Damodaran recommendation: 5.5%"),
        ("Cost of Equity", "=B3+B4*B5", "CAPM formula"),
    ]
    sheet.append(["Input", "Value", "Explanation"])
    _header(sheet["A2:C2"])
    for row in rows:
        sheet.append(list(row))
    for cell_ref in ("B3", "B5", "B6"):
        _pct(sheet[cell_ref])
    _multiple(sheet["B4"])
    _formula(sheet["B6"])
    _result(sheet["B6"])
    _add_sml_image(sheet, valuation)


def _add_sml_image(sheet, valuation: dict[str, Any]) -> None:
    """
    Add a Security Market Line image to the CAPM worksheet.

    Formula: Expected return = Rf + beta x ERP.
    Source: CAPM/SML convention.
    Example: plots beta from 0 to 2 and company point.
    Required inputs: valuation dict.
    Limitation: static image generated at report time.
    """
    import matplotlib.pyplot as plt

    rf = valuation.get("risk_free_rate") or 0
    erp = valuation.get("market_risk_premium") or 0.055
    beta = valuation.get("levered_beta") or 1
    xs = [0, 0.5, 1, 1.5, 2]
    ys = [rf + x * erp for x in xs]
    fig, ax = plt.subplots(figsize=(5.5, 3.2))
    ax.plot(xs, ys, color="#16213e", linewidth=2)
    ax.scatter([beta], [rf + beta * erp], color="#f0a500", s=70)
    ax.set_title("Security Market Line")
    ax.set_xlabel("Beta")
    ax.set_ylabel("Expected return")
    ax.yaxis.set_major_formatter(lambda value, _pos: f"{value:.1%}")
    ax.grid(True, alpha=0.25)
    output = BytesIO()
    fig.tight_layout()
    fig.savefig(output, format="png", dpi=160)
    plt.close(fig)
    output.seek(0)
    image = Image(output)
    image.anchor = "E3"
    sheet.add_image(image)


def _build_wacc_sheet(sheet, valuation: dict[str, Any]) -> None:
    """
    Build the WACC worksheet.

    Formula: WACC = E/V x Re + D/V x Rd x (1-T).
    Source: Damodaran WACC framework.
    Example: formulas reference CAPM and WACC component cells.
    Required inputs: valuation dict.
    Limitation: book debt is used as proxy for market debt.
    """
    currency = valuation.get("currency", "")
    _title(sheet, "WACC")
    rows = [
        ("Market cap (E)", valuation.get("market_cap"), ""),
        (
            "Total debt (book value)",
            valuation.get("total_debt"),
            "Book value used as proxy for market value of debt. Standard simplification when debt is short-term or trades close to par.",
        ),
        ("V = E + D", "=B3+B4", ""),
        ("Equity weight = E/V", "=B3/B5", ""),
        ("Debt weight = D/V", "=B4/B5", ""),
        ("Cost of equity (Re)", "='CAPM'!B6", ""),
        ("Cost of debt (Rd)", valuation.get("cost_of_debt"), ""),
        ("Tax rate (T)", valuation.get("tax_rate"), ""),
        ("After-tax cost of debt", "=B9*(1-B10)", ""),
        ("WACC", "=(B6*B8)+(B7*B9*(1-B10))", ""),
    ]
    sheet.append(["Component", "Value", "Explanation"])
    _header(sheet["A2:C2"])
    for row in rows:
        sheet.append(list(row))
    for row in (3, 4, 5):
        _money(sheet[f"B{row}"], currency)
    for row in (6, 7, 8, 9, 10, 11, 12):
        _pct(sheet[f"B{row}"])
    for row in (5, 6, 7, 9, 12):
        _formula(sheet[f"B{row}"])
    _result(sheet["B12"])
    if valuation.get("cost_of_debt_estimated"):
        sheet["C9"] = "ESTIMATED - interest expense / total debt missing or outside 1%-15%; Damodaran industry cost of debt used."
        _input(sheet["C9"])
    chart = PieChart()
    labels = Reference(sheet, min_col=1, min_row=3, max_row=4)
    data = Reference(sheet, min_col=2, min_row=3, max_row=4)
    chart.add_data(data)
    chart.set_categories(labels)
    chart.title = "Capital Structure"
    sheet.add_chart(chart, "D3")


def _build_dcf_sheet(sheet, income: pd.DataFrame, cash: pd.DataFrame, valuation: dict[str, Any]) -> None:
    """
    Build the DCF worksheet.

    Formula: FCFF = EBIT x (1-T) + D&A - CapEx - Delta WC; TV = FCF_n x (1+g)/(WACC-g).
    Source: Damodaran FCFF DCF framework.
    Example: five-year formula-driven forecast with yellow assumption cells.
    Required inputs: historical revenue/EBIT/FCF and valuation dict.
    Limitation: D&A, CapEx, and working capital are template assumptions.
    """
    currency = valuation.get("currency", "")
    _title(sheet, "DCF")
    sheet["A3"] = "Assumptions"
    _subheader(sheet["A3"])
    historical_range = _period_range(income.tail(3))
    latest_period = _latest_period(income)
    assumptions = [
        (
            "Revenue growth % per year",
            valuation.get("revenue_growth") if valuation.get("revenue_growth") is not None else 0.05,
            valuation.get("revenue_growth_source") or "Fallback assumption (historical revenue data unavailable)",
        ),
        ("EBIT margin %", _safe_latest(income, "ebit_margin") / 100 if _safe_latest(income, "ebit_margin") else 0.12, f"{latest_period} actual"),
        ("Tax rate", valuation.get("tax_rate"), f"Company effective tax rate {latest_period}"),
        ("D&A % revenue", valuation.get("depreciation_pct_revenue") or 0.03, f"{latest_period} actual"),
        ("CapEx % revenue", valuation.get("capex_pct_revenue") or 0.04, f"3-year historical average ({historical_range})"),
        ("Working capital % revenue", valuation.get("working_capital_pct_revenue") or 0.02, "3-year historical average"),
        ("Terminal growth rate", valuation.get("terminal_growth"), "Capped between 1.5% and 2.5% based on long-term economic growth assumptions"),
        ("Discount rate = WACC", "='WACC'!B12", "WACC from CAPM + cost of debt"),
    ]
    sheet["C3"] = "Source"
    _subheader(sheet["C3"])
    for idx, row in enumerate(assumptions, start=4):
        sheet[f"A{idx}"], sheet[f"B{idx}"], sheet[f"C{idx}"] = row
        if idx <= 10:
            _input(sheet[f"B{idx}"])
        else:
            _formula(sheet[f"B{idx}"])
        _pct(sheet[f"B{idx}"])

    sheet["A13"] = "Historical Data"
    _subheader(sheet["A13"])
    sheet.append(["Period", "Revenue", "EBIT", "FCF"])
    _header(sheet["A14:D14"])
    hist = income.tail(3).merge(cash[["year", "free_cash_flow"]], on="year", how="left")
    for _, row in hist.iterrows():
        sheet.append([row.get("period") or row.get("year"), row.get("revenue"), row.get("ebit"), row.get("free_cash_flow")])

    start_row = 21
    sheet[f"A{start_row}"] = "Forecast"
    _subheader(sheet[f"A{start_row}"])
    headers = ["Year", "Revenue", "EBIT", "Tax", "D&A", "CapEx", "Delta WC", "FCF", "PV FCF"]
    for col, header in enumerate(headers, start=1):
        sheet.cell(start_row + 1, col).value = header
    _header(sheet[f"A{start_row + 1}:I{start_row + 1}"])
    latest_revenue_cell = f"B{14 + len(hist)}"
    for i in range(1, 6):
        row = start_row + 1 + i
        previous_revenue = latest_revenue_cell if i == 1 else f"B{row - 1}"
        sheet[f"A{row}"] = f"Year {i}"
        sheet[f"B{row}"] = f"={previous_revenue}*(1+$B$4)"
        sheet[f"C{row}"] = f"=B{row}*$B$5"
        sheet[f"D{row}"] = f"=C{row}*$B$6"
        sheet[f"E{row}"] = f"=B{row}*$B$7"
        sheet[f"F{row}"] = f"=B{row}*$B$8"
        sheet[f"G{row}"] = f"=(B{row}-{previous_revenue})*$B$9"
        sheet[f"H{row}"] = f"=C{row}-D{row}+E{row}-F{row}-G{row}"
        sheet[f"I{row}"] = f"=H{row}/(1+$B$11)^{i}"
        for col in range(2, 10):
            _formula(sheet.cell(row, col))

    out_row = start_row + 9
    sheet[f"A{out_row}"], sheet[f"B{out_row}"] = "Terminal value", f"=H{start_row + 6}*(1+$B$10)/($B$11-$B$10)"
    sheet[f"A{out_row + 1}"], sheet[f"B{out_row + 1}"] = "PV Terminal Value", f"=B{out_row}/(1+$B$11)^5"
    sheet[f"A{out_row + 2}"], sheet[f"B{out_row + 2}"] = "Enterprise value", f"=SUM(I{start_row + 2}:I{start_row + 6})+B{out_row + 1}"
    sheet[f"A{out_row + 3}"], sheet[f"B{out_row + 3}"] = "Equity value", f"=B{out_row + 2}-'WACC'!B4+'Raw Data'!B9"
    raw_implied_price = (valuation.get("dcf") or {}).get("implied_price")
    raw_implied_formula = f"B{out_row + 3}*1000000/'Raw Data'!B10"
    sheet[f"A{out_row + 4}"], sheet[f"B{out_row + 4}"] = "Implied share price", f"=MAX(0,B{out_row + 3}*1000000/'Raw Data'!B10)"
    sheet[f"C{out_row + 4}"] = (
        f'=IF({raw_implied_formula}<0,'
        f'"DCF model produced negative equity value ("&TEXT({raw_implied_formula},"0.00")&" {currency} raw); clamped to zero. '
        'This indicates assumptions imply firm worthless under current trajectory; review Scenario tab",'
        '"Calculated DCF result")'
    )
    sheet[f"A{out_row + 5}"], sheet[f"B{out_row + 5}"] = "Current market price", valuation.get("current_price")
    sheet[f"A{out_row + 6}"], sheet[f"B{out_row + 6}"] = "Upside / downside", f"=B{out_row + 4}/B{out_row + 5}-1"
    sheet[f"A{out_row + 8}"], sheet[f"B{out_row + 8}"] = "Cross-check: Python implementation result", raw_implied_price
    sheet[f"A{out_row + 9}"], sheet[f"B{out_row + 9}"] = "Cross-check upside / downside", (valuation.get("dcf") or {}).get("upside")
    sheet[f"A{out_row + 10}"] = "Both should match the Excel formula result; a difference indicates calculation inconsistency."
    for row in range(out_row, out_row + 7):
        _formula(sheet[f"B{row}"])
    for row in (out_row + 2, out_row + 3):
        _money(sheet[f"B{row}"], currency)
    _result(sheet[f"B{out_row + 4}"])
    sheet[f"B{out_row + 4}"].number_format = "0.00"
    _formula(sheet[f"C{out_row + 4}"])
    sheet[f"C{out_row + 4}"].alignment = Alignment(vertical="top", wrap_text=True)
    _pct(sheet[f"B{out_row + 6}"])
    _money(sheet[f"B{out_row + 8}"], currency)
    _pct(sheet[f"B{out_row + 9}"])
    sheet[f"B{out_row + 9}"].number_format = "0.00%"


def _build_validation_sheet(sheet, validation_result: dict[str, Any] | None, sanity_warnings: list[dict[str, str]]) -> None:
    """
    Build the Validation worksheet.

    Formula: difference = calculated - Damodaran benchmark.
    Source: Damodaran validation datasets and sanity-check thresholds.
    Example: WACC calculated vs industry average.
    Required inputs: validation result and sanity warnings.
    Limitation: validation depends on live Damodaran benchmark availability.
    """
    _title(sheet, "Validation")
    if not validation_result:
        sheet["A3"] = "Validation was not available."
        return
    sheet["A3"] = f"Source: {validation_result.get('source_url')} - Updated {validation_result.get('source_updated')}"
    sheet.append(["Metric", "Calculated", "Damodaran (industry avg)", "Difference", "Status", "Note"])
    _header(sheet["A4:F4"])
    for row in validation_result.get("rows", []):
        difference = row["Difference"]
        sheet.append([row["Metric"], row["Calculated"], row["Damodaran (industry avg)"], difference, row["Status"], row.get("Note", "")])
    for row in range(5, 5 + len(validation_result.get("rows", []))):
        for col in (2, 3):
            _pct(sheet.cell(row, col))
        sheet.cell(row, 4).number_format = '+0.00%"pp";[Red]-0.00%"pp";0.00"pp"'
        status_cell = sheet.cell(row, 5)
        if "OK" in str(status_cell.value):
            status_cell.fill = PatternFill("solid", fgColor=STATUS_GREEN)
            status_cell.font = Font(bold=True, color=STATUS_GREEN_TEXT)
        elif "Warn" in str(status_cell.value) or "Review" in str(status_cell.value):
            status_cell.fill = PatternFill("solid", fgColor=STATUS_YELLOW)
            status_cell.font = Font(bold=True, color=STATUS_YELLOW_TEXT)
        elif "Check" in str(status_cell.value) or "Critical" in str(status_cell.value):
            status_cell.fill = PatternFill("solid", fgColor=STATUS_RED)
            status_cell.font = Font(bold=True, color=STATUS_RED_TEXT)
        status_cell.border = THIN_BORDER
    data_end = 4 + len(validation_result.get("rows", []))
    if data_end >= 5:
        sheet.conditional_formatting.add(
            f"E5:E{data_end}",
            FormulaRule(formula=['ISNUMBER(SEARCH("OK",E5))'], fill=PatternFill("solid", fgColor=STATUS_GREEN), font=Font(bold=True, color=STATUS_GREEN_TEXT)),
        )
        sheet.conditional_formatting.add(
            f"E5:E{data_end}",
            FormulaRule(formula=['ISNUMBER(SEARCH("Review",E5))'], fill=PatternFill("solid", fgColor=STATUS_YELLOW), font=Font(bold=True, color=STATUS_YELLOW_TEXT)),
        )
        sheet.conditional_formatting.add(
            f"E5:E{data_end}",
            FormulaRule(formula=['OR(ISNUMBER(SEARCH("Check",E5)),ISNUMBER(SEARCH("Critical",E5)))'], fill=PatternFill("solid", fgColor=STATUS_RED), font=Font(bold=True, color=STATUS_RED_TEXT)),
        )
    start = 11
    if validation_result.get("tax_note"):
        sheet["A9"] = validation_result["tax_note"]
        sheet["A9"].font = Font(italic=True, color="666666")
        sheet.merge_cells("A9:F9")
    if validation_result.get("tax_effective_note"):
        sheet["A10"] = validation_result["tax_effective_note"]
        sheet["A10"].font = Font(italic=True, color="666666")
        sheet.merge_cells("A10:F10")
    sheet[f"A{start}"] = "Sanity checks"
    _subheader(sheet[f"A{start}"])
    sheet[f"A{start + 1}"], sheet[f"B{start + 1}"] = "Severity", "Message"
    _header(sheet[f"A{start + 1}:B{start + 1}"])
    for idx, warning in enumerate(sanity_warnings, start=start + 2):
        sheet[f"A{idx}"] = warning.get("severity")
        sheet[f"B{idx}"] = warning.get("message")
    if validation_result.get("explanations"):
        expl_row = start + 4 + len(sanity_warnings)
        sheet[f"A{expl_row}"] = "Possible explanations"
        _subheader(sheet[f"A{expl_row}"])
        for offset, text in enumerate(validation_result["explanations"], start=1):
            sheet[f"A{expl_row + offset}"] = text


def _build_raw_data_sheet(sheet, data: dict, income: pd.DataFrame, balance: pd.DataFrame, cash: pd.DataFrame, beta_match: Any) -> None:
    """
    Build the Raw Data worksheet.

    Formula: not applicable.
    Source: yfinance statements and matched Damodaran row.
    Example: stores sources, timestamps, raw statement tables, and Damodaran row values.
    Required inputs: data dict, statement frames, beta match.
    Limitation: compact raw dump, not a full yfinance object archive.
    """
    _title(sheet, "Raw Data")
    info = data.get("info", {})
    rows = [
        ("Source", DATA_SOURCES),
        ("Generated", current_timestamp()),
        ("Disclaimer", DISCLAIMER),
        ("Ticker", data.get("ticker")),
        ("financialCurrency", info.get("financialCurrency")),
        ("currentPrice", info.get("currentPrice") or info.get("regularMarketPrice")),
        ("cash", _safe_latest(balance, "cash")),
        ("sharesOutstanding", info.get("sharesOutstanding")),
        ("Damodaran source", beta_match.source_url),
        ("Damodaran industry", beta_match.matched_industry),
    ]
    for idx, row in enumerate(rows, start=3):
        sheet[f"A{idx}"], sheet[f"B{idx}"] = row
    _write_frame(sheet, "Income Statement Metrics", income, 15)
    _write_frame(sheet, "Balance Sheet Metrics", balance, 15 + len(income) + 4)
    _write_frame(sheet, "Cash Flow Metrics", cash, 15 + len(income) + len(balance) + 8)


def _write_frame(sheet, title: str, frame: pd.DataFrame, start_row: int) -> None:
    """
    Write a pandas DataFrame to a worksheet.

    Formula: not applicable.
    Source: internal workbook helper.
    Example: _write_frame(sheet, "Income", income, 15).
    Required inputs: sheet, title, frame, start row.
    Limitation: writes display values, not original raw yfinance statement objects.
    """
    sheet[f"A{start_row}"] = title
    _subheader(sheet[f"A{start_row}"])
    if frame.empty:
        sheet[f"A{start_row + 1}"] = "No data"
        return
    display = frame.copy()
    data_columns = [column for column in display.columns if column not in {"year", "period"}]
    display["Note"] = ""
    if data_columns:
        empty_mask = display[data_columns].isna().all(axis=1)
        display.loc[empty_mask, "Note"] = "Data not available from source"
    for col_idx, col in enumerate(display.columns, start=1):
        sheet.cell(start_row + 1, col_idx).value = col
    _header(sheet[f"A{start_row + 1}:{get_column_letter(len(display.columns))}{start_row + 1}"])
    for row_idx, (_, row) in enumerate(display.iterrows(), start=start_row + 2):
        for col_idx, value in enumerate(row.tolist(), start=1):
            sheet.cell(row_idx, col_idx).value = value


def _safe_latest(frame: pd.DataFrame, column: str) -> float | None:
    """
    Read the latest numeric value from a DataFrame column.

    Formula: not applicable.
    Source: internal helper.
    Example: latest revenue from income metrics.
    Required inputs: frame and column.
    Limitation: returns None when no numeric value exists.
    """
    if frame.empty or column not in frame.columns:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.iloc[-1]) if not values.empty else None


def _latest_period(frame: pd.DataFrame) -> str:
    """Return the latest fiscal period label for Excel assumption sources."""
    if frame.empty:
        return "latest FY"
    row = frame.iloc[-1]
    if "period" in frame.columns and pd.notna(row.get("period")):
        return str(row.get("period")).split(" ")[0]
    if "year" in frame.columns and pd.notna(row.get("year")):
        return f"FY{int(row.get('year'))}"
    return "latest FY"


def _period_range(frame: pd.DataFrame) -> str:
    """Return a compact fiscal period range for Excel source notes."""
    if frame.empty:
        return "available FY history"
    labels = []
    for _, row in frame.iterrows():
        if "period" in frame.columns and pd.notna(row.get("period")):
            labels.append(str(row.get("period")).split(" ")[0])
        elif "year" in frame.columns and pd.notna(row.get("year")):
            labels.append(f"FY{int(row.get('year'))}")
    if not labels:
        return "available FY history"
    if len(labels) == 1:
        return labels[0]
    return f"{labels[0]}-{labels[-1]}"


def _implied_price_source_note(raw_implied_price: float | None, currency: str) -> str:
    """Return the DCF source note for the visible clamped implied share price."""
    if raw_implied_price is None:
        return "Calculated DCF result"
    try:
        raw_value = float(raw_implied_price)
    except (TypeError, ValueError):
        return "Calculated DCF result"
    if raw_value < 0:
        return (
            f"DCF model produced negative equity value ({raw_value:.2f} {currency} raw); clamped to zero. "
            "This indicates assumptions imply firm worthless under current trajectory; review Scenario tab"
        )
    return "Calculated DCF result"




def _autofit(sheet) -> None:
    """
    Auto-size worksheet columns with a reasonable cap.

    Formula: width based on max displayed text length.
    Source: internal workbook formatting.
    Example: called for every worksheet before export.
    Required inputs: worksheet.
    Limitation: approximate width, not Excel's native autofit.
    """
    for column in sheet.columns:
        max_length = 8
        column_letter = get_column_letter(column[0].column)
        for cell in column:
            if cell.value is not None:
                max_length = max(max_length, min(len(str(cell.value)), 60))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
        sheet.column_dimensions[column_letter].width = min(max_length + 2, 42)
