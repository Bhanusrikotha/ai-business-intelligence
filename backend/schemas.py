"""
backend/schemas.py
------------------
All Pydantic request and response models for the FastAPI API.

What Pydantic does
------------------
Pydantic automatically:
  - Validates that incoming JSON has the required fields.
  - Converts types (e.g. string "123" → int 123 if needed).
  - Returns a clear HTTP 422 error if validation fails.
  - Serialises Python dicts to JSON for responses.

Models defined here
-------------------
REQUEST models  (what the client sends TO the API):
  - QuestionRequest       : POST /api/ask

RESPONSE models (what the API sends BACK to the client):
  - HealthResponse        : GET  /api/health
  - AnalyticsResponse     : POST /api/ask (success)
  - ErrorResponse         : POST /api/ask (failure / unsupported)
  - MonthlyDataPoint      : nested inside AnalyticsResponse
  - ProductDataPoint      : nested inside AnalyticsResponse
  - RegionDataPoint       : nested inside AnalyticsResponse
"""

from typing import Any, Optional
from pydantic import BaseModel, Field, field_validator


# ══════════════════════════════════════════════════════════════════════════════
# REQUEST MODELS
# ══════════════════════════════════════════════════════════════════════════════

class QuestionRequest(BaseModel):
    """
    Body of the POST /api/ask request.

    Fields
    ------
    question : str — the natural-language question from the user.
                     Must be non-empty after stripping whitespace.
    """
    question: str = Field(
        ...,                          # ... means this field is REQUIRED
        min_length=1,
        max_length=500,
        description="Natural-language business question",
        examples=["What is the total revenue?"],
    )

    @field_validator("question", mode="before")
    @classmethod
    def strip_whitespace(cls, v: str) -> str:
        """Strip leading/trailing whitespace before length validation."""
        if isinstance(v, str):
            return v.strip()
        return v


# ══════════════════════════════════════════════════════════════════════════════
# NESTED DATA MODELS (used inside AnalyticsResponse.supporting_data)
# ══════════════════════════════════════════════════════════════════════════════

class MonthlyDataPoint(BaseModel):
    """One row in the monthly revenue table / chart."""
    year_month:        str
    month_name:        str
    monthly_revenue:   float
    transaction_count: int
    total_units:       int
    mom_change:        Optional[float] = None
    mom_pct:           Optional[float] = None
    mom_label:         str = "N/A"


class ProductDataPoint(BaseModel):
    """One row in the product revenue table / bar chart."""
    rank:              int
    product:           str
    product_revenue:   float
    total_units_sold:  int
    transaction_count: int


class RegionDataPoint(BaseModel):
    """One row in the region revenue table / bar chart."""
    rank:              int
    region:            str
    total_revenue:     float
    total_units:       int
    transaction_count: int


# ══════════════════════════════════════════════════════════════════════════════
# RESPONSE MODELS
# ══════════════════════════════════════════════════════════════════════════════

class HealthResponse(BaseModel):
    """Response body for GET /api/health."""
    status:         str = "ok"
    message:        str
    database_rows:  int


class AnalyticsResponse(BaseModel):
    """
    Successful response body for POST /api/ask.

    Fields
    ------
    success          : always True for this model.
    question         : the original question echoed back.
    intent           : which analytics function was invoked.
    answer           : human-readable answer sentence.
    supporting_data  : dict containing tables/charts data for the frontend.
    query_description: plain-English description of the SQL used.
    execution_time_ms: how long the full request took (ms).
    """
    success:           bool = True
    question:          str
    intent:            str
    answer:            str
    supporting_data:   dict[str, Any] = {}
    query_description: str = ""
    execution_time_ms: float


class ErrorResponse(BaseModel):
    """
    Error or unsupported-question response for POST /api/ask.

    Fields
    ------
    success   : always False for this model.
    question  : the original question echoed back.
    intent    : "unsupported" or "error".
    message   : human-readable error explanation.
    hint      : suggested questions the user can try.
    """
    success:           bool = False
    question:          str
    intent:            str = "unsupported"
    message:           str
    hint:              list[str] = []
    execution_time_ms: float = 0.0
