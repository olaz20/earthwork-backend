from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ComputationStatus(str, Enum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


class ComputationMethod(str, Enum):
    grid = "grid"
    tin = "tin"


class Interpolation(str, Enum):
    linear = "linear"
    idw = "idw"
    nearest = "nearest"


class Extrapolation(str, Enum):
    idw = "idw"
    nearest = "nearest"
    none = "none"


class CutScope(str, Enum):
    site = "site"
    fill_boundary = "fill_boundary"


class ComputationParameters(BaseModel):
    """All lengths are in the project's unit."""

    model_config = ConfigDict(extra="forbid")

    cell_size: float | None = Field(
        None, gt=0, description="Grid method only. Auto-chosen from site area and point spacing if omitted."
    )
    interpolation: Interpolation = Interpolation.linear
    extrapolation: Extrapolation = Field(
        Extrapolation.idw,
        description="How elevations are extended from the survey hull out to the site boundary. "
        "'none' fails if the survey does not cover the site.",
    )
    max_extrapolation_distance: float | None = Field(
        None, gt=0, description="Fail if the boundary is further than this from the nearest survey point."
    )
    idw_power: float = Field(2.0, gt=0, le=10)
    idw_neighbors: int = Field(12, ge=1, le=64)
    boundary_spacing: float | None = Field(
        None, gt=0, description="Spacing of the densified site-boundary vertices used for extrapolation."
    )
    dz_tolerance: float = Field(
        0.0, ge=0, description="|progress - initial| at or below this is treated as no change (survey noise)."
    )
    cut_scope: CutScope = Field(
        CutScope.site,
        description="With a fill boundary: 'site' reports cut anywhere on site, "
        "'fill_boundary' reports cut only inside the fill polygon.",
    )
    max_cells: int = Field(4_000_000, ge=1_000, le=50_000_000)


class ComputationCreate(BaseModel):
    """Omitted inputs are resolved from the project (and the choice is stored on the run)."""

    model_config = ConfigDict(extra="forbid")

    initial_survey_id: int | None = Field(None, description="Default: the project's initial topo.")
    progress_survey_id: int | None = Field(None, description="Default: the latest progress survey.")
    site_boundary_id: int | None = Field(None, description="Default: the latest site boundary.")
    fill_boundary_id: int | None = Field(
        None, description="Default: the latest fill boundary linked to the progress survey, if any."
    )
    method: ComputationMethod = ComputationMethod.grid
    parameters: ComputationParameters = Field(default_factory=ComputationParameters)

    @model_validator(mode="after")
    def _distinct_surveys(self):
        if (
            self.initial_survey_id is not None
            and self.initial_survey_id == self.progress_survey_id
        ):
            raise ValueError("initial_survey_id and progress_survey_id must differ")
        return self


class ComputationInputs(BaseModel):
    initial_survey_id: int | None
    progress_survey_id: int | None
    site_boundary_id: int | None
    fill_boundary_id: int | None


class ComputationResults(BaseModel):
    site_area: float
    fill_area: float
    fill_volume: float
    cut_volume: float
    net_volume: float = Field(description="fill_volume - cut_volume")


class ComputationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    status: ComputationStatus
    method: str | None
    inputs: ComputationInputs
    parameters: dict[str, Any] | None = Field(None, description="Parameters as requested")
    resolved_parameters: dict[str, Any] | None = Field(
        None, description="Parameters actually used (auto values filled in); set once the run starts"
    )
    results: ComputationResults | None = None
    diagnostics: dict[str, Any] | None = None
    error: str | None = None
    created_at: datetime
    completed_at: datetime | None = None

    @classmethod
    def from_row(cls, row) -> "ComputationRead":
        stored = row.parameters or {}
        results = None
        if row.status == ComputationStatus.completed.value and row.fill_volume is not None:
            results = ComputationResults(
                site_area=row.site_area,
                fill_area=row.fill_area,
                fill_volume=row.fill_volume,
                cut_volume=row.cut_volume,
                net_volume=row.fill_volume - row.cut_volume,
            )
        return cls(
            id=row.id,
            project_id=row.project_id,
            status=row.status,
            method=row.method,
            inputs=ComputationInputs(
                initial_survey_id=row.initial_survey_id,
                progress_survey_id=row.progress_survey_id,
                site_boundary_id=row.site_boundary_id,
                fill_boundary_id=row.fill_boundary_id,
            ),
            parameters=stored.get("requested"),
            resolved_parameters=stored.get("resolved"),
            results=results,
            diagnostics=stored.get("diagnostics"),
            error=row.error,
            created_at=row.created_at,
            completed_at=row.completed_at,
        )


class ComputationList(BaseModel):
    items: list[ComputationRead]
    total: int
    limit: int
    offset: int