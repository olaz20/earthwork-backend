from datetime import datetime

from sqlalchemy import DateTime, String, Text, func, Enum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.schemas.common import LengthUnit
from app.db.base import Base



from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.survey import Survey
    from app.models.boundary import Boundary

class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(Text)
    crs: Mapped[str | None] = mapped_column(String(50))  # e.g. "EPSG:32631"
    unit: Mapped[LengthUnit] = mapped_column(
        Enum(LengthUnit, native_enum=False, length=20),
        default=LengthUnit.metre,
        server_default=LengthUnit.metre.value,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    surveys: Mapped[list["Survey"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )
    boundaries: Mapped[list["Boundary"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )