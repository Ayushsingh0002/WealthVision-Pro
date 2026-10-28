"""
analytics.py — Risk metrics, rule-based insights, and optional AI assistant
               for WealthVision Pro.

All financial formulas are documented. Rule-based insights are clearly
labelled as such — no machine-learning models are used or implied.
"""

import os
import warnings
from typing import Optional

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Risk Metrics
# ---------------------------------------------------------------------------

def max_drawdown(cum_returns: pd.Series) -> float:
    """
    Maximum peak-to-trough drawdown.

    cum_returns : Series of cumulative return multipliers (e.g. 1.0, 1.05, 0.97)

    Formula:
        rolling_max = cum_returns.cummax()
        drawdowns   = (cum_returns - rolling_max) / rolling_max
        return min(drawdowns)   # negative, e.g. -0.123

    Returns 0.0 for series with fewer than 2 elements.
    """
    if cum_returns is None or len(cum_returns) < 2:
        return 0.0
    rolling_max = cum_returns.cummax()
    with np.errstate(invalid="ignore", divide="ignore"):
        drawdowns = (cum_returns - rolling_max) / rolling_max.replace(0, np.nan)
    result = float(drawdowns.min())
    return result if np.isfinite(result) else 0.0


def historical_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """
    Historical Value at Risk (1-day, as a fractional loss).

    returns    : Series of daily fractional returns (e.g. 0.012, -0.023)
    confidence : typically 0.95 (95 % confidence)

    Formula:
        VaR = percentile(returns, (1 - confidence) × 100)

    Result is negative, e.g. -0.021 means "95 % VaR is 2.1 %".
    Returns 0.0 if fewer than 30 data points.
    """
    returns = pd.Series(returns).dropna()
    if len(returns) < 30:
        return 0.0
    return float(np.percentile(returns, (1 - confidence) * 100))


def conditional_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """
    Conditional Value at Risk (Expected Shortfall) — mean of returns below VaR.

    Formula:
        threshold = percentile(returns, (1 - confidence) × 100)
        CVaR      = mean(returns[returns <= threshold])

    Returns 0.0 if fewer than 30 data points.
    """
    returns = pd.Series(returns).dropna()
    if len(returns) < 30:
        return 0.0
    threshold = np.percentile(returns, (1 - confidence) * 100)
    tail = returns[returns <= threshold]
    if tail.empty:
        return float(threshold)
    return float(tail.mean())


def correlation_matrix(holdings: list[dict]) -> Optional[pd.DataFrame]:
    """
    Pearson correlation matrix of daily returns for all holdings.

    holdings : list of dicts with keys "symbol" and "history" (DataFrame)

    Returns a square DataFrame labelled by symbol, or None if fewer than
    2 holdings have valid history (≥ 30 common trading days).
    """
    close_dict: dict[str, pd.Series] = {}
    for h in holdings:
        hist = h.get("history")
        if hist is not None and len(hist) >= 30:
            close_dict[h["symbol"]] = hist["Close"]

    if len(close_dict) < 2:
        return None

    price_df = pd.DataFrame(close_dict).dropna()
    returns_df = price_df.pct_change().dropna()

    if len(returns_df) < 30:
        return None

    return returns_df.corr()


def risk_contribution(
    holdings: list[dict], cov_matrix: pd.DataFrame
) -> dict[str, float]:
    """
    Percentage of total portfolio variance contributed by each holding.

    Formula:
        w  = weights vector (matching cov_matrix column order)
        MC = cov_matrix @ w          (marginal contribution)
        RC = w × MC                  (risk contribution)
        RC_pct = RC / sum(RC) × 100

    Returns {"SYMBOL": float, ...}.
    Returns {} if fewer than 2 holdings or cov_matrix is None.
    """
    if cov_matrix is None or len(holdings) < 2:
        return {}

    sym_order = list(cov_matrix.columns)
    weight_map = {h["symbol"]: h["weight"] / 100 for h in holdings}
    w = np.array([weight_map.get(s, 0.0) for s in sym_order])

    if w.sum() <= 0:
        return {}
    w = w / w.sum()  # normalise

    mc = cov_matrix.values @ w
    rc = w * mc
    total_rc = rc.sum()

    if total_rc <= 0:
        return {}

    rc_pct = rc / total_rc * 100
    return {sym: float(pct) for sym, pct in zip(sym_order, rc_pct)}


