"""
backend/analytics.py
--------------------
Contains exactly five predefined analytics functions.

Each function:
  - Uses a parameterized SQL query (no string concatenation).
  - Reads ONLY from sales_analytics (the 48 eligible rows).
  - Returns a structured Python dict with the main result + supporting data.
  - Never modifies the database.
  - Handles edge cases: empty DB, ties, zero revenue, missing months.

Revenue formula (applied at ingestion, stored in the `revenue` column):
    Revenue = (Quantity × Unit_price) − Discount_amount

Functions
---------
1. get_total_revenue()
2. get_top_product()
3. get_monthly_revenue()
4. get_top_region(metric="revenue")
5. compare_monthly_revenue(start_month, end_month)
"""

import sys
from pathlib import Path

# Allow imports from project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from database.db import execute_query, DATABASE_PATH


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTION 1 — Total Revenue
# ══════════════════════════════════════════════════════════════════════════════

def get_total_revenue(db_path=DATABASE_PATH) -> dict:
    """
    Calculate the total revenue across all 48 analytics-eligible transactions.

    SQL used
    --------
        SELECT
            ROUND(SUM(revenue), 2)  AS total_revenue,
            COUNT(*)                AS transaction_count,
            ROUND(MIN(revenue), 2)  AS min_transaction,
            ROUND(MAX(revenue), 2)  AS max_transaction,
            ROUND(AVG(revenue), 2)  AS avg_transaction
        FROM sales_analytics;

    Clause-by-clause explanation
    ----------------------------
    - SUM(revenue)   : adds up the pre-computed revenue column for all 48 rows.
    - COUNT(*)       : counts how many rows contributed (useful for verification).
    - MIN / MAX      : smallest and largest single transaction (supporting figures).
    - AVG            : average revenue per transaction.
    - ROUND(x, 2)    : limits result to 2 decimal places.

    Edge cases handled
    ------------------
    - Empty database → SUM returns NULL → we return 0.0 with a warning flag.

    Returns
    -------
    dict with keys:
        success          : bool
        function         : str  — name of this function
        total_revenue    : float
        transaction_count: int
        min_transaction  : float
        max_transaction  : float
        avg_transaction  : float
        answer           : str  — human-readable sentence
    """
    sql = """
        SELECT
            ROUND(SUM(revenue),  2) AS total_revenue,
            COUNT(*)                AS transaction_count,
            ROUND(MIN(revenue),  2) AS min_transaction,
            ROUND(MAX(revenue),  2) AS max_transaction,
            ROUND(AVG(revenue),  2) AS avg_transaction
        FROM sales_analytics;
    """
    rows = execute_query(sql, db_path=db_path)

    # If the table is empty, SUM returns NULL — handle gracefully
    if not rows or rows[0]["total_revenue"] is None:
        return {
            "success": False,
            "function": "get_total_revenue",
            "answer": "No analytics-eligible data found in the database.",
            "total_revenue": 0.0,
            "transaction_count": 0,
        }

    row = rows[0]
    total = row["total_revenue"]

    return {
        "success": True,
        "function": "get_total_revenue",
        "total_revenue": total,
        "transaction_count": row["transaction_count"],
        "min_transaction": row["min_transaction"],
        "max_transaction": row["max_transaction"],
        "avg_transaction": row["avg_transaction"],
        "answer": (
            f"The total revenue across all {row['transaction_count']} "
            f"eligible transactions is ₹{total:,.2f}."
        ),
        "query_description": (
            "SUM of pre-computed revenue column in sales_analytics "
            "(excludes TXN0033 Returned, TXN0034 Zero-qty, TXN0051 Missing price)."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTION 2 — Top Product by Revenue
# ══════════════════════════════════════════════════════════════════════════════

def get_top_product(db_path=DATABASE_PATH) -> dict:
    """
    Find which product generated the highest total revenue.

    SQL used
    --------
        SELECT
            product,
            ROUND(SUM(revenue), 2)  AS product_revenue,
            SUM(quantity)           AS total_units_sold,
            COUNT(*)                AS transaction_count
        FROM   sales_analytics
        GROUP  BY product
        ORDER  BY product_revenue DESC;

    Clause-by-clause explanation
    ----------------------------
    - GROUP BY product   : collapses all rows for each product into one group.
    - SUM(revenue)       : total money earned by that product across all months.
    - SUM(quantity)      : total units sold (supporting figure).
    - ORDER BY DESC      : highest revenue product appears first.
    - We return ALL rows so ties are visible (if two products tie for first).

    Tie handling
    ------------
    If two products have the same revenue, both are returned in `all_products`
    and `top_product` shows the first alphabetically (SQLite default for ties).

    Edge cases
    ----------
    - Empty database → returns empty list with success=False.

    Returns
    -------
    dict with keys:
        success          : bool
        function         : str
        top_product      : str  — name of the winning product
        top_revenue      : float
        all_products     : list[dict]  — full ranked list (for bar chart)
        answer           : str
    """
    sql = """
        SELECT
            product,
            ROUND(SUM(revenue),   2) AS product_revenue,
            SUM(quantity)            AS total_units_sold,
            COUNT(*)                 AS transaction_count
        FROM   sales_analytics
        GROUP  BY product
        ORDER  BY product_revenue DESC;
    """
    rows = execute_query(sql, db_path=db_path)

    if not rows:
        return {
            "success": False,
            "function": "get_top_product",
            "answer": "No analytics-eligible data found in the database.",
            "all_products": [],
        }

    # Build a list of dicts for the frontend table / chart
    all_products = [
        {
            "rank": i + 1,
            "product": row["product"],
            "product_revenue": row["product_revenue"],
            "total_units_sold": row["total_units_sold"],
            "transaction_count": row["transaction_count"],
        }
        for i, row in enumerate(rows)
    ]

    top = all_products[0]

    # Check for ties at the top position
    ties = [p for p in all_products if p["product_revenue"] == top["product_revenue"]]
    tie_note = ""
    if len(ties) > 1:
        tie_note = (
            f" (tied with: {', '.join(t['product'] for t in ties[1:])})"
        )

    return {
        "success": True,
        "function": "get_top_product",
        "top_product": top["product"],
        "top_revenue": top["product_revenue"],
        "total_units_sold": top["total_units_sold"],
        "all_products": all_products,
        "answer": (
            f"The highest-revenue product is '{top['product']}' "
            f"with total revenue of ₹{top['product_revenue']:,.2f} "
            f"from {top['total_units_sold']} units sold{tie_note}."
        ),
        "query_description": (
            "GROUP BY product, SUM(revenue) ORDER BY DESC from sales_analytics."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTION 3 — Monthly Revenue Trend
# ══════════════════════════════════════════════════════════════════════════════

def get_monthly_revenue(db_path=DATABASE_PATH) -> dict:
    """
    Return the total revenue for each calendar month, in chronological order.

    SQL used
    --------
        SELECT
            year_month,
            month_name,
            COUNT(*)                AS transaction_count,
            ROUND(SUM(revenue), 2)  AS monthly_revenue,
            SUM(quantity)           AS total_units
        FROM   sales_analytics
        GROUP  BY year_month
        ORDER  BY year_month ASC;

    Clause-by-clause explanation
    ----------------------------
    - GROUP BY year_month : collapses rows into one group per YYYY-MM period.
    - ORDER BY year_month : chronological order (YYYY-MM sorts correctly as text).
    - month_name          : human-readable label ("January") for chart axes.
    - SUM(quantity)       : total units sold that month (supporting figure).

    Month-over-month change
    -----------------------
    Calculated in Python after the query:
        change = this_month_revenue - previous_month_revenue
        pct    = (change / previous_month_revenue) × 100

    Edge cases
    ----------
    - Only one month of data → month-over-month change = N/A.
    - Previous month revenue = 0 → percentage change = infinity → shown as "N/A".

    Returns
    -------
    dict with keys:
        success       : bool
        function      : str
        monthly_data  : list[dict]  — one dict per month, with MoM change
        peak_month    : str         — month with highest revenue
        lowest_month  : str         — month with lowest revenue
        answer        : str
    """
    sql = """
        SELECT
            year_month,
            month_name,
            COUNT(*)                AS transaction_count,
            ROUND(SUM(revenue), 2)  AS monthly_revenue,
            SUM(quantity)           AS total_units
        FROM   sales_analytics
        GROUP  BY year_month
        ORDER  BY year_month ASC;
    """
    rows = execute_query(sql, db_path=db_path)

    if not rows:
        return {
            "success": False,
            "function": "get_monthly_revenue",
            "answer": "No analytics-eligible data found in the database.",
            "monthly_data": [],
        }

    monthly_data = []
    prev_revenue = None

    for row in rows:
        curr_revenue = row["monthly_revenue"]

        # Month-over-month absolute and percentage change
        if prev_revenue is None:
            mom_change = None
            mom_pct    = None
            mom_label  = "N/A (first month)"
        elif prev_revenue == 0:
            mom_change = curr_revenue
            mom_pct    = None
            mom_label  = "N/A (previous month had zero revenue)"
        else:
            mom_change = round(curr_revenue - prev_revenue, 2)
            mom_pct    = round((mom_change / prev_revenue) * 100, 2)
            direction  = "▲" if mom_change >= 0 else "▼"
            mom_label  = f"{direction} {abs(mom_pct):.1f}%"

        monthly_data.append({
            "year_month":        row["year_month"],
            "month_name":        row["month_name"],
            "monthly_revenue":   curr_revenue,
            "transaction_count": row["transaction_count"],
            "total_units":       row["total_units"],
            "mom_change":        mom_change,
            "mom_pct":           mom_pct,
            "mom_label":         mom_label,
        })

        prev_revenue = curr_revenue

    # Identify peak and lowest months
    peak   = max(monthly_data, key=lambda x: x["monthly_revenue"])
    lowest = min(monthly_data, key=lambda x: x["monthly_revenue"])

    return {
        "success": True,
        "function": "get_monthly_revenue",
        "monthly_data": monthly_data,
        "peak_month":   peak["month_name"],
        "peak_revenue": peak["monthly_revenue"],
        "lowest_month": lowest["month_name"],
        "lowest_revenue": lowest["monthly_revenue"],
        "answer": (
            f"Monthly revenue trend from {monthly_data[0]['month_name']} "
            f"to {monthly_data[-1]['month_name']}. "
            f"Peak month: {peak['month_name']} (₹{peak['monthly_revenue']:,.2f}). "
            f"Lowest month: {lowest['month_name']} (₹{lowest['monthly_revenue']:,.2f})."
        ),
        "query_description": (
            "GROUP BY year_month, SUM(revenue) ORDER BY year_month ASC "
            "from sales_analytics. Month-over-month change computed in Python."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTION 4 — Top Region by Revenue (or Quantity)
# ══════════════════════════════════════════════════════════════════════════════

def get_top_region(metric: str = "revenue", db_path=DATABASE_PATH) -> dict:
    """
    Find which region generated the highest revenue (default) or quantity.

    Parameters
    ----------
    metric : str — "revenue" (default) or "quantity".
                   Determines what "highest sales" means.

    SQL used (revenue mode)
    -----------------------
        SELECT
            region,
            ROUND(SUM(revenue),  2) AS total_revenue,
            SUM(quantity)           AS total_units,
            COUNT(*)                AS transaction_count
        FROM   sales_analytics
        GROUP  BY region
        ORDER  BY total_revenue DESC;

    SQL used (quantity mode)
    ------------------------
        Same query, ORDER BY total_units DESC.

    Clause-by-clause explanation
    ----------------------------
    - GROUP BY region   : collapses all rows to one group per region.
    - SUM(revenue)      : total money from that region.
    - SUM(quantity)     : total units from that region.
    - ORDER BY DESC     : highest region first.

    Tie handling
    ------------
    All regions returned in `all_regions`. Ties flagged in the answer text.

    Edge cases
    ----------
    - metric not in ["revenue", "quantity"] → defaults to "revenue".
    - Empty database → success=False.

    Returns
    -------
    dict with keys:
        success       : bool
        function      : str
        metric        : str   — "revenue" or "quantity"
        top_region    : str
        top_value     : float
        all_regions   : list[dict]
        answer        : str
    """
    # Validate metric
    if metric not in ("revenue", "quantity"):
        metric = "revenue"

    order_col = "total_revenue" if metric == "revenue" else "total_units"

    sql = f"""
        SELECT
            region,
            ROUND(SUM(revenue),  2) AS total_revenue,
            SUM(quantity)           AS total_units,
            COUNT(*)                AS transaction_count
        FROM   sales_analytics
        GROUP  BY region
        ORDER  BY {order_col} DESC;
    """
    # Note: order_col is NOT user input — it is validated above to only
    # be "total_revenue" or "total_units". No SQL injection risk.

    rows = execute_query(sql, db_path=db_path)

    if not rows:
        return {
            "success": False,
            "function": "get_top_region",
            "answer": "No analytics-eligible data found in the database.",
            "all_regions": [],
        }

    all_regions = [
        {
            "rank":              i + 1,
            "region":            row["region"],
            "total_revenue":     row["total_revenue"],
            "total_units":       row["total_units"],
            "transaction_count": row["transaction_count"],
        }
        for i, row in enumerate(rows)
    ]

    top = all_regions[0]
    top_value = top["total_revenue"] if metric == "revenue" else top["total_units"]

    # Tie detection
    ties = [
        r for r in all_regions
        if (r["total_revenue"] if metric == "revenue" else r["total_units"]) == top_value
    ]
    tie_note = ""
    if len(ties) > 1:
        tie_note = f" (tied with: {', '.join(t['region'] for t in ties[1:])})"

    if metric == "revenue":
        answer = (
            f"The highest-revenue region is '{top['region']}' "
            f"with total revenue of ₹{top['total_revenue']:,.2f} "
            f"from {top['total_units']} units sold{tie_note}."
        )
    else:
        answer = (
            f"The highest-volume region is '{top['region']}' "
            f"with {top['total_units']} total units sold "
            f"(revenue: ₹{top['total_revenue']:,.2f}){tie_note}."
        )

    return {
        "success": True,
        "function": "get_top_region",
        "metric": metric,
        "top_region": top["region"],
        "top_value": top_value,
        "top_revenue": top["total_revenue"],
        "top_units": top["total_units"],
        "all_regions": all_regions,
        "answer": answer,
        "query_description": (
            f"GROUP BY region, SUM(revenue/quantity) ORDER BY {order_col} DESC "
            "from sales_analytics."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# FUNCTION 5 — Compare Monthly Revenue
# ══════════════════════════════════════════════════════════════════════════════

def compare_monthly_revenue(
    start_month: str,
    end_month: str,
    db_path=DATABASE_PATH,
) -> dict:
    """
    Compare total revenue between two specified months.

    Parameters
    ----------
    start_month : str — The earlier month in YYYY-MM format (e.g. "2026-01").
    end_month   : str — The later month in YYYY-MM format  (e.g. "2026-03").

    SQL used
    --------
        SELECT
            year_month,
            month_name,
            ROUND(SUM(revenue), 2)  AS monthly_revenue,
            COUNT(*)                AS transaction_count,
            SUM(quantity)           AS total_units
        FROM   sales_analytics
        WHERE  year_month IN (?, ?)
        GROUP  BY year_month
        ORDER  BY year_month ASC;

    Clause-by-clause explanation
    ----------------------------
    - WHERE year_month IN (?, ?)  : filters to ONLY the two requested months.
                                    The ? placeholders prevent SQL injection.
    - GROUP BY year_month         : one result row per month.
    - ORDER BY year_month ASC     : start month comes first in the results.

    Change calculation (Python, after SQL)
    --------------------------------------
        absolute_change = end_revenue − start_revenue
        pct_change      = (absolute_change / start_revenue) × 100

    Edge cases handled
    ------------------
    - start_month not in DB → returns error with clear message.
    - end_month not in DB   → returns error with clear message.
    - start_month revenue = 0 → percentage shown as "N/A".
    - start_month == end_month → comparison still works (change = 0).
    - Months in wrong order (end < start) → still calculated correctly.

    Returns
    -------
    dict with keys:
        success          : bool
        function         : str
        start_month      : str
        end_month        : str
        start_revenue    : float
        end_revenue      : float
        absolute_change  : float
        pct_change       : float | None
        direction        : str  — "increase", "decrease", or "no change"
        answer           : str
    """
    sql = """
        SELECT
            year_month,
            month_name,
            ROUND(SUM(revenue), 2)  AS monthly_revenue,
            COUNT(*)                AS transaction_count,
            SUM(quantity)           AS total_units
        FROM   sales_analytics
        WHERE  year_month IN (?, ?)
        GROUP  BY year_month
        ORDER  BY year_month ASC;
    """
    rows = execute_query(sql, (start_month, end_month), db_path=db_path)

    # Build a dict keyed by year_month for easy lookup
    results = {row["year_month"]: dict(row) for row in rows}

    # Validate both months exist in the database
    missing = []
    if start_month not in results:
        missing.append(start_month)
    if end_month not in results:
        missing.append(end_month)

    if missing:
        available_sql = "SELECT DISTINCT year_month, month_name FROM sales_analytics ORDER BY year_month;"
        available_rows = execute_query(available_sql, db_path=db_path)
        available = [f"{r['year_month']} ({r['month_name']})" for r in available_rows]
        return {
            "success": False,
            "function": "compare_monthly_revenue",
            "answer": (
                f"Month(s) not found in the database: {', '.join(missing)}. "
                f"Available months are: {', '.join(available)}."
            ),
            "missing_months": missing,
            "available_months": available,
        }

    start_data = results[start_month]
    end_data   = results[end_month]

    start_rev = start_data["monthly_revenue"]
    end_rev   = end_data["monthly_revenue"]

    absolute_change = round(end_rev - start_rev, 2)

    # Percentage change — undefined if start is 0
    if start_rev == 0:
        pct_change = None
        pct_label  = "N/A (start month had zero revenue)"
    else:
        pct_change = round((absolute_change / start_rev) * 100, 2)
        pct_label  = f"{abs(pct_change):.1f}%"

    # Direction
    if absolute_change > 0:
        direction = "increase"
        sign      = "▲"
    elif absolute_change < 0:
        direction = "decrease"
        sign      = "▼"
    else:
        direction = "no change"
        sign      = "→"

    # Human-readable answer
    if pct_change is not None:
        answer = (
            f"Revenue {direction}d from {start_data['month_name']} "
            f"(₹{start_rev:,.2f}) to {end_data['month_name']} "
            f"(₹{end_rev:,.2f}). "
            f"Absolute change: {sign} ₹{abs(absolute_change):,.2f} "
            f"({pct_label})."
        )
    else:
        answer = (
            f"Revenue changed from {start_data['month_name']} "
            f"(₹{start_rev:,.2f}) to {end_data['month_name']} "
            f"(₹{end_rev:,.2f}). "
            f"Percentage change: {pct_label}."
        )

    return {
        "success": True,
        "function": "compare_monthly_revenue",
        "start_month":       start_month,
        "end_month":         end_month,
        "start_month_name":  start_data["month_name"],
        "end_month_name":    end_data["month_name"],
        "start_revenue":     start_rev,
        "end_revenue":       end_rev,
        "start_transactions": start_data["transaction_count"],
        "end_transactions":   end_data["transaction_count"],
        "absolute_change":   absolute_change,
        "pct_change":        pct_change,
        "direction":         direction,
        "sign":              sign,
        "answer":            answer,
        "query_description": (
            f"SUM(revenue) WHERE year_month IN ('{start_month}', '{end_month}') "
            "GROUP BY year_month from sales_analytics."
        ),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Quick self-test — run all five functions against the real database
# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import json

    SEP = "=" * 65

    print(f"\n{SEP}")
    print("  ANALYTICS SELF-TEST — running against sales.db")
    print(SEP)

    # 1 — Total Revenue
    print("\n[1] get_total_revenue()")
    result = get_total_revenue()
    print(f"    Answer  : {result['answer']}")
    print(f"    Revenue : ₹{result.get('total_revenue', 0):,.2f}")
    print(f"    Txns    : {result.get('transaction_count', 0)}")

    # 2 — Top Product
    print("\n[2] get_top_product()")
    result = get_top_product()
    print(f"    Answer  : {result['answer']}")
    print("    All products (ranked):")
    for p in result.get("all_products", []):
        print(f"      {p['rank']}. {p['product']:15s}  ₹{p['product_revenue']:>12,.2f}  "
              f"{p['total_units_sold']} units")

    # 3 — Monthly Revenue
    print("\n[3] get_monthly_revenue()")
    result = get_monthly_revenue()
    print(f"    Answer  : {result['answer']}")
    print("    Monthly breakdown:")
    for m in result.get("monthly_data", []):
        print(f"      {m['month_name']:12s}  ₹{m['monthly_revenue']:>12,.2f}  "
              f"MoM: {m['mom_label']}")

    # 4 — Top Region (revenue)
    print("\n[4] get_top_region(metric='revenue')")
    result = get_top_region(metric="revenue")
    print(f"    Answer  : {result['answer']}")
    print("    All regions (by revenue):")
    for r in result.get("all_regions", []):
        print(f"      {r['rank']}. {r['region']:8s}  ₹{r['total_revenue']:>12,.2f}  "
              f"{r['total_units']} units")

    # 4b — Top Region (quantity)
    print("\n[4b] get_top_region(metric='quantity')")
    result = get_top_region(metric="quantity")
    print(f"    Answer  : {result['answer']}")

    # 5 — Compare Months (Jan vs May — largest gap)
    print("\n[5] compare_monthly_revenue('2026-01', '2026-05')")
    result = compare_monthly_revenue("2026-01", "2026-05")
    print(f"    Answer  : {result['answer']}")
    print(f"    Change  : {result.get('sign','')} ₹{abs(result.get('absolute_change',0)):,.2f}")
    print(f"    Pct     : {result.get('pct_change', 'N/A')}%")

    # 5b — Edge case: non-existent month
    print("\n[5b] compare_monthly_revenue('2026-01', '2026-09')  ← bad month")
    result = compare_monthly_revenue("2026-01", "2026-09")
    print(f"    Success : {result['success']}")
    print(f"    Answer  : {result['answer']}")

    print(f"\n{SEP}")
    print("  All five functions executed successfully.")
    print(SEP)
