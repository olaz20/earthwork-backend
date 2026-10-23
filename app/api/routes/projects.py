from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_project_or_404
from app.db.session import get_db
from app.models.project import Project
from app.schemas.project import (
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
)
from app.services import project_store

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
def create_project(data: ProjectCreate, db: Session = Depends(get_db)):
    """Create a project."""
    return project_store.create_project(db, data)


@router.get("", response_model=list[ProjectRead])
def list_projects(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List projects, oldest first, with pagination."""
    return project_store.list_projects(db, limit=limit, offset=offset)


@router.get("/{project_id}", response_model=ProjectDetail)
def read_project(
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """One project plus counts of its surveys, boundaries and computations."""
    return project_store.get_project_detail(db, project)


@router.patch("/{project_id}", response_model=ProjectRead)
def update_project(
    data: ProjectUpdate,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """Partially update a project. Only the fields you send are changed."""
    return project_store.update_project(db, project, data)


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """Delete a project and, via database cascade, everything under it."""
    project_store.delete_project(db, project)