from datetime import date

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404, get_survey_or_404
from app.db.session import get_db
from app.models.project import Project
from app.models.survey import Survey
from app.schemas.common import SurfaceType
from app.schemas.survey import PointsPage, SurveyRead
from app.services import survey_service

router = APIRouter(prefix="/projects/{project_id}/surveys", tags=["surveys"])


@router.post(
    "",
    response_model=SurveyRead,
    status_code=status.HTTP_201_CREATED,
    responses={409: {}, 413: {}, 422: {}},
)
def upload_survey(
    kind: SurfaceType = Form(...),
    surveyed_on: date = Form(..., description="Date the survey was taken (YYYY-MM-DD)"),
    file: UploadFile = File(..., description="CSV with a header row containing x, y, z"),
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """Upload a topographic survey as a CSV file.

    The first row must be a header with `x`, `y`, `z` (or easting, northing,
    elevation). Comma, semicolon and tab delimiters are accepted. The whole
    file is rejected if any row is invalid.
    """
    return survey_service.create_survey(
        db, project, kind=kind, surveyed_on=surveyed_on, file=file
    )


@router.get("", response_model=list[SurveyRead])
def list_surveys(
    kind: SurfaceType | None = Query(None, description="Filter by survey kind"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """List this project's surveys, oldest first."""
    return survey_service.list_surveys(
        db, project.id, kind=kind, limit=limit, offset=offset
    )


@router.get("/{survey_id}", response_model=SurveyRead)
def read_survey(survey: Survey = Depends(get_survey_or_404)):
    """Survey metadata, including its point count."""
    return survey


@router.get("/{survey_id}/points", response_model=PointsPage)
def read_points(
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    survey: Survey = Depends(get_survey_or_404),
    db: Session = Depends(get_db),
):
    """Paginated x,y,z points, for inspection and plotting."""
    return survey_service.get_points_page(db, survey, limit=limit, offset=offset)


@router.delete("/{survey_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_survey(
    survey: Survey = Depends(get_survey_or_404),
    db: Session = Depends(get_db),
):
    """Delete a survey and its points. Blocked if a computation uses it."""
    survey_service.delete_survey(db, survey)