# -*- coding: utf-8 -*-
"""
server.py  WealthVision Pro  Flask backend.
Run:  python server.py   then open http://127.0.0.1:5000
"""

import traceback
import warnings

from flask import Flask, jsonify, request, render_template, Response

import database
import market_data
import portfolio as portfolio_module
import analytics

warnings.filterwarnings("ignore")

app = Flask(__name__)
app.config["JSON_SORT_KEYS"] = False

_conn = database.init_db("wealthvision.db")


def _conn_get():
    return _conn


# ── error helper: pass code HERE, not outside ──────────────
def _err(msg: str, code: int = 400):
    return jsonify({"error": msg}), code


# ══════════════════════════════════════════════════════════
# Portfolio payload builder
# ══════════════════════════════════════════════════════════

def _build_portfolio_payload(portfolio_id: int):
    raw = database.get_holdings(_conn_get(), portfolio_id)
    if not raw:
        return None

    symbols    = [h["symbol"] for h in raw]
    stock_data = {sym: market_data.fetch_stock_data(sym) for sym in symbols}
    failed     = [s for s, d in stock_data.items() if d is None]

    holdings = portfolio_module.build_holdings(
        [{"symbol": h["symbol"], "shares": h["shares"],
          "cost_basis": h["cost_basis"], "id": h["id"]} for h in raw],
        stock_data,
    )
    if not holdings:
        return {"error": f"No data for: {', '.join(failed)}", "holdings": []}

    summary = portfolio_module.build_portfolio_summary(holdings)
    if not summary:
        return None

    safe = []
    for h in summary["holdings"]:
        safe.append({
            "id":            h["id"],
            "symbol":        h["symbol"],
            "name":          h["name"],
            "shares":        round(h["shares"], 4),
            "cost_basis":    round(h["cost_basis"], 2),
            "price":         round(h["price"], 2),
            "change_pct":    round(h["change_pct"], 2),
            "sector":        h["sector"],
            "weight":        round(h["weight"], 2),
            "value":         round(h["value"], 2),
            "cost":          round(h["cost"], 2),
            "pnl":           round(h["pnl"], 2),
            "pnl_pct":       round(h["pnl_pct"], 2),
            "daily_pnl":     round(h["daily_pnl"], 2),
            "volatility":    round(h["volatility"], 2),
            "sharpe":        round(h["sharpe"], 2),
            "high_52w":      round(h["high_52w"], 2),
            "low_52w":       round(h["low_52w"], 2),
            "position_52w":  round(h["position_52w"], 1),
            "pe_ratio":      round(h.get("pe_ratio") or 0, 2),
            "dividend_yield":round(h.get("dividend_yield") or 0, 2),
            "fetched_at":    h.get("fetched_at", ""),
        })

    hist_df = summary.get("history")
    history = []
    if hist_df is not None and not hist_df.empty:
        for _, row in hist_df.iterrows():
            history.append({"date": str(row["date"])[:10],
                            "value": round(float(row["value"]), 2)})

    rc_map   = analytics.risk_contribution(summary["holdings"], summary.get("cov_matrix"))
    insights = analytics.generate_insights(summary)

    return {
        "holdings":          safe,
        "total_value":       round(summary["total_value"], 2),
        "total_cost":        round(summary["total_cost"], 2),
        "total_pnl":         round(summary["total_pnl"], 2),
        "total_pnl_pct":     round(summary["total_pnl_pct"], 2),
        "daily_pnl":         round(summary["daily_pnl"], 2),
        "volatility":        round(summary["volatility"], 2),
        "sharpe":            round(summary["sharpe"], 2),
        "max_drawdown":      round(summary["max_drawdown"] * 100, 2),
        "risk_score":        summary["risk_score"],
        "risk_profile":      summary["risk_profile"],
        "sectors":           {k: round(v, 2) for k, v in summary.get("sectors", {}).items()},
        "history":           history,
        "risk_contribution": {k: round(v, 2) for k, v in rc_map.items()},
        "insights":          insights,
        "failed_symbols":    failed,
    }


# ══════════════════════════════════════════════════════════
# SPA
# ══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


# ══════════════════════════════════════════════════════════
# Portfolio CRUD
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios", methods=["GET"])
def list_portfolios():
    return jsonify(database.list_portfolios(_conn_get()))


@app.route("/api/portfolios", methods=["POST"])
def create_portfolio():
    data = request.get_json(force=True) or {}
    name = str(data.get("name", "")).strip()
    if not name:
        return _err("Portfolio name is required.")
    try:
        pid = database.create_portfolio(_conn_get(), name)
        return jsonify({"id": pid, "name": name}), 201
    except ValueError as e:
        return _err(str(e))


@app.route("/api/portfolios/<int:portfolio_id>", methods=["DELETE"])
def delete_portfolio(portfolio_id):
    try:
        database.delete_portfolio(_conn_get(), portfolio_id)
        return jsonify({"ok": True})
    except ValueError as e:
        return _err(str(e), 404)


