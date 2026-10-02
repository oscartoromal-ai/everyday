"""task estimate: how long a task's work is thought to take, in minutes

Revision ID: b7d2e9c41f05
Revises: e6b1d4f08a37
Create Date: 2026-10-02 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7d2e9c41f05'
down_revision: Union[str, Sequence[str], None] = 'e6b1d4f08a37'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. A plain ADD COLUMN: a batch would rebuild the table by
    dropping it, which the blocks' and nudges' enforced keys to it refuse."""
    op.add_column('tasks', sa.Column('estimate_minutes', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema (SQLite's own DROP COLUMN, for the same reason)."""
    op.drop_column('tasks', 'estimate_minutes')
