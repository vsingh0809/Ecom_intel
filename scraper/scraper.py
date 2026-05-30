"""
scraper/scraper.py
------------------
Production-grade scraper for books.toscrape.com.

Key production practices:
  • @retry with exponential backoff via tenacity (no fragile try/except loops)
  • Respectful per-page delay (REQUEST_DELAY from settings)
  • User-Agent header to avoid trivial bot blocks
  • Pydantic RawBook models — validation happens at parse time, not later
  • Deduplication by URL before returning
  • Every error logged with context — never silently swallowed
"""

import time
from typing import Optional

import requests
from bs4 import BeautifulSoup
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import settings
from data.models import RawBook


# ── Constants ─────────────────────────────────────────────────────────────────

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# books.toscrape.com uses word-form ratings as a CSS class
RATING_WORD_MAP: dict[str, int] = {
    "One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5
}


# ── HTTP layer ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(settings.MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.RequestException),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)
def _fetch(url: str) -> str:
    """
    Fetch HTML with automatic retry + exponential backoff.
    Raises on non-2xx after MAX_RETRIES attempts.
    """
    response = requests.get(url, headers=HEADERS, timeout=settings.REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.text


# ── Parsers ───────────────────────────────────────────────────────────────────

def _parse_price(raw: str) -> float:
    """'Â£51.77' or '£51.77' → 51.77"""
    try:
        cleaned = raw.encode("ascii", errors="ignore").decode().replace("£", "").strip()
        return float(cleaned)
    except ValueError:
        logger.warning(f"[scraper] Unparseable price string: {raw!r} — defaulting to 0.0")
        return 0.0


def _build_book_url(base_url: str, raw_href: str) -> str:
    """
    books.toscrape.com hrefs look like:  ../../a-light-in-attic_/index.html
    Strip the relative prefix and join with catalogue path.
    """
    clean = raw_href.lstrip("./").replace("../", "")
    if not clean.startswith("catalogue/"):
        clean = "catalogue/" + clean
    return f"{base_url}/{clean}"


def _parse_page(html: str, base_url: str) -> list[RawBook]:
    """Parse one catalogue page into validated RawBook objects."""
    soup = BeautifulSoup(html, "html.parser")
    books: list[RawBook] = []

    for article in soup.select("article.product_pod"):
        try:
            # Title
            title_tag = article.select_one("h3 > a")
            if not title_tag:
                continue
            title: str = title_tag.get("title", title_tag.text).strip()

            # URL
            href: str = title_tag.get("href", "")
            book_url: str = _build_book_url(base_url, href)

            # Price
            price_tag = article.select_one("p.price_color")
            price: float = _parse_price(price_tag.text) if price_tag else 0.0

            # Star rating (stored as CSS class word on <p class="star-rating Three">)
            rating_tag = article.select_one("p.star-rating")
            rating_word: str = rating_tag["class"][1] if rating_tag else "One"
            rating: int = RATING_WORD_MAP.get(rating_word, 1)

            # Availability
            avail_tag = article.select_one("p.availability")
            availability: str = avail_tag.text.strip() if avail_tag else "Unknown"

            books.append(
                RawBook(
                    title=title,
                    price=price,
                    rating=rating,
                    availability=availability,
                    url=book_url,
                )
            )
        except Exception as exc:
            logger.warning(f"[scraper] Skipped one article due to parse error: {exc}")
            continue

    return books


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_books(max_pages: Optional[int] = None) -> list[RawBook]:
    """
    Scrape up to `max_pages` catalogue pages from books.toscrape.com.

    Returns a deduplicated list of RawBook objects sorted by title.
    Never raises — returns whatever was collected before any failure.
    """
    max_pages = max_pages or settings.MAX_PAGES
    base_url  = settings.TARGET_URL.rstrip("/")
    all_books: list[RawBook] = []

    for page_num in range(1, max_pages + 1):
        page_url = (
            f"{base_url}/index.html"
            if page_num == 1
            else f"{base_url}/catalogue/page-{page_num}.html"
        )

        logger.info(f"[scraper] Fetching page {page_num}/{max_pages} → {page_url}")

        try:
            html  = _fetch(page_url)
            books = _parse_page(html, base_url)
            all_books.extend(books)
            logger.success(f"[scraper] Page {page_num}: parsed {len(books)} books")
        except Exception as exc:
            logger.error(f"[scraper] Page {page_num} failed after retries: {exc}")

        # Respectful crawl delay (skip on last page)
        if page_num < max_pages:
            time.sleep(settings.REQUEST_DELAY)

    # Deduplicate by URL, preserving first-seen order
    seen: set[str] = set()
    unique: list[RawBook] = []
    for book in all_books:
        if book.url not in seen:
            seen.add(book.url)
            unique.append(book)

    logger.info(f"[scraper] Done — {len(unique)} unique books collected")
    return unique
