"""
scripts/load_data.py
--------------------
Ingests the original CSV into the SQLite database.

What this script does (in order):
  1. Reads the original CSV using Pandas — does NOT modify it.
  2. Validates every row against the approved eligibility rules.
  3. Inserts all 51 rows into sales_raw (source mirror).
  4. Inserts the 48 eligible rows into sales_analytics with derived columns.
  5. Logs excluded transactions to exclusion_log (with reasons).
  6. Writes one summary row to ingestion_log.
  7. Prints a full ingestion report to the terminal.

Eligibility rules (approved in Phase 1):
  R1 — Status = 'Returned'    → exclude
  R2 — Unit_price is NULL     → exclude
  R3 — Quantity = 0           → exclude

Safe to re-run: UNIQUE constraint on transaction_id means duplicate rows
are silently skipped using INSERT OR IGNORE.

Usage:
  python scripts/load_data.py
"""

import sys
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

import pandas as pd

# ── Import db.py from the sibling database/ package ───────────────────────────
# We add the project root to sys.path so that Python can find the
# database package regardless of where the script is called from.
PROJECT_ROOT = Path(__file__).parent.parent          # ai-business-intelligence/
sys.path.insert(0, str(PROJECT_ROOT))

from database.db import get_connection, initialise_database, DATABASE_PATH

# ── File paths ─────────────────────────────────────────────────────────────────
CSV_PATH = PROJECT_ROOT / "data" / "ai_bi_assistant_sales_data - GET.csv"

# ── Month name lookup (used to populate the month_name column) ─────────────────
MONTH_NAMES = {
    1: "January", 2: "February", 3: "March",    4: "April",
    5: "May",     6: "June",     7: "July",      8: "August",
    9: "September", 10: "October", 11: "November", 12: "December",
}


# ── Step 1: Read the CSV ───────────────────────────────────────────────────────
def read_csv(csv_path: Path) -> pd.DataFrame:
    """
    Read the original CSV into a Pandas DataFrame.

    - Reads ALL columns exactly as they appear.
    - Does NOT rename, drop, or modify any column.
    - keep_default_na=True means blank Unit_price cells become NaN (Python's
      way of saying "this value is missing").

    Parameters
    ----------
    csv_path : Path — path to the CSV file.

    Returns
    -------
    pd.DataFrame — raw, unmodified DataFrame with 51 rows and 10 columns.
    """
    if not csv_path.exists():
        raise FileNotFoundError(
            f"CSV not found at: {csv_path}\n"
            "Place the original file in the data/ folder."
        )

    df = pd.read_csv(csv_path, keep_default_na=True)

    # Strip any accidental whitespace from string columns
    # (does NOT change actual values, just removes invisible spaces)
    for col in df.select_dtypes(include="object").columns:
        df[col] = df[col].str.strip()

    return df


# ── Step 2: Validate the DataFrame ────────────────────────────────────────────
def validate_dataframe(df: pd.DataFrame) -> None:
    """
    Confirm that the loaded DataFrame has the expected structure.
    Raises ValueError with a clear message if anything is wrong.

    Checks:
      - All 10 expected columns are present.
      - No unexpected columns were added.
      - Row count is at least 1.
    """
    expected_columns = [
        "Transaction_Id", "Order_date", "Product", "Category",
        "Region", "Sales_channel", "Quantity", "Unit_price",
        "Discount_amount", "Status",
    ]
    missing = [c for c in expected_columns if c not in df.columns]
    if missing:
        raise ValueError(f"CSV is missing expected columns: {missing}")

    if len(df) == 0:
        raise ValueError("CSV contains no data rows.")

    print(f"[load_data] CSV validated: {len(df)} rows, {len(df.columns)} columns.")


