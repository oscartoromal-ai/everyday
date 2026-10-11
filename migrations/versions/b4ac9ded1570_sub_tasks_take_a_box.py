"""sub-tasks take a box: "- " lines in task descriptions become "- [ ] "

A task's description read every "- " (or "* ") line as a sub-task; since
2026-10-11 only a line with a box is one ("- [ ] ", "- [x] "), and "- " is a
plain bullet, as in any Markdown (app/checklist.py). Every sub-task written
the old way keeps being one: its line takes an open box. Lines in fenced
code are left as written. Repeating tasks' templates hold descriptions too.

Revision ID: b4ac9ded1570
Revises: c7a3f9e2d418
Create Date: 2026-10-11 10:00:00.000000

"""
import re
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b4ac9ded1570'
down_revision: Union[str, Sequence[str], None] = 'c7a3f9e2d418'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A sub-task as the old app/checklist.py read it, without a box.
_UNBOXED = re.compile(r"^([ \t]*[-*][ \t]+)(?!\[[ xX]\][ \t]+\S)(\S.*)$")
_FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


def boxed(notes: str) -> str:
    """The description with an open box on each sub-task written without one."""
    out = []
    fence = None
    for raw in notes.split("\n"):
        if fence is not None:
            if re.fullmatch(rf"[ \t]*{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", raw):
                fence = None
            out.append(raw)
        elif opens := _FENCE.match(raw):
            fence = opens[1]
            out.append(raw)
        elif match := _UNBOXED.match(raw):
            marker = match[1].rstrip(" \t")
            out.append(f"{marker} [ ] {match[2]}")
        else:
            out.append(raw)
    return "\n".join(out)


def upgrade() -> None:
    """Upgrade schema."""
    bind = op.get_bind()
    for table in ("tasks", "recurrence_templates"):
        rows = bind.execute(sa.text(f"SELECT id, notes FROM {table} WHERE notes != ''")).all()
        for row_id, notes in rows:
            new = boxed(notes)
            if new != notes:
                bind.execute(
                    sa.text(f"UPDATE {table} SET notes = :notes WHERE id = :id"),
                    {"notes": new, "id": row_id},
                )


def downgrade() -> None:
    """Downgrade schema."""
    # Nothing to undo: the old app read "- [ ] " lines as sub-tasks too.
    pass
