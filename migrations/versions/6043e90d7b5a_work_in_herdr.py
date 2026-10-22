"""work_sessions and work_spans: the work seen in herdr, recorded

Each terminal seen in herdr is a session (its folder, its agent, the task or
project it is filed under); its spans are the stretches Oscar was at it and
its agent worked or waited on him (app/services/work_log.py).

Revision ID: 6043e90d7b5a
Revises: c4e8a2f61b07
Create Date: 2026-10-22 13:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '6043e90d7b5a'
down_revision: Union[str, Sequence[str], None] = 'c4e8a2f61b07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'work_sessions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('terminal_id', sa.String(length=80), nullable=False),
        sa.Column('workspace', sa.String(length=255), nullable=False),
        sa.Column('cwd', sa.Text(), nullable=False),
        sa.Column('agent', sa.String(length=40), nullable=False),
        sa.Column('agent_session', sa.String(length=120), nullable=False),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('task_id', sa.Integer(), nullable=True),
        sa.Column('project_id', sa.Integer(), nullable=True),
        sa.Column('filed_by', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('seen_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('terminal_id'),
    )
    op.create_index('ix_work_sessions_task_id', 'work_sessions', ['task_id'])
    op.create_index('ix_work_sessions_project_id', 'work_sessions', ['project_id'])
    op.create_table(
        'work_spans',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['session_id'], ['work_sessions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_work_spans_session_id', 'work_spans', ['session_id'])
    op.create_index('ix_work_spans_started_at', 'work_spans', ['started_at'])


def downgrade() -> None:
    op.drop_table('work_spans')
    op.drop_table('work_sessions')
