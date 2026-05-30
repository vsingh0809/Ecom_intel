"""
config/settings.py
------------------
Single source of truth for all application configuration.
All values come from environment variables with sensible defaults.
Call settings.validate() at startup to catch missing keys early (fail-fast).
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

    # ── Scraping ───────────────────────────────────────────────────────────────
    TARGET_URL: str        = os.getenv("TARGET_URL", "https://books.toscrape.com")
    MAX_PAGES: int         = int(os.getenv("MAX_PAGES", "5"))
    REQUEST_DELAY: float   = float(os.getenv("REQUEST_DELAY", "1.5"))
    REQUEST_TIMEOUT: int   = int(os.getenv("REQUEST_TIMEOUT", "15"))
    MAX_RETRIES: int        = int(os.getenv("MAX_RETRIES", "3"))

    # ── AI ─────────────────────────────────────────────────────────────────────
    GEMINI_API_KEY: str    = os.getenv("GEMINI_API_KEY", "")
    GROQ_API_KEY: str    = os.getenv("GROQ_API_KEY", "")
    GEMINI_MODEL: str      = os.getenv("GEMINI_MODEL", 'gemini-2.5-flash')
    GROQ_MODEL: str      = os.getenv("GROQ_MODEL")
    AI_BATCH_SIZE: int     = int(os.getenv("AI_BATCH_SIZE", "5"))
    AI_BATCH_DELAY: float  = float(os.getenv("AI_BATCH_DELAY", "4.5"))

    # ── Database ───────────────────────────────────────────────────────────────
    @property
    def DB_PATH(self) -> str:
        return str(self.DATA_DIR / "books.db")

    @property
    def DB_URL(self) -> str:
        return f"sqlite:///{self.DB_PATH}"

    # ── App ────────────────────────────────────────────────────────────────────
    APP_TITLE: str  = os.getenv("APP_TITLE", "E-Commerce Intelligence Dashboard")
    LOG_LEVEL: str  = os.getenv("LOG_LEVEL", "INFO")

    def bootstrap(self) -> None:
        """Create required directories. Call once at app startup."""
        self.DATA_DIR.mkdir(exist_ok=True)
        self.LOGS_DIR.mkdir(exist_ok=True)

    def validate(self) -> None:
        """
        Fail-fast: raise immediately if critical config is missing.
        Call this at the start of pipeline.py before doing any work.
        """
        missing = []
        if not self.GEMINI_API_KEY:
            missing.append("GEMINI_API_KEY")
        if missing:
            raise EnvironmentError(
                f"\n[config] Missing required environment variables: "
                f"{', '.join(missing)}\n"
                f"→ Copy .env.example to .env and fill in your keys.\n"
            )


# Singleton — import this everywhere
settings = Settings()
