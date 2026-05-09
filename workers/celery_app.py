import logging
from celery import Celery

from app.config import settings

logger = logging.getLogger(__name__)

celery_app = Celery(
    "travel_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    result_expires=3600,
    beat_schedule={
        # Every 6 hours: scan active users and check for flight price drops
        "monitor-flight-prices": {
            "task": "workers.tasks.monitor_prices_all_users",
            "schedule": 6 * 3600,
        },
        # Every hour: purge expired cache rows from PostgreSQL
        "cleanup-expired-cache": {
            "task": "workers.tasks.cleanup_expired_cache",
            "schedule": 3600.0,
        },
    },
)
