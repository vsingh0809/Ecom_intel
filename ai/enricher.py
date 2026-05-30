"""
ai/enricher.py
--------------
Groq-powered company intelligence enrichment.

Key production practices:
  • Anti-hallucination: scraped emails/phones passed as ground truth — AI told to
    use ONLY those, never fabricate. If not found, return "N/A".
  • Structured JSON output: response_format=json_object forces valid JSON
  • Retry with exponential backoff (tenacity)
  • Fallback enrichment when AI fails — never crashes the pipeline
  • Token optimization: cleaned text only, max ~20K chars total
  • Single Groq client reused across all calls
  • Temperature 0.1 for deterministic, factual output
"""

import json
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


# ── Prompt Engineering ────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a business intelligence analyst. Your job is to extract structured company information from website content.

CRITICAL RULES — READ CAREFULLY:
1. ONLY extract information that is EXPLICITLY STATED or STRONGLY IMPLIED in the provided website text.
2. If a piece of information is NOT found in the text, you MUST return "N/A" for that field. NEVER FABRICATE OR GUESS.
3. For emails and phone numbers: I will provide you with emails and phones that were found on the website via regex extraction. Use ONLY those. Do NOT invent any contact details.
4. The "core_service" should be a concise summary of what the company actually does, based on the content.
5. The "target_customer" should be inferred from case studies, testimonials, or service descriptions on the site.
6. The "probable_pain_point" should be inferred from the problems the company claims to solve for its customers.
7. The "outreach_opener" must reference SPECIFIC details from the website content — never use generic templates.

You must respond with ONLY a valid JSON object. No explanation. No markdown. No code fences. Raw JSON only."""

USER_PROMPT_TEMPLATE = """Analyze this company website and extract a business profile.

COMPANY URL: {url}
WEBSITE NAME (provided by user): {website_name}

CONTACT INFORMATION FOUND ON WEBSITE (use these EXACTLY, do not modify or invent):
- Emails found: {emails}
- Phone numbers found: {phones}

WEBSITE CONTENT (from {page_count} pages):
{content}

Return a JSON object with exactly these fields:
{{
  "website_name": "The website/brand name as it appears on the site (use the provided name if you can't find one)",
  "company_name": "The full legal/official company name if found, otherwise use website name",
  "address": "Full physical address if found on the site, otherwise N/A",
  "mobile_number": "Primary phone number from the FOUND list above, otherwise N/A",
  "mail": ["array", "of", "emails", "from the FOUND list above"],
  "core_service": "What the company does - be specific, based on actual website content",
  "target_customer": "Who their customers are - infer from site content, case studies, testimonials",
  "probable_pain_point": "What problems their customers likely face that this company solves",
  "outreach_opener": "A personalized, specific outreach message referencing details from THIS company's website"
}}"""


# ── Groq Client ──────────────────────────────────────────────────────────────

_client: Optional[Groq] = None


def _get_client() -> Groq:
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


# ── API Call with Retry ───────────────────────────────────────────────────────

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=4, max=30),
    retry=retry_if_exception_type(Exception),
    before_sleep=lambda s: logger.warning(
        f"[ai] Retrying (attempt {s.attempt_number}) — "
        f"{type(s.outcome.exception()).__name__}: {str(s.outcome.exception())[:120]}"
    ),
    reraise=True,
)
def _call_groq(system_prompt: str, user_prompt: str) -> dict:
    """
    Send prompt to Groq → receive structured JSON.
    Uses json_object response format for guaranteed valid JSON.
    """
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=settings.AI_TEMPERATURE,
        max_tokens=settings.AI_MAX_TOKENS,
        response_format={"type": "json_object"},
    )
    raw = response.choices[0].message.content.strip()

    # Strip markdown fences just in case
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()

    parsed = json.loads(raw)

    # Log token usage for optimization tracking
    usage = response.usage
    if usage:
        logger.info(
            f"[ai] Tokens — prompt: {usage.prompt_tokens}, "
            f"completion: {usage.completion_tokens}, "
            f"total: {usage.total_tokens}"
        )

    return parsed


# ── Batch Processing ──────────────────────────────────────────────────────────

BATCH_SYSTEM_PROMPT = """You are a business intelligence analyst. Extract structured company information from website content for MULTIPLE companies.

