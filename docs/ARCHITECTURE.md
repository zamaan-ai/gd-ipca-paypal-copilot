# GD-IPCA Mark 2 — Architecture & Solution Blueprint

Comprehensive architectural reference for the Goal-Driven Intent-to-Portfolio Compilation & Semantic Jargon-Abstraction Engine.

---

## 1. System Topology

```
┌────────────────────────────────────────────────────────┐
│                   Vite + React SPA                     │
│   (Glassmorphism, Recharts, Interactive Workflows)     │
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS / REST (JWT Bearer)
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Nginx Reverse Proxy                  │
│   (Gzip compression, static assets, rate limiting)     │
└───────────────────────────┬────────────────────────────┘
                            │ /api/v1/*
                            ▼
┌────────────────────────────────────────────────────────┐
│                   FastAPI Application                  │
│  ├── /auth (JWT, Bcrypt, Role-based Isolation)        │
│  ├── /intent (NLP Parser -> Deterministic AST)         │
│  ├── /simulate (Stochastic Vectorized Monte Carlo)     │
│  ├── /portfolios (Holdings, Cash, Valuations)          │
│  ├── /rebalance (Drift Engine + Plain-English)         │
│  ├── /market (Live Tickers + Historical Fallback)      │
│  └── /health (Live Component Probes)                   │
└──────────────┬──────────────────────────┬──────────────┘
               │                          │
               ▼                          ▼
┌───────────────────────────────┐ ┌──────────────────────┐
│  MySQL 8.0 Primary Storage    │ │   Redis 7 Cache      │
│  (SQLAlchemy + Alembic DDL)   │ │  (Prices & Sessions) │
│  [SQLite Dev Fallback]        │ │ [In-Memory Fallback] │
└───────────────────────────────┘ └──────────────────────┘
```

---

## 2. Core Subsystems

### A. Intent Compiler Subsystem
Translates human free-form prose into a formal mathematical Intent AST:
- **Lexical Extraction**: Extracts target amounts, time horizons, emergency reserves, and qualitative risk descriptions.
- **Deterministic Mapping**: Maps risk expressions to risk index $\gamma \in [0, 10]$ and confidence threshold $\alpha \in [0.80, 0.95]$.
- **Milestone Generation**: Synthesizes periodic checkpoints along the horizon.

### B. Stochastic Monte Carlo Engine
- **Vectorized Paths**: Simulates $N$ correlated paths ($N \ge 5,000$).
- **Regime Switching**: 4-state Markov transition model (Normal, Bull, Bear, Crisis).
- **Fat Tails**: Student-$t$ copula shocks to simulate extreme market events.
- **Ring-Fenced Reserve**: Liquid emergency reserve is protected from market drawdowns.

### C. Multi-Asset Broker Engine & Order Matching
- Executes market orders with real-time quote lookups.
- Enforces purchasing power constraints on buys.
- Enforces share availability constraints on sells.
- Recomputes portfolio total valuation and updates individual holding cost bases and allocation weights.
- Emits ledger records to `transactions` table.

### D. Rebalancing & Semantic Jargon-Abstraction
- Checks deviations between current holding weights and target weights.
- Generates required rebalancing trades (sells over-allocated assets, buys under-allocated assets).
- Produces **Zero-Jargon Explanations**: Converts quantitative adjustments into plain-English language that explains *why* the trade occurred and assures the investor that their emergency reserve remains protected.

### E. Resilient Dual-Engine Persistence
- Production: MySQL 8.0 with connection pooling (`pool_pre_ping`, `pool_recycle`).
- Development & Testing: Transparent in-memory / local SQLite fallback when MySQL is offline.
- Redis 7 caching with automatic fallback to thread-safe in-memory cache.
- Live market data with Yahoo Finance and fallback to canonical 5-year historical prices.
