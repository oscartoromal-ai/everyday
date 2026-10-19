"""tasks: an id is never given twice

A task's id names it beyond its row: its folder of the everyday files
(tasks/<id>-<words>/), its history (task_revisions keeps a deleted task's),
the notes' links. Without AUTOINCREMENT, SQLite gave a new task the id of
the newest one deleted, and the new task took on the deleted one's history
and any folder of it not yet in the trash. The table is built again with
AUTOINCREMENT, its count past every id a task ever had, its history's too.

Revision ID: 9380518192ab
Revises: e5f1a9c3d7b2
Create Date: 2026-10-19 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '9380518192ab'
down_revision: Union[str, Sequence[str], None] = 'e5f1a9c3d7b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table(
        'tasks', recreate='always', table_kwargs={'sqlite_autoincrement': True}
    ):
        pass
    conn = op.get_bind()
    top = conn.exec_driver_sql(
        'SELECT max(m) FROM (SELECT max(id) AS m FROM tasks'
        ' UNION ALL SELECT max(task_id) FROM task_revisions)'
    ).scalar()
    conn.exec_driver_sql("DELETE FROM sqlite_sequence WHERE name = 'tasks'")
    if top:
        conn.exec_driver_sql(
            "INSERT INTO sqlite_sequence (name, seq) VALUES ('tasks', ?)", (top,)
        )


def downgrade() -> None:
    with op.batch_alter_table(
        'tasks', recreate='always', table_kwargs={'sqlite_autoincrement': False}
    ):
        pass
