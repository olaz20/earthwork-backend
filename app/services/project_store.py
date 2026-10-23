from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.boundary import Boundary
from app.models.computation import Computation
from app.models.project import Project
from app.models.survey import Survey
from app.schemas.project import (
    ProjectCounts,
    ProjectCreate,
    ProjectDetail,
    ProjectRead,
    ProjectUpdate,
)
from sqlalchemy.sql.selectable import ScalarSelect

def create_project(db: Session, data: ProjectCreate) -> Project:
    project = Project(**data.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)  # load DB-generated values (id, created_at)
    return project


def list_projects(db: Session, *, limit: int, offset: int) -> list[Project]:
    stmt = select(Project).order_by(Project.id).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def get_project(db: Session, project_id: int) -> Project | None:
    return db.get(Project, project_id)


def get_project_detail(db: Session, project: Project) -> ProjectDetail:
    """Project plus child counts, fetched in a single round trip.

    Uses COUNT subqueries so no child rows (e.g. 50,000 survey points'
    parents) are ever loaded into Python.
    """

    def count_of(model) -> "ScalarSelect":
        return (
            select(func.count(model.id))
            .where(model.project_id == project.id)
            .scalar_subquery()
        )

    row = db.execute(
        select(count_of(Survey), count_of(Boundary), count_of(Computation))
    ).one()

    return ProjectDetail(
        **ProjectRead.model_validate(project).model_dump(),
        counts=ProjectCounts(surveys=row[0], boundaries=row[1], computations=row[2]),
    )


def update_project(db: Session, project: Project, data: ProjectUpdate) -> Project:
    # exclude_unset: only fields the client actually sent
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(project, field, value)
    db.commit()
    db.refresh(project)
    return project


def delete_project(db: Session, project: Project) -> None:
    
    db.delete(project)
    db.commit()