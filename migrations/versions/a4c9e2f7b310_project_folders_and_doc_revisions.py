"""project folders and doc revisions: a project's folder in the everyday files, and each document's history

Revision ID: a4c9e2f7b310
Revises: f3b8c2d71e95
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a4c9e2f7b310'
down_revision: Union[str, Sequence[str], None] = 'f3b8c2d71e95'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: the folder's name (written as the app first reads the
    everyday files), and the revisions, starting with every document as it
    stands. A plain ADD COLUMN: a batch would rebuild projects by dropping
    it, which the keys to it refuse."""
    op.add_column('projects', sa.Column('folder', sa.String(length=200), nullable=True))
    op.create_table('project_doc_revisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('doc_id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('actor', sa.String(length=20), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['project_docs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_doc_revisions_doc', 'project_doc_revisions', ['doc_id', 'at'], unique=False)
    op.execute(
        "INSERT INTO project_doc_revisions (doc_id, at, actor, body) "
        "SELECT id, updated_at, 'system', body FROM project_docs ORDER BY id"
    )


def downgrade() -> None:
    """Downgrade schema (SQLite's own DROP COLUMN, for the same reason)."""
    op.drop_index('ix_project_doc_revisions_doc', table_name='project_doc_revisions')
    op.drop_table('project_doc_revisions')
    op.drop_column('projects', 'folder')