# ══════════════════════════════════════════════════════════
# Holdings CRUD
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios/<int:portfolio_id>/holdings", methods=["GET"])
def list_holdings(portfolio_id):
    return jsonify(database.get_holdings(_conn_get(), portfolio_id))


@app.route("/api/portfolios/<int:portfolio_id>/holdings", methods=["POST"])
def add_holding(portfolio_id):
    data = request.get_json(force=True) or {}
    symbol = str(data.get("symbol", "")).strip().upper()

    try:
        shares = float(data.get("shares", 0))
        cost   = float(data.get("cost_basis", 0))
    except (ValueError, TypeError):
        return _err("shares and cost_basis must be numbers.")

    if not symbol:
        return _err("Symbol is required.")
    if shares <= 0:
        return _err("Shares must be greater than zero.")
    if cost <= 0:
        return _err("Purchase price must be greater than zero.")

    # Validate ticker — FIX: pass code directly to _err, NOT as tuple outside
    if not market_data.validate_ticker(symbol):
        return _err(
            f"'{symbol}' was not found on Yahoo Finance. "
            "For Indian stocks use .NS (NSE) or .BO (BSE) suffix.",
            422,
        )

    try:
        hid = database.add_holding(_conn_get(), portfolio_id, symbol, shares, cost)
        return jsonify({"id": hid, "symbol": symbol}), 201
    except ValueError as e:
        return _err(str(e))


@app.route("/api/holdings/<int:holding_id>", methods=["PUT"])
def update_holding(holding_id):
    data = request.get_json(force=True) or {}
    try:
        shares = float(data.get("shares", 0))
        cost   = float(data.get("cost_basis", 0))
    except (ValueError, TypeError):
        return _err("shares and cost_basis must be numbers.")
    if shares <= 0:
        return _err("Shares must be greater than zero.")
    if cost <= 0:
        return _err("Purchase price must be greater than zero.")
    try:
        database.update_holding(_conn_get(), holding_id, shares, cost)
        return jsonify({"ok": True})
    except ValueError as e:
        return _err(str(e), 404)


@app.route("/api/holdings/<int:holding_id>", methods=["DELETE"])
def delete_holding(holding_id):
    try:
        database.remove_holding(_conn_get(), holding_id)
        return jsonify({"ok": True})
    except ValueError as e:
        return _err(str(e), 404)


# ══════════════════════════════════════════════════════════
# Portfolio analytics
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios/<int:portfolio_id>/summary", methods=["GET"])
def portfolio_summary(portfolio_id):
    try:
        result = _build_portfolio_payload(portfolio_id)
        if result is None:
            return jsonify({"holdings": [], "total_value": 0}), 200
        return jsonify(result)
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return _err(f"Failed to compute summary: {e}", 500)


@app.route("/api/portfolios/<int:portfolio_id>/risk", methods=["GET"])
def portfolio_risk(portfolio_id):
    try:
        import numpy as np
        raw = database.get_holdings(_conn_get(), portfolio_id)
        if not raw:
            return jsonify({}), 200

        symbols    = [h["symbol"] for h in raw]
        stock_data = {sym: market_data.fetch_stock_data(sym) for sym in symbols}
        holdings   = portfolio_module.build_holdings(
            [{"symbol": h["symbol"], "shares": h["shares"],
              "cost_basis": h["cost_basis"], "id": h["id"]} for h in raw],
            stock_data,
        )
        if not holdings:
            return jsonify({}), 200

        summary      = portfolio_module.build_portfolio_summary(holdings)
        port_returns = portfolio_module.compute_historical_returns(summary)

        var_val  = analytics.historical_var(port_returns) * 100 if port_returns is not None else 0
        cvar_val = analytics.conditional_var(port_returns) * 100 if port_returns is not None else 0

        corr_df   = analytics.correlation_matrix(holdings)
        corr_data = None
        if corr_df is not None:
            corr_data = {
                "symbols": list(corr_df.columns),
                "matrix":  [[round(v, 3) for v in row] for row in corr_df.values.tolist()],
            }

        hist_df = summary.get("history")
        dd_series = []
        if hist_df is not None and not hist_df.empty:
            vals = hist_df["value"].values.astype(float)
            peak = np.maximum.accumulate(vals)
            dd   = [(v-p)/p*100 if p>0 else 0.0 for v, p in zip(vals, peak)]
            dd_series = [
                {"date": str(hist_df["date"].iloc[i])[:10], "drawdown": round(dd[i], 2)}
                for i in range(len(dd))
            ]

        return jsonify({
            "var_95":          round(var_val, 3),
            "cvar_95":         round(cvar_val, 3),
            "max_drawdown":    round(summary["max_drawdown"] * 100, 2),
            "volatility":      round(summary["volatility"], 2),
            "correlation":     corr_data,
            "drawdown_series": dd_series,
        })
    except Exception as e:
        app.logger.error(traceback.format_exc())
        return _err(str(e), 500)


