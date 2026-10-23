import io
from datetime import date
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy import insert, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.exceptions import (
    ConflictError,
    FileValidationError,
    PayloadTooLargeError,
)
from app.models.computation import Computation
from app.models.project import Project
from app.models.survey import ONE_INITIAL_INDEX, Survey, SurveyPoint
from app.schemas.common import SurfaceType
from app.schemas.survey import PointRead, PointsPage
from app.services.survey_parser import parse_survey_csv

ALLOWED_EXTENSIONS = {".csv", ".txt", ".xyz"}


def _validate_upload(file: UploadFile) -> str:
    """Check extension and size; return a safe filename."""
    name = Path(file.filename or "").name
    if Path(name).suffix.lower() not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"Unsupported file type. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )
    file.file.seek(0, io.SEEK_END)
    size = file.file.tell()
    file.file.seek(0)
    if size > settings.max_upload_bytes:
        raise PayloadTooLargeError(f"File exceeds the {settings.max_upload_mb} MB limit")
    return name[:255]


def _initial_exists(db: Session, project_id: int) -> bool:
    stmt = (
        select(Survey.id)
        .where(Survey.project_id == project_id, Survey.kind == SurfaceType.initial_topo)
        .limit(1)
    )
    return db.scalar(stmt) is not None


def create_survey(
    db: Session,
    project: Project,
    *,
    kind: SurfaceType,
    surveyed_on: date,
    file: UploadFile,
) -> Survey:
    filename = _validate_upload(file)

    # 1. Parse and validate BEFORE touching the database.
    points = parse_survey_csv(file.file)
    if len(points) < settings.min_survey_points:
        raise FileValidationError(
            f"A surface needs at least {settings.min_survey_points} points; found {len(points)}"
        )

    # 2. Business rule (friendly message; the DB index is the real guard).
    if kind == SurfaceType.initial_topo and _initial_exists(db, project.id):
        raise ConflictError("This project already has an initial topo")

    # 3. One transaction: the survey and all its points are saved together or not at all.
    survey = Survey(
        project_id=project.id,
        kind=kind,
        surveyed_on=surveyed_on,
        source_filename=filename,
        point_count=len(points),
    )
    try:
        db.add(survey)
        db.flush()  # assigns survey.id without committing
        for chunk in points.iter_chunks(settings.insert_chunk_size):
            db.execute(
                insert(SurveyPoint),
                [{"survey_id": survey.id, "x": x, "y": y, "z": z} for x, y, z in chunk],
            )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        if ONE_INITIAL_INDEX in str(exc.orig):  # two uploads raced past the check above
            raise ConflictError("This project already has an initial topo") from exc
        raise
    except Exception:
        db.rollback()
        raise

    db.refresh(survey)  # load created_at
    return survey


def list_surveys(
    db: Session,
    project_id: int,
    *,
    kind: SurfaceType | None,
    limit: int,
    offset: int,
) -> list[Survey]:
    stmt = select(Survey).where(Survey.project_id == project_id)
    if kind is not None:
        stmt = stmt.where(Survey.kind == kind)
    stmt = stmt.order_by(Survey.surveyed_on, Survey.id).limit(limit).offset(offset)
    return list(db.scalars(stmt))


def get_survey(db: Session, project_id: int, survey_id: int) -> Survey | None:
    """Looks up by BOTH ids, so a survey of another project is simply 'not found'."""
    stmt = select(Survey).where(Survey.id == survey_id, Survey.project_id == project_id)
    return db.scalar(stmt)


def get_points_page(db: Session, survey: Survey, *, limit: int, offset: int) -> PointsPage:
    # Select plain columns, not ORM objects: far faster for large reads.
    rows = db.execute(
        select(SurveyPoint.x, SurveyPoint.y, SurveyPoint.z)
        .where(SurveyPoint.survey_id == survey.id)
        .order_by(SurveyPoint.id)
        .limit(limit)
        .offset(offset)
    ).all()
    return PointsPage(
        items=[PointRead(x=r.x, y=r.y, z=r.z) for r in rows],
        total=survey.point_count,
        limit=limit,
        offset=offset,
    )


def delete_survey(db: Session, survey: Survey) -> None:
    used = db.scalar(
        select(Computation.id)
        .where(
            or_(
                Computation.initial_survey_id == survey.id,
                Computation.progress_survey_id == survey.id,
            )
        )
        .limit(1)
    )
    if used is not None:
        # Deleting would null the computation's inputs and break traceability.
        raise ConflictError(
            "Survey is used by one or more computations. Delete those first."
        )
    db.delete(survey)  # the database cascades to survey_points
    db.commit()