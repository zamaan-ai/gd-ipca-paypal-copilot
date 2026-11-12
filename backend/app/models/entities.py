"""
GD-IPCA SQLAlchemy ORM Models
Complete database schema supporting MySQL 8.0 & SQLite.
Models: User, IntentGoal, Portfolio, Holding, Transaction, RebalanceEvent, OrderExecution, SimulationRun, MarketPrice.
"""
from datetime import datetime, timezone
import uuid
import json
from typing import Any, Dict, List
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    ForeignKey,
    Text,
    UniqueConstraint,
    Index,
)
from sqlalchemy.orm import relationship
from app.db.session import Base


def _now():
    return datetime.now(timezone.utc)


def _gen_uuid() -> str:
    return str(uuid.uuid4())


class User(Base):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    email = Column(String(255), unique=True, nullable=False, index=True)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(255), nullable=True)
    role = Column(String(32), default="user", nullable=False)  # "user" | "admin"
    is_active = Column(Boolean, default=True, nullable=False)
    risk_default = Column(Float, default=3.5)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    goals = relationship("IntentGoal", back_populates="user", cascade="all, delete-orphan")
    portfolios = relationship("Portfolio", back_populates="user", cascade="all, delete-orphan")
    simulations = relationship("SimulationRun", back_populates="user", cascade="all, delete-orphan")
    rebalances = relationship("RebalanceEvent", back_populates="user", cascade="all, delete-orphan")


