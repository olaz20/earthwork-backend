"""Database access for computations: input resolution, CRUD, point loading."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.boundary import Boundary, BoundaryPoint
from app.models.computation import Computation
from app.models.project import Project
from app.models.survey import Survey, SurveyPoint
from app.schemas.computation import ComputationCreate, ComputationStatus
from app.services.kinds import FILL_KIND, INITIAL_KIND, PROGRESS_KIND, SITE_KIND

MIN_SURVEY_POINTS = 3
MIN_BOUNDARY_POINTS = 3


class ComputationInputError(ValueError):
    """The requested inputs are missing, belong to another project, or are unusable."""


@dataclass(frozen=True)
class ResolvedInputs:
    initial_survey_id: int
    progress_survey_id: int
    site_boundary_id: int
    fill_boundary_id: int | None


# ----------------------------------------------------------------------------- checks
def ensure_projected_crs(project: Project) -> None:
    """Areas/volumes in a geographic CRS (degrees) are meaningless; refuse them."""
    if not project.crs:
        return
    try:
        from pyproj import CRS
    except ImportError:  # pyproj is optional
        return
    try:
        crs = CRS.from_user_input(project.crs)
    except Exception as exc:
        raise ComputationInputError(f"project CRS '{project.crs}' is not recognised") from exc
    if crs.is_geographic:
        raise ComputationInputError(
            f"project CRS '{project.crs}' is geographic (degrees); "
            "reproject the data to a projected CRS before computing areas and volumes"
        )


def _survey(db: Session, project_id: int, survey_id: int, kind, label: str) -> Survey:
    survey = db.get(Survey, survey_id)
    if survey is None or survey.project_id != project_id:
        raise ComputationInputError(f"{label} {survey_id} does not exist in this project")
    if survey.kind != kind:
        raise ComputationInputError(f"{label} {survey_id} is not a {kind.value} survey")
    return survey


def _boundary(db: Session, project_id: int, boundary_id: int, kind, label: str) -> Boundary:
    boundary = db.get(Boundary, boundary_id)
    if boundary is None or boundary.project_id != project_id:
        raise ComputationInputError(f"{label} {boundary_id} does not exist in this project")
    if boundary.kind != kind:
        raise ComputationInputError(f"{label} {boundary_id} is not a {kind.value} boundary")
    return boundary


def _count(db: Session, model, fk, value) -> int:
    return db.scalar(select(func.count()).select_from(model).where(fk == value)) or 0


def resolve_inputs(db: Session, project_id: int, payload: ComputationCreate) -> ResolvedInputs:
    # initial survey
    if payload.initial_survey_id is not None:
        initial = _survey(db, project_id, payload.initial_survey_id, INITIAL_KIND, "initial survey")
    else:
        initial = db.scalars(
            select(Survey).where(Survey.project_id == project_id, Survey.kind == INITIAL_KIND)
        ).first()
        if initial is None:
            raise ComputationInputError("project has no initial topo survey")

    # progress survey
    if payload.progress_survey_id is not None:
        progress = _survey(db, project_id, payload.progress_survey_id, PROGRESS_KIND, "progress survey")
    else:
        progress = db.scalars(
            select(Survey)
            .where(Survey.project_id == project_id, Survey.kind == PROGRESS_KIND)
            .order_by(Survey.surveyed_on.desc(), Survey.id.desc())
        ).first()
        if progress is None:
            raise ComputationInputError("project has no progress survey")

    # site boundary
    if payload.site_boundary_id is not None:
        site = _boundary(db, project_id, payload.site_boundary_id, SITE_KIND, "site boundary")
    else:
        site = db.scalars(
            select(Boundary)
            .where(Boundary.project_id == project_id, Boundary.kind == SITE_KIND)
            .order_by(Boundary.recorded_on.desc(), Boundary.id.desc())
        ).first()
        if site is None:
            raise ComputationInputError("project has no site boundary")

    # fill boundary (optional)
    fill = None
    if payload.fill_boundary_id is not None:
        fill = _boundary(db, project_id, payload.fill_boundary_id, FILL_KIND, "fill boundary")
    else:
        fill = db.scalars(
            select(Boundary)
            .where(
                Boundary.project_id == project_id,
                Boundary.kind == FILL_KIND,
                Boundary.survey_id == progress.id,
            )
            .order_by(Boundary.recorded_on.desc(), Boundary.id.desc())
        ).first()

    for survey, label in ((initial, "initial survey"), (progress, "progress survey")):
        if _count(db, SurveyPoint, SurveyPoint.survey_id, survey.id) < MIN_SURVEY_POINTS:
            raise ComputationInputError(f"{label} {survey.id} has fewer than {MIN_SURVEY_POINTS} points")
    for boundary, label in ((site, "site boundary"), (fill, "fill boundary")):
        if boundary is not None and (
            _count(db, BoundaryPoint, BoundaryPoint.boundary_id, boundary.id) < MIN_BOUNDARY_POINTS
        ):
            raise ComputationInputError(f"{label} {boundary.id} has fewer than {MIN_BOUNDARY_POINTS} vertices")

    return ResolvedInputs(initial.id, progress.id, site.id, fill.id if fill else None)


# ------------------------------------------------------------------------------- CRUD
def create_pending(
    db: Session, project_id: int, inputs: ResolvedInputs, payload: ComputationCreate
) -> Computation:
    row = Computation(
        project_id=project_id,
        initial_survey_id=inputs.initial_survey_id,
        progress_survey_id=inputs.progress_survey_id,
        site_boundary_id=inputs.site_boundary_id,
        fill_boundary_id=inputs.fill_boundary_id,
        status=ComputationStatus.pending.value,
        method=payload.method.value,
        parameters={"requested": payload.parameters.model_dump(mode="json")},
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def list_computations(
    db: Session,
    project_id: int,
    status: ComputationStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Computation], int]:
    cond = [Computation.project_id == project_id]
    if status is not None:
        cond.append(Computation.status == status.value)
    total = db.scalar(select(func.count()).select_from(Computation).where(*cond)) or 0
    rows = db.scalars(
        select(Computation)
        .where(*cond)
        .order_by(Computation.created_at.desc(), Computation.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return list(rows), total


def delete_computation(db: Session, row: Computation) -> None:
    db.delete(row)
    db.commit()


# ------------------------------------------------------------------------ point loading
def load_survey_xyz(db: Session, survey_id: int) -> np.ndarray:
    rows = db.execute(
        select(SurveyPoint.x, SurveyPoint.y, SurveyPoint.z).where(SurveyPoint.survey_id == survey_id)
    ).all()
    return np.asarray(rows, dtype=float).reshape(-1, 3)


def load_boundary_xy(db: Session, boundary_id: int) -> np.ndarray:
    rows = db.execute(
        select(BoundaryPoint.x, BoundaryPoint.y)
        .where(BoundaryPoint.boundary_id == boundary_id)
        .order_by(BoundaryPoint.seq)
    ).all()
    return np.asarray(rows, dtype=float).reshape(-1, 2)
