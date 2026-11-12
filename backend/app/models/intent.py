from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

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

class CompileRequest(BaseModel):
    raw_text: str = Field(..., min_length=10, example="I want to save $150,000 for a house down payment in 5 years while keeping $25,000 ready for emergencies.")

class CompileResponse(BaseModel):
    ast: IntentAST
    utility_equations: Dict[str, Any]
    message: str = "Intent successfully compiled into deterministic AST"
