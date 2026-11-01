from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_db, get_project_or_404, get_report_or_404
from app.models import Project
from app.models.report import Report
from app.schemas.report import ReportCreate, ReportList, ReportRead
from app.services import report_file as report_files
from app.services import report_store
from app.services.report_render import MEDIA_TYPES

router = APIRouter(prefix="/projects/{project_id}/reports", tags=["reports"])


def _read(request: Request, row: Report) -> ReportRead:
    url = request.url_for("download_report", project_id=row.project_id, report_id=row.id)
    return ReportRead.from_row(row, download_url=str(url))


@router.post(
    "",
    response_model=ReportRead,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a report for a computation",
)
def create_report(
    payload: ReportCreate,
    request: Request,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    try:
        row = report_store.generate(db, project, payload)
    except report_store.ReportNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except report_store.ReportNotReady as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _read(request, row)


@router.get("", response_model=ReportList, summary="List reports")
def list_reports(
    request: Request,
    computation_id: int | None = Query(None, description="Only reports for this computation"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    rows, total = report_store.list_reports(db, project.id, computation_id, limit, offset)
    return ReportList(items=[_read(request, r) for r in rows], total=total, limit=limit, offset=offset)


@router.get("/{report_id}/download", name="download_report", summary="Download the report file")
def download_report(report: Report = Depends(get_report_or_404)):
    try:
        path = report_files.resolve(report.project_id, report.stored_name)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report file not found")
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="report file is missing from storage")
    return FileResponse(path, media_type=MEDIA_TYPES.get(report.format, "application/octet-stream"), filename=report.filename)