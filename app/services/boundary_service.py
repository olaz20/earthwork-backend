"""Boundary persistence: create (with ordered vertices), list, fetch, delete."""
from __future__ import annotations

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session, selectinload

from app.models.boundary import Boundary, BoundaryPoint
from app.schemas.boundary import BoundaryCreate
from app.schemas.common import BoundaryType
from app.services import survey_service
from app.services.computation_store import FILL_KIND, PROGRESS_KIND


class BoundaryError(ValueError):
    """The boundary request is inconsistent with the project's data (maps to HTTP 422)."""


def get_boundary(db: Session, project_id: int, boundary_id: int) -> Boundary | None:
    """Boundary with its vertices loaded in order, scoped to the project."""
    return db.scalars(
        select(Boundary)
        .options(selectinload(Boundary.points))
        .where(Boundary.id == boundary_id, Boundary.project_id == project_id)
    ).first()


def list_boundaries(
    db: Session,
    project_id: int,
    kind: BoundaryType | None,
    limit: int,
    offset: int,
) -> tuple[list[tuple[Boundary, int]], int]:
    """Returns ([(boundary, vertex_count), ...], total). Newest recording first."""
    cond = [Boundary.project_id == project_id]
    if kind is not None:
        cond.append(Boundary.kind == kind)

    vertex_count = (
        select(func.count())
        .select_from(BoundaryPoint)
        .where(BoundaryPoint.boundary_id == Boundary.id)
        .correlate(Boundary)
        .scalar_subquery()
    )
    total = db.scalar(select(func.count()).select_from(Boundary).where(*cond)) or 0
    rows = db.execute(
        select(Boundary, vertex_count)
        .where(*cond)
        .order_by(Boundary.recorded_on.desc(), Boundary.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return [(b, int(n or 0)) for b, n in rows], total


def _check_survey_link(db: Session, project_id: int, data: BoundaryCreate) -> None:
    if data.survey_id is None:
        return
    if data.kind != FILL_KIND:
        raise BoundaryError("survey_id only applies to fill boundaries")
    survey = survey_service.get_survey(db, project_id, data.survey_id)
    if survey is None:
        raise BoundaryError(f"survey {data.survey_id} does not exist in this project")
    if survey.kind != PROGRESS_KIND:
        raise BoundaryError(f"survey {data.survey_id} is not a progress survey")


def create_boundary(db: Session, project_id: int, data: BoundaryCreate) -> tuple[Boundary, int]:
    """Insert the boundary and its vertices (seq 0..n-1) in one transaction."""
    _check_survey_link(db, project_id, data)
    try:
        boundary = Boundary(
            project_id=project_id,
            kind=data.kind,
            recorded_on=data.recorded_on,
            survey_id=data.survey_id,
        )
        db.add(boundary)
        db.flush()  # assigns boundary.id
        db.execute(
            insert(BoundaryPoint),
            [
                {"boundary_id": boundary.id, "seq": i, "x": p.x, "y": p.y}
                for i, p in enumerate(data.points)
            ],
        )
        db.commit()
    except BaseException:
        db.rollback()
        raise
    db.refresh(boundary)
    return boundary, len(data.points)


def delete_boundary(db: Session, boundary: Boundary) -> None:
    """Vertices go with it (ON DELETE CASCADE). Computations that used it keep their row;
    their boundary reference becomes NULL (ON DELETE SET NULL) and reports show '(deleted)'."""
    db.delete(boundary)
    db.commit()