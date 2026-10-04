"""task priority: how much a task matters against the others (urgent, high, medium, low, or none)

Revision ID: 8e3a5c1f9d27
Revises: d5a77acb11b0
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8e3a5c1f9d27'
down_revision: Union[str, Sequence[str], None] = 'd5a77acb11b0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. A plain ADD COLUMN: a batch would rebuild the table by
    dropping it, which the nudges' enforced keys to it refuse."""
    op.add_column('tasks', sa.Column(
        'priority',
        sa.Enum('urgent', 'high', 'medium', 'low', name='taskpriority', native_enum=False),
        nullable=True,
    ))


def downgrade() -> None:
    """Downgrade schema (SQLite's own DROP COLUMN, for the same reason)."""
    op.drop_column('tasks', 'priority')
