# EquityLens - Development Log & Methodology Notes

This document captures the development trajectory of EquityLens, an equity research valuation tool built with Streamlit, Python, and Damodaran sector data. It records design decisions, methodological learnings, and the limits of the model - not just what was built, but why it was built and what we discovered along the way.

## Project Context

EquityLens is a portfolio project demonstrating equity research and corporate finance reasoning at FP&A / equity research analyst level. The tool fetches company financials via yfinance, sector benchmarks from Aswath Damodaran's published datasets at NYU Stern, and produces both an interactive Streamlit dashboard and a downloadable Excel report with CAPM, WACC, and DCF analysis.

The five-tier valuation cascade is the core architectural choice:

1. Standard DCF
2. Smoothed DCF
3. Sector Benchmark DCF
4. Multiples valuation
5. Tangible book floor

Each tier exists to handle a different kind of company. Tiers 1-3 attempt DCF with progressively broader assumptions, Tier 4 falls back to market multiples when DCF cannot produce a sane result, and Tier 5 provides a conservative balance-sheet floor.

## Earlier Build History

This section records the earlier foundation work that happened before the later valuation-specific refinements documented below. Some early assumptions and thresholds were later changed as the model matured, so this section should be read as development history rather than a complete description of the current implementation.

### Initial State

The first working version of the app was functionally useful but visually and methodologically rough. It had the basic shape of a Streamlit financial-analysis tool, but it still felt like a generic prototype:

- Dark blue background with bright blue KPI cards.
- Default Plotly charts with loud default colors.
- Weak numeric hierarchy and muted headline figures.
- Small tab navigation that did not feel like the primary analytical workflow.
- Damodaran data loaded in the background, but the user could not easily trace which file, row, or sector was actually used.
- DCF produced a number even when the result was not economically sensible.

The goal of the early refactor was to raise the app to portfolio quality: cleaner visually, easier to audit, and more honest about valuation uncertainty.

### Early UI Redesign

The visual direction changed from a generic dark prototype to a more restrained fintech dashboard style inspired by tools such as Koyfin, Stockanalysis, and modern finance dashboards.

Key design choices:

- Page background moved to near-black (`#0a0a0f`) instead of blue-tinted dark.
- Cards use `#1a1a24` with subtle borders instead of bright filled panels.
- Semantic colors are reserved for meaning: green for positive, amber for warnings, red for genuinely negative states, and blue for interactive emphasis.
- Status pills use transparent tinted backgrounds instead of heavy fills.
- The app uses Inter and tabular numerals so financial values align cleanly.
- KPI cards are custom HTML components rather than default `st.metric`, because they need sparkline charts, context labels, and benchmark rows.

This was also when the shared Plotly styling layer in `utils/chart_theme.py` became important. The charts moved toward transparent backgrounds, subtle gridlines, horizontal legends, consistent tooltip styling, and muted placeholders for missing data.

### Chart and Insight Improvements

The initial charts used default Plotly colors that clashed with the rest of the app. The chart palette was standardized:

- Revenue and core bars use restrained teal rather than bright default blue.
- Margin lines use semantically distinct but muted colors.
- Liabilities are neutral gray rather than red, because debt is not automatically a loss.
- Cash flow charts use related intensities rather than several unrelated colors.
- Dividend charts were simplified so payout ratio and dividend per share are easier to interpret.

A more important conceptual change was the move from descriptive chart titles to analytical insight titles. Instead of only saying what the chart shows, titles increasingly describe what the data means. For example, a revenue chart should communicate whether growth is accelerating, slowing, or stalled, not merely label itself as revenue development.

### Early Bug Hunting

Several visual and interaction bugs were cleaned up during this stage:

- `undefined` text could appear in chart subtitles when subtitle generation returned missing values.
- The latest revenue bar could render in a different color because of unnecessary "highlight last year" logic.
- Hover tooltips sometimes displayed wrong values because x/y data binding was not consistently list-shaped.
- Plotly modebars appeared on small embedded charts where they added noise.
- The Methodology tab temporarily rendered raw financial data instead of formula documentation.
- Margin chart legends could overlap the title area.
- Some charts displayed fiscal years on the axis even when the underlying data began later.
- Adjacent charts had inconsistent heights.
- Plotly tooltip fonts did not match the rest of the app.
- Streamlit sliders used an unwanted red accent before being aligned to the app palette.

