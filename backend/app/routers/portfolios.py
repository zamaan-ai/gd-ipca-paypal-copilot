"""
Portfolio Management & Transactions Router
Provides portfolio creation, persistence, holdings management, deposits/withdrawals,
and direct trade execution with user-level data isolation.
"""
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.core.security import get_current_user
from app.models.entities import User, Portfolio, Holding, Transaction, OrderExecution, IntentGoal
from app.services.broker import broker_service
from app.services.market_data import market_data_service

router = APIRouter()


class HoldingResponse(BaseModel):
    id: str
    symbol: str
    asset_name: Optional[str]
    asset_class: str
    quantity: float
    cost_basis: float
    current_price: float
    market_value: float
    allocation_pct: float


class PortfolioDetailResponse(BaseModel):
    id: str
    user_id: str
    goal_id: Optional[str]
    name: str
    total_valuation: float
    cash_balance: float
    emergency_reserve: float
    target_equity_pct: float
    target_bond_pct: float
    status: str
    holdings: List[HoldingResponse]
    asset_class_breakdown: Dict[str, float]


class PortfolioSummaryResponse(BaseModel):
    id: str
    name: str
    goal_id: Optional[str]
    total_valuation: float
    cash_balance: float
    emergency_reserve: float
    status: str


class CreatePortfolioRequest(BaseModel):
    name: str = Field(..., min_length=2)
    goal_id: Optional[str] = None
    initial_deposit: float = Field(10000.0, ge=0)
    emergency_reserve: float = Field(0.0, ge=0)
    target_equity_pct: float = Field(0.60, ge=0, le=1.0)


class CashFlowRequest(BaseModel):
    amount: float = Field(..., gt=0)
    note: Optional[str] = None


class TradeRequest(BaseModel):
    symbol: str = Field(..., json_schema_extra={"example": "VTI"})
    side: str = Field(..., json_schema_extra={"example": "BUY"})  # "BUY" | "SELL"
    quantity: float = Field(..., gt=0)
    order_type: str = Field("MARKET")


def _get_user_portfolio_or_404(db: Session, user: User, portfolio_id: str) -> Portfolio:
    query = db.query(Portfolio).filter(Portfolio.id == portfolio_id)
    if user.role != "admin":
        query = query.filter(Portfolio.user_id == user.id)
    p = query.first()
    if not p:
        raise HTTPException(status_code=404, detail="Portfolio not found or access denied")
    return p


