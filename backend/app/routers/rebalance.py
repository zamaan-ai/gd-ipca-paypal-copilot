"""
End-to-End Milestone & Drift Rebalancing Engine
Calculates target drift, preserves emergency reserve, generates plain-English explanations,
and automatically routes rebalance orders through the broker execution engine.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.entities import User, Portfolio, Holding, RebalanceEvent, IntentGoal, OrderExecution
from app.services.market_data import market_data_service
from app.services.broker import broker_service

router = APIRouter()


class RebalanceRequest(BaseModel):
    portfolio_id: Optional[str] = None
    goal_id: Optional[str] = None
    threshold_pct: float = Field(0.02, ge=0.005, le=0.10)
    auto_execute: bool = False


class RebalanceOrderPlan(BaseModel):
    symbol: str
    asset_name: str
    asset_class: str
    side: str  # "BUY" | "SELL"
    quantity: float
    estimated_price: float
    estimated_total: float
    plain_english_reason: str


class RebalanceResponse(BaseModel):
    rebalance_event_id: str
    portfolio_id: str
    goal_id: Optional[str]
    status: str  # "completed" | "preview"
    drift_detected: float
    plain_english_explanation: str
    target_allocation: Dict[str, float]
    current_allocation: Dict[str, float]
    orders: List[RebalanceOrderPlan]
    executed: bool


@router.post("/execute", response_model=RebalanceResponse)
def execute_rebalance(
    req: RebalanceRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Locate portfolio
    portfolio = None
    if req.portfolio_id:
        portfolio = db.query(Portfolio).filter(
            Portfolio.id == req.portfolio_id,
            Portfolio.user_id == current_user.id
        ).first()
    elif req.goal_id:
        portfolio = db.query(Portfolio).filter(
            Portfolio.goal_id == req.goal_id,
            Portfolio.user_id == current_user.id
        ).first()
    else:
        # Pick user's first portfolio
        portfolio = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).first()

    if not portfolio:
        raise HTTPException(status_code=404, detail="No active portfolio found for rebalance")

    # Refresh valuations
    broker_service._recompute_portfolio_valuation(db, portfolio)
    db.commit()

    total_val = portfolio.total_valuation
    if total_val <= 0:
        raise HTTPException(status_code=400, detail="Cannot rebalance empty portfolio")

    # Target allocations
    target_equity = portfolio.target_equity_pct or 0.60
    target_bond = portfolio.target_bond_pct or 0.40

    # Calculate current allocation
    current_equity_val = sum(
        h.market_value for h in portfolio.holdings if h.asset_class in ("US_EQUITY", "INTL_EQUITY")
    )
    current_bond_val = sum(
        h.market_value for h in portfolio.holdings if h.asset_class in ("US_BONDS", "TIPS", "INTL_BONDS")
    )
    cash_val = portfolio.cash_balance

    current_equity_pct = current_equity_val / total_val
    current_bond_pct = current_bond_val / total_val
    current_cash_pct = cash_val / total_val

    # Detect drift
    equity_drift = current_equity_pct - target_equity
    bond_drift = current_bond_pct - target_bond
    max_drift = max(abs(equity_drift), abs(bond_drift))

    proposed_orders = []
    plain_english = []

    # Map core target ETF proxies
    # Equity proxy: VTI (US) + VXUS (Int'l)
    # Bond proxy: BND (US Bond) + VTIP (TIPS)
    # Cash proxy: SGOV
    if abs(equity_drift) > req.threshold_pct or abs(bond_drift) > req.threshold_pct:
        plain_english.append(
            f"Your portfolio allocation has drifted by {max_drift * 100:.1f}%. "
            f"Current equities stand at {current_equity_pct * 100:.1f}% (target: {target_equity * 100:.1f}%)."
        )

        # If equities too high, sell some equity and buy bonds
        if equity_drift > req.threshold_pct:
            dollar_to_shift = round(equity_drift * total_val, 2)
            # Find an equity holding to trim
            eq_holding = next(
                (h for h in portfolio.holdings if h.asset_class in ("US_EQUITY", "INTL_EQUITY")), None
            )
            if eq_holding and eq_holding.market_value > dollar_to_shift:
                sell_sym = eq_holding.symbol
                sell_price = market_data_service.get_latest_price(sell_sym)["price"]
                sell_qty = round(dollar_to_shift / sell_price, 4)
                proposed_orders.append(
                    RebalanceOrderPlan(
                        symbol=sell_sym,
                        asset_name=eq_holding.asset_name or sell_sym,
                        asset_class=eq_holding.asset_class,
                        side="SELL",
                        quantity=sell_qty,
                        estimated_price=sell_price,
                        estimated_total=round(sell_qty * sell_price, 2),
                        plain_english_reason=f"Trim {sell_qty} shares of {sell_sym} to harvest equity gains.",
                    )
                )

            # Buy bonds
            buy_sym = "BND"
            buy_price = market_data_service.get_latest_price(buy_sym)["price"]
            buy_qty = round(dollar_to_shift / buy_price, 4)
            proposed_orders.append(
                RebalanceOrderPlan(
                    symbol=buy_sym,
                    asset_name="Vanguard Total Bond Market ETF",
                    asset_class="US_BONDS",
                    side="BUY",
                    quantity=buy_qty,
                    estimated_price=buy_price,
                    estimated_total=round(buy_qty * buy_price, 2),
                    plain_english_reason=f"Purchase {buy_qty} shares of {buy_sym} to lock in bond yields and steady volatility.",
                )
            )

        # If equities too low, buy equity
        elif equity_drift < -req.threshold_pct:
            dollar_to_shift = round(abs(equity_drift) * total_val, 2)
            buy_sym = "VTI"
            buy_price = market_data_service.get_latest_price(buy_sym)["price"]
            buy_qty = round(dollar_to_shift / buy_price, 4)
            proposed_orders.append(
                RebalanceOrderPlan(
                    symbol=buy_sym,
                    asset_name="Vanguard Total Stock Market ETF",
                    asset_class="US_EQUITY",
                    side="BUY",
                    quantity=buy_qty,
                    estimated_price=buy_price,
                    estimated_total=round(buy_qty * buy_price, 2),
                    plain_english_reason=f"Add {buy_qty} shares of {buy_sym} to restore your target equity growth trajectory.",
                )
            )
    else:
        plain_english.append(
            f"Your portfolio is in excellent alignment! Drift is only {max_drift * 100:.1f}%, well within the "
            f"{req.threshold_pct * 100:.1f}% tolerance band. No adjustments are needed."
        )

    # Protect emergency reserve note
    plain_english.append(
        f"Your guaranteed emergency reserve of ${portfolio.emergency_reserve:,.2f} remains 100% protected in cash equivalents."
    )
    explanation_text = " ".join(plain_english)

    # Record RebalanceEvent in DB
    rebalance_event = RebalanceEvent(
        goal_id=portfolio.goal_id,
        portfolio_id=portfolio.id,
        user_id=current_user.id,
        trigger_reason="Drift Threshold Check" if max_drift > req.threshold_pct else "Periodic Alignment",
        drift_detected=round(max_drift, 4),
        plain_english_explanation=explanation_text,
        status="completed" if req.auto_execute else "preview",
    )
    rebalance_event.target_allocation = {"equity": target_equity, "fixed_income": target_bond}
    rebalance_event.proposed_orders = [o.model_dump() for o in proposed_orders]
    db.add(rebalance_event)
    db.flush()

    # If auto_execute requested, execute sell orders first then buys
    if req.auto_execute and proposed_orders:
        sells = [o for o in proposed_orders if o.side == "SELL"]
        buys = [o for o in proposed_orders if o.side == "BUY"]
        for o in sells:
            broker_service.execute_order(
                db=db,
                portfolio=portfolio,
                symbol=o.symbol,
                side="SELL",
                quantity=o.quantity,
                rebalance_event_id=rebalance_event.id,
                custom_note=o.plain_english_reason,
            )
        for o in buys:
            broker_service.execute_order(
                db=db,
                portfolio=portfolio,
                symbol=o.symbol,
                side="BUY",
                quantity=o.quantity,
                rebalance_event_id=rebalance_event.id,
                custom_note=o.plain_english_reason,
            )

    db.commit()

    return RebalanceResponse(
        rebalance_event_id=rebalance_event.id,
        portfolio_id=portfolio.id,
        goal_id=portfolio.goal_id,
        status="completed" if req.auto_execute else "preview",
        drift_detected=round(max_drift, 4),
        plain_english_explanation=explanation_text,
        target_allocation={"equity": target_equity, "fixed_income": target_bond},
        current_allocation={
            "equity": round(current_equity_pct, 4),
            "fixed_income": round(current_bond_pct, 4),
            "cash": round(current_cash_pct, 4),
        },
        orders=proposed_orders,
        executed=req.auto_execute,
    )
