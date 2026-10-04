"""project doc folders: a project's context in folders and subfolders

Revision ID: f3b6d0a2c8e1
Revises: a9d3f6e21c48
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f3b6d0a2c8e1'
down_revision: Union[str, Sequence[str], None] = 'a9d3f6e21c48'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _docs(*extra: sa.Column, unique: bool = False) -> sa.Table:
    """project_docs as it is copied: the batch is told the table, rather than
    reading it, since its unique (project_id, name) was never named."""
    return sa.Table(
        'project_docs', sa.MetaData(),
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('project_id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('body', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        *extra,
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
        sa.PrimaryKeyConstraint('id'),
        *([sa.UniqueConstraint('project_id', 'name')] if unique else []),
    )


def upgrade() -> None:
    """Upgrade schema: the folders, and a document's folder. A document's
    name is now unique among what sits beside it, which the app checks
    (a folder and a document share names), not across the project."""
    op.create_table('project_doc_folders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('folded', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['project_doc_folders.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_doc_folders_project_id', 'project_doc_folders', ['project_id'], unique=False)
    op.create_index('ix_project_doc_folders_parent_id', 'project_doc_folders', ['parent_id'], unique=False)
    with op.batch_alter_table('project_docs', copy_from=_docs(unique=False)) as batch_op:
        batch_op.add_column(sa.Column('folder_id', sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            'fk_project_docs_folder_id', 'project_doc_folders', ['folder_id'], ['id']
        )
        batch_op.create_index('ix_project_docs_folder_id', ['folder_id'], unique=False)
        batch_op.create_index('ix_project_docs_project_id', ['project_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema: every document back at the top, as named."""
    op.drop_index('ix_project_docs_folder_id', table_name='project_docs')
    folder_id = sa.Column('folder_id', sa.Integer(), nullable=True)
    with op.batch_alter_table(
        'project_docs', copy_from=_docs(folder_id, unique=False), recreate='always'
    ) as batch_op:
        batch_op.drop_column('folder_id')
        batch_op.create_unique_constraint('uq_project_docs_project_id_name', ['project_id', 'name'])
        batch_op.create_index('ix_project_docs_project_id', ['project_id'], unique=False)
    op.drop_index('ix_project_doc_folders_parent_id', table_name='project_doc_folders')
    op.drop_index('ix_project_doc_folders_project_id', table_name='project_doc_folders')
    op.drop_table('project_doc_folders')
