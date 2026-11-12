# GD-IPCA™ Mark 2

**Goal-Driven Intent-to-Portfolio Compilation, Stochastic Forecasting & PayPal Execution Engine**

Licensed under the [MIT License](LICENSE).

---

## Architecture & Capabilities

- **Natural-Language Intent Compilation ([`backend/app/routers/intent.py`](backend/app/routers/intent.py))**: Translates plain-English financial goals into validated Intent ASTs using OpenAI/Gemini extraction when API keys are configured, with deterministic structured parsing fallback.
- **Stochastic Monte Carlo Engine ([`backend/app/services/monte_carlo.py`](backend/app/services/monte_carlo.py))**: Runs 5,000 vectorized simulation paths across 4 market regimes and Student-$t$ fat-tail shocks.
- **PayPal Developer Platform Integration ([`backend/app/services/paypal_service.py`](backend/app/services/paypal_service.py), [`backend/app/routers/paypal.py`](backend/app/routers/paypal.py))**:
  - **OAuth2 Token Exchange** (`POST /v1/oauth2/token`)
  - **PayPal Orders v2** (`POST /v2/checkout/orders`, `POST /v2/checkout/orders/{id}/capture`) for goal funding deposits
  - **PayPal Payouts v1** (`POST /v1/payments/payouts`) for milestone cash disbursements protected by the emergency reserve floor
  - Supports live PayPal Sandbox (`PAYPAL_CLIENT_ID` / `PAYPAL_CLIENT_SECRET`) as well as local sandbox simulation when unconfigured.
- **Agentic Commerce Planner ([`backend/app/routers/agent.py`](backend/app/routers/agent.py), [`backend/app/services/ai_agent.py`](backend/app/services/ai_agent.py))**: Evaluates portfolio readiness against Monte Carlo confidence thresholds and prepares human-in-the-loop PayPal funding, payout, or rebalance tool calls (`/api/v1/agent/tools`, `/plan`, `/execute-paypal`).
- **Portfolio Execution & Audit Ledger ([`backend/app/routers/portfolios.py`](backend/app/routers/portfolios.py), [`backend/app/routers/rebalance.py`](backend/app/routers/rebalance.py))**: Trade execution across 16 ETFs, automated drift rebalancing, and persistent SQL transaction history (MySQL 8.0 / SQLite fallback).

---

## Quick Start

### 1. Environment Configuration (Optional PayPal Sandbox & LLM Keys)
Copy `backend/.env.example` to `backend/.env`:
```env
PAYPAL_MODE=sandbox
PAYPAL_CLIENT_ID=your_sandbox_client_id
PAYPAL_CLIENT_SECRET=your_sandbox_client_secret
OPENAI_API_KEY=
GEMINI_API_KEY=
```

### 2. Docker Compose
```bash
docker compose up --build -d
```
- **Frontend**: `http://localhost:80`
- **API Docs**: `http://localhost:8000/api/docs`

### 3. Local Development
#### Backend
```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt email-validator
uvicorn app.main:app --reload --port 8000
```
#### Frontend
```bash
python3 -m http.server 5173 --bind 127.0.0.1
```
Open **`http://localhost:5173`** (or run `cd frontend && npm install && npm run dev`).

---

## Testing
```bash
# Backend integration & E2E tests
cd backend && pytest tests/ -v

# Frontend unit tests
node --test frontend/test/*.test.js
```

## Demo Credentials
| Account | Email | Password | Role |
|---------|-------|----------|------|
| Demo Investor | `demo@gdipca.io` | `Demo12345!` | User |
| System Admin | `admin@gdipca.io` | `Admin12345!` | Admin |

## Documentation
- [Installation Guide](docs/INSTALLATION.md)
- [REST API Specification](docs/API_DOCUMENTATION.md)
- [Architecture Overview](docs/ARCHITECTURE.md)
