"""Collects everything a report needs from the database into a plain ReportContext."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Boundary, BoundaryPoint, Computation, Project, Survey
from app.schemas.computation import ComputationMethod
from app.services import progress_calc, progress_store
from app.services.report_render import InputRow, ReportContext


def _survey_row(db: Session, role: str, survey_id: int | None) -> InputRow:
    survey = db.get(Survey, survey_id) if survey_id is not None else None
    if survey is None:
        return InputRow(role, "-", None, "not set" if survey_id is None else "(deleted since the run)")
    detail = f"{survey.point_count:,} points"
    if survey.source_filename:
        detail = f"{survey.source_filename}, {detail}"
    return InputRow(role, f"#{survey.id}", survey.surveyed_on, detail)


def _boundary_row(db: Session, role: str, boundary_id: int | None) -> InputRow | None:
    if boundary_id is None:
        return None
    boundary = db.get(Boundary, boundary_id)
    if boundary is None:
        return InputRow(role, "-", None, "(deleted since the run)")
    vertices = db.scalar(
        select(func.count()).select_from(BoundaryPoint).where(BoundaryPoint.boundary_id == boundary.id)
    )
    return InputRow(role, f"#{boundary.id}", boundary.recorded_on, f"{vertices} vertices")


def build_context(db: Session, project: Project, comp: Computation, title: str) -> ReportContext:
    inputs = [
        _survey_row(db, "Initial survey", comp.initial_survey_id),
        _survey_row(db, "Progress survey", comp.progress_survey_id),
        _boundary_row(db, "Site boundary", comp.site_boundary_id),
        _boundary_row(db, "Fill boundary", comp.fill_boundary_id) or InputRow("Fill boundary", "-", None, "none (fill measured over the whole site)"),
    ]

    history = []
    progress = db.get(Survey, comp.progress_survey_id) if comp.progress_survey_id else None
    if progress is not None and comp.method in ("grid", "tin"):
        runs = progress_store.completed_runs(
            db, project.id, method=ComputationMethod(comp.method), date_to=progress.surveyed_on
        )
        history = progress_calc.build_points(runs)

    stored = comp.parameters or {}
    return ReportContext(
        title=title,
        project_name=project.name,
        project_description=project.description,
        crs=project.crs,
        length_unit=project.unit.value,
        computation_id=comp.id,
        method=comp.method,
        computed_at=comp.completed_at,
        generated_at=datetime.now(timezone.utc),
        site_area=comp.site_area,
        fill_area=comp.fill_area,
        fill_volume=comp.fill_volume,
        cut_volume=comp.cut_volume,
        inputs=inputs,
        settings=stored.get("resolved") or stored.get("requested") or {},
        diagnostics=stored.get("diagnostics") or {},
        history=history,
    )