from datetime import date, datetime

from sqlalchemy import (
    BigInteger, Date, DateTime, Enum, ForeignKey, UniqueConstraint, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.schemas.common import BoundaryType



from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.project import Project
    from app.models.boundary import Boundary

class Boundary(Base):
    """A polygon: the site boundary, or a progress fill boundary."""

    __tablename__ = "boundaries"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[BoundaryType] = mapped_column(
        Enum(BoundaryType, native_enum=False, length=30)
    )
    recorded_on: Mapped[date] = mapped_column(Date)
    # Which progress survey this fill boundary belongs to (optional)
    survey_id: Mapped[int | None] = mapped_column(
        ForeignKey("surveys.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    project: Mapped["Project"] = relationship(back_populates="boundaries")
    points: Mapped[list["BoundaryPoint"]] = relationship(
        back_populates="boundary",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="BoundaryPoint.seq",
    )


class BoundaryPoint(Base):
    __tablename__ = "boundary_points"
    __table_args__ = (UniqueConstraint("boundary_id", "seq"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    boundary_id: Mapped[int] = mapped_column(
        ForeignKey("boundaries.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int]  # vertex order around the polygon
    x: Mapped[float]
    y: Mapped[float]

    boundary: Mapped["Boundary"] = relationship(back_populates="points")