

import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from loguru import logger
import json

from config import settings
from pipeline import enrich_single, configure_logging
from data import init_db, load_all_companies


# ── App Setup ─────────────────────────────────────────────────────────────────

app = FastAPI(
    title=settings.APP_TITLE,
    description="AI-powered company website intelligence system",
    version="1.0.0",
)

# CORS — allow all origins (hackathon: publicly accessible, no login)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
RESULTS_FILE = BASE_DIR / "results.json"

def init_db():
    """Initialize the database (creates an empty results.json if it doesn't exist)."""
    if not RESULTS_FILE.exists():
        logger.info(f"[data] Creating new database file at {RESULTS_FILE}")
        with open(RESULTS_FILE, "w", encoding="utf-8") as f:
            json.dump([], f)
    else:
        logger.info(f"[data] Database found at {RESULTS_FILE}")

def load_all_companies():
    """Reads results.json and returns the list of enriched companies."""
    if not RESULTS_FILE.exists():
        logger.warning(f"[data] No results file found at {RESULTS_FILE}")
        return []

    try:
        with open(RESULTS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            # Guarantee we always return a list for the frontend
            return data if isinstance(data, list) else []
            
    except json.JSONDecodeError:
        logger.error("[data] results.json is empty or corrupted.")
        return []
    except Exception as e:
        logger.error(f"[data] Error reading results.json: {e}")
        return []

# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    """Initialize logging, database, and static files on startup."""
    configure_logging()
    settings.bootstrap()
    init_db()
    logger.info(f"[server] {settings.APP_TITLE} started on port {settings.PORT}")


# ── Request/Response Models ──────────────────────────────────────────────────

class EnrichRequest(BaseModel):
    """Request body for POST /enrich."""
    url: str = Field(..., description="Company website URL to enrich")
    website_name: str = Field(
        default="",
        description="Optional website name for record-keeping"
    )


class EnrichResponse(BaseModel):
    """Response body for POST /enrich — matches hackathon schema."""
    website_name: str = "N/A"
    company_name: str = "N/A"
    address: str = "N/A"
    mobile_number: str = "N/A"
    mail: list[str] = []
    core_service: str = "N/A"
    target_customer: str = "N/A"
    probable_pain_point: str = "N/A"
    outreach_opener: str = "N/A"
    website_url: str = ""
    enriched_at: str = None


# ── API Endpoints ─────────────────────────────────────────────────────────────

@app.post("/enrich", response_model=EnrichResponse)
async def enrich_company_endpoint(request: EnrichRequest):
    """
    POST /enrich
    Input:  {"url": "https://example.com", "website_name": "Example Corp"}
    Output: Enriched company profile (hackathon JSON schema)
    """
    url = request.url.strip()
    if not url:
        raise HTTPException(status_code=400, detail="URL is required")

    # Auto-prepend https:// if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    website_name = request.website_name.strip() or "N/A"

    logger.info(f"[api] POST /enrich — url={url}, name={website_name}")

    try:
        result = enrich_single(url, website_name)
        return JSONResponse(content=result, status_code=200)
    except Exception as exc:
        logger.error(f"[api] Enrichment error: {exc}")
        # Return a safe fallback response instead of crashing
        return JSONResponse(
            content={
                "website_name": website_name,
                "company_name": "N/A",
                "address": "N/A",
                "mobile_number": "N/A",
                "mail": [],
                "core_service": "N/A",
                "target_customer": "N/A",
                "probable_pain_point": "N/A",
                "outreach_opener": "N/A",
                "website_url": url,
                "enriched_at": None,
                "error": str(exc),
            },
            status_code=200,  # Still 200 — schema never breaks
        )


@app.get("/results")
async def get_results():
    """
    GET /results
    Returns: Array of all enriched company profiles.
    """
    logger.info("[api] GET /results")
    try:
        companies = load_all_companies()
        return JSONResponse(content=companies, status_code=200)
    except Exception as exc:
        logger.error(f"[api] Error loading results: {exc}")
        return JSONResponse(content=[], status_code=200)


# ── Static Files & Frontend ──────────────────────────────────────────────────

# Mount static files
static_dir = settings.STATIC_DIR
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
async def serve_frontend():
    """Serve the main frontend page."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse(
        content={"message": "Company Intelligence System API", "docs": "/docs"},
        status_code=200,
    )


# ── Health Check ──────────────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint for monitoring."""
    return {"status": "healthy", "service": settings.APP_TITLE}


# ── Run ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "server:app",
        host="0.0.0.0",
        port=settings.PORT,
        reload=True,
        log_level="info",
    )
