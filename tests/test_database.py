"""
tests/test_database.py — Unit tests for database.py persistence layer.

Uses an in-memory SQLite database (:memory:) so no files are created on disk.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import sqlite3
import pytest
import database as db


# ---------------------------------------------------------------------------
# Fixture: fresh in-memory DB per test
# ---------------------------------------------------------------------------

@pytest.fixture
def conn():
    """Return a fresh in-memory connection with the schema initialised."""
    # Bypass the module-level cache so each test gets a clean DB
    c = sqlite3.connect(":memory:", check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.executescript(db._DDL)
    c.commit()
    yield c
    c.close()


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------

class TestPortfolioCRUD:

    def test_init_creates_tables(self, conn):
        tables = {row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()}
        assert "portfolios" in tables
        assert "holdings" in tables

    def test_create_portfolio(self, conn):
        pid = db.create_portfolio(conn, "My Portfolio")
        assert isinstance(pid, int)
        assert pid > 0

    def test_list_portfolios_empty(self, conn):
        assert db.list_portfolios(conn) == []

    def test_list_portfolios_returns_created(self, conn):
        db.create_portfolio(conn, "Alpha")
        db.create_portfolio(conn, "Beta")
        names = [p["name"] for p in db.list_portfolios(conn)]
        assert "Alpha" in names
        assert "Beta" in names

    def test_create_duplicate_raises(self, conn):
        db.create_portfolio(conn, "Dup")
        with pytest.raises(ValueError, match="already exists"):
            db.create_portfolio(conn, "Dup")

    def test_create_blank_name_raises(self, conn):
        with pytest.raises(ValueError):
            db.create_portfolio(conn, "   ")

    def test_delete_portfolio(self, conn):
        pid = db.create_portfolio(conn, "ToDelete")
        db.delete_portfolio(conn, pid)
        assert db.list_portfolios(conn) == []

    def test_delete_nonexistent_raises(self, conn):
        with pytest.raises(ValueError):
            db.delete_portfolio(conn, 9999)


# ---------------------------------------------------------------------------
# Holdings CRUD
# ---------------------------------------------------------------------------

class TestHoldingsCRUD:

    @pytest.fixture
    def pid(self, conn):
        return db.create_portfolio(conn, "Test Portfolio")

    def test_add_holding(self, conn, pid):
        hid = db.add_holding(conn, pid, "AAPL", 10.0, 150.0)
        assert hid > 0
        holdings = db.get_holdings(conn, pid)
        assert len(holdings) == 1
        assert holdings[0]["symbol"] == "AAPL"
        assert holdings[0]["shares"] == 10.0
        assert holdings[0]["cost_basis"] == 150.0

    def test_upsert_averages_cost(self, conn, pid):
        """Adding the same symbol twice should average the cost basis."""
        db.add_holding(conn, pid, "AAPL", 10.0, 100.0)
        db.add_holding(conn, pid, "AAPL", 10.0, 200.0)
        holdings = db.get_holdings(conn, pid)
        # Only one row
        assert len(holdings) == 1
        # Weighted average: (10 × 100 + 10 × 200) / 20 = 150
        assert abs(holdings[0]["shares"]     - 20.0)  < 0.001
        assert abs(holdings[0]["cost_basis"] - 150.0) < 0.001

    def test_remove_holding(self, conn, pid):
        hid = db.add_holding(conn, pid, "MSFT", 5.0, 300.0)
        db.remove_holding(conn, hid)
        assert db.get_holdings(conn, pid) == []

    def test_remove_nonexistent_raises(self, conn, pid):
        with pytest.raises(ValueError):
            db.remove_holding(conn, 9999)

    def test_update_holding(self, conn, pid):
        hid = db.add_holding(conn, pid, "NVDA", 3.0, 400.0)
        db.update_holding(conn, hid, 6.0, 450.0)
        holdings = db.get_holdings(conn, pid)
        assert abs(holdings[0]["shares"]     - 6.0)   < 0.001
        assert abs(holdings[0]["cost_basis"] - 450.0) < 0.001

    def test_add_invalid_shares_raises(self, conn, pid):
        with pytest.raises(ValueError):
            db.add_holding(conn, pid, "AAPL", -1.0, 100.0)

    def test_add_invalid_cost_raises(self, conn, pid):
        with pytest.raises(ValueError):
            db.add_holding(conn, pid, "AAPL", 10.0, 0.0)


# ---------------------------------------------------------------------------
# CSV import / export
# ---------------------------------------------------------------------------

class TestCSV:

    @pytest.fixture
    def pid(self, conn):
        p = db.create_portfolio(conn, "CSV Test")
        db.add_holding(conn, p, "AAPL", 10.0, 150.0)
        db.add_holding(conn, p, "MSFT", 5.0, 300.0)
        return p

    def test_export_csv_has_header(self, conn, pid):
        csv_str = db.export_csv(conn, pid)
        assert "symbol" in csv_str
        assert "shares" in csv_str
        assert "cost_basis" in csv_str

    def test_export_csv_has_data(self, conn, pid):
        csv_str = db.export_csv(conn, pid)
        assert "AAPL" in csv_str
        assert "MSFT" in csv_str

    def test_import_csv(self, conn):
        pid2 = db.create_portfolio(conn, "Import Test")
        csv_text = "symbol,shares,cost_basis\nGOOGL,2,120.0\nAMZN,1,180.0\n"
        n = db.import_csv(conn, pid2, csv_text)
        assert n == 2
        holdings = db.get_holdings(conn, pid2)
        syms = {h["symbol"] for h in holdings}
        assert "GOOGL" in syms
        assert "AMZN" in syms

    def test_import_csv_skips_bad_rows(self, conn):
        pid3 = db.create_portfolio(conn, "Bad CSV Test")
        # Second row is missing cost_basis → should be skipped
        csv_text = "symbol,shares,cost_basis\nGOOGL,2,120.0\nBAD_ROW,abc,xyz\n"
        n = db.import_csv(conn, pid3, csv_text)
        assert n == 1

    def test_roundtrip(self, conn, pid):
        csv_str = db.export_csv(conn, pid)
        pid2 = db.create_portfolio(conn, "Roundtrip")
        n = db.import_csv(conn, pid2, csv_str)
        assert n == 2
        orig = {h["symbol"] for h in db.get_holdings(conn, pid)}
        copy = {h["symbol"] for h in db.get_holdings(conn, pid2)}
        assert orig == copy
