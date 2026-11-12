"""
GD-IPCA Market Data Service
Provides live market data via real provider (yfinance) with fallback to historical canonical dataset.
Caches prices in Redis/memory and automatically stores ticks into the database.
"""
from datetime import datetime, timezone
import logging
from typing import Dict, Any, List, Optional
import pandas as pd
from sqlalchemy.orm import Session

from app.core.config import settings, DATA_DIR
from app.services.cache import cache
from app.models.entities import MarketPrice

logger = logging.getLogger("gdipca.market_data")

# Fallback baseline prices from historical_prices.csv
_BASELINE_PRICES: Dict[str, float] = {
    "VTI": 156.61, "VOO": 145.07, "VB": 113.83, "VXUS": 178.40,
    "VEA": 207.40, "VWO": 199.15, "BND": 122.06, "VCIT": 126.43,
    "VTIP": 122.47, "BNDX": 130.77, "VNQ": 106.75, "GLD": 146.21,
    "BIL": 124.64, "SGOV": 124.58, "VGT": 137.91, "VHT": 161.44,
}

# Assets info dictionary
_ASSETS_INFO: Dict[str, Dict[str, Any]] = {
    "VTI": {"name": "Vanguard Total Stock Market ETF", "class": "US_EQUITY", "risk": 4.5},
    "VOO": {"name": "Vanguard S&P 500 ETF", "class": "US_EQUITY", "risk": 4.5},
    "VB": {"name": "Vanguard Small-Cap ETF", "class": "US_EQUITY", "risk": 6.0},
    "VXUS": {"name": "Vanguard Total International Stock ETF", "class": "INTL_EQUITY", "risk": 5.0},
    "VEA": {"name": "Vanguard FTSE Developed Markets ETF", "class": "INTL_EQUITY", "risk": 4.8},
    "VWO": {"name": "Vanguard FTSE Emerging Markets ETF", "class": "INTL_EQUITY", "risk": 6.5},
    "BND": {"name": "Vanguard Total Bond Market ETF", "class": "US_BONDS", "risk": 2.0},
    "VCIT": {"name": "Vanguard Intermediate-Term Corporate Bond ETF", "class": "US_BONDS", "risk": 2.5},
    "VTIP": {"name": "Vanguard Short-Term TIPS ETF", "class": "TIPS", "risk": 1.5},
    "BNDX": {"name": "Vanguard Total International Bond ETF", "class": "INTL_BONDS", "risk": 2.2},
    "VNQ": {"name": "Vanguard Real Estate ETF", "class": "ALTERNATIVES", "risk": 5.5},
    "GLD": {"name": "SPDR Gold Shares", "class": "ALTERNATIVES", "risk": 4.0},
    "BIL": {"name": "SPDR Bloomberg 1-3 Month T-Bill ETF", "class": "CASH", "risk": 0.5},
    "SGOV": {"name": "iShares 0-3 Month Treasury Bond ETF", "class": "CASH", "risk": 0.5},
    "VGT": {"name": "Vanguard Information Technology ETF", "class": "US_EQUITY", "risk": 6.5},
    "VHT": {"name": "Vanguard Health Care ETF", "class": "US_EQUITY", "risk": 4.0},
}


class MarketDataService:
    def __init__(self):
        self._historical_df = None
        self._load_historical_prices()

    def _load_historical_prices(self):
        csv_path = DATA_DIR / "historical_prices.csv"
        if csv_path.exists():
            try:
                self._historical_df = pd.read_csv(csv_path)
                logger.info(f"Loaded {len(self._historical_df)} rows from historical_prices.csv")
            except Exception as e:
                logger.warning(f"Could not load historical_prices.csv: {e}")

    def get_asset_meta(self, symbol: str) -> Dict[str, Any]:
        return _ASSETS_INFO.get(symbol.upper(), {
            "name": symbol,
            "class": "OTHER",
            "risk": 3.0,
        })

    def get_latest_price(self, symbol: str, db: Optional[Session] = None) -> Dict[str, Any]:
        sym = symbol.upper()
        cache_key = f"market:price:{sym}"
        cached = cache.get(cache_key)
        if cached:
            return cached

        price = None
        source = "historical_baseline"

        # Attempt live lookup if provider is real
        if settings.MARKET_DATA_PROVIDER == "yahoo":
            try:
                import yfinance as yf
                ticker = yf.Ticker(sym)
                # fast_info is rapid and does not download full history
                fast_price = getattr(ticker.fast_info, "last_price", None)
                if fast_price and fast_price > 0:
                    price = round(float(fast_price), 4)
                    source = "yahoo_live"
            except Exception as e:
                logger.debug(f"Live fetch for {sym} failed ({e}), falling back to baseline.")

        # Fallback to historical CSV / dictionary baseline
        if price is None:
            if self._historical_df is not None and sym in self._historical_df.columns:
                price = round(float(self._historical_df[sym].iloc[-1]), 4)
            else:
                price = _BASELINE_PRICES.get(sym, 100.0)

        meta = self.get_asset_meta(sym)
        payload = {
            "symbol": sym,
            "price": price,
            "asset_name": meta["name"],
            "asset_class": meta["class"],
            "risk_score": meta["risk"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": source,
        }

        # Cache price
        cache.set(cache_key, payload, ttl=settings.MARKET_DATA_CACHE_TTL_SECONDS)

        # Persist tick into DB if session is available
        if db is not None:
            try:
                tick = MarketPrice(
                    symbol=sym,
                    close=price,
                    open=price,
                    high=price,
                    low=price,
                    volume=1000.0,
                    source=source,
                )
                db.add(tick)
                db.commit()
            except Exception as e:
                db.rollback()
                logger.debug(f"Failed to persist market tick for {sym}: {e}")

        return payload

    def get_universe_quotes(self, db: Optional[Session] = None) -> List[Dict[str, Any]]:
        quotes = []
        for sym in _ASSETS_INFO.keys():
            quotes.append(self.get_latest_price(sym, db=db))
        return quotes

    def get_historical_bars(self, symbol: str, limit: int = 120) -> List[Dict[str, Any]]:
        sym = symbol.upper()
        if self._historical_df is not None and sym in self._historical_df.columns:
            subset = self._historical_df[["date", sym]].tail(limit)
            return [
                {"date": str(row["date"]), "close": round(float(row[sym]), 4)}
                for _, row in subset.iterrows()
            ]
        # Fallback synthetic series
        base = _BASELINE_PRICES.get(sym, 100.0)
        return [{"date": f"2026-10-{i:02d}", "close": base} for i in range(1, 31)]

    def sync_all_to_db(self, db: Session) -> int:
        count = 0
        for sym in _ASSETS_INFO.keys():
            data = self.get_latest_price(sym, db=None)
            tick = MarketPrice(
                symbol=sym,
                close=data["price"],
                open=data["price"],
                high=data["price"],
                low=data["price"],
                volume=5000.0,
                source=data["source"],
            )
            db.add(tick)
            count += 1
        db.commit()
        return count


market_data_service = MarketDataService()
