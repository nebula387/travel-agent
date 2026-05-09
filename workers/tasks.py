"""
Celery tasks for travel-agent.

All async operations are wrapped with asyncio.run() since Celery workers
run in a sync context. Each task creates its own event loop.
"""
import asyncio
import logging

import httpx

from app.config import settings
from workers.celery_app import celery_app

logger = logging.getLogger(__name__)

_TG_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"


# ── Core tasks ───────────────────────────────────────────────────────────────

@celery_app.task(
    bind=True,
    name="workers.tasks.process_travel_request",
    max_retries=3,
    default_retry_delay=5,
)
def process_travel_request(self, user_id: int, query: str) -> dict:
    """
    Run Orchestrator for a user query and deliver the result via Telegram.
    Used for requests that take >2 seconds.
    """
    from app.agents.orchestrator import Orchestrator

    try:
        result = asyncio.run(Orchestrator().run(query, user_id))
        text = result.get("text", "Готово!")
        send_notification.delay(user_id, text)
        return result
    except Exception as exc:
        logger.exception("process_travel_request failed user=%s", user_id)
        raise self.retry(exc=exc)


@celery_app.task(
    name="workers.tasks.monitor_prices",
    bind=True,
    max_retries=2,
)
def monitor_prices(self, user_id: int, origin: str, destination: str) -> dict:
    """
    Check current flight prices for a route and notify user if price dropped >20%.
    """
    from app.tools.flights import search_flights

    async def _check():
        return await search_flights(origin, destination)

    try:
        result = asyncio.run(_check())
        prices = result.get("prices", [])
        if not prices:
            return {"status": "no_prices"}

        cheapest = prices[0].get("price", 0)
        threshold = _get_price_threshold(user_id, origin, destination)

        if threshold and cheapest < threshold * 0.8:
            msg = (
                f"🔥 Цена упала! {origin} → {destination}: "
                f"${cheapest} (было ~${threshold})\n"
                f"Купить: {result.get('aviasales_link', '')}"
            )
            send_notification.delay(user_id, msg)
            _save_price_threshold(user_id, origin, destination, cheapest)
            return {"status": "notified", "price": cheapest}

        # Save current price as new baseline if not set
        if not threshold:
            _save_price_threshold(user_id, origin, destination, cheapest)

        return {"status": "ok", "price": cheapest}
    except Exception as exc:
        logger.exception("monitor_prices failed user=%s route=%s→%s", user_id, origin, destination)
        raise self.retry(exc=exc)


@celery_app.task(name="workers.tasks.send_notification")
def send_notification(user_id: int, message: str) -> bool:
    """Send a Telegram message to user. Returns True on success."""
    if not settings.telegram_bot_token or settings.telegram_bot_token.startswith("placeholder"):
        logger.debug("Telegram token not set, skipping notification user=%s", user_id)
        return False
    try:
        with httpx.Client(timeout=10.0) as client:
            r = client.post(
                f"{_TG_API}/sendMessage",
                json={
                    "chat_id": user_id,
                    "text": message,
                    "parse_mode": "HTML",
                },
            )
            r.raise_for_status()
            return True
    except Exception:
        logger.exception("send_notification failed user=%s", user_id)
        return False


# ── Periodic tasks ────────────────────────────────────────────────────────────

@celery_app.task(name="workers.tasks.monitor_prices_all_users")
def monitor_prices_all_users() -> dict:
    """
    Celery Beat task (every 6h): check cheap flights for all active users.
    Reads saved routes from Redis and queues individual monitor_prices tasks.
    """
    import redis as sync_redis

    dispatched = 0
    try:
        r = sync_redis.from_url(settings.redis_url, decode_responses=True)
        # Scan for all user context keys
        for key in r.scan_iter("ctx:*"):
            user_id_str = key.split(":", 1)[1]
            if not user_id_str.isdigit():
                continue
            uid = int(user_id_str)
            # Look for saved routes in context
            raw_routes = r.hget(key, "saved_routes")
            if not raw_routes:
                continue
            import json
            routes = json.loads(raw_routes)
            for route in routes[:3]:  # max 3 routes per user per cycle
                origin = route.get("origin", "MOW")
                dest = route.get("destination", "")
                if dest:
                    monitor_prices.delay(uid, origin, dest)
                    dispatched += 1
    except Exception:
        logger.exception("monitor_prices_all_users failed")

    logger.info("monitor_prices_all_users: dispatched %d tasks", dispatched)
    return {"dispatched": dispatched}


@celery_app.task(name="workers.tasks.cleanup_expired_cache")
def cleanup_expired_cache() -> dict:
    """Periodic task: remove expired SearchCache and AgentContext rows."""
    async def _run():
        from datetime import datetime, timezone
        from sqlalchemy import delete
        from app.models.base import async_session_factory
        from app.models.cache import SearchCache, AgentContext

        async with async_session_factory() as session:
            now = datetime.now(timezone.utc)
            r1 = await session.execute(
                delete(SearchCache).where(SearchCache.expires_at < now)
            )
            r2 = await session.execute(
                delete(AgentContext).where(
                    AgentContext.expires_at.isnot(None),
                    AgentContext.expires_at < now,
                )
            )
            await session.commit()
            return r1.rowcount + r2.rowcount

    try:
        deleted = asyncio.run(_run())
        logger.info("cleanup_expired_cache: deleted %d rows", deleted)
        return {"deleted": deleted}
    except Exception:
        logger.exception("cleanup_expired_cache failed")
        return {"deleted": 0}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_price_threshold(user_id: int, origin: str, destination: str) -> float | None:
    import redis as sync_redis
    import json
    try:
        r = sync_redis.from_url(settings.redis_url, decode_responses=True)
        raw = r.hget(f"ctx:{user_id}", f"price_threshold:{origin}:{destination}")
        return float(json.loads(raw)) if raw else None
    except Exception:
        return None


def _save_price_threshold(user_id: int, origin: str, destination: str, price: float) -> None:
    import redis as sync_redis
    import json
    try:
        r = sync_redis.from_url(settings.redis_url, decode_responses=True)
        r.hset(f"ctx:{user_id}", f"price_threshold:{origin}:{destination}", json.dumps(price))
        r.expire(f"ctx:{user_id}", 86400 * 30)  # 30 days
    except Exception:
        logger.exception("_save_price_threshold failed")
