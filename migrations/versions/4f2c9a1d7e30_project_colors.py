"""project colours

Revision ID: 4f2c9a1d7e30
Revises: 130932a6e846
Create Date: 2026-09-28 15:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f2c9a1d7e30'
down_revision: Union[str, Sequence[str], None] = '130932a6e846'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.add_column(sa.Column('color', sa.Integer(), nullable=False, server_default='1'))
    # Existing projects take the hues in turn, so no two neighbours match.
    op.execute('UPDATE projects SET color = ((id - 1) % 8) + 1')


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('projects', schema=None) as batch_op:
        batch_op.drop_column('color')
