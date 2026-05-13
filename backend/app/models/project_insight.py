"""ProjectInsight ORM model — one Claude-generated summary per project.

See ``SPEC_v1.1.md`` section 3 for the contract. One row per project
(``UNIQUE(project_id)``), created lazily on the first
``POST /projects/{id}/insights/refresh`` call. Cascade deletes with
the parent project.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.schemas.insight import InsightStatus

# Postgres ENUM type — the Alembic migration owns CREATE/DROP TYPE.
insight_status_enum = PGEnum(
    InsightStatus,
    name="insight_status",
    values_callable=lambda enum_cls: [m.value for m in enum_cls],
    create_type=False,
)


class ProjectInsight(Base):
    """A cached Claude-generated cross-interview summary for a project."""

    __tablename__ = "project_insights"
    __table_args__ = (
        UniqueConstraint("project_id", name="project_insights_project_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    summary_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Snapshot of the interview IDs that fed the last successful
    # generation. ``[]`` before the first run. Used to compute
    # ``is_stale`` server-side.
    interview_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)),
        nullable=False,
        default=list,
        server_default="{}",
    )

    status: Mapped[InsightStatus] = mapped_column(
        insight_status_enum,
        nullable=False,
        default=InsightStatus.idle,
        server_default=InsightStatus.idle.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
