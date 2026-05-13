"""init

Revision ID: 0001_init
Revises:
Create Date: 2026-05-12 00:00:00.000000

Empty baseline revision. Schema is added in follow-up migrations.
"""

from __future__ import annotations

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "0001_init"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
