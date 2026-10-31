"""
backend/main.py
---------------
FastAPI application entry point.

Defines two routes:
  GET  /api/health  — liveness check, returns DB row count
  POST /api/ask     — accepts a natural-language question, returns analytics

Responsibilities
----------------
- Receive and validate HTTP requests (Pydantic does the validation).
- Delegate business logic to backend/services.py.
- Serialize the response as JSON.
- Return appropriate HTTP status codes.

What this file does NOT do
--------------------------
- No SQL. No LLM calls. No business calculations.

How to run
----------
  cd ai-business-intelligence
  uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000

Swagger UI (interactive API docs):
  http://127.0.0.1:8000/docs

ReDoc (alternative API docs):
  http://127.0.0.1:8000/redoc
"""

import sys
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# Allow sibling-package imports
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from backend.schemas import (
    QuestionRequest,
    AnalyticsResponse,
    ErrorResponse,
    HealthResponse,
)
from backend.services import handle_question
from database.db import execute_query, DATABASE_PATH


# ── Application instance ───────────────────────────────────────────────────────
app = FastAPI(
    title="Mini AI Business Intelligence Assistant",
    description=(
        "Ask natural-language questions about sales data. "
        "The AI classifies your intent and retrieves real figures from SQLite."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS middleware ────────────────────────────────────────────────────────────
# Allows the Streamlit frontend (running on port 8501) to call this API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Restrict to specific origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ══════════════════════════════════════════════════════════════════════════════
# Route 1 — Health check
# ══════════════════════════════════════════════════════════════════════════════

@app.get(
    "/api/health",
    response_model=HealthResponse,
    summary="Health check",
    tags=["Health"],
)
def health_check() -> HealthResponse:
    """
    Verify that the API is running and the database is accessible.

    Returns the number of analytics-eligible rows so the caller can
    confirm data was loaded correctly.

    HTTP 200 — API is healthy.
    HTTP 500 — Database is unreachable (handled by the global exception handler).
    """
    rows = execute_query(
        "SELECT COUNT(*) AS cnt FROM sales_analytics;",
        db_path=DATABASE_PATH,
    )
    db_count = rows[0]["cnt"] if rows else 0

    return HealthResponse(
        status="ok",
        message=(
            f"API is running. Database contains {db_count} "
            "analytics-eligible transactions."
        ),
        database_rows=db_count,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Route 2 — Ask a question
# ══════════════════════════════════════════════════════════════════════════════

@app.post(
    "/api/ask",
    summary="Ask a business intelligence question",
    tags=["Analytics"],
)
def ask_question(body: QuestionRequest, request: Request):
    """
    Accept a natural-language business question and return an analytics answer.

    Workflow
    --------
    1. Pydantic validates the request body (QuestionRequest).
    2. services.handle_question() classifies the intent and calls the
       correct analytics function.
    3. The result is returned as JSON.

    Returns HTTP 200 with AnalyticsResponse on success.
    Returns HTTP 200 with ErrorResponse on unsupported/missing-param questions.
    Returns HTTP 422 if the request body fails Pydantic validation.
    Returns HTTP 500 on unexpected server errors.

    Note: Even unsupported questions return HTTP 200 (not 4xx) because
    the request itself was valid — the question was simply out of scope.
    Returning 422 for valid JSON with an unrecognised question would
    confuse clients. The `success: false` field signals the failure instead.
    """
    result = handle_question(body.question)

    if result["success"]:
        return AnalyticsResponse(
            success=True,
            question=result["question"],
            intent=result["intent"],
            answer=result["answer"],
            supporting_data=result["supporting_data"],
            query_description=result.get("query_description", ""),
            execution_time_ms=result["execution_time_ms"],
        )
    else:
        return ErrorResponse(
            success=False,
            question=result["question"],
            intent=result.get("intent", "unsupported"),
            message=result.get("message", result.get("answer", "")),
            hint=result.get("hint", []),
            execution_time_ms=result.get("execution_time_ms", 0.0),
        )


# ══════════════════════════════════════════════════════════════════════════════
# Global exception handler — catches unexpected server errors
# ══════════════════════════════════════════════════════════════════════════════

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch any unhandled exception and return a safe 500 response.
    The actual error is logged to stderr but never exposed to the client.
    """
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "An internal server error occurred. Please try again.",
            "intent":  "error",
        },
    )


# ══════════════════════════════════════════════════════════════════════════════
# Direct execution entry point
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run(
        "backend.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )
