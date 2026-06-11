# 🔍 Ecom_intel Debug Analysis

## Current System Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│ User Request (Web UI)                                           │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ POST /enrich endpoint (server.py)                               │
│  • Receives URL + website_name                                  │
│  • Calls: enrich_single(url, website_name)                      │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ pipeline.enrich_single() [3-stage pipeline]                     │
│                                                                 │
│  Stage 1: SCRAPING (scraper/scraper.py)                         │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ • Fetches homepage HTML                                │     │
│  │ • Extracts emails/phones via REGEX (raw HTML)          │     │
│  │ • Discovers relevant pages (sitemap OR homepage links) │     │
│  │ • Scrapes up to MAX_PAGES_TO_SCRAPE pages              │     │
│  │ • Returns: {                                           │     │
│  │     "url": "...",                                      │     │
│  │     "pages": {"homepage": "text", "about": "text"...}, │     │
│  │     "raw_emails": ["found@email.com"],                 │     │
│  │     "raw_phones": ["+1-555-0123"],                     │     │
│  │     "success": True/False,                             │     │
│  │     "error": None or "message"                         │     │
│  │   }                                                    │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
│  Stage 2: AI ENRICHMENT (ai/enricher.py)                        │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ • Takes scraped data + Groq AI                         │     │
│  │ • Extracts:                                            │     │
│  │   - website_name, company_name                         │     │
│  │   - address, mobile_number                             │     │
│  │   - mail (list of emails)                              │     │
│  │   - core_service                                       │     │
│  │   - target_customer                                    │     │
│  │   - probable_pain_point                                │     │
│  │   - outreach_opener                                    │     │
│  │ • Fallback if AI fails: returns "N/A" for all fields   │     │
│  │ • Merges regex-extracted contacts                      │     │
│  └────────────────────────────────────────────────────────┘     │
│                                                                 │
│  Stage 3: PERSISTENCE (data/database.py)                        │
│  ┌────────────────────────────────────────────────────────┐     │
│  │ • Validates data as CompanyProfile (Pydantic)          │     │
│  │ • Converts mail list → JSON string (SQLite)            │     │
│  │ • Upserts to SQLite database                           │     │
│  │ • Returns full_dict with metadata                      │     │
│  └────────────────────────────────────────────────────────┘     │
└────────────────────┬────────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────────┐
│ JSON Response to Frontend                                        │
│  {                                                              │
│    "website_name": "...",                                        │
│    "company_name": "...",                                        │
│    "address": "...",            ← Shows "—" if N/A              │
│    "mobile_number": "...",      ← Shows "—" if N/A              │
│    "mail": [...],               ← Shows "—" if empty            │
│    "core_service": "...",                                        │
│    "target_customer": "...",    ← Shows "—" if N/A              │
│    "probable_pain_point": "...", ← Shows "—" if N/A            │
│    "outreach_opener": "...",                                     │
│    "website_url": "...",                                         │
│    "enriched_at": "..."                                          │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔴 Issues & Root Causes

### Issue 1: Fields showing "N/A" (Address, Phone, Email, Target Customer, Pain Point)

**Root Cause**: The AI (`ai/enricher.py`) is returning `"N/A"` for these fields because either:

1. **Scraper found NO website content** → falls back to `_fallback_profile()` 
2. **Scraper found content but AI extraction failed** → Groq returns `"N/A"` intentionally
3. **AI was never called** → Exception caught and fallback used

**Why the frontend shows "—"**:
- The JS function `displayValue()` checks if value equals `"N/A"` → returns `<span class="na">—</span>`
- This is correct behavior for missing data!

---

### Issue 2: loadAllResults endpoint returns empty array

**Root Cause** (FIXED): 
- `server.py` had duplicate `load_all_companies()` reading from a JSON file that never gets written
- Now correctly uses `data/database.py::load_all_companies()` which queries SQLite

**Now Working**:
- ✅ POST `/enrich` saves companies to SQLite database
- ✅ GET `/results` queries SQLite and returns all enriched companies

---

## 🟡 What's Actually Happening

### When you submit a company URL:

```python
# 1. SCRAPER runs
scraped = {
    "url": "https://example.com",
    "pages": {
        "homepage": "...",  # Cleaned HTML text
        "about": "...",     # If found
        # etc (max 5 pages)
    },
    "raw_emails": ["contact@example.com"],  # REGEX extracted
    "raw_phones": ["+1-555-0000"],          # REGEX extracted
    "success": True,
    "error": None
}

# 2. AI ENRICHER runs
enriched = {
    "website_name": "Example",
    "company_name": "Example Inc",
    "address": "N/A",  # ← Not found in content
    "mobile_number": "+1-555-0000",  # From raw_phones merge
    "mail": ["contact@example.com"],  # From raw_emails merge
    "core_service": "Software solutions",
    "target_customer": "N/A",  # ← AI couldn't infer
    "probable_pain_point": "N/A",  # ← AI couldn't infer
    "outreach_opener": "Hi, I found your website..."
}

# 3. PERSISTED to SQLite
# 4. RETURNED to frontend
```

---

## 🟢 Why You're Getting 200 Status

✅ **CORRECT BEHAVIOR**:
- API always returns 200 (schema never breaks)
- Error details are in the `error` field OR server logs
- Frontend shows "—" for missing fields (intentional design)

---

## 🔧 Diagnostic Steps

### 1. **Check Server Logs** (Most Important!)
```bash
# The server now logs EVERYTHING with enhanced logging:
# - Stage 1 (Scraper): "Stage 1: Scraping"
# - Stage 2 (AI): "Stage 2: AI Enrichment"
# - Stage 3 (DB): "Stage 3: Persisting"
# 
# Check for errors like:
# [scraper] Could not fetch {url}  ← No website content
# [ai] Enrichment failed for {url}  ← AI extraction error
# [db] Error loading results        ← Database issue
```

### 2. **Test Each Component Separately**

**Test Scraper Only**:
```python
from scraper import scrape_company
result = scrape_company("https://example.com")
print(f"Pages scraped: {len(result['pages'])}")
print(f"Content length: {sum(len(t) for t in result['pages'].values())} chars")
print(f"Emails found: {result['raw_emails']}")
print(f"Phones found: {result['raw_phones']}")
```

**Test AI Enrichment**:
```python
from ai import enrich_company
enriched = enrich_company(scraped_result, "Example Corp")
print(enriched)
```

### 3. **Check Database**
```python
from data import load_all_companies
companies = load_all_companies()
print(f"Total companies: {len(companies)}")
for company in companies:
    print(f"  - {company['website_name']}: {company['company_name']}")
```

---

## 📊 Why Certain Fields are "N/A"

### Address
- **Requires**: Physical street address in website text
- **Common Issue**: Many companies don't list full address on site
- **Solution**: Only AI extraction works (no regex for addresses)

### Phone
- **If "N/A"**: Regex didn't find, AND AI didn't extract
- **Should Work**: Regex extracts from raw HTML first
- **Check**: Look at `raw_phones` in logs

### Email
- **If empty**: Regex didn't find, AND AI didn't provide
- **Should Work**: Regex always finds email@domain patterns
- **Check**: Look at `raw_emails` in logs

### Target Customer
- **Requires**: Explicit mention in content (About, Case Studies, etc.)
- **AI Must Infer From**: Testimonials, case studies, or service descriptions
- **Common**: Many sites don't explicitly state target customers

### Pain Point
- **Requires**: Site mentions problems they solve
- **AI Must Infer From**: Service descriptions, hero copy, value propositions
- **Common**: Generic marketing sites might not clearly state pain points

---

## ✅ Verification Checklist

- [ ] **Server logs show successful scraping** (check Stage 1)
- [ ] **Pages were extracted** (check page count in logs)
- [ ] **Emails/phones found in raw_* fields** (check logs)
- [ ] **AI processed the content** (check Stage 2)
- [ ] **Company saved to SQLite** (check Stage 3)
- [ ] **GET /results returns non-empty array** (query database)

---

## 🚀 Next Steps

### If fields are still "N/A" after fix:

1. **Check scraper output**
   - Is website content being extracted?
   - Are multiple pages found or just homepage?
   - What's the total character count?

2. **Check AI performance**
   - Is Groq API key valid?
   - Is model returning valid JSON?
   - Check token usage in logs

3. **Improve extraction**
   - Enhance scraper to get more relevant pages
   - Add specialized scrapers for contact/about pages
   - Train AI with better prompts for specific fields

---

## 📝 Recent Fix Applied

**File**: `server.py`
**Changes**:
- ✅ Removed conflicting JSON-based `init_db()` and `load_all_companies()`
- ✅ Now uses correct SQLite functions from `data/__init__.py`
- ✅ Added enhanced logging with `exc_info=True`
- ✅ Removed conflicting file path logic

**Result**: 
- ✅ POST `/enrich` now saves to SQLite
- ✅ GET `/results` now reads from SQLite
- ✅ Logs show actual errors instead of silent failures
