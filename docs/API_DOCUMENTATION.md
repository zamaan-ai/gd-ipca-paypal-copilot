# GD-IPCA Mark 2 — API Specification & Reference

Complete REST API documentation for the Goal-Driven Intent-to-Portfolio Compilation Engine.

All routes are prefixed with `/api/v1`.

---

## 1. Authentication & Session (`/api/v1/auth`)

### `POST /api/v1/auth/register`
Creates a new investor account.
- **Request Body**:
  ```json
  {
    "email": "user@example.com",
    "password": "SecurePassword123!",
    "display_name": "Jane Doe",
    "risk_default": 3.5
  }
  ```
- **Response** (`201 Created`):
  ```json
  {
    "access_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "refresh_token": "eyJhbGciOi...",
    "user": {
      "id": "uuid-v4",
      "email": "user@example.com",
      "display_name": "Jane Doe",
      "role": "user"
    }
  }
  ```

### `POST /api/v1/auth/login`
Authenticates with email and password, returning JWT access token.

### `GET /api/v1/auth/me`
Returns currently authenticated user profile.
- **Headers**: `Authorization: Bearer <token>`

---

## 2. Intent Compiler (`/api/v1/intent`)

### `GET /api/v1/intent/seeds`
Returns the 5 canonical production goal AST presets.

### `POST /api/v1/intent/compile`
Compiles natural language into a deterministic Goal AST.
- **Request Body**:
  ```json
  {
    "raw_text": "I want to save $150,000 for a house down payment in 5 years while keeping $25,000 ready for emergencies.",
    "save_goal": true
  }
  ```
- **Response**:
  ```json
  {
    "ast": {
      "goal_id": "GOAL-HOM-8921",
      "primary_objective": "Home Down Payment",
      "target_valuation": 150000.0,
      "guaranteed_reserve": 25000.0,
      "time_horizon_years": 5.0,
      "risk_profile_index": 3.5,
      "liquidity_constraint": "STRICT_RESERVE",
      "confidence_threshold": 0.90,
      "utility_function_params": {
        "risk_aversion_gamma": 2.4,
        "inflation_adjustment_rate": 0.028
      }
    },
    "utility_equations": {
      "objective": "max P(Σ W̃_t ≥ Target_Valuation)",
      "constraints": [
        "Σ w_i = 1, w_i ≥ 0",
        "P(MaxDrawdown > limit) ≤ 0.10",
        "Liquidity_Reserve ≥ 25000"
      ]
    }
  }
  ```

---

## 3. Monte Carlo Simulation Engine (`/api/v1/simulate`)

### `POST /api/v1/simulate/monte-carlo`
Generates correlated stochastic trajectory percentiles with Student-t fat tails and regime switching.
- **Request Body**:
  ```json
  {
    "ast_id": "GOAL-HOM-8921",
    "runs": 5000,
    "time_horizon_years": 5.0,
    "target_valuation": 150000.0,
    "risk_profile_index": 3.5,
    "guaranteed_reserve": 25000.0,
    "confidence_threshold": 0.90
  }
  ```
- **Response**:
  ```json
  {
    "trajectory_percentiles": [
      { "year": 0, "p10": 30000.0, "p25": 30000.0, "median": 30000.0, "p75": 30000.0, "p90": 30000.0, "target": 150000.0 },
      { "year": 5, "p10": 138000.0, "p25": 149000.0, "median": 162000.0, "p75": 178000.0, "p90": 196000.0, "target": 150000.0 }
    ],
    "success_probability": 0.74,
    "median_final_value": 162000.0,
    "suggested_allocation": {
      "us_equity": 0.28,
      "intl_equity": 0.13,
      "us_bonds": 0.24,
      "tips": 0.10,
      "cash": 0.15,
      "alternatives": 0.10
    },
    "equity_weight": 0.51,
    "bond_weight": 0.49
  }
  ```

---

## 4. Portfolios & Holdings (`/api/v1/portfolios`)

- `GET /api/v1/portfolios`: List user's active portfolios.
- `POST /api/v1/portfolios`: Create new portfolio.
- `GET /api/v1/portfolios/{id}`: Detailed holdings, valuation, and asset class weights.
- `POST /api/v1/portfolios/{id}/deposit`: Deposit funds.
- `POST /api/v1/portfolios/{id}/withdraw`: Withdraw funds (enforces `emergency_reserve` protection).
- `POST /api/v1/portfolios/{id}/trade`: Execute trade order.
- `GET /api/v1/portfolios/{id}/transactions`: Transaction audit ledger.
- `GET /api/v1/portfolios/{id}/orders`: Order execution history.

---

## 5. Rebalancing Engine (`/api/v1/rebalance`)

### `POST /api/v1/rebalance/execute`
- **Request Body**:
  ```json
  {
    "portfolio_id": "uuid-v4",
    "goal_id": "GOAL-HOM-8921",
    "threshold_pct": 0.02,
    "auto_execute": true
  }
  ```
- **Response**:
  ```json
  {
    "rebalance_event_id": "uuid-v4",
    "portfolio_id": "uuid-v4",
    "drift_detected": 0.042,
    "plain_english_explanation": "Your equity allocation grew above target. We trimmed 4.2 shares of VTI and allocated $680 into BND bonds to preserve your $25,000 emergency reserve.",
    "orders": [
      {
        "symbol": "VTI",
        "side": "SELL",
        "quantity": 4.2,
        "estimated_price": 156.61,
        "estimated_total": 657.76
      },
      {
        "symbol": "BND",
        "side": "BUY",
        "quantity": 5.4,
        "estimated_price": 122.06,
        "estimated_total": 659.12
      }
    ],
    "executed": true
  }
  ```

---

## 6. Market Data (`/api/v1/market`)

- `GET /api/v1/market/quote/{symbol}`: Returns live ticker quote, asset class, and risk score.
- `GET /api/v1/market/universe`: Returns latest quotes for all 16 universe ETFs.
- `GET /api/v1/market/history/{symbol}?limit=90`: Returns daily price bars.
- `POST /api/v1/market/sync`: Batch updates and synchronizes market ticks into the database.
