"""
data/models.py
--------------
Pydantic models as typed contracts for the company intelligence pipeline.

CompanyProfile: validated output schema matching hackathon requirements exactly.

Using Pydantic gives us:
  • Automatic type coercion and validation
  • Serialisation to dict/json for DB and API responses
  • Schema stability — missing fields default to safe values ("N/A", [])
"""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, Field, field_validator


class CompanyProfile(BaseModel):
    """
    Enriched company profile — matches the hackathon output schema exactly.
    
    Schema stability: every field has a safe default so the JSON structure
    NEVER breaks, even if scraping or AI extraction fails partially.
    """
    website_url:          str
    website_name:         str  = "N/A"
    company_name:         str  = "N/A"
    address:              str  = "N/A"
    mobile_number:        str  = "N/A"
    mail:                 list[str] = Field(default_factory=list)
    core_service:         str  = "N/A"
    target_customer:      str  = "N/A"
    probable_pain_point:  str  = "N/A"
    outreach_opener:      str  = "N/A"
    enriched_at:          Optional[datetime] = None

    @field_validator("mail", mode="before")
    @classmethod
    def ensure_mail_is_list(cls, v):
        """Handle edge cases: AI might return a string instead of list."""
        if isinstance(v, str):
            if v.strip() in ("", "N/A", "n/a", "null", "None"):
                return []
            # Could be comma-separated
            return [e.strip() for e in v.split(",") if e.strip()]
        if v is None:
            return []
        if isinstance(v, list):
            return [str(e).strip() for e in v if str(e).strip() and str(e).strip().lower() not in ("n/a", "null", "none")]
        return []

    @field_validator("website_url")
    @classmethod
    def normalize_url(cls, v: str) -> str:
        """Ensure URL has a scheme."""
        v = v.strip()
        if not v.startswith(("http://", "https://")):
            v = "https://" + v
        return v.rstrip("/")

    def to_hackathon_dict(self) -> dict:
        """
        Return the exact JSON format the hackathon expects.
        This is the schema judges will validate against.
        """
        return {
            "website_name":        self.website_name,
            "company_name":        self.company_name,
            "address":             self.address,
            "mobile_number":       self.mobile_number,
            "mail":                self.mail if self.mail else [],
            "core_service":        self.core_service,
            "target_customer":     self.target_customer,
            "probable_pain_point": self.probable_pain_point,
            "outreach_opener":     self.outreach_opener,
        }

    def to_full_dict(self) -> dict:
        """Full dict including metadata, for API responses."""
        d = self.to_hackathon_dict()
        d["website_url"] = self.website_url
        d["enriched_at"] = self.enriched_at.isoformat() if self.enriched_at else None
        return d
