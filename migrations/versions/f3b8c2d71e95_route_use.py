"""route use: how much each of the app's routes is used each day, and how it fares

Revision ID: f3b8c2d71e95
Revises: f4d0a341d1cc
Create Date: 2026-10-04 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b8c2d71e95'
down_revision: Union[str, Sequence[str], None] = 'f4d0a341d1cc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('route_use',
    sa.Column('day', sa.Date(), nullable=False),
    sa.Column('route', sa.String(length=300), nullable=False),
    sa.Column('requests', sa.Integer(), nullable=False),
    sa.Column('failures', sa.Integer(), nullable=False),
    sa.Column('total_ms', sa.Integer(), nullable=False),
    sa.Column('slowest_ms', sa.Integer(), nullable=False),
    sa.PrimaryKeyConstraint('day', 'route')
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_table('route_use')
