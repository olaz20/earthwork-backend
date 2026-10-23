from datetime import datetime
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    model_validator,
)

from app.schemas.common import LengthUnit

# Reusable constrained types: validation lives in one place
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Crs = Annotated[
    str,
    StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^EPSG:\d{4,6}$"),
]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)]


class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    description: Description | None = None
    crs: Crs | None = Field(default=None, examples=["EPSG:32631"])
    unit: LengthUnit = LengthUnit.metre


class ProjectUpdate(BaseModel):
    """PATCH body. Every field is optional; only sent fields are changed."""

    model_config = ConfigDict(extra="forbid")

    name: Name | None = None
    description: Description | None = None
    crs: Crs | None = None
    unit: LengthUnit | None = None

    @model_validator(mode="after")
    def check_patch(self):
        if not self.model_fields_set:
            raise ValueError("Provide at least one field to update")
        # name and unit are NOT NULL in the database; reject explicit nulls
        for field in ("name", "unit"):
            if field in self.model_fields_set and getattr(self, field) is None:
                raise ValueError(f"{field} cannot be null")
        return self


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None
    crs: str | None
    unit: LengthUnit
    created_at: datetime


class ProjectCounts(BaseModel):
    surveys: int
    boundaries: int
    computations: int


class ProjectDetail(ProjectRead):
    counts: ProjectCounts