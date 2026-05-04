# Financial Analyzer

Streamlit application for fetching public company financial statements from Yahoo Finance with `yfinance` and visualizing income statement, balance sheet, cash flow, KPIs, and company comparisons.

This project is designed for accounting and corporate finance studies. It supports Nasdaq Helsinki tickers such as `KNEBV.HE` and US tickers such as `AAPL`, `MSFT`, and `NVDA`.

## Features

- Company profile: name, industry, country, market capitalization, and business description
- Income statement analysis: revenue, gross profit, EBITDA, EBIT, net income, and margins
- Balance sheet analysis: assets, liabilities, equity, equity ratio, debt, and net debt
- Cash flow analysis: operating cash flow, capital expenditure, and free cash flow
- KPI dashboard: ROE, ROCE, P/E, and EV/EBITDA
- Analyst overview: growth, margins, cash conversion, leverage, and scorecard
- Dividend history: dividend per share, payout ratio, and dividend yield
- Earnings surprise view when Yahoo Finance provides analyst estimate data
- Scenario analysis calculator for revenue growth and EPS impact
- PDF report export
- PNG chart downloads through the Plotly chart toolbar
- Side-by-side comparison for two companies
- Radar comparison for key peer metrics
- Clear error messages when a ticker cannot be found
- Streamlit loading spinner while data is fetched

## Project Structure

```text
financial_analyzer/
├── app.py
├── requirements.txt
├── utils/
│   ├── __init__.py
│   ├── fetcher.py
│   ├── calculations.py
│   └── visualizations.py
└── README.md
```

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
```

Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

macOS or Linux:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

If you already installed the earlier version, run the same command again because PDF export adds `reportlab`.

## Run the App

From the `financial_analyzer` folder:

```bash
streamlit run app.py
```

Open the local URL shown by Streamlit, usually:

```text
http://localhost:8501
```

## Example Tickers

- `KNEBV.HE` - Kone Oyj
- `NOKIA.HE` - Nokia Oyj
- `AAPL` - Apple Inc.
- `MSFT` - Microsoft Corporation
- `6484.T` - Tokyo Stock Exchange example, data availability may vary

## Notes About Data

The application uses Yahoo Finance through `yfinance`, which is free and does not require an API key. Data availability, line item names, currencies, and reporting periods depend on Yahoo Finance. The app displays monetary statement values in millions using the original `financialCurrency` reported by Yahoo Finance, such as `M EUR`, `M USD`, or `M SEK`; it does not convert currencies automatically.

## Disclaimer

Tämä on opiskelutarkoituksiin tehty työkalu, ei sijoitusneuvonta.