def annualized_volatility(returns: pd.Series) -> float:
    """
    Annualised volatility = std(daily_returns) × √252 × 100 (percent).
    Returns 0.0 for empty or single-element series.
    """
    returns = pd.Series(returns).dropna()
    if len(returns) < 2:
        return 0.0
    return float(returns.std() * np.sqrt(252) * 100)


# ---------------------------------------------------------------------------
# Rule-Based Insights Engine
# ---------------------------------------------------------------------------

def generate_insights(portfolio: dict) -> list[dict]:
    """
    Analyse *portfolio* using deterministic rules and return a list of
    insight dicts.

    *** RULE-BASED ANALYSIS ONLY — no machine-learning models are used. ***

    Each insight dict has keys: type (warning|success|info), icon, title, desc.
    At least one insight is always returned.
    """
    insights: list[dict] = []
    holdings: list[dict] = portfolio.get("holdings", [])

    if not holdings:
        return [{"type": "info", "icon": "📋", "title": "Empty Portfolio",
                 "desc": "Add holdings to see personalised analysis."}]

    total_value: float  = portfolio.get("total_value", 0)
    total_cost: float   = portfolio.get("total_cost", 0)
    total_pnl: float    = portfolio.get("total_pnl", 0)
    total_pnl_pct: float = portfolio.get("total_pnl_pct", 0)
    port_vol: float     = portfolio.get("volatility", 0)
    port_sharpe: float  = portfolio.get("sharpe", 0)
    max_dd: float       = portfolio.get("max_drawdown", 0)

    max_h  = max(holdings, key=lambda h: h["weight"])
    max_weight = max_h["weight"]
    sector_count = len(set(h["sector"] for h in holdings))

    # Sector totals
    sector_weights: dict[str, float] = {}
    for h in holdings:
        sector_weights[h["sector"]] = sector_weights.get(h["sector"], 0) + h["weight"]

    # 1. Concentration warning
    if max_weight > 25:
        abs_val = max_h["value"]
        insights.append({
            "type": "warning", "icon": "⚠️",
            "title": "Concentration Risk",
            "desc": (
                f"{max_h['symbol']} is {max_weight:.0f}% of your portfolio "
                f"(${abs_val:,.0f}). A single position above 25% significantly "
                "increases single-stock risk."
            ),
        })

    # 2. Sector concentration warning
    top_sector, top_sector_pct = max(sector_weights.items(), key=lambda x: x[1])
    if top_sector_pct > 50:
        insights.append({
            "type": "warning", "icon": "📊",
            "title": f"{top_sector} Concentration",
            "desc": (
                f"{top_sector} accounts for {top_sector_pct:.0f}% of your portfolio. "
                "Consider adding defensive or uncorrelated sectors."
            ),
        })

    # 3. High-volatility stock
    high_vol = [(h["symbol"], h["volatility"]) for h in holdings if h["volatility"] > 50]
    for sym, vol in high_vol:
        insights.append({
            "type": "warning", "icon": "🌊",
            "title": f"High Volatility: {sym}",
            "desc": (
                f"{sym} has annualised volatility of {vol:.1f}%, "
                f"roughly {vol/20:.1f}× the typical S&P 500 level (~20%). "
                "This raises overall portfolio risk."
            ),
        })

    # 4. Max drawdown warning
    if max_dd < -0.20:
        abs_loss = abs(max_dd) * total_value
        insights.append({
            "type": "warning", "icon": "📉",
            "title": "Significant Drawdown",
            "desc": (
                f"Your portfolio has experienced a peak-to-trough drawdown of "
                f"{max_dd*100:.1f}% (approximately ${abs_loss:,.0f} from peak value)."
            ),
        })

    # 5. Negative performance
    if total_pnl_pct < -10:
        insights.append({
            "type": "warning", "icon": "🔴",
            "title": "Portfolio Down",
            "desc": (
                f"Your portfolio is down {total_pnl_pct:.1f}% "
                f"(${abs(total_pnl):,.0f}) on invested capital of ${total_cost:,.0f}."
            ),
        })

    # 6. Poor Sharpe
    if port_sharpe < 0.5 and len(holdings) > 2:
        insights.append({
            "type": "info", "icon": "📐",
            "title": "Low Sharpe Ratio",
            "desc": (
                f"Portfolio Sharpe ratio is {port_sharpe:.2f}. "
                "A ratio below 0.5 suggests returns may not justify the risk taken."
            ),
        })

    # 7. Low diversification
    if sector_count < 3:
        insights.append({
            "type": "warning", "icon": "🎯",
            "title": "Low Diversification",
            "desc": (
                f"Portfolio spans only {sector_count} sector(s). "
                "Diversifying across 4+ sectors can reduce concentration risk."
            ),
        })

    # 8. Positive performance
    if total_pnl_pct > 20:
        insights.append({
            "type": "success", "icon": "🚀",
            "title": "Strong Performance",
            "desc": (
                f"Portfolio is up {total_pnl_pct:.1f}% (${total_pnl:,.0f}). "
                "Consider rebalancing if gains have shifted your target allocation."
            ),
        })

    # 9. Good Sharpe
    if port_sharpe > 1.5:
        insights.append({
            "type": "success", "icon": "⭐",
            "title": "Excellent Risk-Adjusted Returns",
            "desc": (
                f"Portfolio Sharpe ratio of {port_sharpe:.2f} indicates strong "
                "risk-adjusted performance relative to the 4% risk-free rate."
            ),
        })

    # 10. Well diversified (positive catch-all)
    if sector_count >= 4 and max_weight < 20 and port_vol < 20:
        insights.append({
            "type": "success", "icon": "🛡️",
            "title": "Well Diversified",
            "desc": (
                f"Portfolio spans {sector_count} sectors with no position above "
                f"{max_weight:.0f}%. Annualised volatility is {port_vol:.1f}%, "
                "indicating well-distributed risk."
            ),
        })

    # Always return at least one insight
    if not insights:
        insights.append({
            "type": "info", "icon": "✨",
            "title": "Portfolio Looks Balanced",
            "desc": (
                "No significant concentration or risk alerts detected. "
                "Continue monitoring and rebalance periodically."
            ),
        })

    return insights[:10]  # cap at 10


