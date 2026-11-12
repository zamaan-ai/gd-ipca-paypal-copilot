"""
GD-IPCA PayPal Developer Platform Router
Handles PayPal Orders v2 (Goal Funding Deposits), Captures, Payouts v1 (Disbursements),
and persistent PayPal settlement ledger synchronization.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import get_current_user
from app.db.session import get_db
from app.models.entities import PayPalPaymentRecord, Portfolio, Transaction, User
from app.routers.portfolios import _get_user_portfolio_or_404, get_portfolio_detail
from app.services.paypal_service import paypal_service

router = APIRouter()


class PayPalCreateOrderRequest(BaseModel):
    portfolio_id: str
    amount: float = Field(..., gt=0, le=1_000_000)
    currency: str = Field("USD", min_length=3, max_length=3)
    goal_id: Optional[str] = None
    description: Optional[str] = None
    ai_rationale: Optional[str] = None


class PayPalCreatePayoutRequest(BaseModel):
    portfolio_id: str
    recipient_email: EmailStr
    amount: float = Field(..., gt=0, le=1_000_000)
    currency: str = Field("USD", min_length=3, max_length=3)
    goal_id: Optional[str] = None
    note: Optional[str] = None
    ai_rationale: Optional[str] = None


@router.get("/status")
def paypal_status():
    return {
        "provider": "PayPal Developer Platform",
        "mode": paypal_service.current_mode(),
        "live_sandbox_configured": paypal_service.is_live_configured(),
        "base_url": settings.PAYPAL_BASE_URL,
        "supported_apis": ["Orders v2 (Checkout/Capture)", "Payouts v1", "Agentic Commerce Toolkit"],
    }


@router.post("/orders/create")
def create_paypal_order(
    req: PayPalCreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    portfolio = _get_user_portfolio_or_404(db, current_user, req.portfolio_id)
    desc = req.description or f"GD-IPCA Goal Funding for {portfolio.name}"

    try:
        order = paypal_service.create_order(
            amount=req.amount,
            currency=req.currency.upper(),
            description=desc,
            reference_id=req.goal_id or portfolio.goal_id or portfolio.id,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    record = PayPalPaymentRecord(
        user_id=current_user.id,
        portfolio_id=portfolio.id,
        goal_id=req.goal_id or portfolio.goal_id,
        payment_type="DEPOSIT_ORDER",
        paypal_order_id=order["id"],
        amount=order["amount"],
        currency=order["currency"],
        status=order["status"],
        mode=order["mode"],
        approval_url=order.get("approval_url"),
        ai_rationale=req.ai_rationale,
    )
    record.raw_response = order.get("raw", {})
    db.add(record)
    db.commit()
    db.refresh(record)

    return {
        "record_id": record.id,
        "paypal_order_id": record.paypal_order_id,
        "status": record.status,
        "mode": record.mode,
        "amount": record.amount,
        "currency": record.currency,
        "approval_url": record.approval_url,
    }


@router.post("/orders/{order_id}/capture")
def capture_paypal_order(
    order_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    record = (
        db.query(PayPalPaymentRecord)
        .filter(PayPalPaymentRecord.paypal_order_id == order_id)
        .first()
    )
    if not record:
        raise HTTPException(status_code=404, detail="PayPal order record not found")
    if record.user_id != current_user.id and current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Access denied for PayPal order")

    portfolio = _get_user_portfolio_or_404(db, current_user, record.portfolio_id)

    if record.status == "COMPLETED":
        return {
            "record_id": record.id,
            "paypal_order_id": record.paypal_order_id,
            "paypal_capture_id": record.paypal_capture_id,
            "status": "COMPLETED",
            "mode": record.mode,
            "amount": record.amount,
            "already_captured": True,
            "portfolio": get_portfolio_detail(portfolio.id, db=db, current_user=current_user),
        }

    try:
        cap = paypal_service.capture_order(order_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    record.status = cap["status"]
    record.paypal_capture_id = cap.get("capture_id")
    record.raw_response = cap.get("raw", {})

    # Credit portfolio cash & valuation atomically
    portfolio.cash_balance = round(portfolio.cash_balance + record.amount, 2)
    portfolio.total_valuation = round(portfolio.total_valuation + record.amount, 2)

    tx = Transaction(
        portfolio_id=portfolio.id,
        symbol=None,
        type="PAYPAL_DEPOSIT",
        quantity=1.0,
        price=record.amount,
        amount=record.amount,
        plain_english_note=(
            f"PayPal Checkout Capture ({record.paypal_capture_id or order_id}) · "
            f"${record.amount:,.2f} {record.currency} [{record.mode}]"
        ),
    )
    db.add(tx)
    db.commit()
    db.refresh(record)

    return {
        "record_id": record.id,
        "paypal_order_id": record.paypal_order_id,
        "paypal_capture_id": record.paypal_capture_id,
        "status": record.status,
        "mode": record.mode,
        "amount": record.amount,
        "already_captured": False,
        "portfolio": get_portfolio_detail(portfolio.id, db=db, current_user=current_user),
    }


@router.post("/payouts/create")
def create_paypal_payout(
    req: PayPalCreatePayoutRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    portfolio = _get_user_portfolio_or_404(db, current_user, req.portfolio_id)

    # Enforce fiduciary ring-fenced emergency reserve safeguard
    available = round(portfolio.cash_balance - portfolio.emergency_reserve, 2)
    if req.amount > available:
        raise HTTPException(
            status_code=400,
            detail=(
                f"PayPal payout denied: Protected emergency reserve of ${portfolio.emergency_reserve:,.2f} "
                f"must remain untouched. Maximum available to disburse is ${max(0.0, available):,.2f}."
            ),
        )

    note = req.note or f"GD-IPCA Goal Disbursement from {portfolio.name}"
    try:
        payout = paypal_service.create_payout(
            recipient_email=req.recipient_email,
            amount=req.amount,
            currency=req.currency.upper(),
            note=note,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    portfolio.cash_balance = round(portfolio.cash_balance - payout["amount"], 2)
    portfolio.total_valuation = round(portfolio.total_valuation - payout["amount"], 2)

    record = PayPalPaymentRecord(
        user_id=current_user.id,
        portfolio_id=portfolio.id,
        goal_id=req.goal_id or portfolio.goal_id,
        payment_type="PAYOUT",
        paypal_payout_batch_id=payout["payout_batch_id"],
        recipient_email=req.recipient_email,
        amount=payout["amount"],
        currency=payout["currency"],
        status=payout["status"],
        mode=payout["mode"],
        ai_rationale=req.ai_rationale,
    )
    record.raw_response = payout.get("raw", {})
    db.add(record)

    tx = Transaction(
        portfolio_id=portfolio.id,
        symbol=None,
        type="PAYPAL_PAYOUT",
        quantity=1.0,
        price=payout["amount"],
        amount=payout["amount"],
        plain_english_note=(
            f"PayPal Payout ({payout['payout_batch_id']}) to {req.recipient_email} · "
            f"${payout['amount']:,.2f} {payout['currency']} [{payout['mode']}]"
        ),
    )
    db.add(tx)
    db.commit()
    db.refresh(record)

    return {
        "record_id": record.id,
        "paypal_payout_batch_id": record.paypal_payout_batch_id,
        "recipient_email": record.recipient_email,
        "status": record.status,
        "mode": record.mode,
        "amount": record.amount,
        "currency": record.currency,
        "portfolio": get_portfolio_detail(portfolio.id, db=db, current_user=current_user),
    }


@router.get("/records", response_model=List[dict])
def list_paypal_records(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    rows = (
        db.query(PayPalPaymentRecord)
        .filter(PayPalPaymentRecord.user_id == current_user.id)
        .order_by(PayPalPaymentRecord.created_at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "portfolio_id": r.portfolio_id,
            "goal_id": r.goal_id,
            "payment_type": r.payment_type,
            "paypal_order_id": r.paypal_order_id,
            "paypal_capture_id": r.paypal_capture_id,
            "paypal_payout_batch_id": r.paypal_payout_batch_id,
            "recipient_email": r.recipient_email,
            "amount": r.amount,
            "currency": r.currency,
            "status": r.status,
            "mode": r.mode,
            "approval_url": r.approval_url,
            "ai_rationale": r.ai_rationale,
            "created_at": r.created_at.isoformat(),
        }
        for r in rows
    ]
