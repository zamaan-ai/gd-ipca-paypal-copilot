"""
GD-IPCA Intent Compiler Router
Compiles natural language into deterministic Intent ASTs,
persists goals with user-level data isolation, and provides sample presets.
"""
from typing import Optional, List, Dict, Any
import hashlib
import re
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.config import get_sample_intents
from app.core.security import get_current_user_optional, get_current_user
from app.models.entities import User, IntentGoal, Portfolio
from app.services.ai_agent import extract_goal_fields_with_llm

router = APIRouter()


class UtilityParams(BaseModel):
    risk_aversion_gamma: float = 2.4
    inflation_adjustment_rate: float = 0.028


class Milestone(BaseModel):
    year: int
    label: str
    target_progress_pct: float


class IntentAST(BaseModel):
    goal_id: str
    primary_objective: str
    target_valuation: float
    guaranteed_reserve: float
    time_horizon_years: float
    risk_profile_index: float
    liquidity_constraint: str = "STRICT_RESERVE"
    confidence_threshold: float = 0.90
    utility_function_params: UtilityParams
    milestones: Optional[List[Milestone]] = None
    preferred_asset_classes: Optional[List[str]] = None
    excluded_assets: Optional[List[str]] = None
    tax_status: Optional[str] = "taxable_brokerage"
    raw_text: Optional[str] = None


class CompileRequest(BaseModel):
    raw_text: str = Field(..., min_length=8)
    save_goal: bool = False


class CompileResponse(BaseModel):
    ast: IntentAST
    utility_equations: Dict[str, Any]
    message: str = "Intent successfully compiled into deterministic AST"
    matched_seed: Optional[str] = None
    saved_to_db: bool = False


def _parse_amounts(text: str) -> list[float]:
    text_l = text.lower()
    amounts = []
    for m in re.finditer(r'\$?\s*([\d,]+(?:\.\d+)?)\s*(k|m|million|thousand)?', text_l):
        val = float(m.group(1).replace(",", ""))
        suf = (m.group(2) or "").lower()
        if suf in ("m", "million"):
            val *= 1_000_000
        elif suf in ("k", "thousand"):
            val *= 1_000
        if val >= 100:
            amounts.append(val)
    return amounts


def parse_raw_text(text: str) -> IntentAST:
    llm_fields = extract_goal_fields_with_llm(text)
    if llm_fields:
        target = llm_fields["target_valuation"]
        reserve = llm_fields["guaranteed_reserve"]
        years = llm_fields["time_horizon_years"]
        risk = llm_fields["risk_profile_index"]
        conf = llm_fields["confidence_threshold"]
        objective = llm_fields["primary_objective"]
    else:
        text_l = text.lower()
        amounts = _parse_amounts(text)

        target = max(amounts) if amounts else 100_000.0
        reserve = min(amounts) if len(amounts) > 1 else round(target * 0.15, 2)

        year_m = re.search(r'(\d+(?:\.\d+)?)\s*(?:year|yr)s?', text_l)
        years = float(year_m.group(1)) if year_m else 5.0

        risk = 3.5
        if any(w in text_l for w in ("low risk", "safe", "conservative", "careful", "low volatility")):
            risk = 2.2
        elif any(w in text_l for w in ("aggressive", "growth", "high risk", "high volatility")):
            risk = 5.5
        elif any(w in text_l for w in ("moderate", "balanced")):
            risk = 3.5

        conf = 0.90
        if "high confidence" in text_l or "very sure" in text_l:
            conf = 0.95
        elif "flexible" in text_l:
            conf = 0.80

        objective = text.strip()[:90] + ("…" if len(text) > 90 else "")

    goal_id = "GOAL-" + hashlib.md5(text.encode()).hexdigest()[:8].upper()

    milestones = []
    for frac, label in [(0.2, "Early Checkpoint"), (0.5, "Midpoint"), (1.0, "Target Ready")]:
        y = max(1, int(round(years * frac)))
        milestones.append(Milestone(year=y, label=label, target_progress_pct=round(frac * 100)))

    return IntentAST(
        goal_id=goal_id,
        primary_objective=objective,
        target_valuation=target,
        guaranteed_reserve=reserve,
        time_horizon_years=years,
        risk_profile_index=risk,
        liquidity_constraint="STRICT_RESERVE",
        confidence_threshold=conf,
        utility_function_params=UtilityParams(),
        milestones=milestones,
        raw_text=text,
    )


