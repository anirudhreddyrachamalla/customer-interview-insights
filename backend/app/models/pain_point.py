"""PainPoint ORM model — one row per Claude-extracted pain point."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

if TYPE_CHECKING:
    from app.models.interview import Interview


class PainPoint(Base):
    """A single pain point extracted from an interview transcript.

    ``severity`` is constrained to 1..5 at the database level via a
    CHECK constraint as well as in the Pydantic schema. The UI sorts by
    ``severity DESC, created_at ASC``; the service layer materializes
    that order so endpoints can return the list as-is.
    """

    __tablename__ = "pain_points"
    __table_args__ = (
        CheckConstraint(
            "severity >= 1 AND severity <= 5",
            name="pain_points_severity_range_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    interview_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interviews.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    text: Mapped[str] = mapped_column(String(500), nullable=False)
    supporting_quote: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp_start_sec: Mapped[float] = mapped_column(Float, nullable=False)
    timestamp_end_sec: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    interview: Mapped[Interview] = relationship(
        "Interview",
        back_populates="pain_points",
    )
