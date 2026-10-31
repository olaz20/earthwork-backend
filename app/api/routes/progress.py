from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project
from app.models import Project
from app.schemas.computation import ComputationMethod
from app.schemas.progress import ProgressSeries, ProgressSummary
from app.services import progress_calc, progress_store

router = APIRouter(prefix="/projects/{project_id}/progress", tags=["progress"])


@router.get(
    "",
    response_model=ProgressSeries,
    summary="Time series of date vs fill volume and area (for the chart)",
)
def progress_series(
    method: ComputationMethod | None = Query(
        None, description="Only use computations run with this method. Recommended when "
        "a project has mixed grid/tin runs, so the series is like-for-like."
    ),
    date_from: date | None = Query(None, description="Earliest survey date (inclusive)"),
    date_to: date | None = Query(None, description="Latest survey date (inclusive)"),
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
):
    """One point per progress survey, using that survey's most recent completed computation."""
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "date_from must not be after date_to")
    runs = progress_store.completed_runs(db, project.id, method, date_from, date_to)
    points = progress_calc.build_points(runs)
    return ProgressSeries(
        project_id=project.id,
        length_unit=project.unit.value,
        method=method,
        count=len(points),
        points=points,
    )


@router.get(
    "/summary",
    response_model=ProgressSummary,
    summary="Latest totals, % complete, last survey date",
)
def progress_summary(
    method: ComputationMethod | None = Query(None, description="Only use computations run with this method"),
    target_volume: float | None = Query(
        None, gt=0, description="Design fill volume (project units^3). Enables percent_complete_volume."
    ),
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
):
    runs = progress_store.completed_runs(db, project.id, method)
    return progress_calc.build_summary(
        project_id=project.id,
        length_unit=project.unit.value,
        points=progress_calc.build_points(runs),
        last_survey=progress_store.last_progress_survey(db, project.id),
        initial_survey_date=progress_store.initial_survey_date(db, project.id),
        progress_surveys=progress_store.progress_survey_count(db, project.id),
        target_volume=target_volume,
    )