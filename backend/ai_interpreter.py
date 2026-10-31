"""
backend/ai_interpreter.py
--------------------------
Groq LLM integration for natural-language intent classification.

What this file does
-------------------
1. Receives a natural-language question from backend/services.py.
2. Builds a structured prompt and sends it to the Groq API.
3. The LLM returns a JSON object identifying the analytical intent
   and any required parameters (e.g. month names).
4. The JSON is parsed and validated with Pydantic.
5. The validated IntentResult is returned to services.py for routing.

What this file does NOT do
--------------------------
- It does NOT run SQL.
- It does NOT calculate numbers.
- It does NOT allow the LLM to invent figures.
- It does NOT expose the API key to the frontend.

Security principle
------------------
The LLM is used ONLY as a classifier. It must return one of six
allowed intent labels. Any other response is rejected as "unsupported".
All numerical calculations happen in SQLite via analytics.py.

Supported intents
-----------------
  total_revenue   → get_total_revenue()
  top_product     → get_top_product()
  monthly_trend   → get_monthly_revenue()
  top_region      → get_top_region()
  compare_months  → compare_monthly_revenue(start_month, end_month)
  unsupported     → error response returned to user

Environment variables required
------------------------------
  GROQ_API_KEY   : your Groq API key (from https://console.groq.com)
  GROQ_MODEL     : model name (default: llama3-8b-8192)

Usage
-----
  from backend.ai_interpreter import classify_with_llm
  result = classify_with_llm("Which product had the best revenue?")
  # result → IntentResult(intent="top_product", params={}, confidence="high")
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, field_validator, ValidationError
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv(Path(__file__).parent.parent / ".env")

# ── Groq client (imported lazily so missing SDK doesn't crash at import time) ─
try:
    from groq import Groq
    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False

# ── Configuration ──────────────────────────────────────────────────────────────
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL   = os.getenv("GROQ_MODEL", "llama3-8b-8192")

# Months available in the dataset
VALID_MONTHS = {
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

ALLOWED_INTENTS = {
    "total_revenue",
    "top_product",
    "monthly_trend",
    "top_region",
    "compare_months",
    "unsupported",
}


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic model for LLM output validation
# ══════════════════════════════════════════════════════════════════════════════

class IntentResult(BaseModel):
    """
    The structured output we expect the LLM to return.

    Fields
    ------
    intent      : one of the six allowed intent labels (validated below).
    params      : optional dict with extracted parameters.
                  For compare_months this must contain start_month and end_month
                  in YYYY-MM format.
    confidence  : "high", "medium", or "low" — the LLM's self-reported
                  confidence. We log this but do not gate on it.
    reasoning   : optional string explaining why the LLM chose this intent.
                  Useful for debugging.
    """
    intent:     str
    params:     dict = {}
    confidence: str  = "high"
    reasoning:  str  = ""

    @field_validator("intent")
    @classmethod
    def validate_intent(cls, v: str) -> str:
        """
        Reject any intent label the LLM invents outside our approved list.
        This is the primary safety gate against hallucinated intent names.
        """
        v_clean = v.strip().lower()
        if v_clean not in ALLOWED_INTENTS:
            # Log the unexpected value and fall back to "unsupported"
            print(
                f"[ai_interpreter] WARNING: LLM returned unknown intent "
                f"'{v}' — falling back to 'unsupported'."
            )
            return "unsupported"
        return v_clean


# ══════════════════════════════════════════════════════════════════════════════
# Prompt builder
# ══════════════════════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """\
You are an intent classifier for a sales analytics application.

The application can answer ONLY these five types of business questions:

1. total_revenue    — questions about overall / total revenue or total sales amount
2. top_product      — questions about which product earned the most revenue
3. monthly_trend    — questions about monthly revenue patterns or trends over time
4. top_region       — questions about which region had the highest sales or revenue
5. compare_months   — questions comparing revenue between two specific months

If the question does NOT match any of the above, classify it as:
6. unsupported

YOUR TASK:
Classify the user's question and return ONLY a valid JSON object with this exact structure:

{
  "intent": "<one of the six intent labels>",
  "params": {
    "start_month": "<YYYY-MM if compare_months, else omit>",
    "end_month":   "<YYYY-MM if compare_months, else omit>",
    "metric":      "<revenue or quantity for top_region, else omit>"
  },
  "confidence": "<high | medium | low>",
  "reasoning":  "<one sentence explaining your choice>"
}

MONTH MAPPING (dataset covers January to June 2026):
  January  → 2026-01
  February → 2026-02
  March    → 2026-03
  April    → 2026-04
  May      → 2026-05
  June     → 2026-06

