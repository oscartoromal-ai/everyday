"""habits: out of the day's notes, into files of their own

A habit was checked by its row in the day's notes ("/habit name"), the
row's words its note. It is now ticked on Today's habits pane (or
Calendar's sheet) and its words are its own file's, habits/<slug>.md: what
it is (`notes`), then its log, a comment a day (the checks' notes). The
habit rows leave every page (the day's file is written again from the page
as the app starts), each check keeping its note; a check not done and
with no note (a box unticked, nothing said) is no longer anything and
goes. The habits table is built again with AUTOINCREMENT, as the tasks'
was, since an id names the habit's file in the index and its history.

Revision ID: b7e3c1a95d42
Revises: 9380518192ab
Create Date: 2026-10-20 16:00:00.000000

"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'b7e3c1a95d42'
down_revision: Union[str, Sequence[str], None] = '9380518192ab'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table(
        'habits', recreate='always', table_kwargs={'sqlite_autoincrement': True}
    ) as batch_op:
        batch_op.add_column(sa.Column('notes', sa.Text(), nullable=False, server_default=''))
        batch_op.add_column(sa.Column('file_hash', sa.String(length=16), nullable=True))
    conn = op.get_bind()
    pages = conn.exec_driver_sql('SELECT id, blocks, version FROM notebook_pages').fetchall()
    for page_id, blocks, version in pages:
        kept = json.loads(blocks) if isinstance(blocks, str) else blocks
        if not any(b.get('kind') == 'habit' for b in kept):
            continue
        kept = [b for b in kept if b.get('kind') != 'habit']
        # A window with the page open from before asks which to keep.
        conn.exec_driver_sql(
            'UPDATE notebook_pages SET blocks = ?, version = ? WHERE id = ?',
            (json.dumps(kept), version + 1, page_id),
        )
    conn.exec_driver_sql("DELETE FROM habit_checks WHERE done = 0 AND trim(note) = ''")


def downgrade() -> None:
    with op.batch_alter_table(
        'habits', recreate='always', table_kwargs={'sqlite_autoincrement': False}
    ) as batch_op:
        batch_op.drop_column('file_hash')
        batch_op.drop_column('notes')
