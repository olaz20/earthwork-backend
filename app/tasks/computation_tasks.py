"""Celery tasks for computations."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from celery.signals import worker_process_init, worker_ready
from sqlalchemy import select

import app.models  # noqa: F401  registers every ORM model so relationships resolve in the worker
from app.core.celery_app import celery_app
from app.db.session import SessionLocal, engine  # adjust if your engine has another name
from app.models.computation import Computation
from app.schemas.computation import ComputationStatus
from app.services.computation_runner import run_computation

logger = logging.getLogger(__name__)

REQUEUE_AFTER_SECONDS = 60


@celery_app.task(name="computations.run")
def run_computation_task(computation_id: int) -> None:
    """Thin wrapper: all the logic (and error recording) lives in run_computation."""
    run_computation(computation_id)


@worker_process_init.connect
def _fresh_db_pool(**_kwargs) -> None:
    """Each forked worker process needs its own database connections."""
    engine.dispose()


@worker_ready.connect
def _requeue_orphaned_pending(**_kwargs) -> None:
    """Jobs accepted by the API but lost (Redis restart, flushed queue) would stay 'pending'
    forever. When a worker starts, queue them again. Duplicates are harmless: run_computation
    claims a job atomically, so only one worker ever runs it."""
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=REQUEUE_AFTER_SECONDS)
    try:
        with SessionLocal() as db:
            ids = db.scalars(
                select(Computation.id).where(
                    Computation.status == ComputationStatus.pending.value,
                    Computation.created_at < cutoff,
                )
            ).all()
        for computation_id in ids:
            run_computation_task.delay(computation_id)
        if ids:
            logger.warning("re-queued %d pending computation(s): %s", len(ids), list(ids))
    except Exception:  # noqa: BLE001 - never stop a worker from starting
        logger.exception("could not re-queue pending computations")