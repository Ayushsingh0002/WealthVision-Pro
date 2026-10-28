"""
database.py — SQLite persistence for WealthVision Pro.

Manages portfolios and holdings across Streamlit sessions.
Uses stdlib sqlite3; no additional dependencies required.
"""

import sqlite3
import csv
import io
import warnings
from datetime import datetime, timezone
from typing import Optional

# Module-level connection cache keyed by db_path
_CONNECTIONS: dict[str, sqlite3.Connection] = {}

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS portfolios (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT    NOT NULL UNIQUE,
    created TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS holdings (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id   INTEGER NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
    symbol         TEXT    NOT NULL,
    shares         REAL    NOT NULL CHECK(shares > 0),
    cost_basis     REAL    NOT NULL CHECK(cost_basis > 0),
    added_at       TEXT    NOT NULL
);
"""


def _now_utc() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def init_db(db_path: str = "wealthvision.db") -> sqlite3.Connection:
    """
    Open (or create) the SQLite database at db_path, run CREATE TABLE
    statements, enable WAL mode and foreign-key enforcement, and return the
    open connection.  Called once at app startup.

    Connections are cached by path so Streamlit reruns reuse the same handle.
    """
    if db_path in _CONNECTIONS:
        try:
            # Verify the connection is still alive
            _CONNECTIONS[db_path].execute("SELECT 1")
            return _CONNECTIONS[db_path]
        except Exception:
            pass  # stale connection — fall through to reconnect

    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(_DDL)
    conn.commit()
    _CONNECTIONS[db_path] = conn
    return conn


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------

def create_portfolio(conn: sqlite3.Connection, name: str) -> int:
    """
    Insert a portfolio with the given name.  Returns the new portfolio id.
    Raises ValueError if name is blank or already exists.
    """
    name = name.strip()
    if not name:
        raise ValueError("Portfolio name cannot be blank.")
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO portfolios (name, created) VALUES (?, ?)",
                (name, _now_utc()),
            )
            return cur.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"A portfolio named '{name}' already exists.")


def list_portfolios(conn: sqlite3.Connection) -> list[dict]:
    """
    Return all portfolios as a list of dicts sorted by name.
    Returns [] if no portfolios exist.
    """
    rows = conn.execute(
        "SELECT id, name, created FROM portfolios ORDER BY name"
    ).fetchall()
    return [dict(r) for r in rows]


def get_portfolio(conn: sqlite3.Connection, portfolio_id: int) -> Optional[dict]:
    """Return a single portfolio dict, or None if not found."""
    row = conn.execute(
        "SELECT id, name, created FROM portfolios WHERE id = ?",
        (portfolio_id,),
    ).fetchone()
    return dict(row) if row else None


def delete_portfolio(conn: sqlite3.Connection, portfolio_id: int) -> None:
    """
    Delete a portfolio and all its holdings (CASCADE handles the holdings).
    Raises ValueError if portfolio_id does not exist.
    """
    if not get_portfolio(conn, portfolio_id):
        raise ValueError(f"Portfolio id={portfolio_id} does not exist.")
    with conn:
        conn.execute("DELETE FROM portfolios WHERE id = ?", (portfolio_id,))


def rename_portfolio(conn: sqlite3.Connection, portfolio_id: int, new_name: str) -> None:
    """Rename a portfolio. Raises ValueError on duplicate or missing id."""
    new_name = new_name.strip()
    if not new_name:
        raise ValueError("Portfolio name cannot be blank.")
    if not get_portfolio(conn, portfolio_id):
        raise ValueError(f"Portfolio id={portfolio_id} does not exist.")
    try:
        with conn:
            conn.execute(
                "UPDATE portfolios SET name = ? WHERE id = ?",
                (new_name, portfolio_id),
            )
    except sqlite3.IntegrityError:
        raise ValueError(f"A portfolio named '{new_name}' already exists.")


# ---------------------------------------------------------------------------
# Holdings CRUD
# ---------------------------------------------------------------------------

def get_holdings(conn: sqlite3.Connection, portfolio_id: int) -> list[dict]:
    """
    Return all holdings for a portfolio as a list of dicts.
    Keys: id, portfolio_id, symbol, shares, cost_basis, added_at.
    Returns [] if the portfolio has no holdings.
    """
    rows = conn.execute(
        "SELECT id, portfolio_id, symbol, shares, cost_basis, added_at "
        "FROM holdings WHERE portfolio_id = ? ORDER BY added_at",
        (portfolio_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def add_holding(
    conn: sqlite3.Connection,
    portfolio_id: int,
    symbol: str,
    shares: float,
    cost_basis: float,
) -> int:
    """
    Insert a new holding row and return the new id.
    If the symbol already exists in the portfolio, compute a weighted-average
    cost basis and update shares instead (upsert behaviour).

    Raises ValueError for invalid inputs.
    """
    symbol = symbol.strip().upper()
    if not symbol:
        raise ValueError("Symbol cannot be blank.")
    if shares <= 0:
        raise ValueError("Shares must be greater than zero.")
    if cost_basis <= 0:
        raise ValueError("Cost basis must be greater than zero.")

    existing = conn.execute(
        "SELECT id, shares, cost_basis FROM holdings "
        "WHERE portfolio_id = ? AND symbol = ?",
        (portfolio_id, symbol),
    ).fetchone()

    with conn:
        if existing:
            old_shares = existing["shares"]
            old_cost = existing["cost_basis"]
            new_shares = old_shares + shares
            new_cost = (old_shares * old_cost + shares * cost_basis) / new_shares
            conn.execute(
                "UPDATE holdings SET shares = ?, cost_basis = ? WHERE id = ?",
                (new_shares, new_cost, existing["id"]),
            )
            return existing["id"]
        else:
            cur = conn.execute(
                "INSERT INTO holdings (portfolio_id, symbol, shares, cost_basis, added_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (portfolio_id, symbol, shares, cost_basis, _now_utc()),
            )
            return cur.lastrowid


def update_holding(
    conn: sqlite3.Connection,
    holding_id: int,
    shares: float,
    cost_basis: float,
) -> None:
    """
    Overwrite shares and cost_basis for an existing holding.
    Raises ValueError for invalid inputs or if holding_id does not exist.
    """
    if shares <= 0:
        raise ValueError("Shares must be greater than zero.")
    if cost_basis <= 0:
        raise ValueError("Cost basis must be greater than zero.")
    row = conn.execute(
        "SELECT id FROM holdings WHERE id = ?", (holding_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Holding id={holding_id} does not exist.")
    with conn:
        conn.execute(
            "UPDATE holdings SET shares = ?, cost_basis = ? WHERE id = ?",
            (shares, cost_basis, holding_id),
        )


def remove_holding(conn: sqlite3.Connection, holding_id: int) -> None:
    """
    Delete a single holding row.
    Raises ValueError if holding_id does not exist.
    """
    row = conn.execute(
        "SELECT id FROM holdings WHERE id = ?", (holding_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Holding id={holding_id} does not exist.")
    with conn:
        conn.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))


def clear_portfolio(conn: sqlite3.Connection, portfolio_id: int) -> None:
    """Remove all holdings from a portfolio without deleting the portfolio."""
    with conn:
        conn.execute(
            "DELETE FROM holdings WHERE portfolio_id = ?", (portfolio_id,)
        )


# ---------------------------------------------------------------------------
# CSV Import / Export
# ---------------------------------------------------------------------------

def export_csv(conn: sqlite3.Connection, portfolio_id: int) -> str:
    """
    Return a CSV string (with header) of all holdings for the portfolio.
    Columns: symbol, shares, cost_basis, added_at
    """
    holdings = get_holdings(conn, portfolio_id)
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["symbol", "shares", "cost_basis", "added_at"],
        extrasaction="ignore",
    )
    writer.writeheader()
    writer.writerows(holdings)
    return output.getvalue()


def import_csv(conn: sqlite3.Connection, portfolio_id: int, csv_text: str) -> int:
    """
    Parse csv_text (expected columns: symbol, shares, cost_basis).
    Calls add_holding for each valid row; skips rows with bad data.
    Returns the count of successfully imported rows.

    Handles:
    - BOM characters added by Excel (utf-8-sig)
    - Extra whitespace around values
    - Column names in any case (Symbol, SYMBOL, symbol)
    - Missing or zero values
    """
    # Strip BOM if present
    csv_text = csv_text.lstrip("\ufeff").strip()

    reader = csv.DictReader(io.StringIO(csv_text))

    # Normalise column names to lowercase stripped
    if reader.fieldnames is None:
        return 0
    reader.fieldnames = [f.strip().lower() for f in reader.fieldnames]

    imported = 0
    for row in reader:
        try:
            symbol = str(row.get("symbol", "")).strip().upper()
            if not symbol:
                continue

            shares_raw = str(row.get("shares", "0")).strip()
            cost_raw   = str(row.get("cost_basis", "0")).strip()

            shares     = float(shares_raw) if shares_raw else 0.0
            cost_basis = float(cost_raw)   if cost_raw   else 0.0

            if shares <= 0 or cost_basis <= 0:
                warnings.warn(f"Skipping row — invalid shares/cost: {row}")
                continue

            # Check if symbol already exists — if so, REPLACE (overwrite) it.
            # This ensures a re-imported CSV corrects values rather than doubling shares.
            existing = conn.execute(
                "SELECT id FROM holdings WHERE portfolio_id = ? AND symbol = ?",
                (portfolio_id, symbol),
            ).fetchone()
            if existing:
                update_holding(conn, existing["id"], shares, cost_basis)
            else:
                add_holding(conn, portfolio_id, symbol, shares, cost_basis)
            imported += 1
        except (ValueError, KeyError) as exc:
            warnings.warn(f"Skipping CSV row {row}: {exc}")
    return imported


# ---------------------------------------------------------------------------
# Demo data helper
# ---------------------------------------------------------------------------

DEMO_HOLDINGS = [
    ("AAPL", 30.0, 165.0),
    ("MSFT", 20.0, 340.0),
    ("NVDA", 15.0, 420.0),
    ("JPM",  25.0, 175.0),
    ("VTI",  50.0, 215.0),
]


def ensure_demo_portfolio(conn: sqlite3.Connection) -> int:
    """
    Create (or reuse) a portfolio named 'Demo' and populate it with
    the 5 demo holdings.  Returns the portfolio id.
    """
    row = conn.execute(
        "SELECT id FROM portfolios WHERE name = 'Demo'"
    ).fetchone()
    if row:
        return row["id"]

    pid = create_portfolio(conn, "Demo")
    for symbol, shares, cost in DEMO_HOLDINGS:
        add_holding(conn, pid, symbol, shares, cost)
    return pid
