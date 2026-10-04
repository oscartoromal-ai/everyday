"""project position and settings: projects in an order of their own, and the app's settings

Revision ID: b7e41c9d2a58
Revises: d8e2a6c4f1b9
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7e41c9d2a58'
down_revision: Union[str, Sequence[str], None] = 'd8e2a6c4f1b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. The projects keep the order they had, by creation; a
    plain ADD COLUMN, as a batch would drop the table the tasks' key refers to."""
    op.add_column(
        'projects',
        sa.Column('position', sa.Integer(), nullable=False, server_default=sa.text('0')),
    )
    op.execute(
        "UPDATE projects SET position = ("
        "SELECT COUNT(*) FROM projects AS p WHERE p.created_at < projects.created_at "
        "OR (p.created_at = projects.created_at AND p.id < projects.id))"
    )
    op.create_table('settings',
    sa.Column('key', sa.String(length=80), nullable=False),
    sa.Column('value', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('settings')
    op.drop_column('projects', 'position')
