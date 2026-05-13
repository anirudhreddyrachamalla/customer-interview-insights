"""Interview ORM model — one row per uploaded customer interview."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ENUM as PGEnum
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base
from app.schemas.interview import InterviewSourceKind, InterviewStatus, InterviewType

if TYPE_CHECKING:
    from app.models.pain_point import PainPoint


# Reuse a single PG ENUM instance per type so Alembic autogenerate and
# migrations see a consistent name. ``create_type=False`` keeps SQLAlchemy
# from trying to recreate the type — the Alembic migration owns the
# CREATE TYPE / DROP TYPE statements.
interview_type_enum = PGEnum(
    InterviewType,
    name="interview_type",
    values_callable=lambda enum_cls: [m.value for m in enum_cls],
    create_type=False,
)
interview_status_enum = PGEnum(
    InterviewStatus,
    name="interview_status",
    values_callable=lambda enum_cls: [m.value for m in enum_cls],
    create_type=False,
)
interview_source_kind_enum = PGEnum(
    InterviewSourceKind,
    name="interview_source_kind",
    values_callable=lambda enum_cls: [m.value for m in enum_cls],
    create_type=False,
)


class Interview(Base):
    """An uploaded customer interview and its processing state.

    Mirrors ``SPEC.md`` -> Data model -> Interview. The audio file lives
    under ``backend/storage/audio/`` on the filesystem; only its path
    and filename are stored here. ``transcript_text`` /
    ``transcript_segments`` / pain points are populated by the
    background pipeline (see ``app.services.pipeline``).

    v1.1 added ``source_kind`` and ``transcript_path``; v1.2 narrows
    the accepted transcript extension to ``.vtt``. When
    ``source_kind == 'transcript'`` the upload is a ``.vtt`` file
    rather than an audio file; ``audio_path`` is NULL in that case and
    ``transcript_path`` carries the on-disk transcript location.
    """

    __tablename__ = "interviews"

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

    # v1.1 — distinguishes audio vs. transcript uploads. Always set at
    # upload time; never NULL after migration backfill.
    source_kind: Mapped[InterviewSourceKind] = mapped_column(
        interview_source_kind_enum,
        nullable=False,
        default=InterviewSourceKind.audio,
        server_default=InterviewSourceKind.audio.value,
    )

    # NULL when ``source_kind='transcript'``. ``audio_filename`` keeps
    # its name and carries the transcript filename for transcript
    # uploads — see locked decision #3 in SPEC_v1.1.md.
    audio_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    audio_filename: Mapped[str] = mapped_column(String(512), nullable=False)
    audio_duration_sec: Mapped[float | None] = mapped_column(Float, nullable=True)

    # v1.1 — absolute path of the uploaded transcript file when
    # ``source_kind='transcript'``. NULL for ``source_kind='audio'``.
    transcript_path: Mapped[str | None] = mapped_column(String(1024), nullable=True)

    type: Mapped[InterviewType] = mapped_column(interview_type_enum, nullable=False)
    demographics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    transcript_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    transcript_segments: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONB, nullable=True)

    # Optional free-text notes captured by the interviewer at upload time.
    # Display-only — never fed into the Claude extraction pipeline. Empty
    # strings / whitespace-only are normalized to NULL at the endpoint
    # layer so the DB only ever stores a non-empty string or NULL.
    meeting_notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[InterviewStatus] = mapped_column(
        interview_status_enum,
        nullable=False,
        default=InterviewStatus.uploaded,
        server_default=InterviewStatus.uploaded.value,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    pain_points: Mapped[list[PainPoint]] = relationship(
        "PainPoint",
        back_populates="interview",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
