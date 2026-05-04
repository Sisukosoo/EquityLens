"""Data fetching helpers for Yahoo Finance financial statements."""

from __future__ import annotations

import pandas as pd
import yfinance as yf


class FinancialDataError(Exception):
    """Raised when financial data cannot be fetched or validated."""


def _normalize_ticker(ticker: str) -> str:
    """Normalize user ticker input."""
    return ticker.strip().upper()


def _limit_annual_columns(statement: pd.DataFrame, years: int = 5) -> pd.DataFrame:
    """Keep the latest annual columns and order them from oldest to newest."""
    if statement is None or statement.empty:
        return pd.DataFrame()

    cleaned = statement.copy()
    cleaned.columns = pd.to_datetime(cleaned.columns, errors="coerce")
    cleaned = cleaned.loc[:, cleaned.columns.notna()]

    if cleaned.empty:
        return pd.DataFrame()

    latest_columns = sorted(cleaned.columns, reverse=True)[:years]
    return cleaned.loc[:, sorted(latest_columns)]


def _fetch_statement(ticker_obj: yf.Ticker, statement_name: str) -> pd.DataFrame:
    """Fetch one yearly statement with a property fallback."""
    statement = pd.DataFrame()
    fallback = pd.DataFrame()

    try:
        if statement_name == "income":
            statement = ticker_obj.get_income_stmt(freq="yearly")
        elif statement_name == "balance":
            statement = ticker_obj.get_balance_sheet(freq="yearly")
        elif statement_name == "cash":
            statement = ticker_obj.get_cash_flow(freq="yearly")
        else:
            raise ValueError(f"Unknown statement: {statement_name}")
    except Exception:
        statement = pd.DataFrame()

    try:
        if statement_name == "income":
            fallback = ticker_obj.financials
        elif statement_name == "balance":
            fallback = ticker_obj.balance_sheet
        elif statement_name == "cash":
            fallback = ticker_obj.cashflow
    except Exception:
        fallback = pd.DataFrame()

    if statement is None or statement.empty:
        statement = fallback

    return _limit_annual_columns(statement)


def _fetch_dividends(ticker_obj: yf.Ticker, years: int = 8) -> pd.Series:
    """Fetch dividend history and keep the latest annual observations."""
    try:
        dividends = ticker_obj.dividends
    except Exception:
        return pd.Series(dtype=float)

    if dividends is None or dividends.empty:
        return pd.Series(dtype=float)

    dividends.index = pd.to_datetime(dividends.index, errors="coerce")
    dividends = dividends.loc[dividends.index.notna()]
    annual_dividends = dividends.groupby(dividends.index.year).sum()
    return annual_dividends.tail(years)


def _fetch_earnings_surprises(ticker_obj: yf.Ticker) -> pd.DataFrame:
    """Fetch available analyst EPS surprise data from Yahoo Finance."""
    try:
        earnings_dates = ticker_obj.get_earnings_dates(limit=12)
    except Exception:
        return pd.DataFrame()

    if earnings_dates is None or earnings_dates.empty:
        return pd.DataFrame()

    frame = earnings_dates.reset_index()
    frame.columns = [str(column) for column in frame.columns]
    return frame


def fetch_company_financials(ticker: str) -> dict:
    """Fetch company info and annual financial statements from Yahoo Finance."""
    normalized_ticker = _normalize_ticker(ticker)
    if not normalized_ticker:
        raise FinancialDataError("Ticker symbol is required.")

    ticker_obj = yf.Ticker(normalized_ticker)

    try:
        info = ticker_obj.info or {}
    except Exception as exc:
        raise FinancialDataError(
            f"Could not fetch company information for '{normalized_ticker}'."
        ) from exc

    if not info or (not info.get("longName") and not info.get("shortName")):
        raise FinancialDataError(
            f"Ticker '{normalized_ticker}' was not found. Check the symbol and exchange suffix."
        )

    income_statement = _fetch_statement(ticker_obj, "income")
    balance_sheet = _fetch_statement(ticker_obj, "balance")
    cash_flow = _fetch_statement(ticker_obj, "cash")
    dividends = _fetch_dividends(ticker_obj)
    earnings_surprises = _fetch_earnings_surprises(ticker_obj)

    if income_statement.empty and balance_sheet.empty and cash_flow.empty:
        raise FinancialDataError(
            f"No annual financial statements were found for '{normalized_ticker}'."
        )

    return {
        "ticker": normalized_ticker,
        "info": info,
        "income_statement": income_statement,
        "balance_sheet": balance_sheet,
        "cash_flow": cash_flow,
        "dividends": dividends,
        "earnings_surprises": earnings_surprises,
    }
