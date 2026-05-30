# 📚 E-Commerce Intelligence Dashboard

> Scrape → AI Enrich → Store → Visualise → Deploy

An end-to-end production pipeline that scrapes book data from
[books.toscrape.com](https://books.toscrape.com), enriches each book with
Gemini AI (genre, summary, sentiment, value score), stores results in SQLite,
and surfaces insights in a live Streamlit dashboard.

---

## Architecture

```
pipeline.py
    │
    ├── scraper/scraper.py      HTTP fetch + BeautifulSoup parse
    │       └── tenacity retry, respectful delay, Pydantic RawBook
    │
    ├── ai/enricher.py          Gemini batch enrichment (5 books/call)
    │       └── fallback rule-based enrichment on failure
    │
    └── data/
            ├── models.py       Pydantic contracts: RawBook, EnrichedBook
            └── database.py     SQLAlchemy ORM — upsert, load, stats

dashboard/app.py                Streamlit UI — charts, filters, pipeline runner
```

---

## Quick Start

### 1. Clone & create virtual environment

```bash
git clone <your-repo>
cd ecom_intel
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
```

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure environment

```bash
cp .env.example .env
# Open .env and add your GEMINI_API_KEY
# Get one free at: https://aistudio.google.com
```

### 4. Run the pipeline

```bash
# Scrape 5 pages (~100 books) + AI enrichment
python pipeline.py

# Scrape more pages
python pipeline.py --pages 10

# Fast test (scraper only, no AI)
python pipeline.py --skip-ai
```

### 5. Launch the dashboard

```bash
streamlit run dashboard/app.py
```

Open http://localhost:8501 — click **🚀 Run Pipeline** in the sidebar to
trigger the pipeline directly from the UI.

---

## Project Structure

```
ecom_intel/
├── config/
│   ├── __init__.py
│   └── settings.py         # Single source of truth for all config
├── scraper/
│   ├── __init__.py
│   └── scraper.py          # Requests + BS4 with tenacity retry
├── ai/
│   ├── __init__.py
│   └── enricher.py         # Gemini batch enrichment
├── data/
│   ├── __init__.py
│   ├── models.py           # Pydantic data contracts
│   └── database.py         # SQLAlchemy ORM layer
├── dashboard/
│   └── app.py              # Streamlit dashboard
├── logs/
│   └── .gitkeep
├── pipeline.py             # Main orchestrator
├── requirements.txt        # Pinned dependencies
├── .env.example            # Config template
├── .gitignore
├── Procfile                # Railway deployment
└── runtime.txt             # Python 3.11.9
```

---

## Configuration

| Variable | Default | Description |
|---|---|---|
| `GEMINI_API_KEY` | **required** | Free at aistudio.google.com |
| `MAX_PAGES` | `5` | Pages to scrape (20 books each) |
| `REQUEST_DELAY` | `1.5` | Seconds between page fetches |
| `AI_BATCH_SIZE` | `5` | Books per Gemini call |
| `AI_BATCH_DELAY` | `4.5` | Seconds between Gemini batches |
| `LOG_LEVEL` | `INFO` | `DEBUG` for verbose output |

---

## Deployment (Railway)

```bash
# Install CLI
npm install -g @railway/cli

# Login and initialise
railway login
railway init

# Deploy
railway up

# Set environment variables on Railway dashboard
# (copy contents of your .env)
```

The `Procfile` is pre-configured:
```
web: streamlit run dashboard/app.py --server.port $PORT --server.address 0.0.0.0
```

---

## Production Practices Used

| Practice | Implementation |
|---|---|
| Typed data contracts | Pydantic `RawBook` / `EnrichedBook` models |
| Retry with backoff | `tenacity` on HTTP fetches and Gemini calls |
| Fail-fast config | `settings.validate()` before any work starts |
| Safe upserts | URL as primary key — re-runs never duplicate data |
| Graceful degradation | Rule-based fallback when AI call fails |
| Structured logging | `loguru` → console + rotating file in `logs/` |
| Separation of concerns | Scraper / AI / Data / Dashboard are fully decoupled |
| Rate limit respect | `AI_BATCH_DELAY` honours Gemini free-tier (15 RPM) |
| No secrets in code | All keys via `.env` — `.env` in `.gitignore` |
| Idempotent DB | `init_db()` is safe to call on every startup |

---

## Adapting for Hackathon Day

When you see the actual problem, only these files need editing:

1. **`scraper/scraper.py`** → update `_parse_page()` for the target site
2. **`ai/enricher.py`** → adjust `GENRES` list and prompt schema
3. **`pipeline.py`** → tweak stage logic if needed
4. **`dashboard/app.py`** → add/remove charts to match the data shape

Everything else (retry, DB, logging, deployment) just works.
