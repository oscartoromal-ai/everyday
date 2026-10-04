"""merge notebook page writer and project doc folders

Revision ID: f4d0a341d1cc
Revises: d4b7e9a2c1f5, f3b6d0a2c8e1
Create Date: 2026-10-04 18:46:50.431840

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f4d0a341d1cc'
down_revision: Union[str, Sequence[str], None] = ('d4b7e9a2c1f5', 'f3b6d0a2c8e1')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