# ---------------------------------------------------------------------------
# AI Assistant
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT_TEMPLATE = """\
You are a portfolio analysis assistant. Answer ONLY using the data provided
below. Do not invent figures, prices, or percentages not present in the data.
If the data does not contain enough information to answer, say so.
You are not a financial adviser; always note that answers are for
informational purposes only.

Portfolio data:
{portfolio_summary}
"""


def _build_portfolio_summary_text(portfolio: dict) -> str:
    """Serialise scalar portfolio values into a compact text block."""
    holdings = portfolio.get("holdings", [])
    lines = [
        f"Total value: ${portfolio.get('total_value', 0):,.2f}",
        f"Total cost:  ${portfolio.get('total_cost', 0):,.2f}",
        f"Total P&L:   ${portfolio.get('total_pnl', 0):,.2f} ({portfolio.get('total_pnl_pct', 0):.2f}%)",
        f"Daily P&L:   ${portfolio.get('daily_pnl', 0):,.2f}",
        f"Volatility:  {portfolio.get('volatility', 0):.1f}% annualised",
        f"Sharpe:      {portfolio.get('sharpe', 0):.2f}",
        f"Max drawdown: {portfolio.get('max_drawdown', 0)*100:.1f}%",
        f"Risk score:  {portfolio.get('risk_score', 0)}/100 ({portfolio.get('risk_profile', 'Unknown')})",
        "",
        "Holdings:",
    ]
    for h in holdings:
        lines.append(
            f"  {h['symbol']}: {h['shares']:.2f} shares @ ${h['price']:.2f} "
            f"| weight {h['weight']:.1f}% | P&L {h['pnl_pct']:.1f}% "
            f"| vol {h['volatility']:.1f}%"
        )
    return "\n".join(lines)


def get_openai_client():
    """
    Attempt to initialise an OpenAI client using the OPENAI_API_KEY environment
    variable (also checks a .env file via python-dotenv if available).

    Returns the client on success, None if openai is not installed or the key
    is absent/invalid.
    """
    # Try to load .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        import openai  # optional dependency
        client = openai.OpenAI(api_key=api_key)
        return client
    except Exception as exc:
        warnings.warn(f"[analytics] Could not initialise OpenAI client: {exc}")
        return None