# ══════════════════════════════════════════════════════════
# Ticker validation
# ══════════════════════════════════════════════════════════

@app.route("/api/validate_ticker", methods=["POST"])
def validate_ticker_route():
    data   = request.get_json(force=True) or {}
    symbol = str(data.get("symbol", "")).strip().upper()
    valid  = market_data.validate_ticker(symbol) if symbol else False
    return jsonify({"valid": valid, "symbol": symbol})


# ══════════════════════════════════════════════════════════
# CSV import / export
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios/<int:portfolio_id>/import", methods=["POST"])
def import_csv(portfolio_id):
    if "file" not in request.files:
        return _err("No file received. Upload a CSV with field name 'file'.")
    f = request.files["file"]
    if not f.filename:
        return _err("Empty file received.")
    try:
        csv_text = f.read().decode("utf-8-sig")  # strips BOM
        n = database.import_csv(_conn_get(), portfolio_id, csv_text)
        return jsonify({"imported": n})
    except Exception as e:
        return _err(f"Import failed: {e}", 500)


@app.route("/api/portfolios/<int:portfolio_id>/export", methods=["GET"])
def export_csv(portfolio_id):
    csv_str = database.export_csv(_conn_get(), portfolio_id)
    return Response(
        csv_str,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=holdings.csv"},
    )


# ══════════════════════════════════════════════════════════
# Demo portfolio
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios/<int:portfolio_id>/demo", methods=["POST"])
def load_demo(portfolio_id):
    try:
        database.clear_portfolio(_conn_get(), portfolio_id)
        for symbol, shares, cost in database.DEMO_HOLDINGS:
            database.add_holding(_conn_get(), portfolio_id, symbol, shares, cost)
        return jsonify({"ok": True, "count": len(database.DEMO_HOLDINGS)})
    except Exception as e:
        return _err(str(e), 500)


# ══════════════════════════════════════════════════════════
# Scenario analysis
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios/<int:portfolio_id>/scenario", methods=["POST"])
def scenario(portfolio_id):
    data    = request.get_json(force=True) or {}
    changes = data.get("changes", {})

    raw = database.get_holdings(_conn_get(), portfolio_id)
    if not raw:
        return _err("No holdings found.")

    symbols    = [h["symbol"] for h in raw]
    stock_data = {sym: market_data.fetch_stock_data(sym) for sym in symbols}
    holdings   = portfolio_module.build_holdings(
        [{"symbol": h["symbol"], "shares": h["shares"],
          "cost_basis": h["cost_basis"], "id": h["id"]} for h in raw],
        stock_data,
    )
    if not holdings:
        return _err("Could not fetch market data.", 500)

    summary       = portfolio_module.build_portfolio_summary(holdings)
    current_total = summary["total_value"]

    sim_rows  = []
    sim_total = 0.0
    for h in summary["holdings"]:
        chg       = float(changes.get(h["symbol"], 0)) / 100
        sim_price = h["price"] * (1 + chg)
        sim_value = h["shares"] * sim_price
        sim_pnl   = sim_value - h["cost"]
        sim_pnl_pct = sim_pnl / h["cost"] * 100 if h["cost"] > 0 else 0
        sim_total += sim_value
        sim_rows.append({
            "symbol":      h["symbol"],
            "change_pct":  round(chg * 100, 1),
            "orig_price":  round(h["price"], 2),
            "sim_price":   round(sim_price, 2),
            "sim_value":   round(sim_value, 2),
            "sim_pnl":     round(sim_pnl, 2),
            "sim_pnl_pct": round(sim_pnl_pct, 2),
            "new_weight":  0,
        })

    for r in sim_rows:
        r["new_weight"] = round(r["sim_value"] / sim_total * 100, 2) if sim_total > 0 else 0

    impact     = sim_total - current_total
    impact_pct = impact / current_total * 100 if current_total > 0 else 0

    return jsonify({
        "current_total": round(current_total, 2),
        "sim_total":     round(sim_total, 2),
        "impact":        round(impact, 2),
        "impact_pct":    round(impact_pct, 2),
        "rows":          sim_rows,
    })


# ══════════════════════════════════════════════════════════
# AI assistant
# ══════════════════════════════════════════════════════════

@app.route("/api/portfolios/<int:portfolio_id>/ask", methods=["POST"])
def ask(portfolio_id):
    data     = request.get_json(force=True) or {}
    question = str(data.get("question", "")).strip()
    if not question:
        return _err("question is required.")

    result = _build_portfolio_payload(portfolio_id)
    if not result or not result.get("holdings"):
        return _err("No portfolio data available.")

    client = analytics.get_openai_client()
    answer = analytics.answer_portfolio_question(question, result, client=client)
    return jsonify({"answer": answer})


# ══════════════════════════════════════════════════════════
# Run
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("\n  WealthVision Pro  ->  http://127.0.0.1:5000\n")
    app.run(debug=True, port=5000, use_reloader=False)
