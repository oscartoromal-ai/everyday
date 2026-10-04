"""task runs: a task's acceptance criteria and outcome, its repositories, pull requests and updates

Revision ID: b5d2e8c1f604
Revises: a4c9e2f7b310
Create Date: 2026-10-04 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b5d2e8c1f604'
down_revision: Union[str, Sequence[str], None] = 'a4c9e2f7b310'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. Plain ADD COLUMNs: a batch would rebuild tasks by
    dropping it, which the keys to it refuse."""
    op.add_column('tasks', sa.Column('acceptance', sa.Text(), nullable=False, server_default=''))
    op.add_column('tasks', sa.Column('outcome', sa.Text(), nullable=False, server_default=''))
    op.create_table('task_repos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('location', sa.String(length=1000), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'location')
    )
    op.create_index('ix_task_repos_task_id', 'task_repos', ['task_id'], unique=False)
    op.create_table('task_pull_requests',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('repo', sa.String(length=200), nullable=False),
    sa.Column('number', sa.Integer(), nullable=False),
    sa.Column('title', sa.Text(), nullable=False),
    sa.Column('state', sa.Enum('unknown', 'draft', 'open', 'merged', 'closed', name='pullrequeststate', native_enum=False), nullable=False),
    sa.Column('checked_at', sa.DateTime(), nullable=True),
    sa.Column('check_error', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'repo', 'number')
    )
    op.create_index('ix_task_pull_requests_task_id', 'task_pull_requests', ['task_id'], unique=False)
    op.create_table('task_updates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('actor', sa.String(length=20), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_task_updates_task_id', 'task_updates', ['task_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema (SQLite's own DROP COLUMN, for the same reason)."""
    op.drop_index('ix_task_updates_task_id', table_name='task_updates')
    op.drop_table('task_updates')
    op.drop_index('ix_task_pull_requests_task_id', table_name='task_pull_requests')
    op.drop_table('task_pull_requests')
    op.drop_index('ix_task_repos_task_id', table_name='task_repos')
    op.drop_table('task_repos')
    op.drop_column('tasks', 'outcome')
    op.drop_column('tasks', 'acceptance')
