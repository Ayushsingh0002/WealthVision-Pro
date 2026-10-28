"""
market_data.py — yfinance wrapper for WealthVision Pro.

Provides caching, ticker validation, error handling, and a benchmark feed.
Data is end-of-day / delayed — never labeled as real-time.
"""

import warnings
import re
from datetime import datetime, timezone, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CACHE_TTL_SECONDS: int = 300  # 5 minutes

SECTOR_MAP: dict[str, str] = {
    "Technology": "Technology",
    "Healthcare": "Healthcare",
    "Financial Services": "Finance",
    "Finance": "Finance",
    "Consumer Cyclical": "Consumer",
    "Consumer Defensive": "Consumer",
    "Energy": "Energy",
    "Industrials": "Industrial",
    "Basic Materials": "Materials",
    "Utilities": "Utilities",
    "Real Estate": "Real Estate",
    "Communication Services": "Technology",
}

RISK_FREE_RATE: float = 0.04  # 4% annualised (US T-bill proxy)

# ---------------------------------------------------------------------------
# Module-level cache: { (symbol, period): {"data": dict, "fetched_at": datetime} }
# ---------------------------------------------------------------------------
_CACHE: dict[tuple, dict] = {}
_VALIDATION_CACHE: dict[str, tuple[bool, datetime]] = {}
_VALIDATION_TTL = timedelta(hours=1)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_stock_data(symbol: str, period: str = "1y") -> Optional[dict]:
    """
    Fetch OHLCV + metadata for *symbol* over *period*.

    Returns a dict on success, None on any failure.  Data is labelled as
    delayed/EOD — never real-time.

    Return keys:
        symbol, name, price, prev_close, change_pct, sector, volatility,
        sharpe, market_cap, pe_ratio, dividend_yield, high_52w, low_52w,
        position_52w, history (DataFrame), fetched_at (ISO-8601 UTC str)
    """
    symbol = symbol.strip().upper()
    cache_key = (symbol, period)

    # --- cache hit? ---
    entry = _CACHE.get(cache_key)
    if entry:
        age = (datetime.now(timezone.utc) - entry["fetched_at"]).total_seconds()
        if age < CACHE_TTL_SECONDS:
            return entry["data"]

    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period=period, auto_adjust=True)

        if hist is None or len(hist) < 10:
            warnings.warn(f"[market_data] Insufficient history for {symbol}")
            return None

        # Ensure the index is timezone-naive for consistent downstream handling
        if hist.index.tz is not None:
            hist.index = hist.index.tz_localize(None)

        info: dict = {}
        try:
            info = ticker.info or {}
        except Exception:
            pass  # info is optional; fall back to defaults

        price = float(hist["Close"].iloc[-1])
        prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price

        change_pct = ((price - prev_close) / prev_close * 100) if prev_close != 0 else 0.0

        returns = hist["Close"].pct_change().dropna()
        vol_annualised = float(returns.std() * np.sqrt(252) * 100) if len(returns) > 1 else 0.0

        mean_daily = float(returns.mean()) if len(returns) > 1 else 0.0
        std_daily = float(returns.std()) if len(returns) > 1 else 1.0
        if std_daily > 0:
            sharpe = float(
                np.nan_to_num(
                    (mean_daily * 252 - RISK_FREE_RATE) / (std_daily * np.sqrt(252)),
                    nan=0.0,
                )
            )
        else:
            sharpe = 0.0

        raw_sector = info.get("sector", "Other") or "Other"
        sector = SECTOR_MAP.get(raw_sector, "Other")

        high_52w = float(hist["High"].max())
        low_52w = float(hist["Low"].min())
        rng = high_52w - low_52w
        position_52w = float((price - low_52w) / rng * 100) if rng > 0 else 50.0

        div_yield_raw = info.get("dividendYield") or 0
        dividend_yield = float(div_yield_raw) * 100 if div_yield_raw else 0.0

        fetched_at = datetime.now(timezone.utc)

        data = {
            "symbol": symbol,
            "name": info.get("shortName") or symbol,
            "price": price,
            "prev_close": prev_close,
            "change_pct": change_pct,
            "sector": sector,
            "volatility": vol_annualised,
            "sharpe": sharpe,
            "market_cap": float(info.get("marketCap") or 0),
            "pe_ratio": float(info.get("trailingPE") or 0),
            "dividend_yield": dividend_yield,
            "high_52w": high_52w,
            "low_52w": low_52w,
            "position_52w": position_52w,
            "history": hist,
            "fetched_at": fetched_at.isoformat(),
        }

        _CACHE[cache_key] = {"data": data, "fetched_at": fetched_at}
        return data

    except Exception as exc:
        warnings.warn(f"[market_data] Failed to fetch {symbol}: {exc}")
        return None


def validate_ticker(symbol: str) -> bool:
    """
    Return True if *symbol* is structurally valid AND yfinance returns data.

    Accepts:
      - Plain US tickers:        AAPL, MSFT, BTC-USD
      - Indian NSE tickers:      HDFCBANK.NS, TCS.NS
      - Indian BSE tickers:      HDFCBANK.BO, RELIANCE.BO
      - Other exchange suffixes: e.g. .L (London), .HK (Hong Kong)
      - Crypto pairs:            BTC-USD, ETH-USD

    Results are cached for 1 hour to avoid repeated network calls.
    Returns False on any exception.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        return False

    # Structural check: letters/digits, optionally followed by . or - and more chars
    # Covers: AAPL, HDFCBANK.NS, BTC-USD, 0700.HK
    if not re.fullmatch(r"[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,6})?", symbol):
        return False

    # Check validation cache
    cached = _VALIDATION_CACHE.get(symbol)
    if cached:
        result, ts = cached
        if datetime.now(timezone.utc) - ts < _VALIDATION_TTL:
            return result

    try:
        hist = yf.Ticker(symbol).history(period="5d", auto_adjust=True)
        valid = hist is not None and len(hist) >= 1
    except Exception:
        valid = False

    _VALIDATION_CACHE[symbol] = (valid, datetime.now(timezone.utc))
    return valid


def clear_cache(symbol: Optional[str] = None) -> None:
    """
    Clear the data cache.
    If *symbol* is given, remove all entries for that symbol.
    If *symbol* is None, clear the entire cache.
    """
    global _CACHE
    if symbol is None:
        _CACHE = {}
    else:
        sym = symbol.strip().upper()
        keys_to_delete = [k for k in _CACHE if k[0] == sym]
        for k in keys_to_delete:
            del _CACHE[k]


def get_last_fetch_time(symbol: str, period: str = "1y") -> Optional[str]:
    """
    Return the ISO-8601 UTC string of the last successful fetch for
    (symbol, period), or None if not yet fetched.
    """
    entry = _CACHE.get((symbol.strip().upper(), period))
    if entry:
        return entry["fetched_at"].isoformat() if isinstance(entry["fetched_at"], datetime) else str(entry["fetched_at"])
    return None


def fetch_benchmark(period: str = "1y") -> Optional[pd.DataFrame]:
    """
    Fetch SPY (S&P 500 ETF) as a benchmark.
    Returns a DataFrame with columns [date, close, daily_return],
    or None on failure.
    """
    data = fetch_stock_data("SPY", period=period)
    if data is None:
        return None

    hist = data["history"][["Close"]].copy()
    hist.index.name = "date"
    hist = hist.reset_index()
    hist.columns = ["date", "close"]
    hist["daily_return"] = hist["close"].pct_change()
    return hist.dropna()
