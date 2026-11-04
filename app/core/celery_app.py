"""Celery application (Redis broker). Start a worker with:

    celery -A app.core.celery_app:celery_app worker --loglevel=info --concurrency=2
"""
from celery import Celery

from app.core.config import settings

celery_app = Celery(
    "earthwork",
    broker=settings.redis_url,
    include=["app.tasks.computation_tasks"],  # modules the worker imports to find tasks
)

celery_app.conf.update(
    # Results live in the database (computations table), so no result backend is needed.
    task_ignore_result=True,
    task_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    # One long CPU-bound job per worker slot; do not hoard queued jobs.
    worker_prefetch_multiplier=1,
    # Ack when the task starts: a crash never silently re-runs a half-finished computation.
    task_acks_late=False,
    task_time_limit=60 * 60,        # hard kill after 1 h
    task_soft_time_limit=55 * 60,   # raises inside the task first, so it is recorded as failed
    broker_connection_retry_on_startup=True,
    # Fail fast in the API if Redis is down instead of hanging the request.
    broker_connection_timeout=2,
    task_publish_retry=True,
    task_publish_retry_policy={"max_retries": 2, "interval_start": 0, "interval_step": 0.2, "interval_max": 0.5},
)