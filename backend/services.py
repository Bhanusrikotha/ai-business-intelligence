"""
backend/services.py
--------------------
Business workflow layer.

This file sits BETWEEN the API routes (main.py) and the analytics
functions (analytics.py). It also connects to the AI interpreter
(ai_interpreter.py) once Phase 5 is in place.

Responsibilities
----------------
1. Receive a validated QuestionRequest from the API layer.
2. Determine which analytics function to call (intent routing).
3. Call the correct analytics function with the right parameters.
4. Return a structured result dict for the API to serialise.

What this file does NOT do
--------------------------
- It does NOT handle HTTP — that is main.py's job.
- It does NOT run SQL — that is analytics.py's job.
- It does NOT call the LLM directly — that will be ai_interpreter.py's job.

Intent routing
--------------
In Phase 4 a simple rule-based keyword matcher is used.
In Phase 5 it will be replaced by the Groq LLM classifier.

Supported intents
-----------------
  total_revenue   → get_total_revenue()
  top_product     → get_top_product()
  monthly_trend   → get_monthly_revenue()
  top_region      → get_top_region()
  compare_months  → compare_monthly_revenue(start, end)
  unsupported     → returns an error response
"""

import re
import time
import sys
from pathlib import Path

# Allow sibling-package imports when running from project root
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.analytics import (
    get_total_revenue,
    get_top_product,
    get_monthly_revenue,
    get_top_region,
    compare_monthly_revenue,
)
from backend.ai_interpreter import classify_with_llm

# ── Supported question examples shown to the user on unsupported input ─────────
SUPPORTED_QUESTIONS = [
    "What is the total revenue?",
    "Which product generated the highest revenue?",
    "What is the monthly revenue trend?",
    "Which region generated the highest sales?",
    "How did revenue change between January and March?",
]

# ── Month name → YYYY-MM mapping (data spans Jan–Jun 2026) ────────────────────
MONTH_MAP = {
    "january":   "2026-01",
    "jan":       "2026-01",
    "february":  "2026-02",
    "feb":       "2026-02",
    "march":     "2026-03",
    "mar":       "2026-03",
    "april":     "2026-04",
    "apr":       "2026-04",
    "may":       "2026-05",
    "june":      "2026-06",
    "jun":       "2026-06",
}


# ══════════════════════════════════════════════════════════════════════════════
# Rule-based intent classifier (Phase 4 — replaced by LLM in Phase 5)
# ══════════════════════════════════════════════════════════════════════════════

def classify_intent(question: str) -> dict:
    """
    Map a natural-language question to a structured intent dict using
    simple keyword matching. This is the Phase 4 placeholder — Phase 5
    replaces the body of this function with a Groq LLM call.

    Returns
    -------
    dict with keys:
        intent  : str  — one of the six intent labels
        params  : dict — any parameters extracted from the question
        method  : str  — "rule_based" (Phase 4) or "llm" (Phase 5)
    """
    q = question.lower()

    # ── Intent: compare_months ────────────────────────────────────────────────
    # Must be checked BEFORE top_region / monthly_trend because it contains
    # month names that would otherwise match those patterns.
    if any(kw in q for kw in ["between", "change", "compare", "vs", "versus"]):
        months_found = [ym for name, ym in MONTH_MAP.items() if name in q]
        if len(months_found) >= 2:
            return {
                "intent": "compare_months",
                "params": {
                    "start_month": months_found[0],
                    "end_month":   months_found[1],
                },
                "method": "rule_based",
            }
        # Trigger intent but signal missing params
        return {
            "intent": "compare_months",
            "params": {},
            "method": "rule_based",
        }

    # ── Intent: total_revenue ─────────────────────────────────────────────────
    if any(kw in q for kw in ["total revenue", "overall revenue", "all revenue",
                               "total sales", "sum of revenue"]):
        return {"intent": "total_revenue", "params": {}, "method": "rule_based"}

    # ── Intent: top_product ───────────────────────────────────────────────────
    if any(kw in q for kw in ["product", "item", "best seller",
                               "highest revenue product", "top product"]):
        return {"intent": "top_product", "params": {}, "method": "rule_based"}

    # ── Intent: monthly_trend ─────────────────────────────────────────────────
    if any(kw in q for kw in ["monthly", "month", "trend", "over time",
                               "each month", "per month"]):
        return {"intent": "monthly_trend", "params": {}, "method": "rule_based"}

    # ── Intent: top_region ────────────────────────────────────────────────────
    if any(kw in q for kw in ["region", "area", "location", "zone",
                               "where", "geography"]):
        # Detect if user wants quantity-based ranking
        metric = "quantity" if any(kw in q for kw in [
            "quantity", "units", "volume"
        ]) else "revenue"
        return {
            "intent": "top_region",
            "params": {"metric": metric},
            "method": "rule_based",
        }

    # ── Fallback: unsupported ─────────────────────────────────────────────────
    return {"intent": "unsupported", "params": {}, "method": "rule_based"}


# ══════════════════════════════════════════════════════════════════════════════
# Main service function — called by the API route
# ══════════════════════════════════════════════════════════════════════════════