@router.post("/compile", response_model=CompileResponse)
def compile_intent(
    payload: CompileRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    try:
        seeds = get_sample_intents()
        matched = None
        for s in seeds:
            if s.get("raw_text", "").strip() == payload.raw_text.strip():
                matched = s
                break

        if matched:
            ast = IntentAST(
                goal_id=matched["goal_id"],
                primary_objective=matched["primary_objective"],
                target_valuation=matched["target_valuation"],
                guaranteed_reserve=matched["guaranteed_reserve"],
                time_horizon_years=matched["time_horizon_years"],
                risk_profile_index=matched["risk_profile_index"],
                liquidity_constraint=matched.get("liquidity_constraint", "STRICT_RESERVE"),
                confidence_threshold=matched.get("confidence_threshold", 0.90),
                utility_function_params=UtilityParams(**matched.get("utility_function_params", {})),
                milestones=[Milestone(**m) for m in matched.get("milestones", [])],
                preferred_asset_classes=matched.get("preferred_asset_classes"),
                excluded_assets=matched.get("excluded_assets"),
                tax_status=matched.get("tax_status"),
                raw_text=matched.get("raw_text"),
            )
            matched_id = matched["goal_id"]
        else:
            ast = parse_raw_text(payload.raw_text)
            matched_id = None

        saved = False
        if payload.save_goal and current_user:
            existing = db.query(IntentGoal).filter(
                IntentGoal.goal_id == ast.goal_id,
                IntentGoal.user_id == current_user.id,
            ).first()
            if not existing:
                goal_entity = IntentGoal(
                    goal_id=ast.goal_id,
                    user_id=current_user.id,
                    primary_objective=ast.primary_objective,
                    raw_text=ast.raw_text,
                    target_valuation=ast.target_valuation,
                    guaranteed_reserve=ast.guaranteed_reserve,
                    time_horizon_years=ast.time_horizon_years,
                    risk_profile_index=ast.risk_profile_index,
                    liquidity_constraint=ast.liquidity_constraint,
                    confidence_threshold=ast.confidence_threshold,
                    tax_status=ast.tax_status,
                )
                goal_entity.utility_params = ast.utility_function_params.model_dump()
                goal_entity.milestones = [m.model_dump() for m in ast.milestones] if ast.milestones else []
                db.add(goal_entity)
                db.commit()
                saved = True

        return CompileResponse(
            ast=ast,
            utility_equations={
                "objective": "max P(Σ W̃_t ≥ Target_Valuation)",
                "constraints": [
                    "Σ w_i = 1, w_i ≥ 0",
                    f"P(MaxDrawdown > limit) ≤ {1 - ast.confidence_threshold:.2f}",
                    f"Liquidity_Reserve ≥ {ast.guaranteed_reserve}",
                ],
            },
            matched_seed=matched_id,
            saved_to_db=saved,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/seeds")
def list_seed_intents():
    return get_sample_intents()


@router.get("/goals", response_model=List[IntentAST])
def list_user_goals(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    goals = db.query(IntentGoal).filter(IntentGoal.user_id == current_user.id).all()
    result = []
    for g in goals:
        result.append(
            IntentAST(
                goal_id=g.goal_id,
                primary_objective=g.primary_objective,
                target_valuation=g.target_valuation,
                guaranteed_reserve=g.guaranteed_reserve,
                time_horizon_years=g.time_horizon_years,
                risk_profile_index=g.risk_profile_index,
                liquidity_constraint=g.liquidity_constraint,
                confidence_threshold=g.confidence_threshold,
                utility_function_params=UtilityParams(**g.utility_params),
                milestones=[Milestone(**m) for m in g.milestones],
                preferred_asset_classes=g.preferred_asset_classes,
                excluded_assets=g.excluded_assets,
                tax_status=g.tax_status,
                raw_text=g.raw_text,
            )
        )
    return result
