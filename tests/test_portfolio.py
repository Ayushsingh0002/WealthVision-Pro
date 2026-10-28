"""
tests/test_portfolio.py — Unit tests for portfolio.py calculations.

All tests use synthetic data; no network calls are made.
"""

import sys
import os

# Ensure the project root is on the path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

import portfolio as pm


# ---------------------------------------------------------------------------
# Helpers: build synthetic market-data dicts
# ---------------------------------------------------------------------------

def _make_history(prices: list[float]) -> pd.DataFrame:
    """Create a minimal history DataFrame with a Close column."""
    dates = pd.date_range("2024-01-01", periods=len(prices), freq="B")
    df = pd.DataFrame({"Close": prices, "Open": prices,
                       "High": prices, "Low": prices, "Volume": 1000},
                      index=dates)
    return df


def _make_stock(symbol: str, price: float, history_prices: list[float]) -> dict:
    hist = _make_history(history_prices)
    returns = pd.Series(history_prices).pct_change().dropna()
    vol = float(returns.std() * np.sqrt(252) * 100) if len(returns) > 1 else 0.0
    prev = history_prices[-2] if len(history_prices) >= 2 else price
    chg_pct = (price - prev) / prev * 100 if prev != 0 else 0.0
    return {
        "symbol": symbol,
        "name": symbol,
        "price": price,
        "prev_close": prev,
        "change_pct": chg_pct,
        "sector": "Technology",
        "volatility": vol,
        "sharpe": 0.8,
        "market_cap": 1e12,
        "pe_ratio": 25.0,
        "dividend_yield": 0.0,
        "high_52w": max(history_prices),
        "low_52w": min(history_prices),
        "position_52w": 50.0,
        "history": hist,
        "fetched_at": "2024-01-01T00:00:00+00:00",
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestBuildHoldings:

    def test_total_value_calculation(self):
        """total value = shares × price for each holding."""
        prices_aapl = [100.0 + i for i in range(60)]
        prices_msft = [200.0 + i * 0.5 for i in range(60)]

        stock_data = {
            "AAPL": _make_stock("AAPL", 159.0, prices_aapl),
            "MSFT": _make_stock("MSFT", 229.5, prices_msft),
        }
        raw = [
            {"symbol": "AAPL", "shares": 10.0, "cost_basis": 100.0, "id": 1},
            {"symbol": "MSFT", "shares": 5.0,  "cost_basis": 200.0, "id": 2},
        ]
        holdings = pm.build_holdings(raw, stock_data)
        assert len(holdings) == 2

        aapl_h = next(h for h in holdings if h["symbol"] == "AAPL")
        msft_h = next(h for h in holdings if h["symbol"] == "MSFT")

        assert abs(aapl_h["value"] - 10.0 * 159.0) < 0.01
        assert abs(msft_h["value"] - 5.0 * 229.5) < 0.01

    def test_pnl_calculation(self):
        """P&L = value − cost; P&L% = P&L / cost × 100."""
        prices = [100.0 + i for i in range(60)]
        stock_data = {"AAPL": _make_stock("AAPL", 159.0, prices)}
        raw = [{"symbol": "AAPL", "shares": 10.0, "cost_basis": 120.0, "id": 1}]

        holdings = pm.build_holdings(raw, stock_data)
        h = holdings[0]

        expected_cost = 10.0 * 120.0
        expected_pnl  = 10.0 * 159.0 - expected_cost
        expected_pct  = expected_pnl / expected_cost * 100

        assert abs(h["cost"]    - expected_cost) < 0.01
        assert abs(h["pnl"]     - expected_pnl)  < 0.01
        assert abs(h["pnl_pct"] - expected_pct)  < 0.01

    def test_skips_missing_data(self):
        """Holdings with no market data are silently skipped."""
        stock_data = {"AAPL": None}
        raw = [{"symbol": "AAPL", "shares": 10.0, "cost_basis": 100.0, "id": 1}]
        holdings = pm.build_holdings(raw, stock_data)
        assert holdings == []

    def test_empty_portfolio(self):
        """build_portfolio_summary returns None for an empty list."""
        result = pm.build_portfolio_summary([])
        assert result is None


class TestBuildPortfolioSummary:

    def _two_holding_summary(self):
        prices_a = [100.0 * (1 + 0.001 * i) for i in range(252)]
        prices_b = [200.0 * (1 + 0.002 * i) for i in range(252)]
        stock_data = {
            "AAPL": _make_stock("AAPL", prices_a[-1], prices_a),
            "MSFT": _make_stock("MSFT", prices_b[-1], prices_b),
        }
        raw = [
            {"symbol": "AAPL", "shares": 10.0, "cost_basis": 100.0, "id": 1},
            {"symbol": "MSFT", "shares": 5.0,  "cost_basis": 200.0, "id": 2},
        ]
        holdings = pm.build_holdings(raw, stock_data)
        return pm.build_portfolio_summary(holdings)

    def test_weights_sum_to_100(self):
        summary = self._two_holding_summary()
        total_weight = sum(h["weight"] for h in summary["holdings"])
        assert abs(total_weight - 100.0) < 0.01

    def test_total_value_matches_sum(self):
        summary = self._two_holding_summary()
        sum_values = sum(h["value"] for h in summary["holdings"])
        assert abs(summary["total_value"] - sum_values) < 0.01

    def test_portfolio_volatility_covariance(self):
        """
        Portfolio volatility computed via covariance must be >= 0 and
        less than the max individual vol (due to diversification).
        """
        summary = self._two_holding_summary()
        port_vol = summary["volatility"]
        max_individual_vol = max(h["volatility"] for h in summary["holdings"])
        assert port_vol >= 0
        # Diversified portfolio should be <= max individual vol
        assert port_vol <= max_individual_vol + 1.0  # small tolerance

    def test_risk_score_in_range(self):
        summary = self._two_holding_summary()
        assert 0 <= summary["risk_score"] <= 100

    def test_sectors_present(self):
        summary = self._two_holding_summary()
        assert isinstance(summary["sectors"], dict)
        assert len(summary["sectors"]) >= 1

    def test_history_dataframe(self):
        summary = self._two_holding_summary()
        hist = summary["history"]
        assert isinstance(hist, pd.DataFrame)
        assert "date" in hist.columns
        assert "value" in hist.columns
        assert len(hist) >= 5


class TestMaxDrawdown:

    def test_no_drawdown(self):
        """Monotonically increasing series has zero drawdown."""
        values = pd.DataFrame({"date": range(5), "value": [100, 110, 120, 130, 140]})
        mdd = pm._max_drawdown_from_history(values)
        assert mdd == pytest.approx(0.0, abs=1e-6)

    def test_known_drawdown(self):
        """
        Series: 100, 120, 80, 90 — peak is 120, trough is 80.
        Max drawdown = (80 − 120) / 120 = −33.3%
        """
        values = pd.DataFrame({"date": range(4), "value": [100.0, 120.0, 80.0, 90.0]})
        mdd = pm._max_drawdown_from_history(values)
        expected = (80 - 120) / 120  # ≈ -0.3333
        assert abs(mdd - expected) < 0.001

    def test_empty_returns_zero(self):
        empty = pd.DataFrame(columns=["date", "value"])
        assert pm._max_drawdown_from_history(empty) == 0.0