The larger lesson was that visual polish is not separate from analytical credibility. If a valuation app looks inconsistent, the user has less reason to trust the numbers.

### Foundational Code Issues Found Early

Early review also surfaced deeper code-level issues:

- README and UI text had encoding problems from mixed UTF-8 / latin-1 handling.
- `validation.py` contained a duplicate `_validation_status` function.
- `valuation.py` expected `current_assets` for working-capital calculations, but `build_balance_sheet_metrics` did not produce that field at the time.
- Because of the missing `current_assets` field, working capital could silently fall back to a default assumption while the source text implied a historical average.

This became an important workflow lesson: before building a large feature, it is worth asking the coding agent to look for adjacent issues. The agent may spot structural problems, but it will not safely fix them without a clear request and review.

### Damodaran Data Traceability and Debug View

A hidden debug view was added so the user could inspect how Damodaran data flows through the app. This helped turn the model from a black box into an auditable tool.

The debug view shows:

- Which Damodaran workbook is being loaded, such as `betas.xls` for US data or `betaEurope.xls` for Europe.
- Source path, load time, and parsed row count.
- yfinance industry input, matched Damodaran sector, confidence score, and matching method.
- Top fuzzy-match candidates.
- Used Damodaran values with source file and source row context.
- The matched Damodaran row as raw structured data for inspection.

This became especially useful later when debugging sector-matching mistakes and Europe dataset naming issues.

### Cash-Adjusted Unlevered Beta

Manual comparison against Damodaran workbooks clarified that the model should not simply use raw industry levered beta. The stronger approach is to use Damodaran's cash-adjusted unlevered beta and then relever it to the company's own debt/equity ratio and tax rate.

The reason is methodological: excess cash can dampen observed beta. Cash-adjusted unlevered beta gives a cleaner estimate of operating business risk before the company's own capital structure is applied. The Beta sheet and methodology text were updated to explain this more clearly.

### Marginal Versus Effective Tax Rate

Another early discovery came from inspecting Damodaran beta data. Some sector effective tax-rate values can be close to zero, which is not a good default for unlevering and relevering beta. Damodaran's own workbook notes the choice between effective and marginal tax rates, and marginal rates are often more appropriate for normalized capital-cost work.

The app therefore moved toward clearer tax-rate handling and better disclosure of which rate is used where. Later work added additional tax-context checks in the Excel Validation tab so readers can distinguish between company effective tax rates, country statutory rates, and sector benchmark rates.

### Validation False Positives

The first validation logic was too blunt. Several cases looked like warnings even though they were explainable:

- A Finnish company can naturally have a tax rate different from a broad European sector average.
- A very strong investment-grade company can borrow below the sector average cost of debt.
- Debug and Validation views must show the same benchmark source and value, otherwise the report looks internally inconsistent.

This led to a broader principle used throughout the later project: validation should separate genuine model risk from normal business context. A warning is only useful if it helps the analyst think.

### Early Pytest Coverage

An early `tests/` folder was added with mocked tests so the core logic could be checked without relying on live network access. Initial coverage focused on:

- Damodaran loader behavior and expected columns.
- Industry matching, including case-insensitive matching.
- Value extraction, including reasonable beta ranges and percentage-versus-decimal handling.

The tests found a real issue: uppercase industry text such as `MACHINERY` could match incorrectly before case-insensitive handling was fixed. That made the tests useful not just as documentation, but as a way to catch real regressions.

### Early DCF Methodology Evolution

The earliest DCF assumptions were a mix of data-driven and hardcoded values:

- EBIT margin came from company actuals.
- CapEx used a historical average.
- Revenue growth was initially too static.
- Working capital could fall back too silently.
- Terminal growth was fixed.

The model then moved toward more data-driven assumptions. Revenue growth started using historical CAGR windows with fallbacks, working capital became tied to historical balance-sheet data when available, and the DCF tab gained source strings so every major assumption could be traced.