# ── Step 3: Apply eligibility rules ───────────────────────────────────────────
def classify_rows(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict]]:
    """
    Split the DataFrame into eligible rows and excluded rows.

    Rules (approved in Phase 1):
      R1 — Status = 'Returned'   → exclude
      R2 — Unit_price is NaN     → exclude
      R3 — Quantity = 0          → exclude

    Parameters
    ----------
    df : pd.DataFrame — the raw 51-row DataFrame.

    Returns
    -------
    eligible_df   : pd.DataFrame — rows that pass all three rules.
    excluded_list : list[dict]   — one dict per excluded row containing
                                   transaction_id and exclusion_reason.
    """
    excluded_list = []

    # R1 — Returned transactions
    mask_returned = df["Status"].str.strip().str.lower() == "returned"
    for _, row in df[mask_returned].iterrows():
        excluded_list.append({
            "transaction_id": row["Transaction_Id"],
            "exclusion_reason": "R1: Status = Returned",
        })

    # R2 — Missing Unit_price (NaN after read_csv)
    mask_null_price = df["Unit_price"].isna()
    for _, row in df[mask_null_price].iterrows():
        excluded_list.append({
            "transaction_id": row["Transaction_Id"],
            "exclusion_reason": "R2: Unit_price is NULL",
        })

    # R3 — Zero Quantity
    mask_zero_qty = df["Quantity"] == 0
    for _, row in df[mask_zero_qty].iterrows():
        excluded_list.append({
            "transaction_id": row["Transaction_Id"],
            "exclusion_reason": "R3: Quantity = 0",
        })

    # Combine all exclusion masks
    exclude_mask = mask_returned | mask_null_price | mask_zero_qty

    # eligible_df = rows where none of the exclusion conditions are true
    eligible_df = df[~exclude_mask].copy()

    return eligible_df, excluded_list


# ── Step 4: Parse dates and compute derived columns ────────────────────────────
def enrich_for_analytics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add derived columns needed by the analytics layer to the eligible DataFrame.

    Derived columns added:
      - order_date_iso  : YYYY-MM-DD  (SQLite date functions need ISO format)
      - year_month      : YYYY-MM     (used for GROUP BY month)
      - month_name      : "January"   (human-readable label for charts)
      - revenue         : (Quantity × Unit_price) − Discount_amount

    The original Order_date column (DD-MM-YYYY) is preserved unchanged.

    Parameters
    ----------
    df : pd.DataFrame — the 48-row eligible DataFrame.

    Returns
    -------
    pd.DataFrame — same rows with four additional columns.
    """
    # Parse DD-MM-YYYY → Python datetime
    # dayfirst=True tells Pandas the format starts with day
    df["_parsed_date"] = pd.to_datetime(df["Order_date"], dayfirst=True)

    # YYYY-MM-DD string for SQLite strftime() compatibility
    df["order_date_iso"] = df["_parsed_date"].dt.strftime("%Y-%m-%d")

    # YYYY-MM string for GROUP BY month queries
    df["year_month"] = df["_parsed_date"].dt.strftime("%Y-%m")

    # Human-readable month name
    df["month_name"] = df["_parsed_date"].dt.month.map(MONTH_NAMES)

    # Revenue formula: (Quantity × Unit_price) − Discount_amount
    # Round to 2 decimal places to avoid floating-point noise
    df["revenue"] = (
        df["Quantity"] * df["Unit_price"] - df["Discount_amount"]
    ).round(2)

    # Drop the temporary helper column
    df = df.drop(columns=["_parsed_date"])

    return df


# ── Step 5: Insert into sales_raw ─────────────────────────────────────────────
def insert_raw(df: pd.DataFrame, conn: sqlite3.Connection, loaded_at: str) -> int:
    """
    Insert all 51 source rows into the sales_raw table.

    INSERT OR IGNORE means: if a row with the same transaction_id already
    exists (from a previous run), skip it silently. This makes the script
    safe to re-run without creating duplicates.

    Parameters
    ----------
    df        : pd.DataFrame      — the full 51-row DataFrame.
    conn      : sqlite3.Connection — active database connection.
    loaded_at : str               — ISO timestamp string for the loaded_at column.

    Returns
    -------
    int — number of rows actually inserted (0 if all already existed).
    """
    cursor = conn.cursor()
    inserted = 0

    for _, row in df.iterrows():
        # pd.isna() returns True for NaN (missing Unit_price on TXN0051)
        unit_price = None if pd.isna(row["Unit_price"]) else float(row["Unit_price"])

        cursor.execute(
            """
            INSERT OR IGNORE INTO sales_raw
                (transaction_id, order_date, product, category, region,
                 sales_channel, quantity, unit_price, discount_amount,
                 status, loaded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(row["Transaction_Id"]),
                str(row["Order_date"]),
                str(row["Product"]),
                str(row["Category"]),
                str(row["Region"]),
                str(row["Sales_channel"]),
                int(row["Quantity"]),
                unit_price,                        # None → NULL in SQLite
                float(row["Discount_amount"]),
                str(row["Status"]),
                loaded_at,
            ),
        )
        # cursor.rowcount == 1 means a row was inserted; 0 means it was ignored
        inserted += cursor.rowcount

    return inserted


