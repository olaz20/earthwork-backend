"""Report orchestration: validate -> build context -> render -> write file -> record row."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Computation, Project
from app.models.report import Report
from app.schemas.computation import ComputationStatus
from app.schemas.report import ReportCreate
from app.services import report_file as report_files
from app.services.report_context import build_context
from app.services.report_render import RENDERERS


class ReportNotFound(LookupError):
    """Referenced computation does not exist in this project."""


class ReportNotReady(RuntimeError):
    """The computation has no results yet (pending, running or failed)."""


def generate(db: Session, project: Project, payload: ReportCreate) -> Report:
    comp = db.get(Computation, payload.computation_id)
    if comp is None or comp.project_id != project.id:
        raise ReportNotFound(f"computation {payload.computation_id} does not exist in this project")
    if comp.status != ComputationStatus.completed.value or comp.fill_volume is None:
        raise ReportNotReady(
            f"computation {comp.id} is '{comp.status}'; reports need a completed computation"
        )

    fmt = payload.format.value
    title = payload.title or f"{project.name} - Earthwork report"
    ctx = build_context(db, project, comp, title)
    content = RENDERERS[fmt](ctx)  # CPU-bound, sync route runs in the threadpool

    stored_name = report_files.new_stored_name(fmt)
    report_files.save(project.id, stored_name, content)
    row = Report(
        project_id=project.id,
        computation_id=comp.id,
        title=title,
        format=fmt,
        filename=f"{report_files.slugify(project.name)}-computation-{comp.id}-{ctx.generated_at:%Y%m%d-%H%M}.{fmt}",
        stored_name=stored_name,
        size_bytes=len(content),
    )
    try:
        db.add(row)
        db.commit()
    except BaseException:
        db.rollback()
        report_files.remove(project.id, stored_name)  # no orphan file without a row
        raise
    db.refresh(row)
    return row


def list_reports(
    db: Session, project_id: int, computation_id: int | None, limit: int, offset: int
) -> tuple[list[Report], int]:
    cond = [Report.project_id == project_id]
    if computation_id is not None:
        cond.append(Report.computation_id == computation_id)
    total = db.scalar(select(func.count()).select_from(Report).where(*cond)) or 0
    rows = db.scalars(
        select(Report).where(*cond).order_by(Report.created_at.desc(), Report.id.desc()).limit(limit).offset(offset)
    ).all()
    return list(rows), total