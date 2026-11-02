from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.services import project_store

from app.models.survey import Survey
from app.models.computation import Computation
from app.models.report import Report
from app.services import survey_service, boundary_service
from sqlalchemy import select

from app.models.boundary import Boundary

def get_project_or_404(project_id: int, db: Session = Depends(get_db)) -> Project:
    """Load the project named in the URL, or stop the request with a 404."""
    project = project_store.get_project(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project


def get_survey_or_404(
    survey_id: int,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Survey:
    survey = survey_service.get_survey(db, project.id, survey_id)
    if survey is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey not found")
    return survey



def get_computation_or_404(
    comp_id: int,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Computation:
    computation = db.scalars(
        select(Computation).where(
            Computation.id == comp_id, Computation.project_id == project.id
        )
    ).first()
    if computation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Computation not found")
    return computation


def get_report_or_404(
    report_id: int,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Report:
    report = db.scalars(
        select(Report).where(Report.id == report_id, Report.project_id == project.id)
    ).first()
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Report not found")
    return report

get_project = get_project_or_404


def get_computation(
    comp_id: int,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Computation:
    computation = db.scalars(
        select(Computation).where(
            Computation.id == comp_id, Computation.project_id == project.id
        )
    ).first()
    if computation is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Computation not found")
    return computation

def get_boundary_or_404(
    boundary_id: int,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
) -> Boundary:
    boundary = boundary_service.get_boundary(db, project.id, boundary_id)
    if boundary is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Boundary not found")
    return boundary
