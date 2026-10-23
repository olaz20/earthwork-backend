from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.services import project_store

from app.models.survey import Survey
from app.services import survey_service





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
