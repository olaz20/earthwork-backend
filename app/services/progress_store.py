"""Read-only queries behind the progress endpoints."""
from __future__ import annotations

from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Computation, Survey  # adjust import path if needed
from app.schemas.computation import ComputationMethod, ComputationStatus
from app.services.computation_store import INITIAL_KIND, PROGRESS_KIND
from app.services.progress_calc import SurveyRun


def completed_runs(
    db: Session,
    project_id: int,
    method: ComputationMethod | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[SurveyRun]:
    """One row per progress survey: its most recent completed computation, oldest survey first."""
    cond = [
        Computation.project_id == project_id,
        Computation.status == ComputationStatus.completed.value,
        Computation.progress_survey_id.is_not(None),
        Computation.fill_volume.is_not(None),
        Computation.cut_volume.is_not(None),
        Computation.fill_area.is_not(None),
        Computation.site_area.is_not(None),
    ]
    if method is not None:
        cond.append(Computation.method == method.value)

    ranked = (
        select(
            Computation.id.label("id"),
            func.row_number()
            .over(
                partition_by=Computation.progress_survey_id,
                order_by=(Computation.completed_at.desc().nulls_last(), Computation.id.desc()),
            )
            .label("rn"),
        )
        .where(*cond)
        .subquery()
    )

    stmt = (
        select(Computation, Survey.surveyed_on)
        .join(ranked, ranked.c.id == Computation.id)
        .join(Survey, Survey.id == Computation.progress_survey_id)
        .where(ranked.c.rn == 1)
        .order_by(Survey.surveyed_on, Computation.id)
    )
    if date_from is not None:
        stmt = stmt.where(Survey.surveyed_on >= date_from)
    if date_to is not None:
        stmt = stmt.where(Survey.surveyed_on <= date_to)

    return [
        SurveyRun(
            computation_id=c.id,
            survey_id=c.progress_survey_id,
            surveyed_on=surveyed_on,
            method=c.method,
            site_area=c.site_area,
            fill_area=c.fill_area,
            fill_volume=c.fill_volume,
            cut_volume=c.cut_volume,
        )
        for c, surveyed_on in db.execute(stmt).all()
    ]


def last_progress_survey(db: Session, project_id: int) -> tuple[int, date] | None:
    row = db.execute(
        select(Survey.id, Survey.surveyed_on)
        .where(Survey.project_id == project_id, Survey.kind == PROGRESS_KIND)
        .order_by(Survey.surveyed_on.desc(), Survey.id.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None


def progress_survey_count(db: Session, project_id: int) -> int:
    return (
        db.scalar(
            select(func.count())
            .select_from(Survey)
            .where(Survey.project_id == project_id, Survey.kind == PROGRESS_KIND)
        )
        or 0
    )


def initial_survey_date(db: Session, project_id: int) -> date | None:
    return db.scalar(
        select(Survey.surveyed_on).where(Survey.project_id == project_id, Survey.kind == INITIAL_KIND)
    )