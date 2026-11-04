"""Hands a computation to the right executor: Celery/Redis, or in-process background task."""
from __future__ import annotations

from fastapi import BackgroundTasks

from app.core.config import settings
from app.services.computation_runner import run_computation


class QueueUnavailable(RuntimeError):
    """The task queue (Redis) could not be reached."""


def dispatch(computation_id: int, background: BackgroundTasks) -> None:
    if settings.use_celery:
        from app.tasks.computation_tasks import run_computation_task  # lazy: Celery optional in dev

        try:
            run_computation_task.delay(computation_id)
        except Exception as exc:  # kombu/redis connection errors
            raise QueueUnavailable("the task queue is unavailable") from exc
    else:
        background.add_task(run_computation, computation_id)