CRITICAL RULES:
1. ONLY use information EXPLICITLY STATED in the provided text. If not found, return "N/A".
2. For contact details: use ONLY the emails/phones provided. NEVER fabricate.
3. Respond with ONLY a valid JSON object containing a "companies" key with an array of profiles.
4. Each profile must have exactly these fields: website_name, company_name, address, mobile_number, mail, core_service, target_customer, probable_pain_point, outreach_opener.
5. Return the profiles in the SAME ORDER as the input companies."""

BATCH_USER_TEMPLATE = """Analyze these {count} company websites and extract business profiles for each.

{companies_block}

Return a JSON object with exactly this structure:
{{
  "companies": [
    {{
      "website_name": "...",
      "company_name": "...",
      "address": "... or N/A",
      "mobile_number": "... or N/A",
      "mail": ["array of emails found"],
      "core_service": "...",
      "target_customer": "...",
      "probable_pain_point": "...",
      "outreach_opener": "..."
    }}
  ]
}}

Return exactly {count} company profiles in the companies array, in the same order as input."""


def _build_company_block(scraped: dict, website_name: str, index: int) -> str:
    """Build a text block for one company's scraped data."""
    url = scraped.get("url", "unknown")
    emails = scraped.get("raw_emails", [])
    phones = scraped.get("raw_phones", [])
    pages = scraped.get("pages", {})

    # Combine all page content with labels
    content_parts = []
    for page_name, text in pages.items():
        if text.strip():
            content_parts.append(f"[{page_name.upper()}]:\n{text}")

    content = "\n\n".join(content_parts) if content_parts else "No content could be extracted."

    # Truncate total content to avoid hitting context limits
    if len(content) > 6000:
        content = content[:6000] + "\n... (content truncated for token efficiency)"

    return f"""--- COMPANY {index} ---
URL: {url}
WEBSITE NAME (user-provided): {website_name}
EMAILS FOUND ON SITE: {json.dumps(emails) if emails else 'None found'}
PHONES FOUND ON SITE: {json.dumps(phones) if phones else 'None found'}

WEBSITE CONTENT ({len(pages)} pages scraped):
{content}
--- END COMPANY {index} ---"""


# ── Public API ────────────────────────────────────────────────────────────────

def enrich_company(scraped_data: dict, website_name: str = "N/A") -> dict:
    """
    Enrich a single company using Groq AI.

    Args:
        scraped_data: Output from scraper.scrape_company()
        website_name: User-provided website name for record-keeping

    Returns:
        Dict matching the hackathon JSON schema. Never raises — falls back
        to a safe dict with "N/A" values on any failure.
    """
    url = scraped_data.get("url", "unknown")

    if not scraped_data.get("success") or not scraped_data.get("pages"):
        logger.warning(f"[ai] No scraped content for {url} — returning defaults")
        return _fallback_profile(url, website_name, scraped_data)

    # Build prompt
    pages = scraped_data["pages"]
    emails = scraped_data.get("raw_emails", [])
    phones = scraped_data.get("raw_phones", [])

    content_parts = []
    for page_name, text in pages.items():
        if text.strip():
            content_parts.append(f"[{page_name.upper()}]:\n{text}")
    content = "\n\n".join(content_parts)

    # Token optimization: limit total content
    if len(content) > 8000:
        content = content[:8000] + "\n... (content truncated for token efficiency)"

    user_prompt = USER_PROMPT_TEMPLATE.format(
        url=url,
        website_name=website_name,
        emails=json.dumps(emails) if emails else "None found on the website",
        phones=json.dumps(phones) if phones else "None found on the website",
        page_count=len(pages),
        content=content,
    )

    try:
        result = _call_groq(SYSTEM_PROMPT, user_prompt)
        # Ensure all required fields exist with safe defaults
        return _validate_result(result, url, website_name, scraped_data)
    except Exception as exc:
        logger.error(f"[ai] Enrichment failed for {url}: {exc}")
        return _fallback_profile(url, website_name, scraped_data)