class IntentGoal(Base):
    __tablename__ = "intent_goals"

    goal_id = Column(String(64), primary_key=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    primary_objective = Column(Text, nullable=False)
    raw_text = Column(Text, nullable=True)
    target_valuation = Column(Float, nullable=False)
    guaranteed_reserve = Column(Float, nullable=False)
    time_horizon_years = Column(Float, nullable=False)
    risk_profile_index = Column(Float, nullable=False)
    liquidity_constraint = Column(String(64), default="STRICT_RESERVE")
    confidence_threshold = Column(Float, default=0.90)
    tax_status = Column(String(64), default="taxable_brokerage")
    status = Column(String(32), default="active")  # "active" | "archived" | "completed"

    # JSON stored as text for maximum cross-DB compatibility (MySQL & SQLite)
    _utility_params = Column("utility_params", Text, nullable=True)
    _milestones = Column("milestones", Text, nullable=True)
    _preferred_asset_classes = Column("preferred_asset_classes", Text, nullable=True)
    _excluded_assets = Column("excluded_assets", Text, nullable=True)

    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    user = relationship("User", back_populates="goals")
    portfolio = relationship("Portfolio", back_populates="goal", uselist=False)
    simulations = relationship("SimulationRun", back_populates="goal", cascade="all, delete-orphan")
    rebalance_events = relationship("RebalanceEvent", back_populates="goal", cascade="all, delete-orphan")

    @property
    def utility_params(self) -> Dict[str, Any]:
        return json.loads(self._utility_params) if self._utility_params else {}

    @utility_params.setter
    def utility_params(self, value: Dict[str, Any]):
        self._utility_params = json.dumps(value) if value is not None else None

    @property
    def milestones(self) -> List[Dict[str, Any]]:
        return json.loads(self._milestones) if self._milestones else []

    @milestones.setter
    def milestones(self, value: List[Dict[str, Any]]):
        self._milestones = json.dumps(value) if value is not None else None

    @property
    def preferred_asset_classes(self) -> List[str]:
        return json.loads(self._preferred_asset_classes) if self._preferred_asset_classes else []

    @preferred_asset_classes.setter
    def preferred_asset_classes(self, value: List[str]):
        self._preferred_asset_classes = json.dumps(value) if value is not None else None

    @property
    def excluded_assets(self) -> List[str]:
        return json.loads(self._excluded_assets) if self._excluded_assets else []

    @excluded_assets.setter
    def excluded_assets(self, value: List[str]):
        self._excluded_assets = json.dumps(value) if value is not None else None


class Portfolio(Base):
    __tablename__ = "portfolios"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    goal_id = Column(String(64), ForeignKey("intent_goals.goal_id", ondelete="SET NULL"), nullable=True, index=True)
    name = Column(String(255), nullable=False)
    total_valuation = Column(Float, default=0.0)
    cash_balance = Column(Float, default=0.0)
    emergency_reserve = Column(Float, default=0.0)
    target_equity_pct = Column(Float, default=0.60)
    target_bond_pct = Column(Float, default=0.40)
    status = Column(String(32), default="active")  # "active" | "frozen" | "closed"
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    # Relationships
    user = relationship("User", back_populates="portfolios")
    goal = relationship("IntentGoal", back_populates="portfolio")
    holdings = relationship("Holding", back_populates="portfolio", cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="portfolio", cascade="all, delete-orphan")
    orders = relationship("OrderExecution", back_populates="portfolio", cascade="all, delete-orphan")
    rebalances = relationship("RebalanceEvent", back_populates="portfolio")


class Holding(Base):
    __tablename__ = "holdings"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    portfolio_id = Column(String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(32), nullable=False, index=True)
    asset_name = Column(String(255), nullable=True)
    asset_class = Column(String(64), default="US_EQUITY")
    quantity = Column(Float, default=0.0)
    cost_basis = Column(Float, default=0.0)
    current_price = Column(Float, default=0.0)
    market_value = Column(Float, default=0.0)
    allocation_pct = Column(Float, default=0.0)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    portfolio = relationship("Portfolio", back_populates="holdings")

    __table_args__ = (
        UniqueConstraint("portfolio_id", "symbol", name="uq_portfolio_symbol"),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    portfolio_id = Column(String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String(32), nullable=True, index=True)
    type = Column(String(32), nullable=False)  # BUY, SELL, DEPOSIT, WITHDRAWAL, REBALANCE
    quantity = Column(Float, default=0.0)
    price = Column(Float, default=0.0)
    amount = Column(Float, nullable=False)
    fee = Column(Float, default=0.0)
    plain_english_note = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=_now, nullable=False)

    portfolio = relationship("Portfolio", back_populates="transactions")


class RebalanceEvent(Base):
    __tablename__ = "rebalance_events"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    goal_id = Column(String(64), ForeignKey("intent_goals.goal_id", ondelete="SET NULL"), nullable=True, index=True)
    portfolio_id = Column(String(36), ForeignKey("portfolios.id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    trigger_reason = Column(String(255), default="Manual rebalance")
    drift_detected = Column(Float, default=0.0)
    plain_english_explanation = Column(Text, nullable=True)
    status = Column(String(32), default="completed")  # "pending", "completed", "rejected"
    
    _target_allocation = Column("target_allocation", Text, nullable=True)
    _proposed_orders = Column("proposed_orders", Text, nullable=True)
    executed_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="rebalances")
    goal = relationship("IntentGoal", back_populates="rebalance_events")
    portfolio = relationship("Portfolio", back_populates="rebalances")
    orders = relationship("OrderExecution", back_populates="rebalance_event")

    @property
    def target_allocation(self) -> Dict[str, float]:
        return json.loads(self._target_allocation) if self._target_allocation else {}

    @target_allocation.setter
    def target_allocation(self, value: Dict[str, float]):
        self._target_allocation = json.dumps(value) if value is not None else None

    @property
    def proposed_orders(self) -> List[Dict[str, Any]]:
        return json.loads(self._proposed_orders) if self._proposed_orders else []

    @proposed_orders.setter
    def proposed_orders(self, value: List[Dict[str, Any]]):
        self._proposed_orders = json.dumps(value) if value is not None else None


class OrderExecution(Base):
    __tablename__ = "order_executions"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    portfolio_id = Column(String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    rebalance_event_id = Column(String(36), ForeignKey("rebalance_events.id", ondelete="SET NULL"), nullable=True)
    symbol = Column(String(32), nullable=False)
    side = Column(String(16), nullable=False)  # BUY | SELL
    order_type = Column(String(32), default="MARKET")
    quantity = Column(Float, nullable=False)
    requested_price = Column(Float, nullable=True)
    executed_price = Column(Float, nullable=True)
    executed_quantity = Column(Float, default=0.0)
    status = Column(String(32), default="FILLED")  # PENDING, SUBMITTED, PARTIALLY_FILLED, FILLED, REJECTED, CANCELLED
    broker_order_id = Column(String(128), nullable=True)
    plain_english_status = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    portfolio = relationship("Portfolio", back_populates="orders")
    rebalance_event = relationship("RebalanceEvent", back_populates="orders")


class SimulationRun(Base):
    __tablename__ = "simulation_runs"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    goal_id = Column(String(64), ForeignKey("intent_goals.goal_id", ondelete="SET NULL"), nullable=True, index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    n_paths = Column(Integer, nullable=False, default=5000)
    success_probability = Column(Float, nullable=True)
    median_final_value = Column(Float, nullable=True)
    equity_weight = Column(Float, nullable=True)
    bond_weight = Column(Float, nullable=True)
    port_mu = Column(Float, nullable=True)
    port_sigma = Column(Float, nullable=True)
    max_drawdown_p95 = Column(Float, nullable=True)

    _trajectory_summary = Column("trajectory_summary", Text, nullable=True)
    _allocation = Column("allocation", Text, nullable=True)
    created_at = Column(DateTime, default=_now, nullable=False)

    user = relationship("User", back_populates="simulations")
    goal = relationship("IntentGoal", back_populates="simulations")

    @property
    def trajectory_summary(self) -> List[Dict[str, Any]]:
        return json.loads(self._trajectory_summary) if self._trajectory_summary else []

    @trajectory_summary.setter
    def trajectory_summary(self, value: List[Dict[str, Any]]):
        self._trajectory_summary = json.dumps(value) if value is not None else None

    @property
    def allocation(self) -> Dict[str, float]:
        return json.loads(self._allocation) if self._allocation else {}

    @allocation.setter
    def allocation(self, value: Dict[str, float]):
        self._allocation = json.dumps(value) if value is not None else None


class MarketPrice(Base):
    __tablename__ = "market_prices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String(32), nullable=False, index=True)
    timestamp = Column(DateTime, default=_now, nullable=False, index=True)
    open = Column(Float, nullable=True)
    high = Column(Float, nullable=True)
    low = Column(Float, nullable=True)
    close = Column(Float, nullable=False)
    volume = Column(Float, default=0.0)
    source = Column(String(64), default="yahoo")

    __table_args__ = (
        Index("ix_market_symbol_time", "symbol", "timestamp"),
    )


class PayPalPaymentRecord(Base):
    """Persists PayPal Sandbox/Live Orders, Captures, Payouts, and AI Agent rationales."""
    __tablename__ = "paypal_payments"

    id = Column(String(36), primary_key=True, default=_gen_uuid)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    portfolio_id = Column(String(36), ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False, index=True)
    goal_id = Column(String(64), nullable=True)

    payment_type = Column(String(32), nullable=False)  # "DEPOSIT_ORDER" | "PAYOUT"
    paypal_order_id = Column(String(64), nullable=True, index=True)
    paypal_capture_id = Column(String(64), nullable=True)
    paypal_payout_batch_id = Column(String(64), nullable=True)
    recipient_email = Column(String(255), nullable=True)

    amount = Column(Float, nullable=False)
    currency = Column(String(8), default="USD", nullable=False)
    status = Column(String(32), nullable=False, default="CREATED")  # CREATED | COMPLETED | SUCCESS | FAILED
    mode = Column(String(32), nullable=False, default="sandbox_simulation")  # sandbox_live | sandbox_simulation
    approval_url = Column(Text, nullable=True)
    ai_rationale = Column(Text, nullable=True)
    _raw_response = Column("raw_response", Text, nullable=True)

    created_at = Column(DateTime, default=_now, nullable=False)
    updated_at = Column(DateTime, default=_now, onupdate=_now, nullable=False)

    @property
    def raw_response(self) -> Dict[str, Any]:
        return json.loads(self._raw_response) if self._raw_response else {}

    @raw_response.setter
    def raw_response(self, value: Dict[str, Any]):
        self._raw_response = json.dumps(value) if value is not None else None
