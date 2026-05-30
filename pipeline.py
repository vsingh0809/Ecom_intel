"""
pipeline.py
-----------
Orchestrator: scrape → AI enrich → persist.
This is the only file you need to run to populate the database.

Usage:
    python pipeline.py                  # 5 pages, full AI enrichment
    python pipeline.py --pages 10       # scrape 10 pages (~200 books)
    python pipeline.py --skip-ai        # scrape only, skip Gemini (fast test)

Production design:
    • validate() called before any work starts (fail-fast)
    • Each stage is isolated — a scraper failure doesn't lose AI results
    • Structured JSON logging to logs/pipeline.log for debugging
    • Exit code 1 on fatal errors (for CI/monitoring systems)
"""

import argparse
import sys
from pathlib import Path

from loguru import logger

from config import settings
from scraper import scrape_books
from ai import enrich_books
from data import init_db, upsert_books, load_all_books


# ── Logging setup ─────────────────────────────────────────────────────────────

def _configure_logging() -> None:
    settings.bootstrap()  # ensure logs/ directory exists

    logger.remove()  # remove default handler

    # Console: coloured, human-readable
    logger.add(
        sys.stdout,
        level=settings.LOG_LEVEL,
        format=(
            "<green>{time:HH:mm:ss}</green> | "
            "<level>{level:<8}</level> | "
            "{message}"
        ),
        colorize=True,
    )

    # File: structured, rotated, retained for 7 days
    logger.add(
        settings.LOGS_DIR / "pipeline.log",
        level="DEBUG",
        rotation="10 MB",
        retention="7 days",
        format="{time:YYYY-MM-DD HH:mm:ss} | {level:<8} | {module}.{function} | {message}",
        enqueue=True,       # non-blocking writes
    )


# ── Pipeline stages ───────────────────────────────────────────────────────────

def _stage_scrape(pages: int) -> list:
    logger.info("━━━ Stage 1: Scraping ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    books = scrape_books(max_pages=pages)
    if not books:
        logger.critical("[pipeline] Scraper returned 0 books — aborting")
        sys.exit(1)
    return books


def _stage_enrich(raw_books: list, skip_ai: bool) -> list:
    if skip_ai:
        logger.warning("[pipeline] --skip-ai set: using raw books without enrichment")
        return raw_books

    logger.info("━━━ Stage 2: AI Enrichment ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    return enrich_books(raw_books)


def _stage_persist(books: list) -> None:
    logger.info("━━━ Stage 3: Persisting ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    records = [b.model_dump() for b in books]
    stats   = upsert_books(records)
    logger.info(f"[pipeline] DB write: {stats}")


# ── Main ──────────────────────────────────────────────────────────────────────

def run(pages: int, skip_ai: bool) -> None:
    _configure_logging()

    logger.info(
        f"╔══════════════════════════════════════════════════╗\n"
        f"║   E-Commerce Intelligence Pipeline              ║\n"
        f"║   pages={pages:<4}  skip_ai={str(skip_ai):<5}                   ║\n"
        f"╚══════════════════════════════════════════════════╝"
    )

    # Fail fast on missing config
    if not skip_ai:
        try:
            settings.validate()
        except EnvironmentError as exc:
            logger.critical(str(exc))
            sys.exit(1)

    # Initialise DB schema
    init_db()

    # Run all three stages
    raw_books = _stage_scrape(pages)
    books     = _stage_enrich(raw_books, skip_ai)
    _stage_persist(books)

    # Final summary
    total = len(load_all_books())
    logger.success(
        f"\n✅ Pipeline finished — {total} total books in database\n"
        f"   Next: streamlit run dashboard/app.py"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="E-Commerce Intelligence Pipeline",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=settings.MAX_PAGES,
        help="Number of catalogue pages to scrape (20 books per page)",
    )
    parser.add_argument(
        "--skip-ai",
        action="store_true",
        help="Skip Gemini enrichment — useful for testing the scraper alone",
    )
    args = parser.parse_args()
    run(pages=args.pages, skip_ai=args.skip_ai)
