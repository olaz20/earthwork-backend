from __future__ import annotations

import datetime as dt
import math

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

from app.schemas.common import BoundaryType

MAX_VERTICES = 100_000


def _shoelace_area(points: list) -> float:
    """Unsigned polygon area from ordered vertices (planar, in project units²)."""
    total = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        total += points[i].x * points[j].y - points[j].x * points[i].y
    return abs(total) / 2.0


class BoundaryPointIn(BaseModel):
    x: float = Field(allow_inf_nan=False)
    y: float = Field(allow_inf_nan=False)


class BoundaryPointOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    seq: int
    x: float
    y: float


class BoundaryCreate(BaseModel):
    """JSON body for creating a boundary. A file upload is parsed into this same shape."""

    model_config = ConfigDict(extra="forbid")

    kind: BoundaryType
    recorded_on: dt.date
    survey_id: int | None = Field(
        None, description="Progress survey this fill boundary belongs to (optional)"
    )
    points: list[BoundaryPointIn] = Field(
        min_length=3,
        max_length=MAX_VERTICES,
        description="Vertices in order around the polygon. Do not repeat the first point at the end.",
    )

    @model_validator(mode="after")
    def _clean_and_check_polygon(self):
        pts = list(self.points)

        # Drop consecutive duplicates (common in CSV exports)
        deduped = [pts[0]]
        for p in pts[1:]:
            if not (math.isclose(p.x, deduped[-1].x) and math.isclose(p.y, deduped[-1].y)):
                deduped.append(p)

        # Drop the closing vertex if the file repeated the first point
        if len(deduped) > 1 and math.isclose(deduped[0].x, deduped[-1].x) and math.isclose(
            deduped[0].y, deduped[-1].y
        ):
            deduped.pop()

        if len(deduped) < 3:
            raise ValueError("a boundary needs at least 3 distinct vertices")
        if _shoelace_area(deduped) <= 1e-9:
            raise ValueError("boundary has zero area (vertices are collinear)")

        self.points = deduped
        return self


class BoundaryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    kind: BoundaryType
    recorded_on: dt.date
    survey_id: int | None
    created_at: dt.datetime
    vertex_count: int = Field(0, description="Number of vertices")


class BoundaryDetail(BoundaryRead):
    points: list[BoundaryPointOut]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def area(self) -> float:
        """Polygon area in project units², from the stored vertices."""
        return _shoelace_area(self.points) if len(self.points) >= 3 else 0.0


class BoundaryList(BaseModel):
    items: list[BoundaryRead]
    total: int
    limit: int
    offset: int