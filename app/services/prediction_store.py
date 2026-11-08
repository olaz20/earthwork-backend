"""Prediction orchestration: history -> forecast -> stored snapshot; and listing."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.prediction import Prediction
from app.models.project import Project
from app.schemas.prediction import PredictionCreate, PredictionMetric
from app.services import progress_store
from app.services.prediction_engine import (
    ForecastParams,
    Observation,
    PredictionError,
    forecast,
)

__all__ = ["PredictionError", "generate", "list_predictions"]


def _value(run, metric: PredictionMetric) -> float:
    if metric == PredictionMetric.fill_area:
        return run.fill_area
    if metric == PredictionMetric.net_volume:
        return run.fill_volume - run.cut_volume
    return run.fill_volume


def generate(db: Session, project: Project, payload: PredictionCreate) -> Prediction:
    runs = progress_store.completed_runs(db, project.id, method=payload.computation_method)
    if len(runs) < 2:
        raise PredictionError(
            "a forecast needs at least 2 completed computations on different progress surveys "
            f"(this project has {len(runs)}); run a computation for each progress survey first"
        )

    metric = payload.metric
    params = ForecastParams(
        method=payload.method.value,
        recent_points=payload.recent_points,
        horizon_days=payload.horizon_days,
        step_days=payload.step_days,
        confidence=payload.confidence,
        target_value=payload.target_value,
        nonnegative=metric != PredictionMetric.net_volume,
        cap=runs[-1].site_area if metric == PredictionMetric.fill_area else None,
    )
    today: date = datetime.now(timezone.utc).date()
    result = forecast(
        [Observation(r.surveyed_on, _value(r, metric), r.computation_id) for r in runs],
        params,
        today,
    )

    completion = result["completion"]
    estimate = (
        date.fromisoformat(completion["estimate"])
        if completion and completion["estimate"]
        else None
    )
    row = Prediction(
        project_id=project.id,
        metric=metric.value,
        method=payload.method.value,
        target_value=payload.target_value,
        predicted_completion_date=estimate,
        parameters={
            "requested": payload.model_dump(mode="json"),
            "resolved": {"generated_on": today.isoformat(), "site_area_cap": params.cap, "nonnegative": params.nonnegative},
        },
        result=result,
    )
    try:
        db.add(row)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    db.refresh(row)
    return row


def list_predictions(
    db: Session, project_id: int, metric: PredictionMetric | None, limit: int, offset: int
) -> tuple[list[Prediction], int]:
    cond = [Prediction.project_id == project_id]
    if metric is not None:
        cond.append(Prediction.metric == metric.value)
    total = db.scalar(select(func.count()).select_from(Prediction).where(*cond)) or 0
    rows = db.scalars(
        select(Prediction)
        .where(*cond)
        .order_by(Prediction.created_at.desc(), Prediction.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total