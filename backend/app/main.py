"""
GD-IPCA Mark 2 — FastAPI Application Entry Point
Production Goal-Driven Intent-to-Portfolio Compilation & Execution Engine
"""
import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.db.session import init_db, SessionLocal
from app.routers import auth, intent, simulate, portfolios, rebalance, market, health, paypal, agent
from app.routers.auth import ensure_seed_users

# Configure structured logging
logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("gdipca.main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database tables and seed accounts
    logger.info("Initializing GD-IPCA Mark 2 system components...")
    try:
        init_db()
        db = SessionLocal()
        ensure_seed_users(db)
        db.close()
        logger.info("Database and seed users verified.")
    except Exception as e:
        logger.error(f"Startup database initialization error: {e}")
    yield
    logger.info("GD-IPCA engine shutting down...")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description="Goal-Driven Intent-to-Portfolio Compilation & Semantic Jargon-Abstraction Engine (Mark 2)",
    version=settings.VERSION,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    lifespan=lifespan,
)

# Production CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "PATCH"],
    allow_headers=["*"],
    expose_headers=["X-Process-Time"],
)


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = f"{process_time:.4f}s"
    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception(f"Unhandled error processing {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": "InternalServerError",
            "message": str(exc) if settings.DEBUG else "An unexpected internal server error occurred.",
            "path": request.url.path,
        },
    )


# Include Routers
app.include_router(health.router, prefix=settings.API_V1_STR, tags=["Health"])
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["Authentication & Session"])
app.include_router(intent.router, prefix=f"{settings.API_V1_STR}/intent", tags=["Intent Compiler"])
app.include_router(simulate.router, prefix=f"{settings.API_V1_STR}/simulate", tags=["Monte Carlo Simulation"])
app.include_router(portfolios.router, prefix=f"{settings.API_V1_STR}/portfolios", tags=["Portfolios & Holdings"])
app.include_router(rebalance.router, prefix=f"{settings.API_V1_STR}/rebalance", tags=["Rebalance & Execution"])
app.include_router(market.router, prefix=f"{settings.API_V1_STR}/market", tags=["Market Data Provider"])
app.include_router(paypal.router, prefix=f"{settings.API_V1_STR}/paypal", tags=["PayPal Developer Platform"])
app.include_router(agent.router, prefix=f"{settings.API_V1_STR}/agent", tags=["AI Agentic Commerce"])


@app.get("/")
def root():
    return {
        "engine": "GD-IPCA Mark 2",
        "version": settings.VERSION,
        "environment": settings.ENVIRONMENT,
        "status": "operational",
        "docs": "/api/docs",
        "endpoints": {
            "health": f"GET {settings.API_V1_STR}/health",
            "auth_login": f"POST {settings.API_V1_STR}/auth/login",
            "auth_me": f"GET {settings.API_V1_STR}/auth/me",
            "compile": f"POST {settings.API_V1_STR}/intent/compile",
            "seeds": f"GET {settings.API_V1_STR}/intent/seeds",
            "monte_carlo": f"POST {settings.API_V1_STR}/simulate/monte-carlo",
            "portfolios": f"GET {settings.API_V1_STR}/portfolios",
            "rebalance": f"POST {settings.API_V1_STR}/rebalance/execute",
            "market_universe": f"GET {settings.API_V1_STR}/market/universe",
            "paypal_order": f"POST {settings.API_V1_STR}/paypal/orders/create",
            "paypal_payout": f"POST {settings.API_V1_STR}/paypal/payouts/create",
            "agent_plan": f"POST {settings.API_V1_STR}/agent/plan",
        },
    }