# ── Step 6: Insert into sales_analytics ───────────────────────────────────────
def insert_analytics(
    eligible_df: pd.DataFrame, conn: sqlite3.Connection
) -> int:
    """
    Insert the 48 eligible rows into sales_analytics.

    Also uses INSERT OR IGNORE so reruns are safe.

    Parameters
    ----------
    eligible_df : pd.DataFrame      — enriched eligible rows.
    conn        : sqlite3.Connection — active database connection.

    Returns
    -------
    int — number of rows actually inserted.
    """
    cursor = conn.cursor()
    inserted = 0

    for _, row in eligible_df.iterrows():
        cursor.execute(
            """
            INSERT OR IGNORE INTO sales_analytics
                (transaction_id, order_date, order_date_iso, year_month,
                 month_name, product, category, region, sales_channel,
                 quantity, unit_price, discount_amount, revenue, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                str(row["Transaction_Id"]),
                str(row["Order_date"]),
                str(row["order_date_iso"]),
                str(row["year_month"]),
                str(row["month_name"]),
                str(row["Product"]),
                str(row["Category"]),
                str(row["Region"]),
                str(row["Sales_channel"]),
                int(row["Quantity"]),
                float(row["Unit_price"]),
                float(row["Discount_amount"]),
                float(row["revenue"]),
                str(row["Status"]),
            ),
        )
        inserted += cursor.rowcount

    return inserted


# ── Step 7: Log exclusions ─────────────────────────────────────────────────────
def log_exclusions(
    excluded_list: list[dict], conn: sqlite3.Connection, logged_at: str
) -> None:
    """
    Insert one row into exclusion_log for every excluded transaction.

    Parameters
    ----------
    excluded_list : list[dict]       — output of classify_rows().
    conn          : sqlite3.Connection
    logged_at     : str              — ISO timestamp.
    """
    cursor = conn.cursor()
    for exc in excluded_list:
        cursor.execute(
            """
            INSERT INTO exclusion_log (transaction_id, exclusion_reason, logged_at)
            VALUES (?, ?, ?)
            """,
            (exc["transaction_id"], exc["exclusion_reason"], logged_at),
        )


# ── Step 8: Write ingestion summary row ───────────────────────────────────────
def log_ingestion(
    conn: sqlite3.Connection,
    run_at: str,
    source_file: str,
    total_source_rows: int,
    rows_loaded_raw: int,
    rows_eligible: int,
    excluded_list: list[dict],
) -> None:
    """
    Insert one summary row into ingestion_log for this run.

    Parameters
    ----------
    exclusion_details is stored as a JSON string so it is human-readable
    and can be parsed programmatically later.
    """
    exclusion_details = json.dumps(
        [{"id": e["transaction_id"], "reason": e["exclusion_reason"]}
         for e in excluded_list],
        indent=2,
    )
    conn.cursor().execute(
        """
        INSERT INTO ingestion_log
            (run_at, source_file, total_source_rows, rows_loaded_raw,
             rows_eligible, rows_excluded, exclusion_details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_at,
            source_file,
            total_source_rows,
            rows_loaded_raw,
            rows_eligible,
            len(excluded_list),
            exclusion_details,
        ),
    )