@router.get("", response_model=List[PortfolioSummaryResponse])
def list_portfolios(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    portfolios = db.query(Portfolio).filter(Portfolio.user_id == current_user.id).all()
    # Refresh valuations
    for p in portfolios:
        broker_service._recompute_portfolio_valuation(db, p)
    db.commit()

    return [
        PortfolioSummaryResponse(
            id=p.id,
            name=p.name,
            goal_id=p.goal_id,
            total_valuation=p.total_valuation,
            cash_balance=p.cash_balance,
            emergency_reserve=p.emergency_reserve,
            status=p.status,
        )
        for p in portfolios
    ]


@router.post("", response_model=PortfolioDetailResponse, status_code=status.HTTP_201_CREATED)
def create_portfolio(
    req: CreatePortfolioRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    reserve = req.emergency_reserve
    if req.goal_id:
        goal = db.query(IntentGoal).filter(
            IntentGoal.goal_id == req.goal_id,
            IntentGoal.user_id == current_user.id
        ).first()
        if goal and reserve == 0:
            reserve = goal.guaranteed_reserve

    portfolio = Portfolio(
        user_id=current_user.id,
        goal_id=req.goal_id,
        name=req.name,
        cash_balance=req.initial_deposit,
        emergency_reserve=reserve,
        target_equity_pct=req.target_equity_pct,
        target_bond_pct=round(1.0 - req.target_equity_pct, 4),
        total_valuation=req.initial_deposit,
        status="active",
    )
    db.add(portfolio)
    db.flush()

    if req.initial_deposit > 0:
        tx = Transaction(
            portfolio_id=portfolio.id,
            symbol=None,
            type="DEPOSIT",
            quantity=1.0,
            price=req.initial_deposit,
            amount=req.initial_deposit,
            plain_english_note=f"Initial capital deposit of ${req.initial_deposit:,.2f}",
        )
        db.add(tx)

    db.commit()
    db.refresh(portfolio)

    return get_portfolio_detail(portfolio.id, db=db, current_user=current_user)


@router.get("/{portfolio_id}", response_model=PortfolioDetailResponse)
def get_portfolio_detail(
    portfolio_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_user_portfolio_or_404(db, current_user, portfolio_id)
    broker_service._recompute_portfolio_valuation(db, p)
    db.commit()
    db.refresh(p)

    holdings_list = []
    class_map = {}
    total_val = p.total_valuation or 1.0

    for h in p.holdings:
        holdings_list.append(
            HoldingResponse(
                id=h.id,
                symbol=h.symbol,
                asset_name=h.asset_name,
                asset_class=h.asset_class,
                quantity=h.quantity,
                cost_basis=h.cost_basis,
                current_price=h.current_price,
                market_value=h.market_value,
                allocation_pct=round(h.market_value / total_val, 4),
            )
        )
        class_map[h.asset_class] = class_map.get(h.asset_class, 0.0) + h.market_value

    class_map["CASH"] = class_map.get("CASH", 0.0) + p.cash_balance
    class_pcts = {k: round(v / total_val, 4) for k, v in class_map.items()}

    return PortfolioDetailResponse(
        id=p.id,
        user_id=p.user_id,
        goal_id=p.goal_id,
        name=p.name,
        total_valuation=p.total_valuation,
        cash_balance=p.cash_balance,
        emergency_reserve=p.emergency_reserve,
        target_equity_pct=p.target_equity_pct,
        target_bond_pct=p.target_bond_pct,
        status=p.status,
        holdings=holdings_list,
        asset_class_breakdown=class_pcts,
    )


@router.post("/{portfolio_id}/deposit", response_model=PortfolioDetailResponse)
def deposit_cash(
    portfolio_id: str,
    req: CashFlowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_user_portfolio_or_404(db, current_user, portfolio_id)
    p.cash_balance = round(p.cash_balance + req.amount, 2)
    p.total_valuation = round(p.total_valuation + req.amount, 2)

    tx = Transaction(
        portfolio_id=p.id,
        symbol=None,
        type="DEPOSIT",
        quantity=1.0,
        price=req.amount,
        amount=req.amount,
        plain_english_note=req.note or f"Cash deposit of ${req.amount:,.2f}",
    )
    db.add(tx)
    db.commit()
    return get_portfolio_detail(portfolio_id, db=db, current_user=current_user)


@router.post("/{portfolio_id}/withdraw", response_model=PortfolioDetailResponse)
def withdraw_cash(
    portfolio_id: str,
    req: CashFlowRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_user_portfolio_or_404(db, current_user, portfolio_id)
    available = p.cash_balance - p.emergency_reserve
    if req.amount > available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Withdrawal denied: Protected emergency reserve of ${p.emergency_reserve:,.2f} "
                f"must be maintained. Maximum available to withdraw is ${max(0.0, available):,.2f}."
            ),
        )

    p.cash_balance = round(p.cash_balance - req.amount, 2)
    p.total_valuation = round(p.total_valuation - req.amount, 2)

    tx = Transaction(
        portfolio_id=p.id,
        symbol=None,
        type="WITHDRAWAL",
        quantity=1.0,
        price=req.amount,
        amount=req.amount,
        plain_english_note=req.note or f"Cash withdrawal of ${req.amount:,.2f}",
    )
    db.add(tx)
    db.commit()
    return get_portfolio_detail(portfolio_id, db=db, current_user=current_user)


@router.post("/{portfolio_id}/trade", response_model=dict)
def place_trade(
    portfolio_id: str,
    req: TradeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_user_portfolio_or_404(db, current_user, portfolio_id)
    try:
        order = broker_service.execute_order(
            db=db,
            portfolio=p,
            symbol=req.symbol,
            side=req.side,
            quantity=req.quantity,
            order_type=req.order_type,
        )
        return {
            "order_id": order.id,
            "broker_order_id": order.broker_order_id,
            "status": order.status,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "executed_price": order.executed_price,
            "plain_english_status": order.plain_english_status,
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/{portfolio_id}/transactions", response_model=List[dict])
def get_transactions(
    portfolio_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_user_portfolio_or_404(db, current_user, portfolio_id)
    txs = (
        db.query(Transaction)
        .filter(Transaction.portfolio_id == p.id)
        .order_by(Transaction.timestamp.desc())
        .all()
    )
    return [
        {
            "id": tx.id,
            "symbol": tx.symbol,
            "type": tx.type,
            "quantity": tx.quantity,
            "price": tx.price,
            "amount": tx.amount,
            "fee": tx.fee,
            "plain_english_note": tx.plain_english_note,
            "timestamp": tx.timestamp.isoformat(),
        }
        for tx in txs
    ]


@router.get("/{portfolio_id}/orders", response_model=List[dict])
def get_orders(
    portfolio_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    p = _get_user_portfolio_or_404(db, current_user, portfolio_id)
    orders = (
        db.query(OrderExecution)
        .filter(OrderExecution.portfolio_id == p.id)
        .order_by(OrderExecution.created_at.desc())
        .all()
    )
    return [
        {
            "id": o.id,
            "broker_order_id": o.broker_order_id,
            "symbol": o.symbol,
            "side": o.side,
            "quantity": o.quantity,
            "requested_price": o.requested_price,
            "executed_price": o.executed_price,
            "status": o.status,
            "plain_english_status": o.plain_english_status,
            "created_at": o.created_at.isoformat(),
        }
        for o in orders
    ]
