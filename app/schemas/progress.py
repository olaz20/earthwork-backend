from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, Field

from app.schemas.computation import ComputationMethod


class ProgressPoint(BaseModel):
    """One progress survey, represented by its latest completed computation."""

    date: dt.date = Field(description="Date of the progress survey (surveyed_on)")
    survey_id: int
    computation_id: int
    method: str | None
    site_area: float
    fill_area: float
    fill_volume: float
    cut_volume: float
    net_volume: float = Field(description="fill_volume - cut_volume")
    percent_complete_area: float = Field(description="fill_area / site_area x 100, clamped to 0-100")
    fill_volume_change: float | None = Field(None, description="Change since the previous point")
    fill_area_change: float | None = None
    days_since_previous: int | None = None


class ProgressSeries(BaseModel):
    project_id: int
    length_unit: str = Field(description="Project length unit: areas are unit^2, volumes unit^3")
    method: ComputationMethod | None = Field(None, description="Method filter that was applied")
    count: int
    points: list[ProgressPoint]


class ProgressSummary(BaseModel):
    project_id: int
    length_unit: str
    has_data: bool = Field(description="False until at least one computation has completed")

    # Latest totals (from the most recent progress survey that has a completed computation)
    latest: ProgressPoint | None = None

    # Completion
    percent_complete_area: float | None = Field(None, description="fill_area / site_area x 100")
    target_volume: float | None = Field(None, description="Echo of the target_volume query parameter")
    percent_complete_volume: float | None = Field(
        None, description="fill_volume / target_volume x 100. Not clamped: >100 means over-filled. "
        "Null unless target_volume is supplied."
    )

    # Survey dates
    initial_survey_date: dt.date | None = None
    last_survey_date: dt.date | None = Field(None, description="Most recent progress survey, computed or not")
    last_survey_id: int | None = None
    latest_survey_computed: bool = Field(
        description="False when a newer progress survey exists that has no completed computation yet"
    )
    days_since_start: int | None = Field(None, description="Initial survey -> latest computed survey")

    # Activity
    progress_surveys: int
    computed_surveys: int
    fill_volume_change: float | None = Field(None, description="Latest vs previous computed survey")
    fill_area_change: float | None = None