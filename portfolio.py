"""
portfolio.py — Portfolio-level financial calculations for WealthVision Pro.

All functions accept pre-fetched data (no network calls here).
Uses correct covariance-matrix-based volatility and proper Sharpe ratio.
"""

import warnings
from typing import Optional

import numpy as np
import pandas as pd

# Risk profile thresholds (matches app1.py RISK_PROFILES)
RISK_PROFILES: dict[str, dict] = {
    "Conservative": {"range": (0, 30),   "color": "#10b981", "desc": "Capital preservation focused"},
    "Moderate":     {"range": (30, 60),  "color": "#f59e0b", "desc": "Balanced growth strategy"},
    "Aggressive":   {"range": (60, 100), "color": "#ef4444", "desc": "High growth, high volatility"},
}

RISK_FREE_RATE: float = 0.04  # 4 % annualised


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_holdings(
    raw_positions: list[dict],
    stock_data: dict[str, Optional[dict]],
) -> list[dict]:
    """
    Merge database holding rows with live market data into enriched dicts.

    raw_positions : [{"symbol": str, "shares": float, "cost_basis": float}, ...]
    stock_data    : {"AAPL": {<market_data return>}, "MSFT": None, ...}

    For each position where stock_data[symbol] is not None, compute:
        value     = shares × price
        cost      = shares × cost_basis
        pnl       = value − cost
        pnl_pct   = pnl / cost × 100  (0 if cost == 0)
        daily_pnl = shares × price × (change_pct / 100)
        weight    = 0.0  (filled later by build_portfolio_summary)

    Skips positions where stock_data[symbol] is None and emits a warning.
    Returns the list of augmented holding dicts.
    """
    holdings: list[dict] = []

    for pos in raw_positions:
        symbol = str(pos.get("symbol", "")).strip().upper()
        data = stock_data.get(symbol)

        if data is None:
            warnings.warn(f"[portfolio] No data for {symbol} — skipping.")
            continue

        shares: float = float(pos.get("shares", 0))
        cost_basis: float = float(pos.get("cost_basis", 0))

        if shares <= 0 or cost_basis <= 0:
            warnings.warn(f"[portfolio] Invalid shares/cost_basis for {symbol} — skipping.")
            continue

        price: float = data["price"]
        change_pct: float = data.get("change_pct", 0.0)

        value = shares * price
        cost = shares * cost_basis
        pnl = value - cost
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0.0
        daily_pnl = shares * price * (change_pct / 100)

        holding = {
            # From DB
            "id": pos.get("id"),
            "symbol": symbol,
            "shares": shares,
            "cost_basis": cost_basis,
            # From market data
            "name": data.get("name", symbol),
            "price": price,
            "prev_close": data.get("prev_close", price),
            "change_pct": change_pct,
            "sector": data.get("sector", "Other"),
            "volatility": data.get("volatility", 0.0),
            "sharpe": data.get("sharpe", 0.0),
            "market_cap": data.get("market_cap", 0),
            "pe_ratio": data.get("pe_ratio", 0),
            "dividend_yield": data.get("dividend_yield", 0),
            "high_52w": data.get("high_52w", price),
            "low_52w": data.get("low_52w", price),
            "position_52w": data.get("position_52w", 50.0),
            "history": data.get("history"),
            "fetched_at": data.get("fetched_at"),
            # Calculated
            "value": value,
            "cost": cost,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "daily_pnl": daily_pnl,
            "weight": 0.0,  # filled by build_portfolio_summary
        }
        holdings.append(holding)

    return holdings


def build_portfolio_summary(holdings: list[dict]) -> Optional[dict]:
    """
    Build a complete portfolio-level summary from an enriched holdings list.

    Steps:
    1. Fill weight for each holding.
    2. Compute covariance-matrix-based portfolio volatility.
    3. Compute portfolio-level Sharpe ratio from aligned daily returns.
    4. Compute max drawdown from the portfolio value series.
    5. Compute risk score and risk profile.
    6. Build sector breakdown dict.
    7. Build historical portfolio-value DataFrame.

    Returns None if holdings is empty.
    """
    if not holdings:
        return None

    # --- 1. Totals and weights ---
    total_value: float = sum(h["value"] for h in holdings)
    total_cost: float = sum(h["cost"] for h in holdings)
    total_pnl: float = total_value - total_cost
    total_pnl_pct: float = (total_pnl / total_cost * 100) if total_cost > 0 else 0.0
    daily_pnl: float = sum(h["daily_pnl"] for h in holdings)

    for h in holdings:
        h["weight"] = (h["value"] / total_value * 100) if total_value > 0 else 0.0

    # --- 2. Covariance-based portfolio volatility ---
    port_volatility, cov_matrix, aligned_returns = _covariance_volatility(holdings)

    # --- 3. Portfolio Sharpe from aligned daily returns ---
    port_sharpe = _portfolio_sharpe(aligned_returns)

    # --- 4. Historical portfolio-value series ---
    port_history_df = _build_history(holdings)

    # --- 5. Max drawdown ---
    max_dd = _max_drawdown_from_history(port_history_df)

    # --- 6. Risk score ---
    max_weight = max(h["weight"] for h in holdings)
    sector_count = len(set(h["sector"] for h in holdings))
    vols = [h["volatility"] for h in holdings if h["volatility"] > 0]
    avg_vol = float(np.mean(vols)) if vols else 0.0

    risk_score = int(
        np.clip(
            max_weight * 1.2 + avg_vol * 0.8 - sector_count * 4 + (10 if max_weight > 25 else 0),
            0, 100,
        )
    )

    risk_profile = _risk_profile_for_score(risk_score)

    # --- 7. Sector breakdown ---
    sectors: dict[str, float] = {}
    for h in holdings:
        sectors[h["sector"]] = sectors.get(h["sector"], 0.0) + h["value"]

    return {
        "holdings": holdings,
        "total_value": total_value,
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "total_pnl_pct": total_pnl_pct,
        "daily_pnl": daily_pnl,
        "volatility": port_volatility,
        "sharpe": port_sharpe,
        "max_drawdown": max_dd,
        "risk_score": risk_score,
        "risk_profile": risk_profile,
        "sectors": sectors,
        "history": port_history_df,
        "cov_matrix": cov_matrix,
        "aligned_returns": aligned_returns,
    }


