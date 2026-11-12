"""
Health Check & System Diagnostics Router
"""
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import get_system_config, DATA_DIR, settings
from app.db.session import get_db, engine
from app.services.cache import cache
from app.services.paypal_service import paypal_service
from app.services.ai_agent import active_ai_provider

router = APIRouter()


@router.get("/health")
def health_check(db: Session = Depends(get_db)):
    cfg = get_system_config()

    # DB connection check
    db_ok = False
    db_dialect = str(engine.dialect.name)
    try:
        db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "healthy" if db_ok and DATA_DIR.exists() else "degraded",
        "engine": "GD-IPCA Mark 2",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "database": {
            "status": "connected" if db_ok else "disconnected",
            "dialect": db_dialect,
        },
        "cache": {
            "type": "redis" if cache.is_redis_online() else "in-memory",
            "redis_connected": cache.is_redis_online(),
        },
        "market_data_provider": settings.MARKET_DATA_PROVIDER,
        "broker_mode": settings.BROKER_MODE,
        "paypal_mode": paypal_service.current_mode(),
        "ai_provider": active_ai_provider(),
        "data_dir": str(DATA_DIR),
        "data_ok": DATA_DIR.exists(),
        "components": {
            "intent_compiler": "ready",
            "monte_carlo": "ready",
            "portfolio_engine": "ready",
            "broker_engine": "ready",
            "rebalance_engine": "ready",
            "paypal_platform": "ready",
            "ai_agent_copilot": "ready",
            "auth_security": "ready",
        },
    }