def handle_question(question: str) -> dict:
    """
    Orchestrate the full question-answering workflow.

    Workflow
    --------
    1. Record start time.
    2. Classify the question intent (rule-based in Phase 4, LLM in Phase 5).
    3. Route to the correct analytics function.
    4. Return a result dict that main.py will serialise as JSON.

    Parameters
    ----------
    question : str — The natural-language question from the user.

    Returns
    -------
    dict with at least:
        success          : bool
        question         : str
        intent           : str
        answer           : str
        supporting_data  : dict
        query_description: str
        execution_time_ms: float
    """
    start_time = time.perf_counter()

    # Step 1 — classify intent
    # Try the LLM first; fall back to rule-based if LLM is unavailable
    llm_result = classify_with_llm(question)
    if llm_result.get("error"):
        # LLM failed (missing API key, network error, etc.) → use rule-based
        intent_result = classify_intent(question)
        intent_result["method"] = "rule_based_fallback"
    else:
        intent_result = llm_result
    intent  = intent_result["intent"]
    params  = intent_result.get("params", {})

    # Step 2 — route to the correct analytics function
    analytics_result = _route(intent, params)

    elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)

    # Step 3 — build the unified response dict
    if analytics_result.get("success"):
        return _build_success(question, intent, analytics_result, elapsed_ms)
    else:
        return _build_error(question, intent, analytics_result, elapsed_ms)


def _route(intent: str, params: dict) -> dict:
    """
    Call the correct analytics function based on the classified intent.

    Parameters
    ----------
    intent : str  — Classified intent label.
    params : dict — Extracted parameters (e.g. start_month, end_month).

    Returns
    -------
    dict — Raw result from the analytics function.
    """
    if intent == "total_revenue":
        return get_total_revenue()

    elif intent == "top_product":
        return get_top_product()

    elif intent == "monthly_trend":
        return get_monthly_revenue()

    elif intent == "top_region":
        metric = params.get("metric", "revenue")
        return get_top_region(metric=metric)

    elif intent == "compare_months":
        start = params.get("start_month")
        end   = params.get("end_month")
        if not start or not end:
            return {
                "success": False,
                "function": "compare_monthly_revenue",
                "answer": (
                    "I could not identify two months in your question. "
                    "Please include two month names, e.g. "
                    "'How did revenue change between January and March?'"
                ),
            }
        return compare_monthly_revenue(start, end)

    else:  # unsupported
        return {
            "success": False,
            "function": "unsupported",
            "answer": (
                f"I could not understand the question: '{intent}'. "
                "Please try one of the supported questions."
            ),
        }


def _build_success(
    question: str,
    intent: str,
    result: dict,
    elapsed_ms: float,
) -> dict:
    """
    Convert a successful analytics result into the standard API response dict.
    """
    # Build supporting_data based on intent
    supporting_data: dict = {}

    if intent == "total_revenue":
        supporting_data = {
            "transaction_count": result.get("transaction_count"),
            "min_transaction":   result.get("min_transaction"),
            "max_transaction":   result.get("max_transaction"),
            "avg_transaction":   result.get("avg_transaction"),
        }

    elif intent == "top_product":
        supporting_data = {
            "all_products": result.get("all_products", []),
        }

    elif intent == "monthly_trend":
        supporting_data = {
            "monthly_data":  result.get("monthly_data", []),
            "peak_month":    result.get("peak_month"),
            "peak_revenue":  result.get("peak_revenue"),
            "lowest_month":  result.get("lowest_month"),
            "lowest_revenue": result.get("lowest_revenue"),
        }

    elif intent == "top_region":
        supporting_data = {
            "metric":      result.get("metric", "revenue"),
            "all_regions": result.get("all_regions", []),
        }

    elif intent == "compare_months":
        supporting_data = {
            "start_month":       result.get("start_month"),
            "end_month":         result.get("end_month"),
            "start_month_name":  result.get("start_month_name"),
            "end_month_name":    result.get("end_month_name"),
            "start_revenue":     result.get("start_revenue"),
            "end_revenue":       result.get("end_revenue"),
            "start_transactions": result.get("start_transactions"),
            "end_transactions":  result.get("end_transactions"),
            "absolute_change":   result.get("absolute_change"),
            "pct_change":        result.get("pct_change"),
            "direction":         result.get("direction"),
            "sign":              result.get("sign"),
        }

    return {
        "success":           True,
        "question":          question,
        "intent":            intent,
        "answer":            result.get("answer", ""),
        "supporting_data":   supporting_data,
        "query_description": result.get("query_description", ""),
        "execution_time_ms": elapsed_ms,
    }


def _build_error(
    question: str,
    intent: str,
    result: dict,
    elapsed_ms: float,
) -> dict:
    """
    Convert a failed or unsupported result into a standard error response dict.
    """
    return {
        "success":           False,
        "question":          question,
        "intent":            intent if intent != "unsupported" else "unsupported",
        "answer":            result.get("answer", "An unexpected error occurred."),
        "message":           result.get("answer", "An unexpected error occurred."),
        "hint":              SUPPORTED_QUESTIONS,
        "supporting_data":   {},
        "query_description": "",
        "execution_time_ms": elapsed_ms,
    }