The early Source column idea became one of the most important report-design decisions. A valuation model is much easier to review when the user can see not only the assumption value, but also where it came from.

### Early Edge-Case Work: Why One DCF Was Not Enough

The most important early valuation lesson came from cyclical and transition companies. A single DCF can produce economically impossible or useless results when the current year is a trough or when the company is undergoing a business-model shift.

Neste was the key example. A plain DCF could produce negative implied equity value because recent margins were depressed. Clamping the value to zero would have been mathematically neat but analytically useless. A real analyst would switch methodology rather than pretend a negative share price is meaningful.

That observation led to the five-tier valuation architecture:

| Tier | Early role in the model |
|---:|---|
| 1 | Standard DCF using company-specific actuals and averages |
| 2 | Smoothed DCF using longer-term averages |
| 3 | Sector Benchmark DCF using Damodaran sector assumptions |
| 4 | Multiples valuation using EV/EBITDA, EV/Sales, and P/Book |
| 5 | Tangible book value floor |

Later iterations refined the exact acceptance thresholds and status labels, but the core idea stayed the same: if the primary valuation method breaks, the tool should say so clearly and move to a more appropriate fallback rather than hiding the problem.

### Early Portfolio Takeaways

Several themes became useful from a portfolio-story perspective:

- **Data lineage:** every valuation input should be traceable to a source.
- **Methodological transparency:** beta, tax, WACC, DCF, and multiples should be explainable from the workbook.
- **Edge-case handling:** the tool should behave sensibly for stable companies, cyclicals, transition stories, and structurally incompatible business models.
- **Test coverage:** mocked tests can catch real bugs without depending on live yfinance or Damodaran availability.
- **Uncertainty communication:** confidence levels, selected tiers, and validation notes matter as much as the implied price.

These early lessons became the basis for the later reverse DCF, analyst checks, business model compatibility checks, and expanded Methodology documentation.

## Development Trajectory

### Phase 1 - Diagnosing the Growth Company Problem

Initial test results showed Apple at roughly -65% versus market and Microsoft at roughly -51% versus market under Tier 1 Standard DCF. The reflexive interpretation was that the market was overpricing tech. After investigation, that interpretation was too simplistic. The deviations were largely structural, caused by Apple revenue volatility distorting the historical CAGR and by using the latest FY EBIT margin as the steady-state margin assumption for companies where the market is pricing forward growth.

Rather than calibrating the model to produce more flattering numbers, I added a **reverse DCF** capability. The reverse DCF holds all Tier 1 DCF inputs constant except revenue growth, then solves for the growth rate that would make the implied price equal the current market price. This turned the model from a calculator that says "the value is X" into a diagnostic tool that explains the gap between market expectations and historical performance.

For Microsoft and Alphabet, reverse DCF revealed market-implied growth of roughly 43%, against Yahoo revenue growth estimates around 18-22% and historical CAGR around 12%. The gap is real, consistent across two large technology companies, and informative: the market is pricing AI-era growth that is far above what the historical inputs alone justify.

### Phase 2 - Excel Report Quality Fixes

The first detailed review of the Johnson & Johnson Excel report exposed several small but visible issues:

- **Beta/CAPM/WACC auditability.** These sheets needed real Excel formulas rather than only Python-computed values. The fix made Beta, CAPM, and WACC auditable in the workbook. DCF tier outputs remain report values written by the Python valuation engine.
- **CAGR naming was off by one.** Source text could read like "4-year CAGR (FY2022-FY2025)" when computed from four data points. CAGR over n data points spans n-1 growth periods, so the labels were corrected to describe the actual number of growth periods.
- **Tier 2 status text was incomplete.** Status could read `ACCEPTED - ` with an empty reason. Accepted and rejected statuses now use consistent reason text.
- **Reverse DCF source attribution.** All reverse DCF rows originally used the same source text. The rows now distinguish between solved values, Tier 1 assumptions, yfinance analyst fields, derived calculations, and interpretation text.
- **Tier 3 SKIPPED versus REJECTED.** When a matched Damodaran sector has a non-positive EBIT margin, the Sector Benchmark DCF does not produce a meaningful operating-company valuation. The model now labels this as skipped rather than pretending the calculation ran and failed normally.

