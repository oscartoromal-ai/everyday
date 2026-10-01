"""project folded: a project's card folded to its header

Revision ID: e6b1d4f08a37
Revises: a5c8e2f17d43
Create Date: 2026-10-01 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e6b1d4f08a37'
down_revision: Union[str, Sequence[str], None] = 'a5c8e2f17d43'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. A plain ADD COLUMN: a batch would rebuild the table by
    dropping it, which the tasks' enforced key to it refuses."""
    op.add_column(
        'projects',
        sa.Column('folded', sa.Boolean(), nullable=False, server_default=sa.text('0')),
    )


def downgrade() -> None:
    """Downgrade schema (SQLite's own DROP COLUMN, for the same reason)."""
    op.drop_column('projects', 'folded')
