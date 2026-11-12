"""
GD-IPCA AI Reasoning & PayPal Agentic Commerce Service
Supports OpenAI / Google Gemini via httpx with deterministic quantitative fallback.
Exposes PayPal Agent Toolkit compatible schemas for autonomous goal funding & payouts.
"""
from __future__ import annotations
import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import settings

logger = logging.getLogger("gdipca.ai_agent")

# OpenAI / MCP-compatible tool declarations for PayPal Agentic Commerce
PAYPAL_AGENT_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "create_paypal_funding_order",
            "description": "Create a PayPal Orders v2 payment intent to fund the investor's goal portfolio via PayPal Checkout.",
            "parameters": {
                "type": "object",
                "properties": {
                    "amount": {"type": "number", "description": "USD amount to fund via PayPal"},
                    "goal_id": {"type": "string", "description": "Target Goal AST identifier"},
                    "rationale": {"type": "string", "description": "Plain-English fiduciary reason for funding"},
                },
                "required": ["amount", "rationale"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "initiate_paypal_payout",
            "description": "Disburse excess capital above the guaranteed emergency reserve to the investor's PayPal email via PayPal Payouts v1.",
            "parameters": {
                "type": "object",
                "properties": {
                    "recipient_email": {"type": "string", "description": "Recipient PayPal email"},
                    "amount": {"type": "number", "description": "USD payout amount"},
                    "note": {"type": "string", "description": "Milestone payout note"},
                },
                "required": ["recipient_email", "amount"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "run_monte_carlo_projection",
            "description": "Evaluate 5,000-path stochastic success probability for the active Goal AST.",
            "parameters": {
                "type": "object",
                "properties": {
                    "target_valuation": {"type": "number"},
                    "time_horizon_years": {"type": "number"},
                    "risk_profile_index": {"type": "number"},
                },
                "required": ["target_valuation", "time_horizon_years"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "execute_portfolio_rebalance",
            "description": "Evaluate portfolio drift and rebalance holdings while preserving emergency cash floor.",
            "parameters": {
                "type": "object",
                "properties": {
                    "portfolio_id": {"type": "string"},
                    "auto_execute": {"type": "boolean"},
                },
                "required": ["portfolio_id"],
            },
        },
    },
]


def active_ai_provider() -> str:
    if (settings.OPENAI_API_KEY or "").strip():
        return "openai"
    if (settings.GEMINI_API_KEY or "").strip():
        return "gemini"
    return "deterministic_quant_engine"


def _call_llm_json(system_prompt: str, user_prompt: str) -> Optional[Dict[str, Any]]:
    """Call OpenAI or Gemini REST API cleanly if configured; returns parsed JSON dict or None."""
    openai_key = (settings.OPENAI_API_KEY or "").strip()
    gemini_key = (settings.GEMINI_API_KEY or "").strip()

    try:
        if openai_key:
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": settings.LLM_MODEL or "gpt-4o-mini",
                        "response_format": {"type": "json_object"},
                        "temperature": 0.2,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return json.loads(content)

        if gemini_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(
                    url,
                    json={
                        "contents": [{"parts": [{"text": f"{system_prompt}\n\nUser input:\n{user_prompt}"}]}],
                        "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
                    },
                )
            if resp.status_code == 200:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                return json.loads(text)
    except Exception as exc:
        logger.warning(f"LLM API call failed, falling back to deterministic engine: {exc}")

    return None


def extract_goal_fields_with_llm(raw_text: str) -> Optional[Dict[str, Any]]:
    """Extract structured Goal AST parameters via LLM when API key is configured."""
    if active_ai_provider() == "deterministic_quant_engine":
        return None

    system = (
        "You are a financial intent compiler. Extract a JSON object with keys: "
        "primary_objective (short title string), target_valuation (float USD), "
        "guaranteed_reserve (float USD), time_horizon_years (float), "
        "risk_profile_index (float 1.0 to 9.0), confidence_threshold (float 0.75 to 0.98)."
    )
    parsed = _call_llm_json(system, raw_text)
    if not parsed:
        return None
    try:
        return {
            "primary_objective": str(parsed.get("primary_objective") or raw_text[:80]),
            "target_valuation": max(1000.0, float(parsed["target_valuation"])),
            "guaranteed_reserve": max(0.0, float(parsed.get("guaranteed_reserve", 15000.0))),
            "time_horizon_years": max(0.5, min(50.0, float(parsed.get("time_horizon_years", 5.0)))),
            "risk_profile_index": max(1.0, min(9.5, float(parsed.get("risk_profile_index", 3.5)))),
            "confidence_threshold": max(0.70, min(0.99, float(parsed.get("confidence_threshold", 0.90)))),
        }
    except (KeyError, TypeError, ValueError):
        return None


def plan_agentic_action(
    prompt: str,
    goal: Dict[str, Any],
    portfolio: Dict[str, Any],
    success_probability: float,
    default_email: str = "demo-buyer@personal.example.com",
) -> Dict[str, Any]:
    """
    Agentic Commerce Planner: decides the optimal PayPal or Portfolio action
    based on user intent, Monte Carlo goal confidence, and emergency reserve constraints.
    """
    prompt_l = (prompt or "").lower()
    cash_bal = float(portfolio.get("cash_balance", 0.0))
    reserve = float(portfolio.get("emergency_reserve", 0.0))
    total_val = float(portfolio.get("total_valuation", 0.0))
    target_val = float(goal.get("target_valuation", 150000.0))
    conf_target = float(goal.get("confidence_threshold", 0.90))
    available_surplus = max(0.0, round(cash_bal - reserve, 2))

    # Extract explicit amount or email if mentioned
    amt_match = re.search(r"\$?\s*([\d,]+(?:\.\d+)?)\s*(k|thousand)?", prompt_l)
    explicit_amt = None
    if amt_match:
        val = float(amt_match.group(1).replace(",", ""))
        if amt_match.group(2):
            val *= 1000.0
        if val >= 10:
            explicit_amt = round(val, 2)

    email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", prompt or "")
    recipient_email = email_match.group(0) if email_match else default_email

    # Determine action type via intent + portfolio telemetry
    is_payout_intent = any(w in prompt_l for w in ("payout", "withdraw", "disburse", "send to paypal", "cash out"))
    is_rebalance_intent = any(w in prompt_l for w in ("rebalance", "drift", "trim", "hedge"))
    is_funding_intent = any(w in prompt_l for w in ("fund", "deposit", "top up", "add cash", "shortfall", "paypal", "boost"))

    action_type = "PAYPAL_FUNDING"
    tool_name = "create_paypal_funding_order"
    amount = 5000.0
    tool_args: Dict[str, Any] = {}
    safeguard_ok = True
    safeguard_note = f"Emergency reserve of ${reserve:,.2f} remains 100% ring-fenced."

    if is_payout_intent:
        action_type = "PAYPAL_PAYOUT"
        tool_name = "initiate_paypal_payout"
        requested = explicit_amt or min(2500.0, available_surplus)
        if requested > available_surplus or requested <= 0:
            safeguard_ok = False
            amount = available_surplus
            safeguard_note = (
                f"Requested payout (${requested:,.2f}) exceeds withdrawable surplus (${available_surplus:,.2f}) "
                f"above your protected ${reserve:,.2f} reserve. Capped to ${available_surplus:,.2f}."
            )
        else:
            amount = requested
            safeguard_note = f"Verified safe: ${available_surplus - amount:,.2f} cash remains above ${reserve:,.2f} reserve."
        tool_args = {
            "recipient_email": recipient_email,
            "amount": round(max(0.0, amount), 2),
            "note": f"Agentic milestone disbursement for {goal.get('primary_objective', 'Portfolio Goal')}",
        }
    elif is_rebalance_intent and not is_funding_intent:
        action_type = "REBALANCE"
        tool_name = "execute_portfolio_rebalance"
        amount = 0.0
        tool_args = {
            "portfolio_id": portfolio.get("id", ""),
            "auto_execute": True,
        }
    else:
        action_type = "PAYPAL_FUNDING"
        tool_name = "create_paypal_funding_order"
        gap = max(0.0, target_val - total_val)
        recommended = round(min(25000.0, max(1000.0, gap * 0.08)), 2)
        amount = explicit_amt if explicit_amt else recommended
        tool_args = {
            "amount": amount,
            "goal_id": goal.get("goal_id"),
            "rationale": (
                f"Fund ${amount:,.2f} via PayPal Orders v2 to raise goal readiness for "
                f"'{goal.get('primary_objective', 'Target Goal')}'."
            ),
        }

    # Optional LLM enhancement for natural-language executive reasoning
    llm_summary = None
    if active_ai_provider() != "deterministic_quant_engine":
        llm_res = _call_llm_json(
            "You are GD-IPCA, an AI fiduciary wealth & PayPal Agentic Commerce copilot. "
            "Return JSON with keys: 'reasoning' (2 concise sentences) and 'expected_impact' (1 concise sentence).",
            json.dumps({
                "user_prompt": prompt,
                "goal_objective": goal.get("primary_objective"),
                "target_valuation": target_val,
                "portfolio_valuation": total_val,
                "cash_balance": cash_bal,
                "emergency_reserve": reserve,
                "success_probability": round(success_probability, 4),
                "planned_action": action_type,
                "amount": amount,
            }),
        )
        if llm_res:
            llm_summary = llm_res

    if llm_summary and isinstance(llm_summary, dict) and llm_summary.get("reasoning"):
        reasoning = str(llm_summary["reasoning"])
        expected_impact = str(llm_summary.get("expected_impact") or "Improves goal execution certainty.")
    else:
        if action_type == "PAYPAL_PAYOUT":
            reasoning = (
                f"Evaluated cash balance (${cash_bal:,.2f}) against your ${reserve:,.2f} fiduciary reserve floor. "
                f"Prepared a PayPal Payouts v1 disbursement of ${tool_args['amount']:,.2f} to {recipient_email}."
            )
            expected_impact = "Delivers instant liquidity to your PayPal wallet without compromising reserve safety."
        elif action_type == "REBALANCE":
            reasoning = (
                f"Analyzed current holdings against target equity/bond weights for '{goal.get('primary_objective', 'Goal')}'. "
                "Prepared drift normalization trades while keeping cash reserves locked."
            )
            expected_impact = "Restores target risk profile and harvests drifted equity gains."
        else:
            prob_pct = success_probability * 100
            target_pct = conf_target * 100
            reasoning = (
                f"Monte Carlo simulation currently places '{goal.get('primary_objective', 'Goal')}' at {prob_pct:.1f}% success "
                f"(SLA target: {target_pct:.0f}%). Adding ${amount:,.2f} via PayPal Checkout strengthens your capital trajectory."
            )
            expected_impact = f"Increases portfolio liquidity to ${total_val + amount:,.2f} and accelerates target readiness."

    return {
        "ai_provider": active_ai_provider(),
        "action_type": action_type,
        "tool_call": {
            "name": tool_name,
            "arguments": tool_args,
        },
        "safeguard_passed": safeguard_ok,
        "safeguard_note": safeguard_note,
        "reasoning": reasoning,
        "expected_impact": expected_impact,
        "requires_user_approval": True,
    }
