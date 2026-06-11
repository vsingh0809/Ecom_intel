"""
data/database.py
----------------
SQLAlchemy ORM layer for company profiles — the only place that touches the DB.

Design decisions:
  • website_url is the PRIMARY KEY — safe to enrich the same company multiple times
  • mail stored as JSON string (SQLite has no native array type)
  • pool_pre_ping=True — avoids stale connections on Render
  • All public functions return plain dicts, not ORM objects
"""

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    create_engine, Column, String, Float, Integer, DateTime, Text, inspect
)
from sqlalchemy.orm import DeclarativeBase, Session
from loguru import logger

from config import settings


# ── ORM Setup ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class CompanyRecord(Base):
    __tablename__ = "companies"

    # Identity
    website_url    = Column(String,  primary_key=True)

    # Core fields (match hackathon schema)
    website_name         = Column(String,  nullable=False, default="N/A")
    company_name         = Column(String,  nullable=False, default="N/A")
    address              = Column(String,  default="N/A")
    mobile_number        = Column(String,  default="N/A")
    mail                 = Column(Text,    default="[]")  # JSON array string
    core_service         = Column(Text,    default="N/A")
    target_customer      = Column(Text,    default="N/A")
    probable_pain_point  = Column(Text,    default="N/A")
    outreach_opener      = Column(Text,    default="N/A")

    # Metadata
    enriched_at = Column(DateTime, default=datetime.utcnow)


# ── Engine (module-level singleton) ───────────────────────────────────────────

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.DB_URL,
            echo=False,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},  # needed for SQLite
        )
    return _engine


# ── Public API ────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist. Idempotent."""
    settings.bootstrap()
    Base.metadata.create_all(get_engine())
    logger.info("[db] Schema initialised")


def _ensure_datetime(value: Any) -> datetime:
    """
    Convert value to datetime object.
    Handles: datetime, ISO string (with or without Z), and None.
    """
    if isinstance(value, datetime):
        return value
    
    if isinstance(value, str):
        try:
            # Handle ISO format with Z timezone
            if value.endswith('Z'):
                value = value[:-1] + '+00:00'
            return datetime.fromisoformat(value)
        except (ValueError, AttributeError) as e:
            logger.warning(f"[db] Failed to parse enriched_at '{value}': {e}")
            return datetime.utcnow()
    
    # Default case (None, int, etc.)
    return datetime.utcnow()


def upsert_company(profile_dict: dict) -> dict[str, str]:
    """
    Insert or update a company profile.
    The 'mail' field is converted from list to JSON string for storage.
    Returns {"action": "inserted"} or {"action": "updated"}.
    
    CRITICAL: enriched_at must be a Python datetime object.
    If passed as ISO string, it will be automatically parsed to datetime.
    """
    # Convert mail list to JSON string for SQLite storage
    data = dict(profile_dict)
    if isinstance(data.get("mail"), list):
        data["mail"] = json.dumps(data["mail"])

    # Only keep columns that exist in the table
    valid_cols = {c.name for c in CompanyRecord.__table__.columns}
    clean = {k: v for k, v in data.items() if k in valid_cols}

    # ── CRITICAL FIX: Ensure enriched_at is a datetime object ──────────────────
    # SQLite DateTime type only accepts Python datetime.datetime objects
    if "enriched_at" in clean and clean["enriched_at"] is not None:
        clean["enriched_at"] = _ensure_datetime(clean["enriched_at"])
    else:
        clean["enriched_at"] = datetime.utcnow()

    with Session(get_engine()) as session:
        existing = session.get(CompanyRecord, clean["website_url"])
        if existing:
            for k, v in clean.items():
                setattr(existing, k, v)
            action = "updated"
        else:
            session.add(CompanyRecord(**clean))
            action = "inserted"
        session.commit()

    logger.info(f"[db] {action} company: {clean.get('website_url', 'unknown')}")
    return {"action": action}


def load_all_companies() -> list[dict[str, Any]]:
    """
    Load all company profiles as a list of dicts.
    Converts mail JSON string back to list.
    Returns empty list (not None) when table is empty.
    """
    with Session(get_engine()) as session:
        rows = session.query(CompanyRecord).order_by(
            CompanyRecord.enriched_at.desc()
        ).all()

    if not rows:
        return []

    results = []
    for row in rows:
        d = {c.name: getattr(row, c.name) for c in CompanyRecord.__table__.columns}
        # Convert mail JSON string back to list
        try:
            d["mail"] = json.loads(d["mail"]) if d["mail"] else []
        except (json.JSONDecodeError, TypeError):
            d["mail"] = []
        # Convert datetime to ISO string for JSON serialization
        if d.get("enriched_at"):
            d["enriched_at"] = d["enriched_at"].isoformat()
        results.append(d)

    return results


def get_company_by_url(url: str) -> Optional[dict[str, Any]]:
    """Look up a single company by URL. Returns None if not found."""
    url = url.strip().rstrip("/")

    with Session(get_engine()) as session:
        row = session.get(CompanyRecord, url)

    if not row:
        return None

    d = {c.name: getattr(row, c.name) for c in CompanyRecord.__table__.columns}
    try:
        d["mail"] = json.loads(d["mail"]) if d["mail"] else []
    except (json.JSONDecodeError, TypeError):
        d["mail"] = []
    if d.get("enriched_at"):
        d["enriched_at"] = d["enriched_at"].isoformat()
    return d