### Phase 3 - Damodaran Europe Data File Naming

European tickers such as `NESTE.HE` and `KNEBV.HE` initially failed to load full Tier 4 multiples coverage. EV/EBITDA worked, while EV/Sales and P/Book showed load failures.

The root cause was Damodaran's inconsistent Europe filename convention:

| Dataset | US filename | Europe filename |
|---|---|---|
| Beta | `betas.xls` | `betaEurope.xls` |
| P/E | `pedata.xls` | `peEurope.xls` |
| Price/Sales | `psdata.xls` | `psEurope.xls` |
| Price/Book | `pbvdata.xls` | `pbvEurope.xls` |
| EV/EBITDA | `vebitda.xls` | `vebitEurope.xls` |

The original code treated Europe filenames too mechanically, which produced invalid URLs such as `psdataEurope.xls` and `pbvdataEurope.xls`. The loader was changed to use explicit filenames after checking the published Damodaran dataset structure. European tickers now have full multiples coverage for the Tier 4 median calculation.

### Phase 4 - Sector Matching: The JNJ Insurance Bug

JNJ, whose yfinance industry is `Drug Manufacturers - General`, was being matched to Damodaran sector `Insurance (General)` with 55.3% confidence. The cause was simple string similarity giving too much weight to the shared generic word "General". Pharma sectors in Damodaran's taxonomy do not use that word in the same way.

The fix was a curated industry mapping and keyword-priority layer. Domain-specific terms such as "drug" and "pharma" outweigh generic terms such as "general". After the fix, JNJ maps to `Drugs (Pharmaceutical)` with high confidence, and the resulting valuation uses a more appropriate sector beta.

This was a useful reminder that sector classification is upstream of the valuation math. A small classification error can flow into the beta, cost of equity, WACC, terminal value, and implied price.

### Phase 5 - Sanity Checks: From Calculator to Analyst Tool

The original Validation tab contained only a basic implied-price sanity message. It was functional but not analytically useful. The Excel Validation tab was expanded to surface observations an equity research analyst would want to investigate:

- **Margin volatility:** flags when latest FY EBIT margin deviates materially from the three-year average.
- **Margin assumption sensitivity:** flags when Tier 1 and Tier 2 implied prices differ materially.
- **Cost of debt context:** compares company cost of debt against the Damodaran sector benchmark.
- **Tax structure:** compares effective tax rate against a country statutory tax-rate lookup.
- **Beta methodology:** compares yfinance beta against Damodaran-relevered beta and explains the methodology difference.

A critical architectural decision was keeping these analyst observations in a separate Excel-only path: `build_excel_sanity_checks()`. The existing `run_sanity_checks()` function is wired into Streamlit gating. Adding routine analyst observations there would have changed UI behavior and forced users to override warnings for normal cases. Keeping the pipelines separate preserved the meaning of gating warnings while allowing the Excel report to become more useful.

### Phase 6 - Reverse DCF Interpretation for Cyclicals

For `NESTE.HE`, with manual sector override to `Green & Renewable Energy`, the reverse DCF solver fails because Tier 1 EBIT margin is only 1.8%. Revenue growth alone cannot bridge the gap to market price when the current margin is at a cyclical trough. The original failure message framed this as the market implying growth beyond the search range, which was misleading.

The interpretation logic was improved to detect when current Tier 1 EBIT margin is less than 50% of the company's five-year average EBIT margin. In that case, the reverse DCF explains that the market may be pricing margin recovery rather than pure revenue growth. That is a more honest interpretation because the standard reverse DCF holds margins constant.

This was a small code change but an important methodological change. The model now acknowledges its own limitation instead of blaming the market price.

### Phase 7 - Pre-Report Streamlit Valuation Summary

Originally, valuation results appeared mainly after clicking **Generate Excel Report** and opening the downloaded workbook. The Streamlit dashboard showed company KPIs, financial quality, and historical data, but the core valuation output was too hidden.

The dashboard now shows valuation output inline: selected implied price, selected method, upside/downside, tier comparison, and reverse DCF analysis. The reverse DCF UI handles three cases:

1. Numeric solution available.
2. Solver failed, but diagnostic explanation is available.
3. Valuation not yet computed, so the section stays hidden.

