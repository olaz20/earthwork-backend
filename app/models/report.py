from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    computation_id: Mapped[int | None] = mapped_column(
        ForeignKey("computations.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(String(150))
    format: Mapped[str] = mapped_column(String(10))  # "pdf", "xlsx"
    file_path: Mapped[str] = mapped_column(String(500))
    
    filename: Mapped[str] = mapped_column(String(255))  # name offered on download
    stored_name: Mapped[str] = mapped_column(String(100))  # name on disk (uuid)
    size_bytes: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )