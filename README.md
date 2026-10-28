# WealthVision Pro

A premium dark-themed stock portfolio tracker built with Flask + vanilla JS.
Correct financial calculations, SQLite persistence, risk analytics, rule-based
insights, optional AI assistant, and scenario analysis.

---

## Prerequisites

- Python 3.9+
- Internet connection (for Yahoo Finance market data)

---

## Installation

```bash
pip install -r requirements.txt
```

---

## Running

```bash
python server.py
```

Open **http://127.0.0.1:5000** in your browser.

---

## Running Tests

```bash
python -m pytest tests/ -v
```

54 tests, no network access required.

---

## Project Structure

```
server.py              Flask backend + REST API
templates/index.html   Single-page application shell
static/css/style.css   Premium dark UI styles
static/js/app.js       Frontend logic (Chart.js, fetch API)

database.py            SQLite persistence
market_data.py         yfinance wrapper with caching
portfolio.py           Financial calculations
analytics.py           Risk metrics, insights, AI assistant

requirements.txt       Dependencies
demo_portfolio_india.csv  Sample Indian portfolio CSV
tests/                 54 unit tests
wealthvision.db        SQLite DB (auto-created on first run)
app1.py                Original Streamlit app (preserved)
```

---

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET  | `/api/portfolios` | List all portfolios |
| POST | `/api/portfolios` | Create portfolio `{"name": "..."}` |
| DELETE | `/api/portfolios/<id>` | Delete portfolio |
| GET  | `/api/portfolios/<id>/holdings` | List holdings |
| POST | `/api/portfolios/<id>/holdings` | Add holding |
| PUT  | `/api/holdings/<id>` | Edit holding |
| DELETE | `/api/holdings/<id>` | Remove holding |
| GET  | `/api/portfolios/<id>/summary` | Full analytics payload |
| GET  | `/api/portfolios/<id>/risk` | VaR, CVaR, correlation, drawdown |
| POST | `/api/portfolios/<id>/scenario` | Scenario simulation |
| POST | `/api/portfolios/<id>/ask` | AI assistant |
| POST | `/api/portfolios/<id>/import` | Import CSV (multipart) |
| GET  | `/api/portfolios/<id>/export` | Export CSV |
| POST | `/api/portfolios/<id>/demo` | Load demo holdings |
| POST | `/api/validate_ticker` | Validate ticker symbol |

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Optional | Enables GPT-4o-mini in AI Assistant tab |

Create a `.env` file in the project root:
```
OPENAI_API_KEY=sk-...
```

---

## Ticker Format

| Exchange | Format | Example |
|----------|--------|---------|
| US stocks | `SYMBOL` | `AAPL`, `MSFT` |
| NSE India | `SYMBOL.NS` | `HDFCBANK.NS`, `TCS.NS` |
| BSE India | `SYMBOL.BO` | `RELIANCE.BO` |
| Crypto | `PAIR` | `BTC-USD`, `ETH-USD` |

---

## Known Limitations

- Market data is delayed/EOD from Yahoo Finance — never real-time.
- VaR/CVaR require ≥ 30 days of portfolio history.
- Correlation matrix requires ≥ 2 holdings with 30+ common trading days.
- Not financial advice.
