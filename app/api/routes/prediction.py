from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project_or_404
from app.models.project import Project
from app.schemas.prediction import (
    PredictionCreate,
    PredictionList,
    PredictionMetric,
    PredictionRead,
)
from app.services import prediction_store

router = APIRouter(prefix="/projects/{project_id}/predictions", tags=["predictions"])


@router.post(
    "",
    response_model=PredictionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a forecast from the computation history",
)
def create_prediction(
    payload: PredictionCreate,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """Fits a trend to the project's completed computations (one point per progress survey)
    and projects it forward, with a prediction interval and, if `target_value` is given, an
    estimated completion date with an earliest/latest range."""
    try:
        row = prediction_store.generate(db, project, payload)
    except prediction_store.PredictionError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return PredictionRead.from_row(row, project.unit.value)


@router.get("", response_model=PredictionList, summary="List forecasts")
def list_predictions(
    metric: PredictionMetric | None = Query(None, description="Only forecasts of this metric"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    rows, total = prediction_store.list_predictions(db, project.id, metric, limit, offset)
    return PredictionList(
        items=[PredictionRead.from_row(r, project.unit.value) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )