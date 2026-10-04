"""project repos and docs: a project's repositories and its context, AGENTS.md first

Revision ID: d8e2a6c4f1b9
Revises: 8e3a5c1f9d27
Create Date: 2026-10-04 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd8e2a6c4f1b9'
down_revision: Union[str, Sequence[str], None] = '8e3a5c1f9d27'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: the two tables, and an empty AGENTS.md for every
    project there is, as a new project gets one."""
    op.create_table('project_repos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('location', sa.String(length=1000), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_repos_project_id', 'project_repos', ['project_id'], unique=False)
    op.create_table('project_docs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('project_id', 'name')
    )
    op.create_index('ix_project_docs_project_id', 'project_docs', ['project_id'], unique=False)
    op.execute(
        "INSERT INTO project_docs (project_id, name, body, updated_at) "
        "SELECT id, 'AGENTS.md', '', created_at FROM projects ORDER BY id"
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_project_docs_project_id', table_name='project_docs')
    op.drop_table('project_docs')
    op.drop_index('ix_project_repos_project_id', table_name='project_repos')
    op.drop_table('project_repos')
