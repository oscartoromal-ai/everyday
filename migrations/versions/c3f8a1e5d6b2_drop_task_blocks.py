"""drop task blocks: a task no longer takes time on the calendar

Revision ID: c3f8a1e5d6b2
Revises: b7d2e9c41f05
Create Date: 2026-10-02 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3f8a1e5d6b2'
down_revision: Union[str, Sequence[str], None] = 'b7d2e9c41f05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: the blocks go, and with them the nudges about missed ones."""
    op.execute("DELETE FROM nudges WHERE type = 'missed_block'")
    op.drop_index('ix_blocks_state', table_name='blocks')
    op.drop_index('ix_blocks_start', table_name='blocks')
    op.drop_table('blocks')


def downgrade() -> None:
    """Downgrade schema: the table back, empty."""
    op.create_table('blocks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('start', sa.DateTime(), nullable=False),
    sa.Column('end', sa.DateTime(), nullable=False),
    sa.Column('state', sa.Enum('planned', 'completed', 'missed', name='blockstate', native_enum=False), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_blocks_start', 'blocks', ['start'], unique=False)
    op.create_index('ix_blocks_state', 'blocks', ['state'], unique=False)
