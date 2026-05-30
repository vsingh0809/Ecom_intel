"""
data/models.py
--------------
Pydantic models act as typed contracts between pipeline stages.
  RawBook     → what the scraper produces
  EnrichedBook → what the AI enricher produces

Using Pydantic gives us:
  • Automatic type coercion (string "4.5" → float 4.5)
  • Validation errors with clear messages
  • Serialisation to dict/json for DB persistence
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class RawBook(BaseModel):
    """
    Data contract for a scraped book.
    Every field here must be filled by the scraper — no AI guesses.
    """
    title:        str
    price:        float          # in GBP (£)
    rating:       int            # 1–5 stars
    availability: str
    url:          str
    scraped_at:   datetime = Field(default_factory=datetime.utcnow)

    @field_validator("rating")
    @classmethod
    def rating_in_range(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError(f"Rating must be 1–5, got {v}")
        return v

    @field_validator("price")
    @classmethod
    def price_non_negative(cls, v: float) -> float:
        if v < 0:
            raise ValueError(f"Price cannot be negative, got {v}")
        return round(v, 2)


class EnrichedBook(RawBook):
    """
    Extends RawBook with AI-generated fields.
    All AI fields have safe defaults so a DB record is always valid
    even if enrichment partially failed.
    """
    genre:        str   = "Unknown"
    summary:      str   = ""
    sentiment:    str   = "Neutral"     # Positive | Neutral | Negative
    value_score:  float = 0.0           # 0.0–10.0 computed by AI
    enriched_at:  Optional[datetime] = None

    @field_validator("value_score")
    @classmethod
    def clamp_value_score(cls, v: float) -> float:
        return round(max(0.0, min(10.0, v)), 2)

    @field_validator("sentiment")
    @classmethod
    def valid_sentiment(cls, v: str) -> str:
        allowed = {"Positive", "Neutral", "Negative"}
        return v if v in allowed else "Neutral"

    def value_label(self) -> str:
        """Human-readable value tier. Used in dashboard."""
        if self.value_score >= 7.0:
            return "Great Deal"
        elif self.value_score >= 4.0:
            return "Fair"
        return "Overpriced"
