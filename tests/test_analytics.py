"""
tests/test_analytics.py — Unit tests for analytics.py risk metrics and insights.

All tests use synthetic data; no network calls are made.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
import pandas as pd
import pytest

import analytics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_returns(n: int = 100, seed: int = 42, mean: float = 0.0005,
                  std: float = 0.015) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(mean, std, n))


def _make_holding(symbol: str, weight: float, vol: float,
                  hist_prices=None, sector: str = "Technology") -> dict:
    if hist_prices is None:
        hist_prices = [100.0 + i for i in range(252)]
    dates = pd.date_range("2023-01-01", periods=len(hist_prices), freq="B")
    hist = pd.DataFrame({"Close": hist_prices}, index=dates)
    returns = pd.Series(hist_prices).pct_change().dropna()
    sharpe = float((returns.mean() * 252 - 0.04) / (returns.std() * np.sqrt(252) + 1e-9))
    return {
        "symbol": symbol,
        "weight": weight,
        "volatility": vol,
        "sharpe": sharpe,
        "sector": sector,
        "history": hist,
        "value": weight * 10000,
        "cost": weight * 9000,
        "pnl": weight * 1000,
        "pnl_pct": 11.1,
        "shares": 10.0,
        "price": weight * 1000,
    }


# ---------------------------------------------------------------------------
# VaR / CVaR
# ---------------------------------------------------------------------------

class TestVaRCVaR:

    def test_var_95_is_negative(self):
        returns = _make_returns(200)
        var = analytics.historical_var(returns, confidence=0.95)
        assert var < 0

    def test_var_95_known_value(self):
        """With a known distribution, VaR should be near 5th percentile."""
        rng = np.random.default_rng(0)
        returns = pd.Series(rng.normal(0, 0.01, 1000))
        var = analytics.historical_var(returns, 0.95)
        p5 = float(np.percentile(returns, 5))
        assert abs(var - p5) < 1e-10

    def test_insufficient_data_returns_zero(self):
        short = _make_returns(20)
        assert analytics.historical_var(short) == 0.0
        assert analytics.conditional_var(short) == 0.0

    def test_cvar_is_less_than_or_equal_var(self):
        """CVaR (expected shortfall) should be <= VaR (more extreme)."""
        returns = _make_returns(500)
        var  = analytics.historical_var(returns)
        cvar = analytics.conditional_var(returns)
        assert cvar <= var


# ---------------------------------------------------------------------------
# Max drawdown
# ---------------------------------------------------------------------------

class TestMaxDrawdown:

    def test_no_drawdown_monotone(self):
        series = pd.Series([1.0, 1.05, 1.10, 1.15, 1.20])
        assert analytics.max_drawdown(series) == pytest.approx(0.0, abs=1e-6)

    def test_known_drawdown(self):
        """Peak=1.20 at idx 1, trough=0.80 at idx 2 → MDD = (0.80−1.20)/1.20"""
        series = pd.Series([1.0, 1.20, 0.80, 0.90])
        mdd = analytics.max_drawdown(series)
        expected = (0.80 - 1.20) / 1.20
        assert abs(mdd - expected) < 1e-6

    def test_empty_returns_zero(self):
        assert analytics.max_drawdown(pd.Series([])) == 0.0

    def test_single_element_returns_zero(self):
        assert analytics.max_drawdown(pd.Series([1.0])) == 0.0


# ---------------------------------------------------------------------------
# Correlation matrix
# ---------------------------------------------------------------------------

class TestCorrelationMatrix:

    def test_two_holdings_shape(self):
        h1 = _make_holding("AAPL", 50, 20)
        h2 = _make_holding("MSFT", 50, 25)
        corr = analytics.correlation_matrix([h1, h2])
        assert corr is not None
        assert corr.shape == (2, 2)

    def test_diagonal_is_one(self):
        h1 = _make_holding("AAPL", 50, 20)
        h2 = _make_holding("MSFT", 50, 25)
        corr = analytics.correlation_matrix([h1, h2])
        np.testing.assert_allclose(np.diag(corr.values), 1.0, atol=1e-6)

    def test_values_in_range(self):
        h1 = _make_holding("AAPL", 50, 20)
        h2 = _make_holding("MSFT", 50, 25)
        h3 = _make_holding("NVDA", 0,  35, sector="Technology")
        corr = analytics.correlation_matrix([h1, h2, h3])
        assert corr is not None
        assert (corr.values >= -1.0).all()
        assert (corr.values <=  1.0).all()

    def test_insufficient_holdings_returns_none(self):
        h1 = _make_holding("AAPL", 100, 20)
        assert analytics.correlation_matrix([h1]) is None

    def test_insufficient_data_returns_none(self):
        """Holdings with < 30 data points return None."""
        dates = pd.date_range("2024-01-01", periods=10, freq="B")
        short_hist = pd.DataFrame({"Close": [100.0 + i for i in range(10)]}, index=dates)
        h1 = _make_holding("AAPL", 50, 20)
        h1["history"] = short_hist
        h2 = _make_holding("MSFT", 50, 25)
        h2["history"] = short_hist
        result = analytics.correlation_matrix([h1, h2])
        assert result is None


# ---------------------------------------------------------------------------
# Risk contribution
# ---------------------------------------------------------------------------

class TestRiskContribution:

    def test_contributions_sum_to_100(self):
        h1 = _make_holding("AAPL", 60, 20)
        h2 = _make_holding("MSFT", 40, 25)
        symbols = ["AAPL", "MSFT"]
        cov = pd.DataFrame(
            [[0.04, 0.01], [0.01, 0.06]],
            index=symbols, columns=symbols
        )
        rc = analytics.risk_contribution([h1, h2], cov)
        total = sum(rc.values())
        assert abs(total - 100.0) < 0.1

    def test_single_holding_returns_empty(self):
        h1 = _make_holding("AAPL", 100, 20)
        result = analytics.risk_contribution([h1], None)
        assert result == {}

    def test_no_cov_returns_empty(self):
        h1 = _make_holding("AAPL", 60, 20)
        h2 = _make_holding("MSFT", 40, 25)
        result = analytics.risk_contribution([h1, h2], None)
        assert result == {}


# ---------------------------------------------------------------------------
# Insights engine
# ---------------------------------------------------------------------------

class TestGenerateInsights:

    def _make_portfolio(self, holdings, total_value=10000, total_cost=9000,
                        vol=18.0, sharpe=0.9, max_dd=-0.05):
        total_pnl = total_value - total_cost
        return {
            "holdings": holdings,
            "total_value": total_value,
            "total_cost": total_cost,
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / total_cost * 100,
            "volatility": vol,
            "sharpe": sharpe,
            "max_drawdown": max_dd,
        }

    def test_concentration_triggers_warning(self):
        """A single holding > 25% must produce a concentration warning."""
        h1 = _make_holding("AAPL", 80, 20, sector="Technology")  # 80% weight
        h2 = _make_holding("MSFT", 20, 15, sector="Finance")
        port = self._make_portfolio([h1, h2])
        insights = analytics.generate_insights(port)
        types_titles = [(i["type"], i["title"]) for i in insights]
        assert any(t == "warning" and "Concentration" in title
                   for t, title in types_titles)

    def test_no_concentration_warning_for_balanced(self):
        """Equal-weight 5-holding portfolio should not trigger concentration."""
        holdings = [
            _make_holding("AAPL", 20, 18, sector="Technology"),
            _make_holding("MSFT", 20, 20, sector="Finance"),
            _make_holding("JNJ",  20, 12, sector="Healthcare"),
            _make_holding("XOM",  20, 22, sector="Energy"),
            _make_holding("GE",   20, 16, sector="Industrial"),
        ]
        port = self._make_portfolio(holdings, vol=15.0, sharpe=1.2)
        insights = analytics.generate_insights(port)
        assert not any(i["type"] == "warning" and "Concentration Risk" in i["title"]
                       for i in insights)

    def test_always_returns_at_least_one_insight(self):
        h1 = _make_holding("AAPL", 50, 15)
        h2 = _make_holding("MSFT", 50, 18)
        port = self._make_portfolio([h1, h2])
        insights = analytics.generate_insights(port)
        assert len(insights) >= 1

    def test_insight_desc_contains_actual_values(self):
        """Concentration insight description must include the symbol name."""
        h1 = _make_holding("BIGCO", 90, 25, sector="Technology")
        h2 = _make_holding("SMALL", 10, 15, sector="Finance")
        port = self._make_portfolio([h1, h2])
        insights = analytics.generate_insights(port)
        concentration_insights = [i for i in insights if "Concentration" in i["title"]]
        assert concentration_insights
        assert "BIGCO" in concentration_insights[0]["desc"]

    def test_empty_portfolio_returns_info(self):
        port = {"holdings": [], "total_value": 0, "total_cost": 0,
                "total_pnl": 0, "total_pnl_pct": 0,
                "volatility": 0, "sharpe": 0, "max_drawdown": 0}
        insights = analytics.generate_insights(port)
        assert len(insights) == 1
        assert insights[0]["type"] == "info"
