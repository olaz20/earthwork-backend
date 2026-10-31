from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.api.deps import get_computation, get_db, get_project
from app.models import Computation, Project
from app.schemas.computation import (
    ComputationCreate,
    ComputationList,
    ComputationRead,
    ComputationStatus,
)
from app.services import computation_store as store
from app.services.computation_runner import run_computation

router = APIRouter(prefix="/projects/{project_id}/computations", tags=["computations"])


@router.post(
    "",
    response_model=ComputationRead,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Run an area / cut-fill volume computation",
)
def create_computation(
    payload: ComputationCreate,
    background: BackgroundTasks,
    response: Response,
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
):
    """Validates and records the run, then computes in the background.

    Poll `GET /projects/{id}/computations/{comp_id}` until `status` is `completed` or `failed`.
    """
    try:
        store.ensure_projected_crs(project)
        inputs = store.resolve_inputs(db, project.id, payload)
    except store.ComputationInputError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc

    row = store.create_pending(db, project.id, inputs, payload)
    background.add_task(run_computation, row.id)
    response.headers["Location"] = f"/projects/{project.id}/computations/{row.id}"
    return ComputationRead.from_row(row)


@router.get("", response_model=ComputationList, summary="List computations with status and results")
def list_computations(
    status_filter: ComputationStatus | None = Query(None, alias="status"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    project: Project = Depends(get_project),
    db: Session = Depends(get_db),
):
    rows, total = store.list_computations(db, project.id, status_filter, limit, offset)
    return ComputationList(
        items=[ComputationRead.from_row(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{comp_id}", response_model=ComputationRead, summary="One computation: inputs, status, results, error")
def read_computation(computation: Computation = Depends(get_computation)):
    return ComputationRead.from_row(computation)


@router.delete("/{comp_id}", status_code=status.HTTP_204_NO_CONTENT, summary="Remove a run")
def delete_computation(
    computation: Computation = Depends(get_computation),
    db: Session = Depends(get_db),
):
    if computation.status == ComputationStatus.running.value:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="computation is running; try again when it finishes")
    store.delete_computation(db, computation)
    return Response(status_code=status.HTTP_204_NO_CONTENT)