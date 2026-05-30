"""
pipeline.py
-----------
Orchestrator: scrape → AI enrich → persist.

Reusable from both the FastAPI server and the Colab notebook.
Each function is isolated — a scraper failure doesn't crash AI results.

Usage:
    # Single company (web API)
    result = enrich_single("https://example.com", "Example Corp")

    # Batch companies (Colab notebook)
    results = enrich_batch(["https://a.com", "https://b.com"])
"""

import sys
from datetime import datetime
from pathlib import Path

from loguru import logger

from config import settings
from scraper import scrape_company
from ai import enrich_company, enrich_companies_batch
from data import init_db, upsert_company, CompanyProfile


# ── Logging setup ─────────────────────────────────────────────────────────────

def configure_logging() -> None:
    settings.bootstrap()

    logger.remove()

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
        enqueue=True,
    )


# ── Single Company Pipeline ──────────────────────────────────────────────────

def enrich_single(url: str, website_name: str = "N/A") -> dict:
    """
    Full pipeline for a single company: scrape → AI enrich → persist.

    Returns the enriched company profile dict (hackathon format + metadata).
    Never raises — returns a safe fallback dict on any failure.
    """
    logger.info(f"[pipeline] Starting enrichment for: {url}")

    # Ensure DB is ready
    init_db()

    # Stage 1: Scrape
    logger.info("[pipeline] ━━━ Stage 1: Scraping ━━━")
    scraped = scrape_company(url)

    if not scraped.get("success"):
        logger.warning(f"[pipeline] Scraping failed for {url}: {scraped.get('error')}")

    # Stage 2: AI Enrichment
    logger.info("[pipeline] ━━━ Stage 2: AI Enrichment ━━━")
    enriched = enrich_company(scraped, website_name)

    # Stage 3: Validate & Persist
    logger.info("[pipeline] ━━━ Stage 3: Persisting ━━━")
    try:
        profile = CompanyProfile(
            website_url=url,
            enriched_at=datetime.utcnow(),
            **enriched,
        )
        profile_dict = profile.to_full_dict()
        upsert_company(profile_dict)
    except Exception as exc:
        logger.error(f"[pipeline] Validation/persist error: {exc}")
        # Still return the enriched data even if persistence fails
        enriched["website_url"] = url
        enriched["enriched_at"] = datetime.utcnow().isoformat()
        return enriched

    logger.success(f"[pipeline] ✅ Enrichment complete for: {enriched.get('company_name', url)}")
    return profile_dict


# ── Batch Pipeline (for Colab) ────────────────────────────────────────────────

def enrich_batch(urls: list[str]) -> list[dict]:
    """
    Batch pipeline for multiple companies.
    Scrapes all URLs first, then batch-enriches with AI, then persists.

    Returns list of enriched profile dicts in hackathon format.
    """
    if not urls:
        return []

    logger.info(f"[pipeline] Batch enrichment for {len(urls)} URLs")

    # Ensure DB is ready
    init_db()

    # Stage 1: Scrape all
    logger.info("[pipeline] ━━━ Stage 1: Scraping All ━━━")
    scraped_list = []
    website_names = []
    for i, url in enumerate(urls):
        logger.info(f"[pipeline] Scraping {i+1}/{len(urls)}: {url}")
        scraped = scrape_company(url)
        scraped_list.append(scraped)
        # Derive website name from domain
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc.replace("www.", "")
        name = domain.split(".")[0].replace("-", " ").title()
        website_names.append(name)

    # Stage 2: AI Enrichment (batch)
    logger.info("[pipeline] ━━━ Stage 2: Batch AI Enrichment ━━━")
    enriched_list = enrich_companies_batch(scraped_list, website_names)

    # Stage 3: Validate & Persist all
    logger.info("[pipeline] ━━━ Stage 3: Persisting All ━━━")
    results = []
    for url, enriched in zip(urls, enriched_list):
        try:
            profile = CompanyProfile(
                website_url=url,
                enriched_at=datetime.utcnow(),
                **enriched,
            )
            hackathon_dict = profile.to_hackathon_dict()
            full_dict = profile.to_full_dict()
            upsert_company(full_dict)
            results.append(hackathon_dict)
        except Exception as exc:
            logger.error(f"[pipeline] Error persisting {url}: {exc}")
            results.append(enriched)

    logger.success(f"[pipeline] ✅ Batch complete — {len(results)} companies enriched")
    return results


if __name__ == "__main__":
    configure_logging()

    # Interactive mode: ask for URLs
    print("=" * 60)
    print("  Company Intelligence Pipeline")
    print("=" * 60)

    raw_input = input("\nEnter company URLs (JSON array or comma-separated):\n> ").strip()

    # Parse input
    import json
    try:
        urls = json.loads(raw_input)
    except json.JSONDecodeError:
        urls = [u.strip() for u in raw_input.split(",") if u.strip()]

    if not urls:
        print("No URLs provided. Exiting.")
        sys.exit(1)

    print(f"\nProcessing {len(urls)} URLs...")
    results = enrich_batch(urls)

    # Output as formatted JSON
    output = json.dumps(results, indent=2, ensure_ascii=False)
    print("\n" + "=" * 60)
    print("RESULTS:")
    print("=" * 60)
    print(output)

    # Save to file
    output_path = settings.DATA_DIR / "results.json"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(f"\n✅ Results saved to: {output_path}")