def enrich_companies_batch(
    scraped_list: list[dict],
    website_names: list[str],
) -> list[dict]:
    """
    Batch-enrich multiple companies in a single Groq call.
    Falls back to individual calls if batch fails.

    This is more token-efficient for the Colab notebook where we process
    multiple URLs at once. For the web API, use enrich_company() individually.

    Args:
        scraped_list: List of scraper outputs
        website_names: Corresponding website names

    Returns:
        List of dicts matching hackathon schema, in same order as input.
    """
    if len(scraped_list) == 1:
        return [enrich_company(scraped_list[0], website_names[0])]

    # For larger batches (>3), process in sub-batches to stay within context limits
    if len(scraped_list) > 3:
        results = []
        for i in range(0, len(scraped_list), 3):
            batch = scraped_list[i:i+3]
            names = website_names[i:i+3]
            results.extend(enrich_companies_batch(batch, names))
        return results

    # Build batch prompt
    companies_block = "\n\n".join(
        _build_company_block(sd, wn, i+1)
        for i, (sd, wn) in enumerate(zip(scraped_list, website_names))
    )

    user_prompt = BATCH_USER_TEMPLATE.format(
        count=len(scraped_list),
        companies_block=companies_block,
    )

    try:
        result = _call_groq(BATCH_SYSTEM_PROMPT, user_prompt)

        # Extract companies array
        companies = None
        if isinstance(result, dict):
            companies = result.get("companies") or result.get("results")
            if not companies:
                # Try to find any list value
                for v in result.values():
                    if isinstance(v, list):
                        companies = v
                        break

        if companies and len(companies) == len(scraped_list):
            return [
                _validate_result(c, sd["url"], wn, sd)
                for c, sd, wn in zip(companies, scraped_list, website_names)
            ]

        # Wrong count — fall back to individual calls
        logger.warning(
            f"[ai] Batch returned {len(companies) if companies else 0}/"
            f"{len(scraped_list)} — falling back to individual calls"
        )
    except Exception as exc:
        logger.error(f"[ai] Batch enrichment failed: {exc}")

    # Fallback: individual calls
    return [
        enrich_company(sd, wn)
        for sd, wn in zip(scraped_list, website_names)
    ]


# ── Validation & Fallback ────────────────────────────────────────────────────

def _validate_result(
    ai_result: dict,
    url: str,
    website_name: str,
    scraped_data: dict,
) -> dict:
    """
    Ensure AI output has all required fields with safe defaults.
    Merges regex-extracted contacts if AI missed them.
    """
    emails = scraped_data.get("raw_emails", [])
    phones = scraped_data.get("raw_phones", [])

    # Get AI's values with safe defaults
    result = {
        "website_name":        str(ai_result.get("website_name", website_name) or website_name),
        "company_name":        str(ai_result.get("company_name", "N/A") or "N/A"),
        "address":             str(ai_result.get("address", "N/A") or "N/A"),
        "mobile_number":       str(ai_result.get("mobile_number", "N/A") or "N/A"),
        "mail":                ai_result.get("mail", []),
        "core_service":        str(ai_result.get("core_service", "N/A") or "N/A"),
        "target_customer":     str(ai_result.get("target_customer", "N/A") or "N/A"),
        "probable_pain_point": str(ai_result.get("probable_pain_point", "N/A") or "N/A"),
        "outreach_opener":     str(ai_result.get("outreach_opener", "N/A") or "N/A"),
    }

    # Ensure mail is a list
    if isinstance(result["mail"], str):
        if result["mail"].strip().lower() in ("n/a", "", "null", "none"):
            result["mail"] = []
        else:
            result["mail"] = [e.strip() for e in result["mail"].split(",") if e.strip()]

    # Merge regex-extracted emails if AI missed any
    if emails:
        existing_lower = {e.lower() for e in result["mail"]}
        for email in emails:
            if email.lower() not in existing_lower:
                result["mail"].append(email)
                existing_lower.add(email.lower())

    # Use regex-extracted phone if AI returned N/A
    if result["mobile_number"] in ("N/A", "", "null", "None") and phones:
        result["mobile_number"] = phones[0]

    return result


def _fallback_profile(url: str, website_name: str, scraped_data: dict) -> dict:
    """
    Rule-based fallback when AI is unavailable or fails.
    Uses regex-extracted contacts and basic text analysis.
    """
    emails = scraped_data.get("raw_emails", [])
    phones = scraped_data.get("raw_phones", [])
    pages = scraped_data.get("pages", {})

    # Try to extract some info from homepage text
    homepage_text = pages.get("homepage", "")
    core_service = "N/A"
    if homepage_text:
        # Use first meaningful sentence as a rough service description
        sentences = [s.strip() for s in homepage_text.split(". ") if len(s.strip()) > 20]
        if sentences:
            core_service = sentences[0][:200]

    return {
        "website_name":        website_name,
        "company_name":        website_name,
        "address":             "N/A",
        "mobile_number":       phones[0] if phones else "N/A",
        "mail":                emails,
        "core_service":        core_service,
        "target_customer":     "N/A",
        "probable_pain_point": "N/A",
        "outreach_opener":     f"Hi team at {website_name}, I came across your website and would love to connect about potential collaboration opportunities.",
    }