### Phase 8 - Business Model Compatibility Check: The BAC Discovery

Bank of America exposed a structural blind spot. The model produced a positive implied return and initially labeled the result as normal, even though operating-company DCF is structurally inappropriate for banks.

The issue is not that the arithmetic failed. The issue is that the framework does not fit the business model:

- Bank revenue means net interest income plus fees, not product or service sales.
- Free cash flow is dominated by balance-sheet movements and is not a steady operating cash-flow measure.
- CapEx is close to zero and does not behave like industrial reinvestment.
- Working capital concepts do not apply cleanly to bank balance sheets.

The fix was a critical-severity business model compatibility check. It fires for matched Damodaran sectors containing financial-institution or real-estate vehicle patterns such as banks, insurance, REITs, brokerage, reinsurance, investments and asset management, securitized finance, and financial services.

When this check fires, Streamlit gates Excel report generation until the user explicitly overrides the warning. The Excel Summary tab also displays a critical banner and changes confidence wording so that a workbook reader does not miss the warning.

## Methodological Learnings

### What Works Well

**Mature operating companies in stable sectors.** The model produces defensible results for companies such as JNJ, KO, XOM, and KNEBV.HE. They are different sectors, different geographies, and different capital structures, but the model treats them consistently.

**Reverse DCF as a diagnostic.** The most useful output of reverse DCF is the comparison between market-implied growth, model-assumed growth, and the Yahoo revenue growth estimate. Three patterns emerged:

- Small gap: model assumptions are broadly consistent with market expectations.
- Large positive gap with a high Yahoo revenue growth estimate: market prices a growth premium.
- Positive gap with a low or negative Yahoo revenue growth estimate: market may be pricing mean reversion that the estimate has not yet reflected.

The model surfaces the gap. The analyst decides what to do with it.

**Five-tier cascade with explicit acceptance and rejection.** When DCF tiers fail, the tool does not hide the failure. It shows which tiers ran, which tiers were rejected or skipped, and why the selected estimate was chosen.

**Validation tab analyst checks.** The Validation tab is the part that turns the workbook from a calculator into an analyst aid. It flags margin volatility, tax differences, cost of debt context, beta methodology differences, and sensitivity between Tier 1 and Tier 2.

### What Does Not Work - Known Model Limitations

**Growth companies with significant AI or platform premium.** AAPL, MSFT, and GOOGL all produce large negative deviations under the conservative historical DCF. This is expected. Historical CAGR cannot capture forward-looking expectations such as AI optionality, cloud platform strength, or ecosystem durability. Reverse DCF is the recommended interpretive lens for these cases.

A possible future enhancement is a separate external-estimate DCF mode using forward revenue estimates for the first forecast years and then fading toward a longer-term assumption. This was deliberately not implemented in the current version because it would blur the line between historical-data DCF and estimate-driven DCF.

**Mature companies in extended slowdown periods.** Companies such as Nestle and Procter & Gamble can look undervalued or over-penalized when the recent historical window captures a slowdown. The model reflects the historical data honestly, but it does not forecast an operational recovery unless the recovery already appears in the data.

**Cyclicals in business transformation.** Neste is the clearest example. It is cyclical, current margins are depressed, and the business mix has been shifting. Automated industry classification cannot fully understand that transformation. Manual sector override is therefore an important workflow rather than a cosmetic feature.

**Cyclicals in their core sector.** Exxon Mobil shows that cyclical companies can still work in this framework when the sector match is structurally correct and the company is not in a transformation state.

**Financial institutions are structurally outside operating-company DCF scope.** Banks, insurers, REITs, and asset managers need sector-specific methods such as residual income, P/B, dividend discount models, P/AFFO, or embedded value. EquityLens detects these cases and warns the user, but it does not implement those alternative models.

### Sector Classification Is Upstream of Everything

The single most consequential decision for any ticker is the Damodaran sector match. It determines unlevered beta, sector cost of debt, sector tax rate, and fallback benchmarks. The yfinance industry string and Damodaran sector taxonomy are not one-to-one.

Known failure modes include:

