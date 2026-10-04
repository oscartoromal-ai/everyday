"""agent window: chats with an agent (Claude, Codex) from any page

Revision ID: a9d3f6e21c48
Revises: e2c7a9f4b183
Create Date: 2026-10-04 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9d3f6e21c48'
down_revision: Union[str, Sequence[str], None] = 'e2c7a9f4b183'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('agent_conversations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('agent', sa.Enum('claude', 'codex', name='agentkind', native_enum=False), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('agent_messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversation_id', sa.Integer(), nullable=False),
    sa.Column('role', sa.Enum('oscar', 'agent', name='agentrole', native_enum=False), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('failed', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['agent_conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('agent_messages', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_agent_messages_conversation_id'), ['conversation_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('agent_messages', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_agent_messages_conversation_id'))
    op.drop_table('agent_messages')
    op.drop_table('agent_conversations')
