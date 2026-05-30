"""
scraper/scraper.py
------------------
Production-grade smart company website scraper with 3-tier fallback strategy.

Scraping approach (scored heavily in hackathon):
  1. Sitemap Discovery: Try robots.txt → sitemap.xml → fuzzy-match relevant URLs
  2. Homepage Link Crawling: Extract all internal links, score by relevance keywords
  3. Homepage Fallback: Just scrape the homepage if nothing else works

Token optimization (critical for LLM cost and scoring):
  • Strip <script>, <style>, <nav>, <footer>, <header>, cookie banners
  • Collapse whitespace, limit text per page (~4000 chars)
  • Max 5 pages scraped per company → ~20K chars total to LLM

Anti-blocking:
  • Rotated User-Agent strings
  • Respectful delays between requests
  • Proper timeout handling
  • Retry with exponential backoff

Contact extraction:
  • Regex-based email/phone extraction from RAW HTML (before cleaning)
  • These are passed to the LLM as ground truth — prevents hallucination
"""

import re
import time
import xml.etree.ElementTree as ET
from difflib import SequenceMatcher
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Comment
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)

from config import settings


# ── Constants ─────────────────────────────────────────────────────────────────

USER_AGENTS = [
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.5 Safari/605.1.15"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
]

_ua_index = 0

