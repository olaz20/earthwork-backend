from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.common import SurfaceType


class SurveyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    kind: SurfaceType
    surveyed_on: date
    source_filename: str | None
    point_count: int
    created_at: datetime


class PointRead(BaseModel):
    x: float
    y: float
    z: float


class PointsPage(BaseModel):
    items: list[PointRead]
    total: int
    limit: int
    offset: int