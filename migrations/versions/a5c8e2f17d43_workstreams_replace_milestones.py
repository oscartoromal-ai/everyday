"""workstreams replace milestones: lanes of a project's work, with no dates

Revision ID: a5c8e2f17d43
Revises: d41e7c5a9b20
Create Date: 2026-10-01 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a5c8e2f17d43'
down_revision: Union[str, Sequence[str], None] = 'd41e7c5a9b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _keys(on: bool) -> None:
    """Foreign keys on or off. A batch rebuilds a table by dropping it, which
    an enforced key from the tasks refuses; the pragma only takes before the
    migration's first write, so it comes first (and the rebuilds keep every
    row, so nothing is left dangling)."""
    op.execute(f"PRAGMA foreign_keys = {'ON' if on else 'OFF'}")


def upgrade() -> None:
    """Upgrade schema."""
    _keys(False)
    # A dropped milestone leaves; its tasks stay in its project, in none.
    op.execute(
        "UPDATE tasks SET milestone_id = NULL"
        " WHERE milestone_id IN (SELECT id FROM milestones WHERE status = 'dropped')"
    )
    op.execute("DELETE FROM milestones WHERE status = 'dropped'")
    op.execute("UPDATE milestones SET status = 'done' WHERE status = 'reached'")
    with op.batch_alter_table('milestones', schema=None) as batch_op:
        # A workstream has no date of its own; its status is open or done.
        batch_op.drop_column('target_date')
        batch_op.alter_column(
            'status', existing_type=sa.String(length=7), type_=sa.String(length=4),
            existing_nullable=False,
        )
    # Renaming the table carries the tasks' key to it along.
    op.rename_table('milestones', 'workstreams')
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.alter_column('milestone_id', new_column_name='workstream_id')
    # The nudge a milestone's target raised has nothing left to say, and the
    # longest type is now missed_block.
    op.execute("DELETE FROM nudges WHERE type = 'milestone_soon'")
    with op.batch_alter_table('nudges', schema=None) as batch_op:
        batch_op.alter_column(
            'type', existing_type=sa.String(length=14), type_=sa.String(length=12),
            existing_nullable=False,
        )
    # A task's history names its workstream as it named its milestone.
    op.execute(
        "UPDATE task_revisions SET snapshot = json_remove("
        "json_set(snapshot, '$.workstream_id', json_extract(snapshot, '$.milestone_id')),"
        " '$.milestone_id') WHERE json_type(snapshot, '$.milestone_id') IS NOT NULL"
    )
    _keys(True)


def downgrade() -> None:
    """Downgrade schema."""
    _keys(False)
    op.execute(
        "UPDATE task_revisions SET snapshot = json_remove("
        "json_set(snapshot, '$.milestone_id', json_extract(snapshot, '$.workstream_id')),"
        " '$.workstream_id') WHERE json_type(snapshot, '$.workstream_id') IS NOT NULL"
    )
    with op.batch_alter_table('nudges', schema=None) as batch_op:
        batch_op.alter_column(
            'type', existing_type=sa.String(length=12), type_=sa.String(length=14),
            existing_nullable=False,
        )
    with op.batch_alter_table('tasks', schema=None) as batch_op:
        batch_op.alter_column('workstream_id', new_column_name='milestone_id')
    op.rename_table('workstreams', 'milestones')
    with op.batch_alter_table('milestones', schema=None) as batch_op:
        batch_op.add_column(sa.Column('target_date', sa.Date(), nullable=True))
        batch_op.alter_column(
            'status', existing_type=sa.String(length=4), type_=sa.String(length=7),
            existing_nullable=False,
        )
    op.execute("UPDATE milestones SET status = 'reached' WHERE status = 'done'")
    _keys(True)
