from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Computation(Base):
    """One run of the area/volume calculation, with its inputs and results."""

    __tablename__ = "computations"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )

    # Inputs used (so any result can be traced and reproduced)
    initial_survey_id: Mapped[int | None] = mapped_column(
        ForeignKey("surveys.id", ondelete="SET NULL")
    )
    progress_survey_id: Mapped[int | None] = mapped_column(
        ForeignKey("surveys.id", ondelete="SET NULL")
    )
    site_boundary_id: Mapped[int | None] = mapped_column(
        ForeignKey("boundaries.id", ondelete="SET NULL")
    )
    fill_boundary_id: Mapped[int | None] = mapped_column(
        ForeignKey("boundaries.id", ondelete="SET NULL")
    )

    # Process
    status: Mapped[str] = mapped_column(String(20), default="pending")
    method: Mapped[str | None] = mapped_column(String(30))  # e.g. "grid", "tin"
    parameters: Mapped[dict | None] = mapped_column(JSONB)
    error: Mapped[str | None] = mapped_column(Text)

    # Results
    site_area: Mapped[float | None]
    fill_area: Mapped[float | None]
    fill_volume: Mapped[float | None]
    cut_volume: Mapped[float | None]

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Prediction(Base):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    computation_id: Mapped[int | None] = mapped_column(
        ForeignKey("computations.id", ondelete="SET NULL")
    )
    model_name: Mapped[str] = mapped_column(String(50))
    predicted_for: Mapped[date] = mapped_column(Date)
    predicted_fill_volume: Mapped[float | None]
    predicted_completion: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )