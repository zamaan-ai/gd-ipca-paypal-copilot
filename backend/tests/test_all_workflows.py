"""
GD-IPCA Comprehensive Integration Test Suite
Verifies all backend workflows: Auth, Intent, Simulation, Portfolio, Broker, Rebalance, Market Data.
"""
from app.core.config import settings


def test_01_health_check(client):
    res = client.get(f"{settings.API_V1_STR}/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("healthy", "degraded")
    assert data["database"]["status"] == "connected"
    assert "components" in data
    assert data["components"]["intent_compiler"] == "ready"
    assert data["components"]["monte_carlo"] == "ready"


def test_02_auth_login_and_profile(client, auth_headers):
    # Test valid profile lookup
    me = client.get(f"{settings.API_V1_STR}/auth/me", headers=auth_headers)
    assert me.status_code == 200
    assert me.json()["email"] == "demo@gdipca.io"

    # Test unauthorized access
    unauth = client.get(f"{settings.API_V1_STR}/auth/me")
    assert unauth.status_code == 401


def test_03_auth_registration(client):
    reg = client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": "investor_new@example.com", "password": "SecurePassword123!", "display_name": "New Investor"},
    )
    assert reg.status_code == 201
    data = reg.json()
    assert "access_token" in data
    assert data["user"]["email"] == "investor_new@example.com"


def test_04_intent_seeds_and_compile(client, auth_headers):
    # Seeds
    seeds = client.get(f"{settings.API_V1_STR}/intent/seeds")
    assert seeds.status_code == 200
    seed_list = seeds.json()
    assert len(seed_list) >= 5

    # Compile natural language
    payload = {
        "raw_text": "I want to save $250,000 for buying an apartment in 7 years while keeping $35,000 emergency fund safely protected.",
        "save_goal": True,
    }
    compile_res = client.post(f"{settings.API_V1_STR}/intent/compile", json=payload, headers=auth_headers)
    assert compile_res.status_code == 200
    ast = compile_res.json()["ast"]
    assert ast["target_valuation"] == 250000.0
    assert ast["guaranteed_reserve"] == 35000.0
    assert ast["time_horizon_years"] == 7.0
    assert "utility_function_params" in ast


def test_05_monte_carlo_simulation(client):
    sim_req = {
        "ast_id": "GOAL-TEST-1234",
        "runs": 1000,
        "time_horizon_years": 5.0,
        "target_valuation": 150000.0,
        "risk_profile_index": 3.5,
        "guaranteed_reserve": 25000.0,
        "confidence_threshold": 0.90,
    }
    res = client.post(f"{settings.API_V1_STR}/simulate/monte-carlo", json=sim_req)
    assert res.status_code == 200
    data = res.json()
    assert "trajectory_percentiles" in data
    assert len(data["trajectory_percentiles"]) == 6  # year 0 to 5
    # Monotonicity check for percentile bands
    for row in data["trajectory_percentiles"]:
        assert row["p10"] <= row["p25"] <= row["median"] <= row["p75"] <= row["p90"]
    assert 0.0 <= data["success_probability"] <= 1.0
    assert "suggested_allocation" in data


def test_06_portfolio_lifecycle_and_reserve_isolation(client, auth_headers):
    # 1. Create Portfolio
    create_req = {
        "name": "Retirement Target Portfolio",
        "initial_deposit": 40000.0,
        "emergency_reserve": 15000.0,
        "target_equity_pct": 0.65,
    }
    create_res = client.post(f"{settings.API_V1_STR}/portfolios", json=create_req, headers=auth_headers)
    assert create_res.status_code == 201
    p_data = create_res.json()
    p_id = p_data["id"]
    assert p_data["cash_balance"] == 40000.0
    assert p_data["emergency_reserve"] == 15000.0

    # 2. Deposit Cash
    dep_res = client.post(f"{settings.API_V1_STR}/portfolios/{p_id}/deposit", json={"amount": 5000.0}, headers=auth_headers)
    assert dep_res.status_code == 200
    assert dep_res.json()["cash_balance"] == 45000.0

    # 3. Withdraw Cash within safe limit
    wd_res = client.post(f"{settings.API_V1_STR}/portfolios/{p_id}/withdraw", json={"amount": 10000.0}, headers=auth_headers)
    assert wd_res.status_code == 200
    assert wd_res.json()["cash_balance"] == 35000.0

    # 4. Withdraw cash violating emergency reserve -> MUST FAIL (Protected reserve constraint)
    # Available = 35000 - 15000 = 20000. Trying to withdraw 25000 should raise 400!
    wd_fail = client.post(f"{settings.API_V1_STR}/portfolios/{p_id}/withdraw", json={"amount": 25000.0}, headers=auth_headers)
    assert wd_fail.status_code == 400
    assert "emergency reserve" in wd_fail.json()["detail"].lower()


