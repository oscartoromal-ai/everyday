"""stays: out of the day's notes, into a table of their own

Where Oscar stays was written in the day's notes ("/stay", then its items,
each "- [ ] name: value", ticked once sorted), a stay block of the page. It
is now written on Today's stay pane (or Calendar's sheet), each item a row
of stay_items. The stay blocks leave every page (the day's file is written
again from the page as the app starts, and a page left with nothing goes
with its file); each item keeps its name, value and sorted or not, in the
order it was written. A note written after "/stay" is dropped (Oscar's call
on 2026-10-20: none was ever written).

Revision ID: c4e8a2f61b07
Revises: b7e3c1a95d42
Create Date: 2026-10-20 18:00:00.000000

"""
import json
import re
from datetime import datetime
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = 'c4e8a2f61b07'
down_revision: Union[str, Sequence[str], None] = 'b7e3c1a95d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# A stay's item, as its block held it: "- [ ] accommodation: a flat" ("- [x] " once sorted).
ITEM = re.compile(r"^- \[([ xX])\] ([^:]*?)\s*(?::\s?(.*))?$")


def _trimmed(blocks: list[dict]) -> list[dict]:
    """The page's blocks with no blank lines at its top or bottom, as the
    app keeps a page (notebook.normalize): the prose that came after a stay
    at the top starts the page now, its rows' tasks moved up with it."""
    if blocks and blocks[0].get('kind') == 'text':
        first = dict(blocks[0])
        lines = first.get('text', '').split('\n')
        lead = 0
        while lead < len(lines) and not lines[lead].strip():
            lead += 1
        first['text'] = '\n'.join(lines[lead:])
        if first.get('links'):
            first['links'] = {
                str(int(r) - lead): t for r, t in first['links'].items() if int(r) >= lead
            }
        if first.get('folded'):
            first['folded'] = [int(r) - lead for r in first['folded'] if int(r) >= lead]
        blocks = [first, *blocks[1:]]
        if not first['text'].strip():
            return _trimmed(blocks[1:])
    if blocks and blocks[-1].get('kind') == 'text':
        last = dict(blocks[-1])
        lines = last.get('text', '').split('\n')
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            return _trimmed(blocks[:-1])
        last['text'] = '\n'.join(lines)
        blocks = [*blocks[:-1], last]
    return blocks


def upgrade() -> None:
    op.create_table(
        'stay_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('day', sa.Date(), nullable=False),
        sa.Column('position', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=80), nullable=False),
        sa.Column('value', sa.Text(), nullable=False),
        sa.Column('done', sa.Boolean(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('day', 'name'),
    )
    conn = op.get_bind()
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    pages = conn.exec_driver_sql('SELECT id, day, blocks, version FROM notebook_pages').fetchall()
    for page_id, day, blocks, version in pages:
        blocks = json.loads(blocks) if isinstance(blocks, str) else blocks
        stays = [b for b in blocks if b.get('kind') == 'stay']
        if not stays:
            continue
        items: dict[str, tuple[str, str, bool]] = {}
        for block in stays:
            for line in block.get('text', '').split('\n'):
                item = ITEM.match(line.strip())
                name = ' '.join((item[2] if item else '').split())[:80]
                if name and name.lower() not in items:
                    items[name.lower()] = (name, ' '.join((item[3] or '').split()), item[1] in 'xX')
        for position, (name, value, done) in enumerate(items.values()):
            conn.exec_driver_sql(
                'INSERT INTO stay_items (day, position, name, value, done, updated_at)'
                ' VALUES (?, ?, ?, ?, ?, ?)',
                (day, position, name, value, done, now),
            )
        kept = _trimmed([b for b in blocks if b.get('kind') != 'stay'])
        # A window with the page open from before asks which to keep.
        conn.exec_driver_sql(
            'UPDATE notebook_pages SET blocks = ?, version = ? WHERE id = ?',
            (json.dumps(kept), version + 1, page_id),
        )


def downgrade() -> None:
    conn = op.get_bind()
    items = conn.exec_driver_sql(
        'SELECT day, name, value, done FROM stay_items ORDER BY day, position, id'
    ).fetchall()
    stays: dict[str, list[str]] = {}
    for day, name, value, done in items:
        line = f"- [{'x' if done else ' '}] {name}: {value}".rstrip(' ')
        stays.setdefault(day, ['']).append(line)
    now = datetime.now().isoformat(sep=' ', timespec='seconds')
    for day, lines in stays.items():
        block = {'kind': 'stay', 'text': '\n'.join(lines)}
        page = conn.exec_driver_sql(
            'SELECT id, blocks, version FROM notebook_pages WHERE day = ?', (day,)
        ).fetchone()
        if page is None:
            conn.exec_driver_sql(
                'INSERT INTO notebook_pages (day, blocks, version, writer, writer_seq, updated_at)'
                " VALUES (?, ?, 1, '', 0, ?)",
                (day, json.dumps([block]), now),
            )
            continue
        page_id, blocks, version = page
        blocks = json.loads(blocks) if isinstance(blocks, str) else blocks
        conn.exec_driver_sql(
            'UPDATE notebook_pages SET blocks = ?, version = ? WHERE id = ?',
            (json.dumps([block, *blocks]), version + 1, page_id),
        )
    op.drop_table('stay_items')
