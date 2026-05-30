"""
ai/enricher.py
--------------
Gemini-powered batch enrichment for book records.

Why batch (5 books per call)?
  Gemini free tier = 15 RPM.
  100 books × 1 call each = 100 calls → needs 6+ minutes.
  100 books ÷ 5 per batch = 20 calls  → needs ~90 seconds. ✓

Key production practices:
  • Single Gemini client reused across all calls (no re-init overhead)
  • Strict JSON prompt with explicit schema — no markdown fences allowed
  • Per-call retry with exponential backoff (tenacity)
  • Fallback enrichment when Gemini fails — never crashes the pipeline
  • Pydantic validation on AI output — catches hallucinated field values
  • Gemini RPM-aware delay between batches
"""

import json
import time
from datetime import datetime
from typing import Optional

from groq import Groq
from loguru import logger
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from config import settings
from data.models import RawBook, EnrichedBook


# ── Prompt ────────────────────────────────────────────────────────────────────

GENRES = [
    "Fiction", "Mystery & Thriller", "Romance", "Science Fiction",
    "Fantasy", "Biography", "Self-Help", "History", "Children's",
    "Business", "Travel", "Food & Cooking", "Health", "Science",
    "Philosophy", "Sports", "Other",
]

# One-shot prompt: send N books → get back a JSON array of N objects
BATCH_PROMPT_TEMPLATE = """You are a book metadata enrichment engine for an e-commerce platform.
Given a list of books (title, price in GBP, star rating), return ONLY a valid JSON array.
No preamble. No explanation. No markdown code fences. Raw JSON only.

Each element must match this schema exactly:
{{
  "genre":       "<one of: {genres}>",
  "summary":     "<2-sentence editorial description of what this book is likely about>",
  "sentiment":   "<one of: Positive, Neutral, Negative — based on overall title tone>",
  "value_score": <float 0.0–10.0, where 10 = best value (high rating + low price)>
}}

Books to enrich:
{book_list}

Return a JSON array with exactly {count} elements, in the same order as the input list."""


def _build_prompt(batch: list[RawBook]) -> str:
    book_lines = "\n".join(
        f'{i+1}. "{b.title}" | £{b.price:.2f} | {b.rating}/5 stars | {b.availability}'
        for i, b in enumerate(batch)
    )
    return BATCH_PROMPT_TEMPLATE.format(
        genres=", ".join(GENRES),
        book_list=book_lines,
        count=len(batch),
    )


# ── Gemini client ─────────────────────────────────────────────────────────────

_client: Optional[Groq] = None


def _get_model() -> Groq:
    """Lazy-init: create Groq client once and reuse."""
    global _client
    if _client is None:
        if not settings.GROQ_API_KEY:
            raise EnvironmentError(
                "GROQ_API_KEY is not set. Add it to your .env file."
            )
        _client = Groq(api_key=settings.GROQ_API_KEY)
        logger.info(f"[ai] Groq client ready (model={settings.GROQ_MODEL})")
    return _client


# ── API call with retry ────────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=lambda s: logger.warning(
        f"[ai] Retrying _call_groq (attempt {s.attempt_number}) — "
        f"{type(s.outcome.exception()).__name__}: {str(s.outcome.exception())[:120]}"
    ),
    reraise=False,
)
def _call_gemini(prompt: str) -> Optional[list[dict]]:
    """Send prompt → receive JSON array via Groq."""
    client   = _get_model()
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=8192,
        response_format={"type": "json_object"},  # forces JSON output
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown fences just in case
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    # Groq returns a JSON object, not array — unwrap if needed
    parsed = json.loads(raw)
    if isinstance(parsed, dict):
        # Model may wrap array under a key like {"books": [...]}
        for v in parsed.values():
            if isinstance(v, list):
                return v
        raise ValueError(f"JSON object has no list value: {list(parsed.keys())}")

    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON array, got {type(parsed).__name__}")
    return parsed


# ── Fallback ───────────────────────────────────────────────────────────────────

