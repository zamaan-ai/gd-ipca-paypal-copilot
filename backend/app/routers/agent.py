"""
GD-IPCA Agentic AI Commerce Router
Plans and executes human-in-the-loop PayPal + Portfolio actions using
Monte Carlo diagnostics, fiduciary reserve checks, and PayPal Agent Toolkit schemas.
"""
from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.security import get_current_user
from app.db.session import get_db
from app.models.entities import User
from app.routers.portfolios import _get_user_portfolio_or_404
from app.routers.paypal import (
    PayPalCreateOrderRequest,
    PayPalCreatePayoutRequest,
    capture_paypal_order,
    create_paypal_order,
    create_paypal_payout,
)
from app.services.ai_agent import PAYPAL_AGENT_TOOLS, active_ai_provider, plan_agentic_action
from app.services.monte_carlo import run_monte_carlo
from app.services.paypal_service import paypal_service

router = APIRouter()


class AgentPlanRequest(BaseModel):
    prompt: str = Field(..., min_length=4)
    portfolio_id: str
    goal: Dict[str, Any]


class AgentExecuteRequest(BaseModel):
    action_type: str  # "PAYPAL_FUNDING" | "PAYPAL_PAYOUT"
    portfolio_id: str
    amount: float = Field(..., gt=0)
    goal_id: Optional[str] = None
    recipient_email: Optional[str] = "demo-buyer@personal.example.com"
    ai_rationale: Optional[str] = None


@router.get("/tools")
def list_agent_tools():
    return {
        "ai_provider": active_ai_provider(),
        "paypal_mode": paypal_service.current_mode(),
        "tools": PAYPAL_AGENT_TOOLS,
    }


@router.post("/plan")
def create_agent_plan(
    req: AgentPlanRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    portfolio = _get_user_portfolio_or_404(db, current_user, req.portfolio_id)

    mc = run_monte_carlo(
        time_horizon_years=float(req.goal.get("time_horizon_years", 5.0)),
        target_valuation=float(req.goal.get("target_valuation", 150000.0)),
        risk_profile_index=float(req.goal.get("risk_profile_index", 3.5)),
        guaranteed_reserve=float(req.goal.get("guaranteed_reserve", portfolio.emergency_reserve)),
        confidence_threshold=float(req.goal.get("confidence_threshold", 0.90)),
        n_paths=2000,
    )

    plan = plan_agentic_action(
        prompt=req.prompt,
        goal=req.goal,
        portfolio={
            "id": portfolio.id,
            "cash_balance": portfolio.cash_balance,
            "emergency_reserve": portfolio.emergency_reserve,
            "total_valuation": portfolio.total_valuation,
        },
        success_probability=mc["success_probability"],
        default_email=current_user.email if "@" in current_user.email else "demo-buyer@personal.example.com",
    )
    plan["monte_carlo_success_probability"] = mc["success_probability"]
    plan["paypal_mode"] = paypal_service.current_mode()
    return plan


@router.post("/execute-paypal")
def execute_agent_paypal_action(
    req: AgentExecuteRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if req.action_type == "PAYPAL_FUNDING":
        order = create_paypal_order(
            PayPalCreateOrderRequest(
                portfolio_id=req.portfolio_id,
                amount=req.amount,
                goal_id=req.goal_id,
                description="AI Copilot PayPal Goal Funding",
                ai_rationale=req.ai_rationale or "Agentic AI Goal Gap Funding",
            ),
            db=db,
            current_user=current_user,
        )
        # In sandbox simulation mode, complete capture immediately for 1-click flow;
        # in live sandbox mode, return approval_url so user can approve in PayPal UI or capture after approval.
        if order["mode"] == "sandbox_simulation":
            captured = capture_paypal_order(order["paypal_order_id"], db=db, current_user=current_user)
            return {
                "executed": True,
                "flow": "instant_sandbox_capture",
                "paypal_result": captured,
            }
        return {
            "executed": False,
            "flow": "awaiting_paypal_approval",
            "paypal_result": order,
        }

    if req.action_type == "PAYPAL_PAYOUT":
        payout = create_paypal_payout(
            PayPalCreatePayoutRequest(
                portfolio_id=req.portfolio_id,
                recipient_email=req.recipient_email or "demo-buyer@personal.example.com",
                amount=req.amount,
                goal_id=req.goal_id,
                note=req.ai_rationale or "AI Copilot Milestone Payout",
                ai_rationale=req.ai_rationale or "Agentic AI Safe Surplus Payout",
            ),
            db=db,
            current_user=current_user,
        )
        return {
            "executed": True,
            "flow": "paypal_payout_disbursed",
            "paypal_result": payout,
        }

    raise HTTPException(status_code=400, detail=f"Unsupported agent PayPal action: {req.action_type}")
