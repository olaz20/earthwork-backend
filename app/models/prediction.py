from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Prediction(Base):
    """A forecast generated from a project's computation history (a frozen snapshot)."""

    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    metric: Mapped[str] = mapped_column(String(30))  # fill_volume | fill_area | net_volume
    method: Mapped[str] = mapped_column(String(30))  # linear | recent_rate
    target_value: Mapped[float | None]
    predicted_completion_date: Mapped[date | None] = mapped_column(Date)
    parameters: Mapped[dict] = mapped_column(JSONB)  # {"requested": ..., "resolved": ...}
    result: Mapped[dict] = mapped_column(JSONB)  # history, forecast, summary, completion
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )