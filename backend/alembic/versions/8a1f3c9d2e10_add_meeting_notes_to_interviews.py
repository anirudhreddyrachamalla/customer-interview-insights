"""add meeting_notes to interviews

Revision ID: 8a1f3c9d2e10
Revises: 57f793ed3ba5
Create Date: 2026-05-12 14:00:00.000000+00:00

Adds an optional ``meeting_notes`` ``TEXT`` column to ``interviews``.
The column is ``nullable=True`` with no default; existing rows become
NULL automatically (no backfill needed). The endpoint layer enforces a
10,000-character cap and normalizes empty / whitespace-only values to
NULL before insert.
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = '8a1f3c9d2e10'
down_revision: str | None = '57f793ed3ba5'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        'interviews',
        sa.Column('meeting_notes', sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('interviews', 'meeting_notes')