def compute_historical_returns(portfolio_summary: dict) -> Optional[pd.Series]:
    """
    Derive the portfolio daily-return series from portfolio_summary["history"].
    Returns a pd.Series indexed by date, or None if fewer than 20 data points.
    """
    hist = portfolio_summary.get("history")
    if hist is None or len(hist) < 20:
        return None

    values = hist.set_index("date")["value"] if "date" in hist.columns else hist["value"]
    returns = values.pct_change().dropna()
    if len(returns) < 20:
        return None
    return returns


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _covariance_volatility(
    holdings: list[dict],
) -> tuple[float, Optional[pd.DataFrame], Optional[pd.DataFrame]]:
    """
    Compute portfolio annualised volatility via the covariance matrix.

    Returns (volatility_pct, cov_matrix_df, aligned_returns_df).
    Falls back to weighted-average volatility if < 2 holdings have history.
    """
    close_dict: dict[str, pd.Series] = {}
    for h in holdings:
        hist = h.get("history")
        if hist is not None and len(hist) >= 30:
            close_dict[h["symbol"]] = hist["Close"]

    if len(close_dict) < 2:
        # Fallback: weighted average of individual annualised vols
        weights = np.array([h["weight"] / 100 for h in holdings])
        vols = np.array([h["volatility"] for h in holdings])
        vol = float(np.sqrt(np.dot(weights ** 2, vols ** 2)))
        return vol, None, None

    price_df = pd.DataFrame(close_dict)
    price_df = price_df.dropna()
    returns_df = price_df.pct_change().dropna()

    if len(returns_df) < 30:
        # Still not enough: weighted fallback
        weights = np.array([h["weight"] / 100 for h in holdings])
        vols = np.array([h["volatility"] for h in holdings])
        vol = float(np.sqrt(np.dot(weights ** 2, vols ** 2)))
        return vol, None, None

    cov = returns_df.cov() * 252  # annualised covariance

    # Weights in same column order as returns_df
    sym_order = list(returns_df.columns)
    weight_map = {h["symbol"]: h["weight"] / 100 for h in holdings}
    w = np.array([weight_map.get(s, 0.0) for s in sym_order])

    # Re-normalise in case some symbols dropped out
    if w.sum() > 0:
        w = w / w.sum()

    port_var = float(w @ cov.values @ w)
    port_vol = float(np.sqrt(max(port_var, 0)) * 100)

    return port_vol, cov, returns_df


def _portfolio_sharpe(aligned_returns: Optional[pd.DataFrame]) -> float:
    """
    Portfolio Sharpe ratio from aligned daily returns DataFrame.
    Returns 0.0 if insufficient data.
    """
    if aligned_returns is None or len(aligned_returns) < 30:
        return 0.0

    # Equal weight if we don't have the weights here — caller can override
    n = aligned_returns.shape[1]
    w = np.ones(n) / n
    port_daily = aligned_returns.values @ w
    port_annual_return = float(port_daily.mean() * 252)
    port_annual_vol = float(port_daily.std() * np.sqrt(252))

    if port_annual_vol <= 0:
        return 0.0
    sharpe = (port_annual_return - RISK_FREE_RATE) / port_annual_vol
    return float(np.nan_to_num(sharpe, nan=0.0))


def _build_history(holdings: list[dict]) -> pd.DataFrame:
    """
    Build a historical portfolio-value DataFrame with columns [date, value].
    Aligns all holdings on common trading days.
    """
    close_dict: dict[str, pd.Series] = {}
    shares_map: dict[str, float] = {}

    for h in holdings:
        hist = h.get("history")
        if hist is not None and len(hist) >= 2:
            close_dict[h["symbol"]] = hist["Close"]
            shares_map[h["symbol"]] = h["shares"]

    if not close_dict:
        return pd.DataFrame(columns=["date", "value"])

    price_df = pd.DataFrame(close_dict).dropna()
    if price_df.empty:
        return pd.DataFrame(columns=["date", "value"])

    shares_vec = np.array([shares_map[s] for s in price_df.columns])
    port_values = price_df.values @ shares_vec

    df = pd.DataFrame({"date": price_df.index, "value": port_values})
    df = df.reset_index(drop=True)
    return df


def _max_drawdown_from_history(history_df: pd.DataFrame) -> float:
    """
    Compute max drawdown (negative %) from the portfolio value series.
    Returns 0.0 if insufficient data.
    """
    if history_df is None or len(history_df) < 2:
        return 0.0

    values = history_df["value"].values.astype(float)
    if len(values) < 2:
        return 0.0

    peak = np.maximum.accumulate(values)
    with np.errstate(invalid="ignore", divide="ignore"):
        drawdown = np.where(peak > 0, (values - peak) / peak, 0.0)
    return float(np.nanmin(drawdown))


def _risk_profile_for_score(score: int) -> str:
    """Map a risk score to a profile name."""
    for name, cfg in RISK_PROFILES.items():
        lo, hi = cfg["range"]
        if lo <= score < hi:
            return name
    return "Aggressive"