def test_07_broker_trade_execution_and_ledger(client, auth_headers):
    # Create portfolio with cash
    p_res = client.post(
        f"{settings.API_V1_STR}/portfolios",
        json={"name": "Trading Execution Portfolio", "initial_deposit": 20000.0, "emergency_reserve": 5000.0},
        headers=auth_headers,
    )
    p_id = p_res.json()["id"]

    # Execute BUY order of VTI
    trade_req = {"symbol": "VTI", "side": "BUY", "quantity": 10.0, "order_type": "MARKET"}
    trade_res = client.post(f"{settings.API_V1_STR}/portfolios/{p_id}/trade", json=trade_req, headers=auth_headers)
    assert trade_res.status_code == 200
    order_data = trade_res.json()
    assert order_data["status"] == "FILLED"
    assert order_data["symbol"] == "VTI"
    assert order_data["executed_price"] > 0

    # Verify Portfolio holdings and transactions ledger
    detail = client.get(f"{settings.API_V1_STR}/portfolios/{p_id}", headers=auth_headers).json()
    assert len(detail["holdings"]) == 1
    assert detail["holdings"][0]["symbol"] == "VTI"
    assert detail["holdings"][0]["quantity"] == 10.0

    # Verify transactions ledger entry
    txs = client.get(f"{settings.API_V1_STR}/portfolios/{p_id}/transactions", headers=auth_headers).json()
    assert len(txs) >= 2  # Deposit + Buy trade
    assert any(t["type"] == "BUY" and t["symbol"] == "VTI" for t in txs)


def test_08_rebalance_drift_and_auto_execution(client, auth_headers):
    # Create portfolio
    p_res = client.post(
        f"{settings.API_V1_STR}/portfolios",
        json={"name": "Rebalance Test Portfolio", "initial_deposit": 50000.0, "emergency_reserve": 10000.0, "target_equity_pct": 0.60},
        headers=auth_headers,
    )
    p_id = p_res.json()["id"]

    # Buy only equity to create drift
    client.post(
        f"{settings.API_V1_STR}/portfolios/{p_id}/trade",
        json={"symbol": "VTI", "side": "BUY", "quantity": 150.0},
        headers=auth_headers,
    )

    # Check rebalance (preview mode)
    reb_preview = client.post(
        f"{settings.API_V1_STR}/rebalance/execute",
        json={"portfolio_id": p_id, "auto_execute": False},
        headers=auth_headers,
    )
    assert reb_preview.status_code == 200
    reb_data = reb_preview.json()
    assert "plain_english_explanation" in reb_data
    assert len(reb_data["plain_english_explanation"]) > 10

    # Check auto-execute rebalancing
    reb_exec = client.post(
        f"{settings.API_V1_STR}/rebalance/execute",
        json={"portfolio_id": p_id, "auto_execute": True},
        headers=auth_headers,
    )
    assert reb_exec.status_code == 200
    assert reb_exec.json()["executed"] == True


def test_09_market_data_endpoints(client):
    # Quote lookup
    q = client.get(f"{settings.API_V1_STR}/market/quote/VTI")
    assert q.status_code == 200
    assert q.json()["symbol"] == "VTI"
    assert q.json()["price"] > 0

    # Universe quotes
    u = client.get(f"{settings.API_V1_STR}/market/universe")
    assert u.status_code == 200
    assert len(u.json()) >= 16

    # History lookup
    h = client.get(f"{settings.API_V1_STR}/market/history/VTI?limit=30")
    assert h.status_code == 200
    assert len(h.json()) > 0
    assert "close" in h.json()[0]