def _get_headers() -> dict:
    """Rotate User-Agent across requests."""
    global _ua_index
    ua = USER_AGENTS[_ua_index % len(USER_AGENTS)]
    _ua_index += 1
    return {
        "User-Agent": ua,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


# Relevance keywords — pages matching these are most valuable for business intel
RELEVANCE_KEYWORDS = {
    "about":    10,
    "contact":  10,
    "service":  8,
    "solution": 8,
    "product":  7,
    "team":     6,
    "pricing":  5,
    "case":     5,
    "client":   5,
    "partner":  4,
    "career":   3,
    "industr":  4,
    "platform": 5,
    "feature":  5,
    "compan":   6,
}

# Tags to strip for token optimization
STRIP_TAGS = [
    "script", "style", "noscript", "iframe", "svg", "canvas",
    "video", "audio", "source", "picture", "map",
]

# Common cookie/popup selectors to strip
STRIP_SELECTORS = [
    "[class*='cookie']", "[class*='Cookie']",
    "[id*='cookie']", "[id*='Cookie']",
    "[class*='popup']", "[class*='Popup']",
    "[class*='modal']", "[class*='Modal']",
    "[class*='banner']", "[class*='consent']",
    "[class*='gdpr']", "[class*='GDPR']",
    "[class*='overlay']",
]

# Regex patterns for contact extraction
EMAIL_PATTERN = re.compile(
    r'\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Z|a-z]{2,}\b'
)
PHONE_PATTERN = re.compile(
    r'(?:\+?91[-.\s]?)?(?:0)?(?:[6-9]\d{9})'                            # Indian Mobiles (e.g., +91 9876543210)
    r'|(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)?\d{3}[-.\s]?\d{4}'        # US/North American
    r'|\+\d{1,3}[-.\s]?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}'            # Generic International
)


# ── HTTP Layer ────────────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(settings.MAX_RETRIES),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type((requests.RequestException, requests.Timeout)),
    before_sleep=before_sleep_log(logger, "WARNING"),
    reraise=True,
)
def _fetch(url: str) -> Optional[str]:
    """
    Fetch URL with automatic retry + exponential backoff.
    Returns None on failure instead of raising — scraper must be resilient.
    """
    try:
        response = requests.get(
            url,
            headers=_get_headers(),
            timeout=settings.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.text
    except Exception as exc:
        logger.warning(f"[scraper] Failed to fetch {url}: {exc}")
        raise


def _safe_fetch(url: str) -> Optional[str]:
    """Wrapper that never raises — returns None on any failure."""
    try:
        return _fetch(url)
    except Exception:
        return None


# ── HTML Cleaning ─────────────────────────────────────────────────────────────

def _clean_html(html: str, max_chars: int = None) -> str:
    """
    Token optimization pipeline:
    1. Remove script, style, nav, footer, header, cookie banners
    2. Remove HTML comments
    3. Extract visible text
    4. Collapse whitespace
    5. Truncate to max_chars
    """
    max_chars = max_chars or settings.MAX_TEXT_PER_PAGE

    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        soup = BeautifulSoup(html, "lxml")

    # Remove unwanted tags
    for tag_name in STRIP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove nav, footer, header (common boilerplate)
    for tag_name in ["nav", "header"]:
        for tag in soup.find_all(tag_name):
            tag.decompose()

    # Remove cookie banners and popups by CSS selectors
    for selector in STRIP_SELECTORS:
        try:
            for el in soup.select(selector):
                el.decompose()
        except Exception:
            pass

    # Remove HTML comments
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        comment.extract()

    # Extract text
    text = soup.get_text(separator=" ", strip=True)

    # Collapse whitespace
    text = re.sub(r'\s+', ' ', text).strip()

    # Truncate
    if len(text) > max_chars:
        text = text[:max_chars] + "..."

    return text


# ── Contact Extraction (Regex) ───────────────────────────────────────────────

def _extract_emails(html: str) -> list[str]:
    """Extract email addresses from raw HTML using regex."""
    emails = set(EMAIL_PATTERN.findall(html))
    # Filter out common false positives
    filtered = set()
    for email in emails:
        lower = email.lower()
        # Skip image files, CSS, JS references
        if any(lower.endswith(ext) for ext in ('.png', '.jpg', '.gif', '.svg', '.css', '.js', '.webp')):
            continue
        # Skip common non-email patterns
        if any(kw in lower for kw in ('example.com', 'sentry.io', 'wixpress', 'schema.org', 'w3.org', 'googleapis')):
            continue
        filtered.add(email)
    return sorted(filtered)


def _extract_phones(html: str) -> list[str]:
    """Extract phone numbers from raw HTML using regex."""
    phones = set()
    for match in PHONE_PATTERN.finditer(html):
        phone = match.group().strip()
        # Must have at least 10 digits to be a real phone number
        digits = re.sub(r'\D', '', phone)
        if len(digits) >= 10:
            phones.add(phone)
    return sorted(phones)


# ── Link Discovery ────────────────────────────────────────────────────────────

def _get_base_domain(url: str) -> str:
    """Extract the base domain from a URL."""
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_internal_link(href: str, base_domain: str) -> bool:
    """Check if a link is internal to the website."""
    if not href:
        return False
    if href.startswith(("#", "javascript:", "mailto:", "tel:", "data:")):
        return False
    if href.startswith("/"):
        return True
    return urlparse(href).netloc == urlparse(base_domain).netloc


def _score_link(url: str) -> int:
    """
    Score a URL by relevance to business intelligence.
    Higher score = more likely to contain useful company info.
    """
    lower = url.lower()
    score = 0
    for keyword, weight in RELEVANCE_KEYWORDS.items():
        if keyword in lower:
            score += weight
    # Penalize deep paths (likely blog posts, not core pages)
    path_depth = lower.count("/") - 3  # subtract scheme + domain slashes
    if path_depth > 2:
        score -= path_depth * 2
    # Penalize file downloads
    if any(lower.endswith(ext) for ext in ('.pdf', '.doc', '.zip', '.mp4', '.mp3')):
        score -= 20
    return score


def _discover_links_from_sitemap(base_url: str) -> list[str]:
    """
    Approach 1: Try to find and parse sitemap.xml for relevant URLs.
    """
    sitemap_candidates = [
        f"{base_url}/sitemap.xml",
        f"{base_url}/sitemap_index.xml",
        f"{base_url}/sitemap/sitemap.xml",
    ]

    # Also check robots.txt for sitemap reference
    robots_html = _safe_fetch(f"{base_url}/robots.txt")
    if robots_html:
        for line in robots_html.splitlines():
            if line.lower().startswith("sitemap:"):
                sitemap_url = line.split(":", 1)[1].strip()
                if sitemap_url not in sitemap_candidates:
                    sitemap_candidates.insert(0, sitemap_url)

    for sitemap_url in sitemap_candidates:
        html = _safe_fetch(sitemap_url)
        if not html:
            continue

        try:
            # Strip namespace for easier parsing
            clean_xml = re.sub(r'\sxmlns="[^"]+"', '', html, count=1)
            root = ET.fromstring(clean_xml)

            urls = []
            # Handle both sitemap index and regular sitemap
            for loc in root.iter("loc"):
                if loc.text:
                    urls.append(loc.text.strip())

            if urls:
                logger.info(f"[scraper] Found {len(urls)} URLs in sitemap")
                # Score and filter
                scored = [(url, _score_link(url)) for url in urls]
                scored.sort(key=lambda x: x[1], reverse=True)
                # Return top N relevant links
                relevant = [url for url, score in scored if score > 0]
                return relevant[:settings.MAX_LINKS_PER_SITE]
        except ET.ParseError:
            continue

    return []


def _discover_links_from_homepage(html: str, base_url: str) -> list[str]:
    """
    Approach 2: Extract and score internal links from homepage HTML.
    Uses keyword relevance scoring + fuzzy matching.
    """
    try:
        soup = BeautifulSoup(html, "html.parser")
    except Exception:
        soup = BeautifulSoup(html, "lxml")

    base_domain = _get_base_domain(base_url)
    seen = set()
    scored_links = []

    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"].strip()

        # Resolve relative URLs
        full_url = urljoin(base_url + "/", href)

        # Only internal links
        if not _is_internal_link(href, base_domain):
            continue

        # Deduplicate
        normalized = full_url.rstrip("/").split("?")[0].split("#")[0]
        if normalized in seen or normalized == base_url.rstrip("/"):
            continue
        seen.add(normalized)

        # Score by URL path keywords + anchor text
        score = _score_link(normalized)

        # Also score anchor text
        anchor_text = a_tag.get_text(strip=True).lower()
        for keyword, weight in RELEVANCE_KEYWORDS.items():
            if keyword in anchor_text:
                score += weight

        if score > 0:
            scored_links.append((normalized, score))

    # Sort by score descending
    scored_links.sort(key=lambda x: x[1], reverse=True)

    result = [url for url, score in scored_links[:settings.MAX_LINKS_PER_SITE]]
    logger.info(f"[scraper] Discovered {len(result)} relevant links from homepage")
    return result


# ── Main Scraper ──────────────────────────────────────────────────────────────

def scrape_company(url: str) -> dict:
    """
    Smart multi-approach company website scraper.

    Returns a dict with:
    {
        "url": "https://example.com",
        "pages": {
            "homepage": "cleaned text...",
            "about": "cleaned text...",
            ...
        },
        "raw_emails": ["found@email.com"],
        "raw_phones": ["+1-555-0123"],
        "success": True/False,
        "error": None or "error message"
    }
    """
    # Normalize URL
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    url = url.rstrip("/")

    base_url = _get_base_domain(url)
    result = {
        "url": url,
        "pages": {},
        "raw_emails": [],
        "raw_phones": [],
        "success": False,
        "error": None,
    }

    # ── Step 1: Fetch homepage ────────────────────────────────────────────────
    logger.info(f"[scraper] Starting scrape for: {url}")
    homepage_html = _safe_fetch(url)

    if not homepage_html:
        # Try with www prefix if bare domain
        parsed = urlparse(url)
        if not parsed.netloc.startswith("www."):
            alt_url = f"{parsed.scheme}://www.{parsed.netloc}{parsed.path}"
            logger.info(f"[scraper] Trying alternate URL: {alt_url}")
            homepage_html = _safe_fetch(alt_url)
            if homepage_html:
                url = alt_url
                base_url = _get_base_domain(url)

    if not homepage_html:
        result["error"] = f"Could not fetch {url}"
        logger.error(f"[scraper] Could not fetch homepage: {url}")
        return result

    # Extract contacts from raw HTML (before cleaning!)
    result["raw_emails"] = _extract_emails(homepage_html)
    result["raw_phones"] = _extract_phones(homepage_html)

    # Clean and store homepage text
    result["pages"]["homepage"] = _clean_html(homepage_html)

    # ── Step 2: Discover relevant pages ───────────────────────────────────────
    relevant_links = []

    # Approach 1: Sitemap
    logger.info(f"[scraper] Trying sitemap discovery for {base_url}")
    relevant_links = _discover_links_from_sitemap(base_url)

    # Approach 2: Homepage link crawling (if sitemap found < 2 links)
    if len(relevant_links) < 2:
        logger.info(f"[scraper] Trying homepage link discovery")
        homepage_links = _discover_links_from_homepage(homepage_html, url)
        # Merge, avoiding duplicates
        seen = set(relevant_links)
        for link in homepage_links:
            if link not in seen:
                relevant_links.append(link)
                seen.add(link)

    # Limit total pages
    relevant_links = relevant_links[:settings.MAX_PAGES_TO_SCRAPE - 1]  # -1 for homepage
    logger.info(f"[scraper] Will scrape {len(relevant_links)} additional pages")

    # ── Step 3: Scrape relevant pages ─────────────────────────────────────────
    for link_url in relevant_links:
        time.sleep(settings.REQUEST_DELAY)

        page_html = _safe_fetch(link_url)
        if not page_html:
            continue

        # Extract contacts from this page too
        page_emails = _extract_emails(page_html)
        page_phones = _extract_phones(page_html)
        result["raw_emails"] = list(set(result["raw_emails"] + page_emails))
        result["raw_phones"] = list(set(result["raw_phones"] + page_phones))

        # Derive page name from URL path
        path = urlparse(link_url).path.strip("/")
        page_name = path.split("/")[-1] if path else "page"
        page_name = re.sub(r'[^a-zA-Z0-9]', '_', page_name)[:30]

        result["pages"][page_name] = _clean_html(page_html)

    result["success"] = True
    total_chars = sum(len(t) for t in result["pages"].values())
    logger.success(
        f"[scraper] Done — {len(result['pages'])} pages, "
        f"{total_chars} chars, "
        f"{len(result['raw_emails'])} emails, "
        f"{len(result['raw_phones'])} phones"
    )

    return result
