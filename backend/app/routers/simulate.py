"""
Stochastic Monte Carlo Simulation Router
Vectorized regime-switching fat-tail engine with Redis caching and run persistence.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.monte_carlo import run_monte_carlo
from app.services.cache import cache
from app.core.security import get_current_user_optional
from app.models.entities import User, SimulationRun

router = APIRouter()


class SimulateRequest(BaseModel):
    ast_id: str = Field(..., json_schema_extra={"example": "GOAL-HOM-8921"})
    runs: int = Field(5000, ge=100, le=20000)
    time_horizon_years: float = Field(5.0, gt=0, le=50)
    target_valuation: float = Field(150000.0, gt=0)
    risk_profile_index: float = Field(3.5, ge=0, le=10)
    guaranteed_reserve: float = Field(25000.0, ge=0)
    confidence_threshold: float = Field(0.90, ge=0.5, le=0.99)


class SimulateResponse(BaseModel):
    trajectory_percentiles: List[Dict[str, float]]
    success_probability: float
    median_final_value: float
    suggested_allocation: Dict[str, float]
    equity_weight: float
    bond_weight: float
    port_mu: float
    port_sigma: float
    start_capital: float
    annual_contribution: float
    max_drawdown_p95: float
    meets_confidence: bool
    engine_meta: Dict[str, Any]
    cache_hit: bool = False


@router.post("/monte-carlo", response_model=SimulateResponse)
def monte_carlo(
    req: SimulateRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional),
):
    try:
        cache_key = f"mc:{req.ast_id}:{req.runs}:{req.time_horizon_years}:{req.target_valuation}:{req.risk_profile_index}:{req.guaranteed_reserve}"
        cached = cache.get(cache_key)
        if cached:
            cached["cache_hit"] = True
            return SimulateResponse(**cached)

        result = run_monte_carlo(
            time_horizon_years=req.time_horizon_years,
            target_valuation=req.target_valuation,
            risk_profile_index=req.risk_profile_index,
            guaranteed_reserve=req.guaranteed_reserve,
            confidence_threshold=req.confidence_threshold,
            n_paths=req.runs,
            seed=abs(hash(req.ast_id)) % (2**32),
        )
        result["cache_hit"] = False

        # Cache simulation result for 10 minutes
        cache.set(cache_key, result, ttl=600)

        # Persist simulation run if authenticated
        if current_user:
            try:
                run = SimulationRun(
                    goal_id=req.ast_id,
                    user_id=current_user.id,
                    n_paths=req.runs,
                    success_probability=result["success_probability"],
                    median_final_value=result["median_final_value"],
                    equity_weight=result["equity_weight"],
                    bond_weight=result["bond_weight"],
                    port_mu=result["port_mu"],
                    port_sigma=result["port_sigma"],
                    max_drawdown_p95=result["max_drawdown_p95"],
                )
                run.trajectory_summary = result["trajectory_percentiles"]
                run.allocation = result["suggested_allocation"]
                db.add(run)
                db.commit()
            except Exception:
                db.rollback()

        return SimulateResponse(**result)
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=f"Market data missing: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
