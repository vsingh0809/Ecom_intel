# 🏢 Company Intelligence System

AI-powered company website intelligence system that scrapes company websites, extracts business insights using Groq AI, and displays results through a premium web interface.

## 🚀 Quick Start

### Prerequisites
- Python 3.11+
- Groq API key (free at [console.groq.com](https://console.groq.com))

### Local Setup
```bash
# 1. Clone and enter project
cd ecom_intel

# 2. Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/Mac

# 3. Install dependencies
pip install -r requirements.txt

# 4. Configure environment
# Edit .env and add your GROQ_API_KEY

# 5. Run the server
python server.py

# 6. Open browser
# http://localhost:8000
```

## 📡 API Endpoints

### POST `/enrich`
Enrich a single company URL.
```json
{
  "url": "https://example.com",
  "website_name": "Example Corp"
}
```

### GET `/results`
Returns all enriched company profiles.

### GET `/health`
Health check endpoint.

## 🏗️ Architecture

```
URL Input → Smart Scraper → HTML Cleaner → Groq AI → SQLite DB → Web UI
```

### Smart Scraping (3-tier fallback)
1. **Sitemap Discovery**: Check robots.txt → sitemap.xml → fuzzy-match relevant pages
2. **Homepage Link Crawling**: Extract internal links, score by keyword relevance
3. **Homepage Fallback**: Scrape homepage only if discovery fails

### Token Optimization
- Strip scripts, styles, nav, footer, cookie banners
- Collapse whitespace
- Limit to ~4000 chars per page, max 5 pages
- Total context to LLM: ~20K chars

### Anti-Hallucination
- Regex-extracted emails/phones passed as ground truth
- AI instructed to use ONLY provided contacts
- Missing fields return "N/A" — never fabricated

## 🛠️ Tech Stack
| Component | Technology |
|-----------|-----------|
| Backend | FastAPI + Uvicorn |
| AI | Groq (llama-3.3-70b-versatile) |
| Scraping | requests + BeautifulSoup |
| Database | SQLite + SQLAlchemy |
| Frontend | Vanilla HTML/CSS/JS |
| Deployment | Render (free tier) |

## 📁 Project Structure
```
ecom_intel/
├── config/          # Settings & env management
├── scraper/         # Smart 3-tier company scraper
├── ai/              # Groq AI enrichment engine
├── data/            # Pydantic models + SQLite ORM
├── static/          # Premium glassmorphic frontend
├── server.py        # FastAPI application
├── pipeline.py      # Orchestrator
├── colab_notebook.py # Google Colab reference
└── requirements.txt # Dependencies
```

## 🚀 Deployment (Render)
1. Push to GitHub
2. Create new Web Service on Render
3. Set environment variable: `GROQ_API_KEY`
4. Build command: `pip install -r requirements.txt`
5. Start command: `uvicorn server:app --host 0.0.0.0 --port $PORT`

## 📄 License
MIT
