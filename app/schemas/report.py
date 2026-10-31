from __future__ import annotations

import datetime as dt
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class ReportFormat(str, Enum):
    pdf = "pdf"
    xlsx = "xlsx"


class ReportCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    computation_id: int
    format: ReportFormat = ReportFormat.pdf
    title: str | None = Field(None, min_length=1, max_length=150, description="Default: '<project> - Earthwork report'")


class ReportRead(BaseModel):
    id: int
    project_id: int
    computation_id: int | None
    title: str
    format: ReportFormat
    filename: str
    size_bytes: int
    created_at: dt.datetime
    download_url: str

    @classmethod
    def from_row(cls, row, download_url: str) -> "ReportRead":
        return cls(
            id=row.id,
            project_id=row.project_id,
            computation_id=row.computation_id,
            title=row.title,
            format=row.format,
            filename=row.filename,
            size_bytes=row.size_bytes,
            created_at=row.created_at,
            download_url=download_url,
        )


class ReportList(BaseModel):
    items: list[ReportRead]
    total: int
    limit: int
    offset: int