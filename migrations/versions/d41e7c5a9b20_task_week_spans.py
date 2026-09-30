"""task week spans: a start week and a place on the project's Gantt

Revision ID: d41e7c5a9b20
Revises: ca150db0cfe7
Create Date: 2026-09-30 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd41e7c5a9b20'
down_revision: Union[str, Sequence[str], None] = 'ca150db0cfe7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.add_column(sa.Column('starts_on', sa.Date(), nullable=True))
        batch_op.add_column(sa.Column('position', sa.Integer(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.drop_column('position')
        batch_op.drop_column('starts_on')
