from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.project import Project
from app.services import project_store


def get_project_or_404(project_id: int, db: Session = Depends(get_db)) -> Project:
    """Load the project named in the URL, or stop the request with a 404."""
    project = project_store.get_project(db, project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    return project