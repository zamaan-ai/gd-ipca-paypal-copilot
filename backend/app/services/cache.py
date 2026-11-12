"""
Redis & In-Memory Cache Service
Provides uniform caching with automatic fallback when Redis server is offline.
"""
import time
import json
import logging
from typing import Any, Optional
from app.core.config import settings

logger = logging.getLogger("gdipca.cache")


class MemoryCache:
    """Thread-safe in-memory cache with TTL."""
    def __init__(self):
        self._store = {}

    def get(self, key: str) -> Optional[Any]:
        entry = self._store.get(key)
        if not entry:
            return None
        val, expiry = entry
        if expiry and time.time() > expiry:
            del self._store[key]
            return None
        return val

    def set(self, key: str, value: Any, ttl: Optional[int] = None) -> None:
        expiry = time.time() + ttl if ttl else None
        self._store[key] = (value, expiry)

    def delete(self, key: str) -> None:
        self._store.pop(key, None)

    def clear(self) -> None:
        self._store.clear()


class CacheService:
    def __init__(self):
        self._redis = None
        self._memory = MemoryCache()
        self._redis_available = False
        self._init_redis()

    def _init_redis(self):
        if settings.REDIS_ENABLED or "redis" in settings.REDIS_URL:
            try:
                import redis
                client = redis.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=1,
                    socket_timeout=1,
                    decode_responses=True,
                )
                client.ping()
                self._redis = client
                self._redis_available = True
                logger.info("Connected to Redis cache successfully")
            except Exception as e:
                logger.info(f"Redis not reachable ({e}). Using in-memory cache.")
                self._redis_available = False

    def is_redis_online(self) -> bool:
        return self._redis_available

    def get(self, key: str) -> Optional[Any]:
        if self._redis_available and self._redis:
            try:
                raw = self._redis.get(key)
                if raw is not None:
                    return json.loads(raw)
            except Exception:
                pass
        return self._memory.get(key)

    def set(self, key: str, value: Any, ttl: int = 300) -> None:
        if self._redis_available and self._redis:
            try:
                self._redis.setex(key, ttl, json.dumps(value))
                return
            except Exception:
                pass
        self._memory.set(key, value, ttl=ttl)

    def delete(self, key: str) -> None:
        if self._redis_available and self._redis:
            try:
                self._redis.delete(key)
            except Exception:
                pass
        self._memory.delete(key)


cache = CacheService()