# ── Step 9: Print ingestion report ────────────────────────────────────────────
def print_report(
    total_source_rows: int,
    rows_inserted_raw: int,
    rows_inserted_analytics: int,
    excluded_list: list[dict],
    conn: sqlite3.Connection,
) -> None:
    """
    Print a formatted ingestion summary and a few verification queries.
    """
    separator = "=" * 60

    print(f"\n{separator}")
    print("  INGESTION REPORT")
    print(separator)
    print(f"  Total source rows (CSV)         : {total_source_rows}")
    print(f"  Rows inserted → sales_raw       : {rows_inserted_raw}")
    print(f"  Rows excluded from analytics    : {len(excluded_list)}")
    print(f"  Rows inserted → sales_analytics : {rows_inserted_analytics}")
    print(f"{separator}")

    print("\n  Excluded transactions:")
    for exc in excluded_list:
        print(f"    {exc['transaction_id']:10s}  →  {exc['exclusion_reason']}")

    # ── Verification queries ──────────────────────────────────────────────────
    cursor = conn.cursor()

    print(f"\n{separator}")
    print("  VERIFICATION QUERIES")
    print(separator)

    # Count rows in each table
    for table in ["sales_raw", "sales_analytics", "exclusion_log"]:
        cursor.execute(f"SELECT COUNT(*) FROM {table};")
        count = cursor.fetchone()[0]
        print(f"  SELECT COUNT(*) FROM {table:20s}  →  {count} rows")

    # Total revenue from analytics table
    cursor.execute("SELECT ROUND(SUM(revenue), 2) AS total FROM sales_analytics;")
    total_rev = cursor.fetchone()[0]
    print(f"\n  SELECT SUM(revenue) FROM sales_analytics   →  {total_rev:,.2f}")

    # Monthly revenue breakdown
    print("\n  Monthly revenue breakdown:")
    cursor.execute(
        """
        SELECT month_name, year_month,
               COUNT(*) AS transactions,
               ROUND(SUM(revenue), 2) AS monthly_revenue
        FROM   sales_analytics
        GROUP  BY year_month
        ORDER  BY year_month;
        """
    )
    for row in cursor.fetchall():
        print(
            f"    {row['month_name']:12s} ({row['year_month']})  "
            f"{row['transactions']:2d} transactions  "
            f"Revenue: {row['monthly_revenue']:>12,.2f}"
        )

    print(f"\n{separator}")
    print("  Ingestion complete. Database is ready for analytics.")
    print(f"{separator}\n")


# ── Main orchestrator ──────────────────────────────────────────────────────────
def run_ingestion(csv_path: Path = CSV_PATH, db_path=DATABASE_PATH) -> dict:
    """
    Run the full ingestion pipeline end-to-end.

    Returns a summary dict (useful for programmatic verification in tests).
    """
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"\n[load_data] Starting ingestion at {run_at}")
    print(f"[load_data] Source : {csv_path}")
    print(f"[load_data] Target : {db_path}")

    # 1. Initialise database schema
    initialise_database(db_path)

    # 2. Read CSV
    df = read_csv(csv_path)

    # 3. Validate structure
    validate_dataframe(df)

    # 4. Classify rows (eligible vs excluded)
    eligible_df, excluded_list = classify_rows(df)

    # 5. Enrich eligible rows with derived columns
    eligible_df = enrich_for_analytics(eligible_df)

    # 6. Insert everything inside a single transaction
    #    → if anything fails, ALL changes are rolled back automatically
    with get_connection(db_path) as conn:
        rows_inserted_raw       = insert_raw(df, conn, run_at)
        rows_inserted_analytics = insert_analytics(eligible_df, conn)
        log_exclusions(excluded_list, conn, run_at)
        log_ingestion(
            conn,
            run_at=run_at,
            source_file=str(csv_path),
            total_source_rows=len(df),
            rows_loaded_raw=rows_inserted_raw,
            rows_eligible=rows_inserted_analytics,
            excluded_list=excluded_list,
        )
        conn.commit()

        # 7. Print report (inside the same connection so counts are accurate)
        print_report(
            total_source_rows=len(df),
            rows_inserted_raw=rows_inserted_raw,
            rows_inserted_analytics=rows_inserted_analytics,
            excluded_list=excluded_list,
            conn=conn,
        )

    return {
        "total_source_rows": len(df),
        "rows_inserted_raw": rows_inserted_raw,
        "rows_inserted_analytics": rows_inserted_analytics,
        "excluded_count": len(excluded_list),
        "excluded_transactions": [e["transaction_id"] for e in excluded_list],
    }


# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    run_ingestion()
