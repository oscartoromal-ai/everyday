"""workstream position: a project's workstreams in an order of their own

Revision ID: c3f8a1d5e702
Revises: b7e41c9d2a58
Create Date: 2026-10-04 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8a1d5e702'
down_revision: Union[str, Sequence[str], None] = 'b7e41c9d2a58'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Each project's workstreams keep the order they had, by
    creation; a plain ADD COLUMN, as a batch would drop the table the tasks'
    key refers to."""
    op.add_column(
        'workstreams',
        sa.Column('position', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.execute(
        "UPDATE workstreams SET position = ("
        "SELECT COUNT(*) FROM workstreams AS w "
        "WHERE w.project_id = workstreams.project_id AND w.id < workstreams.id)"
    )


def downgrade() -> None:
    """Downgrade schema (SQLite's own DROP COLUMN, for the same reason)."""
    op.drop_column('workstreams', 'position')