RULES:
- Return ONLY valid JSON. No extra text, no markdown, no code fences.
- Never invent numerical values. Never write SQL.
- If the question mentions two months, extract both as start_month and end_month.
- If the question mentions "units" or "quantity" for region, set metric to "quantity".
- Otherwise leave metric as "revenue".
"""


def _build_user_prompt(question: str) -> str:
    """Wrap the user question in a simple prompt."""
    return f'Classify this question: "{question}"'


# ══════════════════════════════════════════════════════════════════════════════
# Main classifier function
# ══════════════════════════════════════════════════════════════════════════════

def classify_with_llm(question: str) -> dict:
    """
    Send the question to the Groq LLM and return a validated intent dict.

    Flow
    ----
    1. Check that the Groq SDK and API key are available.
    2. Build and send the prompt.
    3. Parse the raw JSON response.
    4. Validate with Pydantic (IntentResult).
    5. Return the validated intent as a plain dict.

    If anything fails (API error, bad JSON, invalid intent), the function
    returns a safe fallback dict with intent="unsupported" and an error
    message — it never raises an exception that would crash the API.

    Parameters
    ----------
    question : str — The user's natural-language question.

    Returns
    -------
    dict with keys:
        intent     : str  — validated intent label
        params     : dict — extracted parameters
        confidence : str
        reasoning  : str
        method     : str  — "llm" or "fallback"
        error      : str  — present only when an error occurred
    """
    # ── Safety check: SDK installed and API key present ───────────────────────
    if not GROQ_AVAILABLE:
        return _fallback("Groq SDK not installed. Run: pip install groq")

    if not GROQ_API_KEY or GROQ_API_KEY == "your_groq_api_key_here":
        return _fallback("GROQ_API_KEY is not set in .env")

    try:
        client = Groq(api_key=GROQ_API_KEY)

        # ── Call the Groq API ─────────────────────────────────────────────────
        chat_completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": _build_user_prompt(question)},
            ],
            temperature=0.1,      # Low temperature → more deterministic output
            max_tokens=256,       # We only need a small JSON object
            response_format={"type": "json_object"},  # Force JSON output
        )

        raw_content = chat_completion.choices[0].message.content
        print(f"[ai_interpreter] Raw LLM response: {raw_content}")

        # ── Parse JSON ────────────────────────────────────────────────────────
        try:
            parsed = json.loads(raw_content)
        except json.JSONDecodeError as e:
            return _fallback(f"LLM returned invalid JSON: {e}. Raw: {raw_content[:200]}")

        # ── Validate with Pydantic ────────────────────────────────────────────
        try:
            intent_result = IntentResult(**parsed)
        except ValidationError as e:
            return _fallback(f"Pydantic validation failed: {e}")

        # ── Normalise compare_months params ───────────────────────────────────
        if intent_result.intent == "compare_months":
            intent_result.params = _normalise_month_params(
                intent_result.params, question
            )

        return {
            "intent":     intent_result.intent,
            "params":     intent_result.params,
            "confidence": intent_result.confidence,
            "reasoning":  intent_result.reasoning,
            "method":     "llm",
        }

    except Exception as e:
        # Groq API rate limit, network error, etc.
        return _fallback(f"Groq API error: {type(e).__name__}: {e}")


# ══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════════════

def _normalise_month_params(params: dict, question: str) -> dict:
    """
    Ensure start_month and end_month are in YYYY-MM format.

    The LLM might return month names (e.g. "January") instead of YYYY-MM.
    This function converts them using our VALID_MONTHS mapping.
    If the LLM already returned YYYY-MM strings, they pass through unchanged.
    If the LLM missed month params, we attempt to extract them from the
    original question as a last resort.
    """
    def resolve(value: Optional[str]) -> Optional[str]:
        if not value:
            return None
        v = value.strip().lower()
        # Already in YYYY-MM format
        if len(v) == 7 and v[4] == "-":
            return v
        # Convert month name to YYYY-MM
        return VALID_MONTHS.get(v, None)

    start = resolve(params.get("start_month"))
    end   = resolve(params.get("end_month"))

    # Last-resort extraction from question text
    if not start or not end:
        months_in_question = [
            ym for name, ym in VALID_MONTHS.items()
            if name in question.lower()
        ]
        if len(months_in_question) >= 2:
            start = start or months_in_question[0]
            end   = end   or months_in_question[1]

    return {"start_month": start, "end_month": end}


def _fallback(error_message: str) -> dict:
    """
    Return a safe fallback intent dict when the LLM call fails.
    Services.py will treat this as "unsupported" with the error as the answer.
    """
    print(f"[ai_interpreter] FALLBACK triggered: {error_message}")
    return {
        "intent":     "unsupported",
        "params":     {},
        "confidence": "low",
        "reasoning":  error_message,
        "method":     "fallback",
        "error":      error_message,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Quick test — run this file directly
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    test_questions = [
        "What is the total revenue?",
        "Which product generated the highest revenue?",
        "What is the monthly revenue trend?",
        "Which region generated the highest sales?",
        "How did revenue change between January and March?",
        "What is the weather today?",          # unsupported
        "Compare revenue between April and June",
    ]

    print("\n" + "=" * 60)
    print("  AI INTERPRETER SELF-TEST")
    print("=" * 60)

    for q in test_questions:
        print(f"\nQ: {q}")
        result = classify_with_llm(q)
        print(f"   Intent    : {result['intent']}")
        print(f"   Params    : {result['params']}")
        print(f"   Confidence: {result['confidence']}")
        print(f"   Method    : {result['method']}")
        if "error" in result:
            print(f"   Error     : {result['error']}")

    print("\n" + "=" * 60)
