"""
Real Market Data Provider Router
Provides quotes, historical price series, and database sync.
"""
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services.market_data import market_data_service

router = APIRouter()


@router.get("/quote/{symbol}")
def get_quote(symbol: str, db: Session = Depends(get_db)):
    return market_data_service.get_latest_price(symbol, db=db)


@router.get("/universe", response_model=List[Dict[str, Any]])
def get_universe(db: Session = Depends(get_db)):
    return market_data_service.get_universe_quotes(db=db)


@router.get("/history/{symbol}", response_model=List[Dict[str, Any]])
def get_history(symbol: str, limit: int = Query(90, ge=10, le=500)):
    return market_data_service.get_historical_bars(symbol, limit=limit)


@router.post("/sync")
def sync_market_prices(db: Session = Depends(get_db)):
    count = market_data_service.sync_all_to_db(db)
    return {"status": "success", "synced_assets": count}
