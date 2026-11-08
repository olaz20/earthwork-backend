from __future__ import annotations

import datetime as dt
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.computation import ComputationMethod


class PredictionMetric(str, Enum):
    fill_volume = "fill_volume"
    fill_area = "fill_area"
    net_volume = "net_volume"


class PredictionMethod(str, Enum):
    linear = "linear"
    recent_rate = "recent_rate"


class PredictionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    metric: PredictionMetric = Field(
        PredictionMetric.fill_volume, description="What to forecast (volumes in unit³, area in unit²)"
    )
    method: PredictionMethod = Field(
        PredictionMethod.linear,
        description="linear: trend over all surveys. recent_rate: trend over the last few surveys "
        "only (the current pace).",
    )
    recent_points: int = Field(3, ge=2, le=20, description="Surveys used by recent_rate")
    horizon_days: int = Field(90, ge=1, le=730, description="How far past today to forecast")
    step_days: int = Field(7, ge=1, le=90, description="Spacing of the forecast points")
    confidence: float = Field(0.9, ge=0.5, le=0.99, description="Level of the prediction interval")
    target_value: float | None = Field(
        None, gt=0,
        description="Design total to reach (e.g. the planned fill volume). Enables the completion date.",
    )
    computation_method: ComputationMethod | None = Field(
        None, description="Only use computations run with this method, so the history is like-for-like"
    )


class HistoryPoint(BaseModel):
    date: dt.date
    computation_id: int
    actual: float
    fitted: float


class ForecastPoint(BaseModel):
    date: dt.date
    value: float
    lower: float | None = None
    upper: float | None = None


class CompletionEstimate(BaseModel):
    target_value: float
    status: str = Field(description="projected | reached | unreachable | beyond_limit")
    estimate: dt.date | None = None
    earliest: dt.date | None = Field(None, description="Upper interval bound reaches the target")
    latest: dt.date | None = Field(None, description="Lower interval bound reaches the target; null = not bounded")
    days_remaining: int | None = Field(None, description="From today; negative = the trend says it should be done already")


class PredictionSummary(BaseModel):
    points_used: int
    points_in_fit: int
    first_observation: dt.date
    last_observation: dt.date
    last_value: float
    rate_per_day: float
    rate_per_week: float
    r_squared: float | None
    residual_std: float | None
    confidence: float
    interval_available: bool
    warnings: list[str]


class PredictionRead(BaseModel):
    id: int
    project_id: int
    metric: PredictionMetric
    method: PredictionMethod
    length_unit: str
    created_at: dt.datetime
    parameters: dict[str, Any]
    summary: PredictionSummary
    completion: CompletionEstimate | None
    history: list[HistoryPoint]
    forecast: list[ForecastPoint]

    @classmethod
    def from_row(cls, row, length_unit: str) -> "PredictionRead":
        result = row.result
        return cls(
            id=row.id,
            project_id=row.project_id,
            metric=row.metric,
            method=row.method,
            length_unit=length_unit,
            created_at=row.created_at,
            parameters=row.parameters.get("requested", {}),
            summary=result["summary"],
            completion=result.get("completion"),
            history=result["history"],
            forecast=result["forecast"],
        )


class PredictionList(BaseModel):
    items: list[PredictionRead]
    total: int
    limit: int
    offset: int