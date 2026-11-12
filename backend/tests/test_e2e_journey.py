"""
End-to-End Complete User Journey Integration Test
Verifies the complete flow from registration to goal compilation,
simulation, portfolio creation, order execution, rebalancing, and audit logging.
"""
from app.core.config import settings


def test_full_investor_journey_e2e(client):
    # Step 1: User Registration
    email = "journey_investor@example.com"
    pwd = "JourneyPassword123!"
    reg_res = client.post(
        f"{settings.API_V1_STR}/auth/register",
        json={"email": email, "password": pwd, "display_name": "Journey Investor", "risk_default": 4.0},
    )
    assert reg_res.status_code == 201
    auth_token = reg_res.json()["access_token"]
    headers = {"Authorization": f"Bearer {auth_token}"}

    # Step 2: Natural Language Goal Compilation
    compile_payload = {
        "raw_text": "I want to accumulate $300,000 for early retirement in 8 years while reserving $40,000 in cash.",
        "save_goal": True,
    }
    comp_res = client.post(f"{settings.API_V1_STR}/intent/compile", json=compile_payload, headers=headers)
    assert comp_res.status_code == 200
    goal_ast = comp_res.json()["ast"]
    goal_id = goal_ast["goal_id"]
    assert goal_ast["target_valuation"] == 300000.0
    assert goal_ast["guaranteed_reserve"] == 40000.0

    # Step 3: Monte Carlo Stochastic Simulation
    sim_payload = {
        "ast_id": goal_id,
        "runs": 2000,
        "time_horizon_years": goal_ast["time_horizon_years"],
        "target_valuation": goal_ast["target_valuation"],
        "risk_profile_index": goal_ast["risk_profile_index"],
        "guaranteed_reserve": goal_ast["guaranteed_reserve"],
        "confidence_threshold": goal_ast["confidence_threshold"],
    }
    sim_res = client.post(f"{settings.API_V1_STR}/simulate/monte-carlo", json=sim_payload, headers=headers)
    assert sim_res.status_code == 200
    sim_data = sim_res.json()
    assert sim_data["success_probability"] > 0
    assert len(sim_data["trajectory_percentiles"]) == 9  # year 0 to 8

    # Step 4: Portfolio Creation linked to Goal AST
    port_payload = {
        "name": "Early Retirement Fund",
        "goal_id": goal_id,
        "initial_deposit": 60000.0,
        "emergency_reserve": goal_ast["guaranteed_reserve"],
        "target_equity_pct": 0.60,
    }
    port_res = client.post(f"{settings.API_V1_STR}/portfolios", json=port_payload, headers=headers)
    assert port_res.status_code == 201
    port_id = port_res.json()["id"]

    # Step 5: Execute Initial Core Allocations (US Equity & Bonds)
    trade_1 = client.post(
        f"{settings.API_V1_STR}/portfolios/{port_id}/trade",
        json={"symbol": "VTI", "side": "BUY", "quantity": 50.0},
        headers=headers,
    )
    assert trade_1.status_code == 200
    assert trade_1.json()["status"] == "FILLED"

    trade_2 = client.post(
        f"{settings.API_V1_STR}/portfolios/{port_id}/trade",
        json={"symbol": "BND", "side": "BUY", "quantity": 40.0},
        headers=headers,
    )
    assert trade_2.status_code == 200
    assert trade_2.json()["status"] == "FILLED"

    # Step 6: Verify Portfolio State & Holdings
    detail_res = client.get(f"{settings.API_V1_STR}/portfolios/{port_id}", headers=headers)
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert len(detail["holdings"]) == 2
    assert detail["emergency_reserve"] == 40000.0

    # Step 7: Rebalancing Drift Evaluation and Auto-Execution
    reb_res = client.post(
        f"{settings.API_V1_STR}/rebalance/execute",
        json={"portfolio_id": port_id, "auto_execute": True, "threshold_pct": 0.01},
        headers=headers,
    )
    assert reb_res.status_code == 200
    reb_data = reb_res.json()
    assert reb_data["executed"] == True
    assert "plain_english_explanation" in reb_data

    # Step 8: Verify Guaranteed Emergency Reserve Constraint Enforcement
    # Available cash = cash_balance - emergency_reserve
    current_cash = client.get(f"{settings.API_V1_STR}/portfolios/{port_id}", headers=headers).json()["cash_balance"]
    excessive_withdrawal = current_cash - 1000  # Leaves less than $40,000 reserve
    if excessive_withdrawal > (current_cash - 40000.0):
        bad_wd = client.post(
            f"{settings.API_V1_STR}/portfolios/{port_id}/withdraw",
            json={"amount": excessive_withdrawal},
            headers=headers,
        )
        assert bad_wd.status_code == 400

    # Step 9: Audit Ledger & Order History Verification
    txs = client.get(f"{settings.API_V1_STR}/portfolios/{port_id}/transactions", headers=headers).json()
    assert len(txs) >= 3  # Initial deposit + 2 trades + any rebalance
    orders = client.get(f"{settings.API_V1_STR}/portfolios/{port_id}/orders", headers=headers).json()
    assert len(orders) >= 2

    # Step 10: PayPal Agentic Commerce & Orders/Payouts Verification
    tools_res = client.get(f"{settings.API_V1_STR}/agent/tools", headers=headers)
    assert tools_res.status_code == 200
    assert len(tools_res.json()["tools"]) >= 3

    plan_res = client.post(
        f"{settings.API_V1_STR}/agent/plan",
        json={"prompt": "Fund $5000 via PayPal to boost my retirement goal readiness", "portfolio_id": port_id, "goal": goal_ast},
        headers=headers,
    )
    assert plan_res.status_code == 200
    assert plan_res.json()["action_type"] == "PAYPAL_FUNDING"

    pp_order = client.post(
        f"{settings.API_V1_STR}/paypal/orders/create",
        json={"portfolio_id": port_id, "amount": 5000.0, "goal_id": goal_id},
        headers=headers,
    )
    assert pp_order.status_code == 200
    pp_order_id = pp_order.json()["paypal_order_id"]

    pp_cap = client.post(
        f"{settings.API_V1_STR}/paypal/orders/{pp_order_id}/capture",
        headers=headers,
    )
    assert pp_cap.status_code == 200
    assert pp_cap.json()["status"] == "COMPLETED"

    # Verify reserve protection rejects unauthorized payout when below reserve
    bad_payout = client.post(
        f"{settings.API_V1_STR}/paypal/payouts/create",
        json={"portfolio_id": port_id, "recipient_email": "buyer@example.com", "amount": 1000.0},
        headers=headers,
    )
    assert bad_payout.status_code == 400
    assert "Protected emergency reserve" in bad_payout.json()["detail"]

    # Now add sufficient cash above the $40,000 emergency reserve to test successful payout
    top_up = client.post(
        f"{settings.API_V1_STR}/portfolios/{port_id}/deposit",
        json={"amount": 25000.0},
        headers=headers,
    )
    assert top_up.status_code == 200

    pp_payout_ok = client.post(
        f"{settings.API_V1_STR}/paypal/payouts/create",
        json={"portfolio_id": port_id, "recipient_email": "buyer@example.com", "amount": 1000.0},
        headers=headers,
    )
    assert pp_payout_ok.status_code == 200
    assert pp_payout_ok.json()["status"] == "SUCCESS"

    pp_records = client.get(f"{settings.API_V1_STR}/paypal/records", headers=headers)
    assert pp_records.status_code == 200
    assert len(pp_records.json()) >= 2
