"""task agent runs: a task launched as an agent run, on which runner, where, and how it stands

Revision ID: c7a3f9e2d418
Revises: b5d2e8c1f604
Create Date: 2026-10-05 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c7a3f9e2d418'
down_revision: Union[str, Sequence[str], None] = 'b5d2e8c1f604'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('task_runs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('runner', sa.String(length=40), nullable=False),
    sa.Column('run_id', sa.String(length=200), nullable=False),
    sa.Column('branch', sa.String(length=255), nullable=False),
    sa.Column('workspace', sa.Text(), nullable=False),
    sa.Column('state', sa.String(length=20), nullable=False),
    sa.Column('started_at', sa.DateTime(), nullable=False),
    sa.Column('checked_at', sa.DateTime(), nullable=True),
    sa.Column('check_error', sa.Text(), nullable=False),
    sa.Column('cleaned', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_task_runs_task_id', 'task_runs', ['task_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_task_runs_task_id', table_name='task_runs')
    op.drop_table('task_runs')
