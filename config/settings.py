"""
config/settings.py
------------------
Single source of truth for all application configuration.
All values come from environment variables with sensible defaults.

Production practices:
  • validate() called at startup — fail-fast on missing GROQ_API_KEY
  • bootstrap() creates required directories idempotently
  • All timeouts and limits are tunable via env vars
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env BEFORE anything else reads os.getenv
load_dotenv()


class Settings:
    # ── Paths ──────────────────────────────────────────────────────────────────
    BASE_DIR: Path = Path(__file__).resolve().parent.parent
    DATA_DIR: Path = BASE_DIR / "data"
    LOGS_DIR: Path = BASE_DIR / "logs"
    STATIC_DIR: Path = BASE_DIR / "static"

    # ── Scraping ───────────────────────────────────────────────────────────────
    REQUEST_TIMEOUT: int     = int(os.getenv("REQUEST_TIMEOUT", "15"))
    REQUEST_DELAY: float     = float(os.getenv("REQUEST_DELAY", "1.0"))
    MAX_RETRIES: int         = int(os.getenv("MAX_RETRIES", "3"))
    MAX_LINKS_PER_SITE: int  = int(os.getenv("MAX_LINKS_PER_SITE", "8"))
    MAX_TEXT_PER_PAGE: int   = int(os.getenv("MAX_TEXT_PER_PAGE", "4000"))
    MAX_PAGES_TO_SCRAPE: int = int(os.getenv("MAX_PAGES_TO_SCRAPE", "5"))

    # ── AI (Groq) ──────────────────────────────────────────────────────────────
    GROQ_API_KEY: str   = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str     = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    AI_TEMPERATURE: float = float(os.getenv("AI_TEMPERATURE", "0.1"))
    AI_MAX_TOKENS: int    = int(os.getenv("AI_MAX_TOKENS", "4096"))

    # ── Database ───────────────────────────────────────────────────────────────
    @property
    def DB_PATH(self) -> str:
        return str(self.DATA_DIR / "companies.db")

    @property
    def DB_URL(self) -> str:
        return f"sqlite:///{self.DB_PATH}"

    # ── App ────────────────────────────────────────────────────────────────────
    APP_TITLE: str  = os.getenv("APP_TITLE", "Company Intelligence System")
    LOG_LEVEL: str  = os.getenv("LOG_LEVEL", "INFO")

    # ── Server ─────────────────────────────────────────────────────────────────
    PORT: int = int(os.getenv("PORT", "8000"))

    def bootstrap(self) -> None:
        """Create required directories. Call once at app startup."""
        self.DATA_DIR.mkdir(exist_ok=True)
        self.LOGS_DIR.mkdir(exist_ok=True)
        self.STATIC_DIR.mkdir(exist_ok=True)

    def validate(self) -> None:
        """
        Fail-fast: raise immediately if critical config is missing.
        Call this at the start of pipeline before doing any work.
        """
        missing = []
        if not self.GROQ_API_KEY:
            missing.append("GROQ_API_KEY")
        if missing:
            raise EnvironmentError(
                f"\n[config] Missing required environment variables: "
                f"{', '.join(missing)}\n"
                f"→ Add GROQ_API_KEY to your .env file.\n"
            )


# Singleton — import this everywhere
settings = Settings()
