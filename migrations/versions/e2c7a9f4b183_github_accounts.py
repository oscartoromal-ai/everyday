"""github accounts: several GitHub accounts connected, each reaching its repositories

Revision ID: e2c7a9f4b183
Revises: c3f8a1d5e702
Create Date: 2026-10-04 22:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e2c7a9f4b183'
down_revision: Union[str, Sequence[str], None] = 'c3f8a1d5e702'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema. The repositories kept are the one account's connected
    so far; its GitHub id is learnt at its next sync. A plain ADD COLUMN and
    an index for the id, so the link's table is not rebuilt."""
    op.add_column('github_link', sa.Column('user_id', sa.Integer(), nullable=True))
    op.create_index('ix_github_link_user_id', 'github_link', ['user_id'], unique=True)
    op.create_table(
        'github_link_repositories',
        sa.Column('link_id', sa.Integer(), nullable=False),
        sa.Column('repository_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['link_id'], ['github_link.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['repository_id'], ['repositories.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('link_id', 'repository_id'),
    )
    op.execute(
        "INSERT INTO github_link_repositories (link_id, repository_id) "
        "SELECT github_link.id, repositories.id FROM github_link, repositories"
    )


def downgrade() -> None:
    """Downgrade schema: back to one account, the first connected."""
    op.drop_table('github_link_repositories')
    op.execute("DELETE FROM github_link WHERE id <> (SELECT min(id) FROM github_link)")
    op.drop_index('ix_github_link_user_id', table_name='github_link')
    op.drop_column('github_link', 'user_id')
