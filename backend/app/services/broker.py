"""
GD-IPCA Broker Integration & Order Matching Engine
Supports simulated paper broker and external broker APIs.
Tracks order status and automatically synchronizes executed trades into the database ledger.
"""
from datetime import datetime, timezone
import uuid
import logging
from typing import Dict, Any, Optional
from sqlalchemy.orm import Session

from app.core.config import settings
from app.services.market_data import market_data_service
from app.models.entities import Portfolio, Holding, Transaction, OrderExecution

logger = logging.getLogger("gdipca.broker")


class BrokerService:
    def __init__(self):
        self.mode = settings.BROKER_MODE

    def execute_order(
        self,
        db: Session,
        portfolio: Portfolio,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str = "MARKET",
        rebalance_event_id: Optional[str] = None,
        custom_note: Optional[str] = None,
    ) -> OrderExecution:
        sym = symbol.upper()
        side_norm = side.upper()
        if side_norm not in ("BUY", "SELL"):
            raise ValueError(f"Invalid order side: {side}")
        if quantity <= 0:
            raise ValueError("Order quantity must be positive")

        # 1. Fetch live market price
        quote = market_data_service.get_latest_price(sym, db=db)
        fill_price = quote["price"]
        total_cost = round(quantity * fill_price, 2)
        fee = 0.0  # Zero-commission ETF model

        # 2. Check capital/holdings constraints
        holding = (
            db.query(Holding)
            .filter(Holding.portfolio_id == portfolio.id, Holding.symbol == sym)
            .first()
        )

        broker_order_id = f"BRK-{uuid.uuid4().hex[:10].upper()}"

        if side_norm == "BUY":
            available_cash = portfolio.cash_balance
            if available_cash < total_cost:
                # Reject order due to insufficient funds
                order = OrderExecution(
                    portfolio_id=portfolio.id,
                    rebalance_event_id=rebalance_event_id,
                    symbol=sym,
                    side="BUY",
                    order_type=order_type,
                    quantity=quantity,
                    requested_price=fill_price,
                    status="REJECTED",
                    broker_order_id=broker_order_id,
                    plain_english_status=(
                        f"Order rejected: Available cash (${available_cash:,.2f}) is below "
                        f"the required order total (${total_cost:,.2f})."
                    ),
                )
                db.add(order)
                db.commit()
                db.refresh(order)
                return order

            # Deduct cash
            portfolio.cash_balance = round(portfolio.cash_balance - total_cost, 2)

            # Update or create holding
            if not holding:
                holding = Holding(
                    portfolio_id=portfolio.id,
                    symbol=sym,
                    asset_name=quote["asset_name"],
                    asset_class=quote["asset_class"],
                    quantity=quantity,
                    cost_basis=fill_price,
                    current_price=fill_price,
                    market_value=total_cost,
                )
                db.add(holding)
            else:
                old_qty = holding.quantity
                new_qty = old_qty + quantity
                new_cost_basis = ((holding.cost_basis * old_qty) + (fill_price * quantity)) / new_qty
                holding.quantity = round(new_qty, 6)
                holding.cost_basis = round(new_cost_basis, 4)
                holding.current_price = fill_price
                holding.market_value = round(holding.quantity * fill_price, 2)

            plain_note = (
                f"Purchased {quantity:,.2f} shares of {sym} ({quote['asset_name']}) at "
                f"${fill_price:,.2f} per share (${total_cost:,.2f})."
            )

        else:  # SELL
            available_qty = holding.quantity if holding else 0.0
            if available_qty < quantity:
                order = OrderExecution(
                    portfolio_id=portfolio.id,
                    rebalance_event_id=rebalance_event_id,
                    symbol=sym,
                    side="SELL",
                    order_type=order_type,
                    quantity=quantity,
                    requested_price=fill_price,
                    status="REJECTED",
                    broker_order_id=broker_order_id,
                    plain_english_status=(
                        f"Order rejected: Portfolio holds {available_qty:,.2f} shares of {sym}, "
                        f"cannot sell {quantity:,.2f} shares."
                    ),
                )
                db.add(order)
                db.commit()
                db.refresh(order)
                return order

            # Add cash
            portfolio.cash_balance = round(portfolio.cash_balance + total_cost, 2)

            # Update holding
            holding.quantity = round(holding.quantity - quantity, 6)
            holding.current_price = fill_price
            holding.market_value = round(holding.quantity * fill_price, 2)
            if holding.quantity <= 1e-6:
                db.delete(holding)

            plain_note = (
                f"Sold {quantity:,.2f} shares of {sym} ({quote['asset_name']}) at "
                f"${fill_price:,.2f} per share, adding ${total_cost:,.2f} to cash balance."
            )

        # 3. Record OrderExecution with FILLED status
        order = OrderExecution(
            portfolio_id=portfolio.id,
            rebalance_event_id=rebalance_event_id,
            symbol=sym,
            side=side_norm,
            order_type=order_type,
            quantity=quantity,
            requested_price=fill_price,
            executed_price=fill_price,
            executed_quantity=quantity,
            status="FILLED",
            broker_order_id=broker_order_id,
            plain_english_status=plain_note,
        )
        db.add(order)

        # 4. Synchronize into Transactions ledger (Requirement 16)
        tx = Transaction(
            portfolio_id=portfolio.id,
            symbol=sym,
            type=side_norm,
            quantity=quantity,
            price=fill_price,
            amount=total_cost,
            fee=fee,
            plain_english_note=custom_note or plain_note,
        )
        db.add(tx)

        # 5. Recalculate portfolio total valuation & allocation percentages
        self._recompute_portfolio_valuation(db, portfolio)

        db.commit()
        db.refresh(order)
        return order

    def _recompute_portfolio_valuation(self, db: Session, portfolio: Portfolio):
        holdings = db.query(Holding).filter(Holding.portfolio_id == portfolio.id).all()
        total_market_val = 0.0
        for h in holdings:
            p = market_data_service.get_latest_price(h.symbol, db=None)["price"]
            h.current_price = p
            h.market_value = round(h.quantity * p, 2)
            total_market_val += h.market_value

        portfolio.total_valuation = round(portfolio.cash_balance + total_market_val, 2)
        for h in holdings:
            if portfolio.total_valuation > 0:
                h.allocation_pct = round(h.market_value / portfolio.total_valuation, 4)
            else:
                h.allocation_pct = 0.0


broker_service = BrokerService()
