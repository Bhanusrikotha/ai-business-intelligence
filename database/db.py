"""
database/db.py
--------------
Responsible for:
  - Creating and returning a SQLite database connection.
  - Defining all four tables and their indexes.
  - Providing a safe, reusable query-execution helper.

No business logic lives here. This file only knows about the
database structure, not about CSV files or analytics.
"""

import sqlite3
import os
from pathlib import Path


# ── Path resolution ────────────────────────────────────────────────────────────
# Build the absolute path to sales.db regardless of where Python is called from.
# __file__  → .../ai-business-intelligence/database/db.py
# .parent   → .../ai-business-intelligence/database/
# So DATABASE_PATH → .../ai-business-intelligence/database/sales.db
DATABASE_PATH = Path(__file__).parent / "sales.db"


# ── SQL: Table definitions ─────────────────────────────────────────────────────

# Table 1 ── sales_raw
# Stores all 51 source records exactly as they appear in the CSV.
# This table is NEVER updated or deleted after initial ingestion.
# unit_price is nullable because TXN0051 has a missing price.
SQL_CREATE_SALES_RAW = """
CREATE TABLE IF NOT EXISTS sales_raw (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  TEXT    NOT NULL UNIQUE,
    order_date      TEXT    NOT NULL,
    product         TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    region          TEXT    NOT NULL,
    sales_channel   TEXT    NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price      REAL,
    discount_amount REAL    NOT NULL DEFAULT 0,
    status          TEXT    NOT NULL,
    loaded_at       TEXT    NOT NULL
);
"""

# Table 2 ── sales_analytics
# Contains only the 48 analytics-eligible records.
# Includes derived columns (order_date_iso, year_month, month_name, revenue)
# so that SQL queries remain simple and fast.
# unit_price is NOT NULL here — rows with missing prices are excluded before insert.
SQL_CREATE_SALES_ANALYTICS = """
CREATE TABLE IF NOT EXISTS sales_analytics (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id  TEXT    NOT NULL UNIQUE,
    order_date      TEXT    NOT NULL,
    order_date_iso  TEXT    NOT NULL,
    year_month      TEXT    NOT NULL,
    month_name      TEXT    NOT NULL,
    product         TEXT    NOT NULL,
    category        TEXT    NOT NULL,
    region          TEXT    NOT NULL,
    sales_channel   TEXT    NOT NULL,
    quantity        INTEGER NOT NULL,
    unit_price      REAL    NOT NULL,
    discount_amount REAL    NOT NULL DEFAULT 0,
    revenue         REAL    NOT NULL,
    status          TEXT    NOT NULL,
    FOREIGN KEY (transaction_id) REFERENCES sales_raw(transaction_id)
);
"""

# Table 3 ── ingestion_log
# One row per script run. Records how many rows were loaded, how many excluded, etc.
SQL_CREATE_INGESTION_LOG = """
CREATE TABLE IF NOT EXISTS ingestion_log (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at            TEXT    NOT NULL,
    source_file       TEXT    NOT NULL,
    total_source_rows INTEGER NOT NULL,
    rows_loaded_raw   INTEGER NOT NULL,
    rows_eligible     INTEGER NOT NULL,
    rows_excluded     INTEGER NOT NULL,
    exclusion_details TEXT    NOT NULL
);
"""

# Table 4 ── exclusion_log
# One row per excluded transaction, with a human-readable reason.
SQL_CREATE_EXCLUSION_LOG = """
CREATE TABLE IF NOT EXISTS exclusion_log (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id   TEXT    NOT NULL,
    exclusion_reason TEXT    NOT NULL,
    logged_at        TEXT    NOT NULL
);
"""

# ── SQL: Indexes ───────────────────────────────────────────────────────────────
# Indexes speed up GROUP BY and WHERE queries on the analytics table.
SQL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS idx_year_month ON sales_analytics(year_month);",
    "CREATE INDEX IF NOT EXISTS idx_region     ON sales_analytics(region);",
    "CREATE INDEX IF NOT EXISTS idx_product    ON sales_analytics(product);",
    "CREATE INDEX IF NOT EXISTS idx_status_raw ON sales_raw(status);",
]


# ── Connection factory ─────────────────────────────────────────────────────────
def get_connection(db_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    """
    Open and return a SQLite connection with useful settings applied.

    Parameters
    ----------
    db_path : Path
        File-system path to the .db file. Created automatically if absent.

    Returns
    -------
    sqlite3.Connection
        A configured connection object. The caller is responsible for
        closing it (use 'with get_connection() as conn:' pattern).

    Settings applied
    ----------------
    - detect_types  : lets sqlite3 map TEXT columns to Python date objects
                      when you use parse_colnames in queries.
    - row_factory   : sqlite3.Row means rows behave like dicts — you can
                      access columns by name: row["revenue"] instead of row[0].
    - foreign_keys  : PRAGMA foreign_keys = ON enforces the FK constraint
                      between sales_analytics and sales_raw.
    """
    # Ensure the directory exists (useful if tests use a temp path)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        db_path,
        detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
    )
    conn.row_factory = sqlite3.Row          # access columns by name
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


# ── Schema initialiser ─────────────────────────────────────────────────────────
def initialise_database(db_path: Path = DATABASE_PATH) -> None:
    """
    Create all four tables and all indexes if they do not already exist.

    Safe to call multiple times — uses CREATE TABLE IF NOT EXISTS so it
    will never overwrite existing data.

    Parameters
    ----------
    db_path : Path
        Path to the SQLite database file.
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()

        # Create the four tables
        for sql in [
            SQL_CREATE_SALES_RAW,
            SQL_CREATE_SALES_ANALYTICS,
            SQL_CREATE_INGESTION_LOG,
            SQL_CREATE_EXCLUSION_LOG,
        ]:
            cursor.execute(sql)

        # Create indexes
        for sql in SQL_INDEXES:
            cursor.execute(sql)

        conn.commit()

    print(f"[db.py] Database initialised at: {db_path}")


# ── Query helper ───────────────────────────────────────────────────────────────
def execute_query(
    sql: str,
    params: tuple = (),
    db_path: Path = DATABASE_PATH,
) -> list:
    """
    Execute a SELECT query and return all matching rows.

    This helper is used by backend/analytics.py so that analytics
    functions never need to manage connections themselves.

    Parameters
    ----------
    sql    : str   — The parameterized SQL query (use ? placeholders).
    params : tuple — Values that replace ? placeholders (prevents SQL injection).
    db_path: Path  — Path to the database (default: production database).

    Returns
    -------
    list[sqlite3.Row]
        A list of Row objects. Each row supports both index access (row[0])
        and column-name access (row["revenue"]).
        Returns an empty list if no rows match.

    Example
    -------
    rows = execute_query(
        "SELECT revenue FROM sales_analytics WHERE region = ?",
        ("North",)
    )
    """
    with get_connection(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute(sql, params)
        return cursor.fetchall()


# ── Quick self-test (run this file directly to verify the DB is healthy) ───────
if __name__ == "__main__":
    initialise_database()

    conn = get_connection()
    cursor = conn.cursor()

    # List all tables in the database
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;")
    tables = cursor.fetchall()
    print("\n[db.py] Tables in database:")
    for t in tables:
        print(f"  OK  {t['name']}")

    # List all indexes
    cursor.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name;")
    indexes = cursor.fetchall()
    print("\n[db.py] Indexes in database:")
    for i in indexes:
        print(f"  OK  {i['name']}")

    conn.close()
    print("\n[db.py] Self-test complete. Database is ready.")
