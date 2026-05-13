"""v1.1 — pain_point.type, interview source_kind/transcript_path, project_insights

Revision ID: c4d8b21f7a05
Revises: 8a1f3c9d2e10
Create Date: 2026-05-13 12:00:00.000000+00:00

Bundles the v1.1 schema changes into a single migration (per
SPEC_v1.1.md):

1. ``pain_point_type`` ENUM + ``pain_points.type`` column (backfilled
   to ``'pain_point'`` then set NOT NULL).
2. ``interview_source_kind`` ENUM + ``interviews.source_kind`` column
   (backfilled to ``'audio'`` then set NOT NULL), ``audio_path``
   nullability relaxed, ``transcript_path`` column added.
3. ``insight_status`` ENUM + ``project_insights`` table.

Downgrade reverses cleanly on an empty / pristine database. It refuses
to restore ``audio_path NOT NULL`` if any row would lose data (i.e.
any ``source_kind='transcript'`` interview exists), bailing with a
runtime error rather than silently dropping rows.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4d8b21f7a05"
down_revision: str | None = "8a1f3c9d2e10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


pain_point_type_enum = postgresql.ENUM(
    "pain_point",
    "workaround",
    "suggestion",
    name="pain_point_type",
    create_type=False,
)
interview_source_kind_enum = postgresql.ENUM(
    "audio",
    "transcript",
    name="interview_source_kind",
    create_type=False,
)
insight_status_enum = postgresql.ENUM(
    "idle",
    "generating",
    "failed",
    name="insight_status",
    create_type=False,
)


def upgrade() -> None:
    bind = op.get_bind()

    # ------------------------------------------------------------------
    # 1. pain_points.type
    # ------------------------------------------------------------------
    pain_point_type_enum.create(bind, checkfirst=True)
    op.add_column(
        "pain_points",
        sa.Column("type", pain_point_type_enum, nullable=True),
    )
    op.execute("UPDATE pain_points SET type = 'pain_point' WHERE type IS NULL")
    op.alter_column("pain_points", "type", nullable=False)

    # ------------------------------------------------------------------
    # 2. interviews.source_kind + audio_path nullability + transcript_path
    # ------------------------------------------------------------------
    interview_source_kind_enum.create(bind, checkfirst=True)
    op.add_column(
        "interviews",
        sa.Column("source_kind", interview_source_kind_enum, nullable=True),
    )
    op.execute("UPDATE interviews SET source_kind = 'audio' WHERE source_kind IS NULL")
    op.alter_column("interviews", "source_kind", nullable=False)
    op.alter_column("interviews", "audio_path", nullable=True)
    op.add_column(
        "interviews",
        sa.Column("transcript_path", sa.String(length=1024), nullable=True),
    )

    # ------------------------------------------------------------------
    # 3. project_insights
    # ------------------------------------------------------------------
    insight_status_enum.create(bind, checkfirst=True)
    op.create_table(
        "project_insights",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("summary_markdown", sa.Text(), nullable=True),
        sa.Column(
            "interview_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
            nullable=False,
        ),
        sa.Column(
            "status",
            insight_status_enum,
            server_default="idle",
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="project_insights_project_id_key"),
    )
    op.create_index(
        op.f("ix_project_insights_project_id"),
        "project_insights",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Refuse to downgrade if any row would lose data when audio_path is
    # restored to NOT NULL (i.e. any transcript-sourced interview).
    transcript_rows = bind.execute(
        sa.text("SELECT COUNT(*) FROM interviews WHERE source_kind = 'transcript'")
    ).scalar_one()
    if transcript_rows:
        raise RuntimeError(
            f"refusing to downgrade: {transcript_rows} interview(s) have "
            "source_kind='transcript' and would lose data when audio_path is "
            "restored to NOT NULL. Delete or convert them first."
        )

    # ------------------------------------------------------------------
    # 3. project_insights
    # ------------------------------------------------------------------
    op.drop_index(op.f("ix_project_insights_project_id"), table_name="project_insights")
    op.drop_table("project_insights")
    insight_status_enum.drop(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 2. interviews
    # ------------------------------------------------------------------
    op.drop_column("interviews", "transcript_path")
    # Restore audio_path NOT NULL. Safe per the transcript-row check above.
    op.alter_column("interviews", "audio_path", nullable=False)
    op.drop_column("interviews", "source_kind")
    interview_source_kind_enum.drop(bind, checkfirst=True)

    # ------------------------------------------------------------------
    # 1. pain_points
    # ------------------------------------------------------------------
    op.drop_column("pain_points", "type")
    pain_point_type_enum.drop(bind, checkfirst=True)
