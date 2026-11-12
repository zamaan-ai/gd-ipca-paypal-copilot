"""
GD-IPCA Mark 2 — Core Production Configuration & Settings
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, List, Union
import json
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

# Robust discovery of data directory
_CURRENT_FILE = Path(__file__).resolve()
_POSSIBLE_DATA_DIRS = [
    _CURRENT_FILE.parents[3] / "data",              # gd-mark-2/data
    _CURRENT_FILE.parents[2] / "data",              # backend/data
    _CURRENT_FILE.parents[2].parent / "data",       # fallback root/data
    Path.cwd() / "data",                            # working dir/data
    Path("/data"),                                  # Docker mount
]

DATA_DIR = next((p for p in _POSSIBLE_DATA_DIRS if p.exists() and p.is_dir()), _POSSIBLE_DATA_DIRS[0])
BASE_DIR = DATA_DIR.parent if DATA_DIR.exists() else _CURRENT_FILE.parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    PROJECT_NAME: str = "GD-IPCA Engine"
    VERSION: str = "2.0.0-PROD"
    API_V1_STR: str = "/api/v1"

    # Security & JWT
    SECRET_KEY: str = os.getenv("SECRET_KEY", "gdipca-super-secure-production-key-change-in-env-32bytes-min")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # CORS
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:80",
        "http://localhost",
    ]

    # Database: MySQL primary with transparent fallback
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://root:password@localhost:3306/gdipca?charset=utf8mb4"
    )
    DB_POOL_PRE_PING: bool = True
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_RECYCLE: int = 3600

    # Redis Cache
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    REDIS_ENABLED: bool = os.getenv("REDIS_ENABLED", "false").lower() in ("true", "1", "yes")

    # Market Data
    MARKET_DATA_PROVIDER: str = os.getenv("MARKET_DATA_PROVIDER", "yahoo")
    MARKET_DATA_CACHE_TTL_SECONDS: int = 300

    # Broker Execution (simulated paper broker or external API)
    BROKER_MODE: str = os.getenv("BROKER_MODE", "paper")
    BROKER_API_KEY: str = os.getenv("BROKER_API_KEY", "")
    BROKER_API_SECRET: str = os.getenv("BROKER_API_SECRET", "")

    # PayPal Developer Platform (Sandbox / Live REST v2)
    PAYPAL_MODE: str = os.getenv("PAYPAL_MODE", "sandbox")
    PAYPAL_CLIENT_ID: str = os.getenv("PAYPAL_CLIENT_ID", "")
    PAYPAL_CLIENT_SECRET: str = os.getenv("PAYPAL_CLIENT_SECRET", "")
    PAYPAL_WEBHOOK_ID: str = os.getenv("PAYPAL_WEBHOOK_ID", "")
    PAYPAL_BASE_URL: str = os.getenv(
        "PAYPAL_BASE_URL",
        "https://api-m.sandbox.paypal.com"
        if os.getenv("PAYPAL_MODE", "sandbox").lower() != "live"
        else "https://api-m.paypal.com",
    )

    # AI / LLM Engine (OpenAI or Gemini; deterministic fallback if unset)
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")


settings = Settings()


def load_json(name: str) -> Union[dict, list]:
    """Load JSON file from DATA_DIR with multiple fallbacks."""
    candidates = [
        DATA_DIR / name,
        _CURRENT_FILE.parents[3] / "data" / name,
        _CURRENT_FILE.parents[2] / "data" / name,
        _CURRENT_FILE.parents[2].parent / "data" / name,
        Path.cwd() / "data" / name,
    ]
    for p in candidates:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError(f"Could not locate dataset '{name}' in any searched directory: {candidates}")


def get_market_parameters() -> dict:
    return load_json("market_parameters.json")


def get_sample_intents() -> list:
    return load_json("sample_intents.json")


def get_system_config() -> dict:
    try:
        return load_json("system_config.json")
    except Exception:
        return {"engine_version": settings.VERSION, "default_monte_carlo_runs": 5000}