- **String similarity false matches:** JNJ matching Insurance because of the word "General". Fixed via curated mapping.
- **Business transformation:** Neste requiring manual override because yfinance classification does not capture the renewable transition cleanly.
- **Sector composition mismatch:** some Damodaran sectors contain a wide mix of profitable and unprofitable companies, which can make sector-level margin or CapEx benchmarks poor fits for individual targets.

The manual override workflow is therefore a core feature. It surfaces sector-classification uncertainty and records the analyst's judgment.

### Multi-Currency and Multi-Region Behavior

Testing across USD, EUR, and CHF tickers confirmed that reported currency labels propagate through the dashboard and workbook. European tickers load Europe-specific Damodaran datasets where available, including beta, margin, CapEx, EV/EBITDA, EV/Sales, and P/Book datasets.

The WACC validation layer references the configured Damodaran WACC datasets for the relevant region, including `wacc.xls`, `waccEurope.xls`, and `waccGlobal.xls` as defined in the validation configuration.

One known limitation remains: the risk-free rate currently uses a broad market benchmark rather than a currency-specific government bond curve for every listing currency. A more precise version would use a US Treasury rate for USD companies, a German Bund reference for EUR companies, and a Swiss government bond reference for CHF companies.

## Tested Companies and Outcomes

| Ticker | Sector / type | Selected tier | Interpretation |
|---|---|---|---|
| JNJ | Mature pharma | Tier 1 | Strong operating-company DCF case |
| KO | Mature consumer staples | Tier 1 | Quality premium versus conservative DCF |
| XOM | Mature integrated oil | Tier 1 | Cyclical company works with correct sector match |
| KNEBV.HE | Mature industrial | Tier 1 | Acceptable mature industrial result |
| PG | Consumer staples in slowdown | Tier 1 | Historical CAGR captures slowdown; market may price recovery |
| GOOGL | Big tech | Tier 1 | Large reverse DCF gap; market prices growth optionality |
| MSFT | Big tech | Tier 1 | Large reverse DCF gap; AI premium visible |
| AAPL | Big tech with outlier year | Tier 1 | Outlier year plus premium valuation |
| NESN.SW | Consumer staples in slowdown | Tier 1 | Deeper slowdown case than PG |
| NESTE.HE | Cyclical plus transformation | Tier 4 | Multiples fallback after DCF tiers fail |
| BAC | Bank / financial institution | Tier 1, flagged | Critical warning: operating-company DCF not applicable |

## Architecture Decisions Worth Recording

1. **Two parallel sanity-check pipelines.** `run_sanity_checks()` handles Streamlit gating. `build_excel_sanity_checks()` writes Excel-only analyst observations.
2. **DCF logic is centralized in `valuation.py`.** Streamlit and Excel consume valuation results rather than maintaining separate valuation engines.
3. **Excel auditability is selective and intentional.** Beta, CAPM, and WACC sheets use Excel formulas where auditability matters. DCF tier outputs are written as report values generated by the Python valuation engine.
4. **Manual sector override is a first-class feature.** It is not a workaround; it is how the user applies analyst judgment when automated classification is uncertain.
5. **Critical-severity sanity checks gate Excel generation by default.** The user can override, but the friction is deliberate.

## What This Project Is Not

EquityLens is not a fund-grade valuation system. Specifically:

- It does not run Monte Carlo simulations or probability-weighted scenarios.
- It does not implement a fade period between explicit forecast growth and terminal growth.
- It does not include an external-estimate-driven DCF tier.
- It does not value banks, REITs, or insurers with their proper sector-specific models.
- It relies on yfinance data availability and therefore inherits yfinance data gaps.

These are deliberate scope choices for a portfolio-grade demonstration of equity research and FP&A reasoning, not omissions due to lack of awareness.

## Closing Note

The most important learning from this project is not about DCF mechanics or Damodaran filenames. It is about the difference between a model that produces a number and a tool that helps an analyst think.

The first version of this app produced numbers. The current version produces numbers, context, and honest warnings about when those numbers are unreliable. Reverse DCF, analyst-level sanity checks, business model compatibility warnings, and manual sector override all follow the same principle: surface uncertainty rather than hide it.

For an equity research role, that principle matters more than any single valuation result.
