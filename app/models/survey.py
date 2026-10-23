from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Enum, ForeignKey, String, func, Index, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.schemas.common import SurfaceType



from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.project import Project

ONE_INITIAL_INDEX = "uq_surveys_one_initial_per_project"

class Survey(Base):
    """One topographic survey: the initial one, or a progress (filled) one."""

    __tablename__ = "surveys"
    __table_args__ = (
        # Business rule enforced by the database: at most one initial topo per project
        Index(
            ONE_INITIAL_INDEX,
            "project_id",
            unique=True,
            postgresql_where=text("kind = 'initial_topo'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[SurfaceType] = mapped_column(
        Enum(SurfaceType, native_enum=False, length=30)
    )
    surveyed_on: Mapped[date] = mapped_column(Date)
    source_filename: Mapped[str | None] = mapped_column(String(255))
    point_count: Mapped[int] = mapped_column(default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="surveys")
    points: Mapped[list["SurveyPoint"]] = relationship(
        back_populates="survey", cascade="all, delete-orphan", passive_deletes=True
    )


class SurveyPoint(Base):
    __tablename__ = "survey_points"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    survey_id: Mapped[int] = mapped_column(
        ForeignKey("surveys.id", ondelete="CASCADE"), index=True
    )
    x: Mapped[float]
    y: Mapped[float]
    z: Mapped[float]

    survey: Mapped["Survey"] = relationship(back_populates="points")