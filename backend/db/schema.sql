-- GD-IPCA Mark 1 — PostgreSQL Schema (Intents + Profiles)
-- TimescaleDB extension recommended for market ticks

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS users (
    user_id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           TEXT UNIQUE NOT NULL,
    display_name    TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    risk_default    NUMERIC(3,1) DEFAULT 3.5
);

CREATE TABLE IF NOT EXISTS intent_asts (
    goal_id                 TEXT PRIMARY KEY,
    user_id                 UUID REFERENCES users(user_id),
    primary_objective       TEXT NOT NULL,
    raw_text                TEXT,
    target_valuation        NUMERIC(18,2) NOT NULL,
    guaranteed_reserve      NUMERIC(18,2) NOT NULL,
    time_horizon_years      NUMERIC(6,2) NOT NULL,
    risk_profile_index      NUMERIC(4,2) NOT NULL,
    liquidity_constraint    TEXT DEFAULT 'STRICT_RESERVE',
    confidence_threshold    NUMERIC(4,3) DEFAULT 0.90,
    utility_params          JSONB,
    milestones              JSONB,
    preferred_asset_classes TEXT[],
    excluded_assets         TEXT[],
    tax_status              TEXT DEFAULT 'taxable_brokerage',
    status                  TEXT DEFAULT 'active',
    created_at              TIMESTAMPTZ DEFAULT NOW(),
    updated_at              TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS simulation_runs (
    run_id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id             TEXT REFERENCES intent_asts(goal_id),
    n_paths             INTEGER NOT NULL,
    success_probability NUMERIC(6,4),
    median_final_value  NUMERIC(18,2),
    trajectory_summary  JSONB,
    allocation          JSONB,
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rebalance_events (
    event_id        UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    goal_id         TEXT REFERENCES intent_asts(goal_id),
    trigger_reason  TEXT,
    plain_english   TEXT,
    orders          JSONB,
    executed_at     TIMESTAMPTZ DEFAULT NOW()
);

-- TimescaleDB hypertable example (run after enabling timescaledb)
-- CREATE TABLE market_ticks (
--     time        TIMESTAMPTZ NOT NULL,
--     symbol      TEXT NOT NULL,
--     price       NUMERIC(18,6),
--     volume      BIGINT
-- );
-- SELECT create_hypertable('market_ticks', 'time');
