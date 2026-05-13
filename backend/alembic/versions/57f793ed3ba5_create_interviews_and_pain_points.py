"""create interviews and pain_points

Revision ID: 57f793ed3ba5
Revises: affaa1b95abd
Create Date: 2026-05-12 12:29:11.990913+00:00

Two Postgres-native ENUM types are introduced (``interview_type`` and
``interview_status``). The model attaches them via
``PGEnum(..., create_type=False)`` so this migration owns the
``CREATE TYPE`` / ``DROP TYPE`` statements explicitly — they run
*before* the table and *after* the table on the inverse direction.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '57f793ed3ba5'
down_revision: str | None = 'affaa1b95abd'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


interview_type_enum = postgresql.ENUM(
    'problem_validation',
    name='interview_type',
    create_type=False,
)
interview_status_enum = postgresql.ENUM(
    'uploaded',
    'transcribing',
    'analyzing',
    'completed',
    'failed',
    name='interview_status',
    create_type=False,
)


def upgrade() -> None:
    # Create the Postgres ENUM types first; the column DDL below
    # references them by name.
    interview_type_enum.create(op.get_bind(), checkfirst=True)
    interview_status_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        'interviews',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('project_id', sa.UUID(), nullable=False),
        sa.Column('audio_path', sa.String(length=1024), nullable=False),
        sa.Column('audio_filename', sa.String(length=512), nullable=False),
        sa.Column('audio_duration_sec', sa.Float(), nullable=True),
        sa.Column('type', interview_type_enum, nullable=False),
        sa.Column(
            'demographics',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column('transcript_text', sa.Text(), nullable=True),
        sa.Column(
            'transcript_segments',
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            'status',
            interview_status_enum,
            server_default='uploaded',
            nullable=False,
        ),
        sa.Column('error_message', sa.Text(), nullable=True),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_interviews_project_id'),
        'interviews',
        ['project_id'],
        unique=False,
    )

    op.create_table(
        'pain_points',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('interview_id', sa.UUID(), nullable=False),
        sa.Column('text', sa.String(length=500), nullable=False),
        sa.Column('supporting_quote', sa.Text(), nullable=False),
        sa.Column('timestamp_start_sec', sa.Float(), nullable=False),
        sa.Column('timestamp_end_sec', sa.Float(), nullable=False),
        sa.Column('severity', sa.Integer(), nullable=False),
        sa.Column(
            'created_at',
            sa.DateTime(timezone=True),
            server_default=sa.text('now()'),
            nullable=False,
        ),
        sa.CheckConstraint(
            'severity >= 1 AND severity <= 5',
            name='pain_points_severity_range_check',
        ),
        sa.ForeignKeyConstraint(
            ['interview_id'], ['interviews.id'], ondelete='CASCADE'
        ),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_pain_points_interview_id'),
        'pain_points',
        ['interview_id'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f('ix_pain_points_interview_id'), table_name='pain_points')
    op.drop_table('pain_points')
    op.drop_index(op.f('ix_interviews_project_id'), table_name='interviews')
    op.drop_table('interviews')

    # Drop ENUM types last so no column depends on them.
    interview_status_enum.drop(op.get_bind(), checkfirst=True)
    interview_type_enum.drop(op.get_bind(), checkfirst=True)
