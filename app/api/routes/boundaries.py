from datetime import date

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.api.deps import get_boundary_or_404, get_db, get_project_or_404
from app.models.boundary import Boundary
from app.models.project import Project
from app.schemas.boundary import (
    BoundaryCreate,
    BoundaryDetail,
    BoundaryList,
    BoundaryPointOut,
    BoundaryRead,
)
from app.schemas.common import BoundaryType
from app.services import boundary_service
from app.services.boundary_parser import BoundaryFileError, parse_vertices

router = APIRouter(prefix="/projects/{project_id}/boundaries", tags=["boundaries"])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # ~ 400k vertices of text; the vertex cap is 100k


def _read(boundary: Boundary, vertex_count: int) -> BoundaryRead:
    return BoundaryRead.model_validate(boundary).model_copy(update={"vertex_count": vertex_count})


def _detail(boundary: Boundary) -> BoundaryDetail:
    return BoundaryDetail(
        id=boundary.id,
        project_id=boundary.project_id,
        kind=boundary.kind,
        recorded_on=boundary.recorded_on,
        survey_id=boundary.survey_id,
        created_at=boundary.created_at,
        vertex_count=len(boundary.points),
        points=[BoundaryPointOut.model_validate(p) for p in boundary.points],
    )


def _create(
    db: Session, project: Project, payload: BoundaryCreate, response: Response
) -> BoundaryRead:
    try:
        boundary, count = boundary_service.create_boundary(db, project.id, payload)
    except boundary_service.BoundaryError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    response.headers["Location"] = f"/projects/{project.id}/boundaries/{boundary.id}"
    return _read(boundary, count)


@router.post(
    "",
    response_model=BoundaryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Upload boundary vertices from a CSV/TXT file",
)
def upload_boundary(
    response: Response,
    file: UploadFile = File(..., description="x,y vertices in order around the polygon (CSV/TXT)"),
    kind: BoundaryType = Form(...),
    recorded_on: date = Form(...),
    survey_id: int | None = Form(None, description="Progress survey a fill boundary belongs to"),
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    """Accepts `x,y` or `easting,northing` columns (header optional for exactly two columns).

    Repeated closing vertices and consecutive duplicates are cleaned up; degenerate polygons
    are rejected with a 422 that says why.
    """
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"file is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )
    try:
        vertices = parse_vertices(data)
        payload = BoundaryCreate(
            kind=kind,
            recorded_on=recorded_on,
            survey_id=survey_id,
            points=[{"x": x, "y": y} for x, y in vertices],
        )
    except BoundaryFileError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except ValidationError as exc:
        message = "; ".join(e["msg"].removeprefix("Value error, ") for e in exc.errors())
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message) from exc
    return _create(db, project, payload, response)


@router.post(
    "/json",
    response_model=BoundaryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a boundary from a JSON list of vertices",
)
def create_boundary_json(
    payload: BoundaryCreate,
    response: Response,
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    return _create(db, project, payload, response)


@router.get("", response_model=BoundaryList, summary="List boundaries, filterable by kind")
def list_boundaries(
    kind: BoundaryType | None = Query(None, description="site or fill"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(get_project_or_404),
    db: Session = Depends(get_db),
):
    rows, total = boundary_service.list_boundaries(db, project.id, kind, limit, offset)
    return BoundaryList(
        items=[_read(b, n) for b, n in rows], total=total, limit=limit, offset=offset
    )


@router.get("/{boundary_id}", response_model=BoundaryDetail, summary="Boundary with ordered vertices")
def read_boundary(boundary: Boundary = Depends(get_boundary_or_404)):
    return _detail(boundary)


@router.delete(
    "/{boundary_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Delete a boundary"
)
def delete_boundary(
    boundary: Boundary = Depends(get_boundary_or_404),
    db: Session = Depends(get_db),
):
    boundary_service.delete_boundary(db, boundary)
    return Response(status_code=status.HTTP_204_NO_CONTENT)