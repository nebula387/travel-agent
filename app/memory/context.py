import json
import logging
from typing import Any

import redis.asyncio as aioredis
from sqlalchemy import select, update

from app.config import settings

logger = logging.getLogger(__name__)

_redis_client: aioredis.Redis | None = None


def get_redis() -> aioredis.Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


class SharedContext:
    """
    Dual-persistence context store: Redis (fast, TTL) + PostgreSQL (durable).
    Redis is primary; PostgreSQL is written async for persistence across restarts.
    """

    TTL_SESSION = 3600  # 1 hour

    def __init__(self, user_id: int) -> None:
        self.user_id = user_id
        self._redis_key = f"ctx:{user_id}"
        self._pg_key = f"user:{user_id}"
        self._redis = get_redis()

    # ── Public API (used by agents) ──────────────────────────────────────────

    async def read(self, field: str, default: Any = None) -> Any:
        """Read a field — Redis first, PostgreSQL fallback."""
        value = await self._redis_get(field)
        if value is not None:
            return value
        value = await self._pg_get(field)
        if value is not None:
            # Warm Redis cache
            await self._redis_set(field, value, self.TTL_SESSION)
        return value if value is not None else default

    async def write(self, field: str, value: Any, ttl: int = TTL_SESSION) -> None:
        """Write to Redis immediately and PostgreSQL in the background."""
        await self._redis_set(field, value, ttl)
        await self._pg_set(field, value)

    # ── Backwards-compat aliases (used by old bot handlers) ──────────────────

    async def get(self, field: str) -> Any | None:
        return await self.read(field)

    async def set(self, field: str, value: Any) -> None:
        await self.write(field, value)

    async def get_all(self) -> dict:
        try:
            raw = await self._redis.hgetall(self._redis_key)
            data = {k: json.loads(v) for k, v in raw.items()}
            return data
        except Exception:
            logger.exception("SharedContext.get_all failed key=%s", self._redis_key)
            return {}

    async def clear(self) -> None:
        await self._redis.delete(self._redis_key)

    # ── Redis internals ──────────────────────────────────────────────────────

    async def _redis_get(self, field: str) -> Any | None:
        try:
            raw = await self._redis.hget(self._redis_key, field)
            return json.loads(raw) if raw else None
        except Exception:
            logger.exception("Redis get failed field=%s", field)
            return None

    async def _redis_set(self, field: str, value: Any, ttl: int) -> None:
        try:
            await self._redis.hset(self._redis_key, field, json.dumps(value, ensure_ascii=False))
            await self._redis.expire(self._redis_key, ttl)
        except Exception:
            logger.exception("Redis set failed field=%s", field)

    # ── PostgreSQL internals ─────────────────────────────────────────────────

    async def _pg_get(self, field: str) -> Any | None:
        try:
            from app.models.base import async_session_factory
            from app.models.cache import AgentContext
            async with async_session_factory() as session:
                row = await session.scalar(
                    select(AgentContext).where(AgentContext.session_key == self._pg_key)
                )
                if row and row.context_data:
                    return row.context_data.get(field)
        except Exception:
            logger.debug("PostgreSQL get skipped (may not be available): %s", field)
        return None

    async def _pg_set(self, field: str, value: Any) -> None:
        try:
            from app.models.base import async_session_factory
            from app.models.cache import AgentContext
            async with async_session_factory() as session:
                row = await session.scalar(
                    select(AgentContext).where(AgentContext.session_key == self._pg_key)
                )
                if row:
                    row.context_data = {**row.context_data, field: value}
                    await session.commit()
                else:
                    session.add(AgentContext(
                        session_key=self._pg_key,
                        context_data={field: value},
                    ))
                    await session.commit()
        except Exception:
            logger.debug("PostgreSQL set skipped (may not be available): %s", field)
