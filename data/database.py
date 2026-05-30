"""
data/database.py
----------------
SQLAlchemy ORM layer — the only place in the codebase that touches the DB.

Design decisions:
  • url is the PRIMARY KEY — safe to run pipeline multiple times (upsert)
  • pool_pre_ping=True — avoids stale connections on Railway
  • All public functions return plain dicts/DataFrames, not ORM objects —
    keeps the rest of the codebase free of SQLAlchemy imports
"""

from datetime import datetime
from typing import Any
import pandas as pd
from sqlalchemy import (
    create_engine, Column, String, Float, Integer, DateTime, Text, inspect
)
from sqlalchemy.orm import DeclarativeBase, Session
from loguru import logger

from config import settings


# ── ORM Setup ─────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    pass


class BookRecord(Base):
    __tablename__ = "books"

    # Identity
    url          = Column(String,  primary_key=True)
    title        = Column(String,  nullable=False, index=True)

    # Scraped fields
    price        = Column(Float,   nullable=False)
    rating       = Column(Integer, nullable=False)
    availability = Column(String,  nullable=False)
    scraped_at   = Column(DateTime, default=datetime.utcnow)

    # AI-enriched fields (nullable — may not be enriched yet)
    genre        = Column(String, default="Unknown")
    summary      = Column(Text,   default="")
    sentiment    = Column(String, default="Neutral")
    value_score  = Column(Float,  default=0.0)
    enriched_at  = Column(DateTime, nullable=True)


# ── Engine (module-level singleton) ───────────────────────────────────────────

_engine = None


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            settings.DB_URL,
            echo=False,
            pool_pre_ping=True,   # keeps connections alive on cloud hosts
            connect_args={"check_same_thread": False},  # needed for SQLite
        )
    return _engine


# ── Public API ────────────────────────────────────────────────────────────────

def init_db() -> None:
    """Create all tables if they don't exist. Idempotent."""
    Base.metadata.create_all(get_engine())
    logger.info("[db] Schema initialised")


def upsert_books(records: list[dict[str, Any]]) -> dict[str, int]:
    """
    Insert new books or update existing ones (keyed on url).
    Returns {"inserted": N, "updated": M} for logging.
    """
    if not records:
        logger.warning("[db] upsert called with empty list — nothing to do")
        return {"inserted": 0, "updated": 0}

    # Resolve valid column names once — guards against extra Pydantic fields
    valid_cols = {c.name for c in BookRecord.__table__.columns}
    inserted = updated = 0

    with Session(get_engine()) as session:
        for rec in records:
            clean = {k: v for k, v in rec.items() if k in valid_cols}
            existing = session.get(BookRecord, clean["url"])
            if existing:
                for k, v in clean.items():
                    setattr(existing, k, v)
                updated += 1
            else:
                session.add(BookRecord(**clean))
                inserted += 1
        session.commit()

    logger.info(f"[db] Upsert complete — inserted={inserted}, updated={updated}")
    return {"inserted": inserted, "updated": updated}


def load_all_books() -> pd.DataFrame:
    """
    Load every book as a DataFrame.
    Returns empty DataFrame (not None) when table is empty — safe for callers.
    """
    with Session(get_engine()) as session:
        rows = session.query(BookRecord).order_by(BookRecord.scraped_at.desc()).all()

    if not rows:
        return pd.DataFrame()

    return pd.DataFrame(
        [{c.name: getattr(row, c.name) for c in BookRecord.__table__.columns}
         for row in rows]
    )


def get_stats() -> dict[str, Any]:
    """Quick aggregate stats — used by dashboard KPI row."""
    df = load_all_books()
    if df.empty:
        return {}

    return {
        "total":          len(df),
        "avg_price":      round(df["price"].mean(), 2),
        "avg_rating":     round(df["rating"].mean(), 2),
        "top_genre":      df["genre"].mode()[0] if "genre" in df.columns else "N/A",
        "enriched_count": int(df["enriched_at"].notna().sum()),
        "last_scraped":   df["scraped_at"].max(),
    }