def answer_portfolio_question(
    question: str, portfolio: dict, client=None
) -> str:
    """
    Answer a natural-language question about the portfolio.

    If *client* is a live OpenAI client, calls GPT-4o-mini with the portfolio
    data injected into the system prompt.

    Falls back to a rule-based keyword matcher when client is None or on any
    API error.  Answers always reference actual portfolio values.
    """
    summary_text = _build_portfolio_summary_text(portfolio)

    if client is not None:
        try:
            system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
                portfolio_summary=summary_text
            )
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": question},
                ],
                temperature=0.2,
                max_tokens=400,
            )
            return response.choices[0].message.content.strip()
        except Exception as exc:
            warnings.warn(f"[analytics] OpenAI call failed: {exc}")
            # fall through to rule-based fallback

    return _rule_based_answer(question, portfolio)


def _rule_based_answer(question: str, portfolio: dict) -> str:
    """Rule-based fallback for common portfolio questions."""
    q = question.lower()
    holdings = portfolio.get("holdings", [])

    if "value" in q:
        return (
            f"Your portfolio is currently valued at "
            f"${portfolio.get('total_value', 0):,.2f}."
        )

    if "volatil" in q:
        top_h = max(holdings, key=lambda h: h.get("volatility", 0), default=None)
        top_info = (
            f" The most volatile holding is {top_h['symbol']} "
            f"at {top_h['volatility']:.1f}%."
            if top_h else ""
        )
        return (
            f"Portfolio annualised volatility is "
            f"{portfolio.get('volatility', 0):.1f}%.{top_info}"
        )

    if "risk" in q:
        return (
            f"Risk profile: {portfolio.get('risk_profile', 'Unknown')} "
            f"(score {portfolio.get('risk_score', 0)}/100). "
            f"Annualised volatility: {portfolio.get('volatility', 0):.1f}%. "
            f"Max drawdown: {portfolio.get('max_drawdown', 0)*100:.1f}%."
        )

    if "loss" in q or "losing" in q or "worst" in q:
        losers = sorted(holdings, key=lambda h: h.get("pnl_pct", 0))
        if not losers:
            return "No holdings found."
        lines = []
        for h in losers[:3]:
            lines.append(f"{h['symbol']}: {h['pnl_pct']:.1f}% (${h['pnl']:,.0f})")
        return "Worst performing holdings:\n" + "\n".join(lines)

    if "performance" in q or "return" in q:
        best = max(holdings, key=lambda h: h.get("pnl_pct", 0), default=None)
        worst = min(holdings, key=lambda h: h.get("pnl_pct", 0), default=None)
        return (
            f"Total return: {portfolio.get('total_pnl_pct', 0):.1f}% "
            f"(${portfolio.get('total_pnl', 0):,.0f}). "
            f"Daily P&L: ${portfolio.get('daily_pnl', 0):,.0f}. "
            + (f"Best: {best['symbol']} ({best['pnl_pct']:.1f}%). " if best else "")
            + (f"Worst: {worst['symbol']} ({worst['pnl_pct']:.1f}%)." if worst else "")
        )

    if "sharpe" in q:
        return (
            f"Portfolio Sharpe ratio: {portfolio.get('sharpe', 0):.2f}. "
            "A ratio above 1.0 is generally considered good."
        )

    if "drawdown" in q:
        mdd = portfolio.get("max_drawdown", 0) * 100
        return f"Maximum historical drawdown: {mdd:.1f}%."

    if "sector" in q or "diversif" in q or "allocation" in q:
        sectors = portfolio.get("sectors", {})
        total = sum(sectors.values())
        lines = [
            f"{s}: {v/total*100:.1f}%"
            for s, v in sorted(sectors.items(), key=lambda x: x[1], reverse=True)
        ]
        return "Sector allocation:\n" + "\n".join(lines)

    return (
        "I can answer questions about portfolio value, volatility, risk, "
        "losses, performance, Sharpe ratio, drawdown, and sector allocation. "
        "What would you like to know?"
    )