def _rule_based_enrichment(book: RawBook) -> dict:
    """
    Deterministic fallback when AI is unavailable.
    Value score = 60% rating weight + 40% cheapness weight, scaled to 0–10.
    """
    cheapness    = max(0.0, 1.0 - book.price / 60.0)
    value_score  = round((book.rating / 5.0) * 6.0 + cheapness * 4.0, 2)
    return {
        "genre":       "Other",
        "summary":     (
            f'"{book.title}" is priced at £{book.price:.2f} '
            f"and holds a {book.rating}/5 star rating."
        ),
        "sentiment":   "Neutral",
        "value_score": value_score,
    }


# ── Batch enrichment ───────────────────────────────────────────────────────────

def _enrich_batch(batch: list[RawBook]) -> list[dict]:
    """
    Enrich one batch via Gemini.
    If batch call returns wrong count (due to truncation repair),
    falls back to one-book-at-a-time calls before using rule-based.
    Always returns exactly len(batch) dicts.
    """
    prompt = _build_prompt(batch)
    result = _call_gemini(prompt)

    # Happy path — got exactly what we asked for
    if result and len(result) == len(batch):
        return result

    # Partial result from truncation repair — fill gaps with individual calls
    if result and 0 < len(result) < len(batch):
        logger.warning(
            f"[ai] Batch returned {len(result)}/{len(batch)} items — "
            "filling missing books with individual calls"
        )
        for i in range(len(result), len(batch)):
            single = _call_gemini(_build_prompt([batch[i]]))
            result.append(single[0] if single else _rule_based_enrichment(batch[i]))
        return result

    # Total failure — fall back to rule-based for entire batch
    logger.warning(f"[ai] Batch call failed entirely — using rule-based fallback")
    return [_rule_based_enrichment(b) for b in batch]


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_books(raw_books: list[RawBook]) -> list[EnrichedBook]:
    """
    Enrich all books in batches of AI_BATCH_SIZE.
    Never raises — any failure for a batch falls back to rule-based enrichment.
    Returns a list of EnrichedBook objects in the same order as input.
    """
    if not raw_books:
        return []

    batch_size  = settings.AI_BATCH_SIZE
    enriched:  list[EnrichedBook] = []
    total       = len(raw_books)
    n_batches   = (total + batch_size - 1) // batch_size

    logger.info(
        f"[ai] Enriching {total} books in {n_batches} batches of {batch_size}"
    )

    for batch_idx in range(n_batches):
        start = batch_idx * batch_size
        end   = min(start + batch_size, total)
        batch = raw_books[start:end]

        logger.info(
            f"[ai] Batch {batch_idx + 1}/{n_batches} "
            f"(books {start + 1}–{end})"
        )

        ai_results = _enrich_batch(batch)

        for book, ai_data in zip(batch, ai_results):
            try:
                enriched.append(
                    EnrichedBook(
                        **book.model_dump(),
                        genre=str(ai_data.get("genre",      "Other")),
                        summary=str(ai_data.get("summary",    "")),
                        sentiment=str(ai_data.get("sentiment",  "Neutral")),
                        value_score=float(ai_data.get("value_score", 0.0)),
                        enriched_at=datetime.utcnow(),
                    )
                )
            except Exception as exc:
                logger.warning(
                    f"[ai] Validation failed for '{book.title}': {exc} — "
                    "using fallback"
                )
                fb = _rule_based_enrichment(book)
                enriched.append(
                    EnrichedBook(
                        **book.model_dump(),
                        **fb,
                        enriched_at=datetime.utcnow(),
                    )
                )

        # Respect Gemini free-tier rate limit (skip delay after last batch)
        if batch_idx < n_batches - 1:
            logger.debug(f"[ai] Sleeping {settings.AI_BATCH_DELAY}s (rate limit)")
            time.sleep(settings.AI_BATCH_DELAY)

    logger.success(f"[ai] Enrichment complete — {len(enriched)}/{total} books enriched")
    return enriched