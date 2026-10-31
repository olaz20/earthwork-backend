"""Runs one computation end to end: load inputs -> engine -> persist result.

``run_computation`` is deliberately a plain function of a single id, so it can be handed
to FastAPI ``BackgroundTasks`` today and to a Celery task tomorrow without changes:

    @celery_app.task
    def run_computation_task(computation_id: int):
        run_computation(computation_id)
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.db.session import SessionLocal  # adjust to your session factory
from app.models import Computation
from app.schemas.computation import ComputationParameters, ComputationStatus
from app.services import computation_store as store
from app.services.surface_model import SurfaceConfig, SurfaceError
from app.services.volume_engine import EngineError, EngineParams, compute_earthwork

logger = logging.getLogger(__name__)

_MAX_ERROR_LEN = 2_000


def _engine_params(method: str, p: ComputationParameters) -> EngineParams:
    return EngineParams(
        method=method,  # type: ignore[arg-type]
        cell_size=p.cell_size,
        boundary_spacing=p.boundary_spacing,
        dz_tolerance=p.dz_tolerance,
        cut_scope=p.cut_scope.value,  # type: ignore[arg-type]
        max_cells=p.max_cells,
        surface=SurfaceConfig(
            interpolation=p.interpolation.value,  # type: ignore[arg-type]
            extrapolation=p.extrapolation.value,  # type: ignore[arg-type]
            idw_power=p.idw_power,
            idw_neighbors=p.idw_neighbors,
            max_extrapolation_distance=p.max_extrapolation_distance,
        ),
    )


def _fail(db: Session, computation_id: int, message: str) -> None:
    db.rollback()
    row = db.get(Computation, computation_id)
    if row is None:
        return
    row.status = ComputationStatus.failed.value
    row.error = message[:_MAX_ERROR_LEN]
    row.completed_at = datetime.now(timezone.utc)
    db.commit()


def run_computation(computation_id: int) -> None:
    with SessionLocal() as db:
        row = db.get(Computation, computation_id)
        if row is None or row.status != ComputationStatus.pending.value:
            return  # deleted before it started, or already picked up

        row.status = ComputationStatus.running.value
        db.commit()

        try:
            requested = (row.parameters or {}).get("requested", {})
            params = ComputationParameters.model_validate(requested)
            engine_params = _engine_params(row.method or "grid", params)

            project = db.get(store.Project, row.project_id)
            store.ensure_projected_crs(project)

            initial = store.load_survey_xyz(db, row.initial_survey_id)
            progress = store.load_survey_xyz(db, row.progress_survey_id)
            site = store.load_boundary_xy(db, row.site_boundary_id)
            fill = (
                store.load_boundary_xy(db, row.fill_boundary_id)
                if row.fill_boundary_id is not None
                else None
            )
            db.commit()  # release the read transaction while the CPU-bound work runs

            result = compute_earthwork(initial, progress, site, fill, engine_params)

            row = db.get(Computation, computation_id)
            if row is None:  # deleted while running
                return
            row.site_area = result.site_area
            row.fill_area = result.fill_area
            row.fill_volume = result.fill_volume
            row.cut_volume = result.cut_volume
            row.parameters = {  # reassign: JSONB in-place mutation is not tracked
                "requested": requested,
                "resolved": result.resolved,
                "diagnostics": result.diagnostics,
            }
            row.status = ComputationStatus.completed.value
            row.error = None
            row.completed_at = datetime.now(timezone.utc)
            db.commit()
        except (store.ComputationInputError, EngineError, SurfaceError) as exc:
            logger.warning("computation %s failed: %s", computation_id, exc)
            _fail(db, computation_id, str(exc))
        except Exception:  # noqa: BLE001 - never leave a run stuck in 'running'
            logger.exception("computation %s crashed", computation_id)
            _fail(db, computation_id, "Internal error while computing; see server logs")