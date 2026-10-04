"""notebook page writer

Revision ID: d4b7e9a2c1f5
Revises: e2c7a9f4b183
Create Date: 2026-10-04 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4b7e9a2c1f5'
down_revision: Union[str, Sequence[str], None] = 'e2c7a9f4b183'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Added in place (no table rebuild): ALTER TABLE ADD COLUMN.
    op.add_column('notebook_pages', sa.Column('writer', sa.String(length=40), nullable=False, server_default=''))
    op.add_column('notebook_pages', sa.Column('writer_seq', sa.Integer(), nullable=False, server_default='0'))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('notebook_pages', schema=None) as batch_op:
        batch_op.drop_column('writer_seq')
        batch_op.drop_column('writer')
