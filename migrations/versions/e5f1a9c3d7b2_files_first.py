"""files first: the planner's words are files, the database their index

Oscar's call on 2026-10-11 (SPEC.md, Files first). A task's description,
acceptance and outcome become its task.md's, a project's about its
project.md's, a day's notes their notebook file's, each kept in its row too
and its file's hash beside it (file_hash). Every Markdown file of the
everyday files is indexed (documents, and documents_fts for its words) and
keeps its history (document_revisions).

A project's documents were files already, the database keeping a copy: the
copy goes. Their history moves to document_revisions (by the project and
the document's path), the folders shown folded to a setting, and a
document whose file is missing (never written out) is written first, so
nothing it held is lost. The files themselves (task.md, project.md, the
notebook's) are written by the app as it starts.

Revision ID: e5f1a9c3d7b2
Revises: b4ac9ded1570
Create Date: 2026-10-11 18:00:00.000000

"""
import json
import logging
from pathlib import Path
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5f1a9c3d7b2'
down_revision: Union[str, Sequence[str], None] = 'b4ac9ded1570'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

log = logging.getLogger(__name__)


def _paths(conn) -> tuple[dict[int, str], dict[int, tuple[int, str]]]:  # noqa: ANN001
    """Each folder's path in its project's context, and each document's
    project and path."""
    folders = {
        row.id: (row.parent_id, row.name)
        for row in conn.execute(sa.text("SELECT id, parent_id, name FROM project_doc_folders"))
    }

    def path(folder_id: int | None) -> str:
        parts = []
        seen = set()
        while folder_id is not None and folder_id in folders and folder_id not in seen:
            seen.add(folder_id)
            parent, name = folders[folder_id]
            parts.append(name)
            folder_id = parent
        return "/".join(reversed(parts))

    folder_paths = {fid: path(fid) for fid in folders}
    docs = {}
    for row in conn.execute(sa.text("SELECT id, project_id, folder_id, name FROM project_docs")):
        where = folder_paths.get(row.folder_id, "") if row.folder_id else ""
        docs[row.id] = (row.project_id, f"{where}/{row.name}" if where else row.name)
    return folder_paths, docs


def _write_missing(conn, docs: dict[int, tuple[int, str]]) -> None:  # noqa: ANN001
    """Each document whose file is not on disk written there, from its copy."""
    try:
        from app.services import everyday

        root = everyday.projects_dir()
    except Exception:  # noqa: BLE001
        return
    project_folders = {
        row.id: row.folder
        for row in conn.execute(sa.text("SELECT id, folder FROM projects"))
        if row.folder
    }
    bodies = {
        row.id: row.body for row in conn.execute(sa.text("SELECT id, body FROM project_docs"))
    }
    for doc_id, (project_id, path) in docs.items():
        folder = project_folders.get(project_id)
        if not folder:
            continue
        target = Path(root, folder, *path.split("/"))
        if target.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((bodies.get(doc_id) or "").encode("utf-8"))
            log.info("Wrote %s from the database's copy", target)
        except OSError as exc:
            log.warning("Could not write %s: %s", target, exc)


def upgrade() -> None:
    """Upgrade schema."""
    conn = op.get_bind()
    op.add_column('tasks', sa.Column('file_hash', sa.String(length=16), nullable=True))
    op.add_column('projects', sa.Column('file_hash', sa.String(length=16), nullable=True))
    op.add_column('notebook_pages', sa.Column('file_hash', sa.String(length=16), nullable=True))

    op.create_table('documents',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('path', sa.String(length=1000), nullable=False),
    sa.Column('owner', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=1000), nullable=False),
    sa.Column('version', sa.String(length=16), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('mtime_ns', sa.Integer(), nullable=False),
    sa.Column('indexed_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('path')
    )
    op.create_index('ix_documents_owner', 'documents', ['owner'], unique=False)
    op.execute(
        "CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5("
        "title, body, tokenize = 'unicode61 remove_diacritics 2')"
    )
    op.create_table('document_revisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('owner', sa.String(length=40), nullable=False),
    sa.Column('name', sa.String(length=1000), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('actor', sa.String(length=20), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(
        'ix_document_revisions_doc', 'document_revisions', ['owner', 'name', 'at'], unique=False
    )

    folder_paths, docs = _paths(conn)
    _write_missing(conn, docs)
    for row in conn.execute(sa.text(
        "SELECT doc_id, at, actor, body FROM project_doc_revisions ORDER BY at, id"
    )).all():
        if row.doc_id not in docs:
            continue
        project_id, path = docs[row.doc_id]
        conn.execute(
            sa.text(
                "INSERT INTO document_revisions (owner, name, at, actor, body) "
                "VALUES (:owner, :name, :at, :actor, :body)"
            ),
            {"owner": f"project:{project_id}", "name": path, "at": row.at, "actor": row.actor,
             "body": row.body},
        )
    folded: dict[str, list[str]] = {}
    for row in conn.execute(sa.text(
        "SELECT id, project_id FROM project_doc_folders WHERE folded"
    )).all():
        folded.setdefault(str(row.project_id), []).append(folder_paths[row.id])
    if folded:
        conn.execute(
            sa.text("INSERT OR REPLACE INTO settings (key, value) VALUES ('context_folded', :v)"),
            {"v": json.dumps({k: sorted(v) for k, v in folded.items()})},
        )

    op.drop_index('ix_project_doc_revisions_doc', table_name='project_doc_revisions')
    op.drop_table('project_doc_revisions')
    op.drop_table('project_docs')
    op.drop_table('project_doc_folders')


def downgrade() -> None:
    """Downgrade schema: the copy's tables back, empty: the app before this
    one reads every document into them from its file as it starts."""
    op.create_table('project_doc_folders',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('parent_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('folded', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['parent_id'], ['project_doc_folders.id'], ),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_doc_folders_project_id', 'project_doc_folders', ['project_id'], unique=False)
    op.create_index('ix_project_doc_folders_parent_id', 'project_doc_folders', ['parent_id'], unique=False)
    op.create_table('project_docs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('project_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.Column('folder_id', sa.Integer(), nullable=True),
    sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ),
    sa.ForeignKeyConstraint(['folder_id'], ['project_doc_folders.id'], name='fk_project_docs_folder_id'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_docs_folder_id', 'project_docs', ['folder_id'], unique=False)
    op.create_index('ix_project_docs_project_id', 'project_docs', ['project_id'], unique=False)
    op.create_table('project_doc_revisions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('doc_id', sa.Integer(), nullable=False),
    sa.Column('at', sa.DateTime(), nullable=False),
    sa.Column('actor', sa.String(length=20), nullable=False),
    sa.Column('body', sa.Text(), nullable=False),
    sa.ForeignKeyConstraint(['doc_id'], ['project_docs.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_project_doc_revisions_doc', 'project_doc_revisions', ['doc_id', 'at'], unique=False)
    op.execute("DELETE FROM settings WHERE key IN ('context_folded', 'everyday_claim')")
    op.drop_index('ix_document_revisions_doc', table_name='document_revisions')
    op.drop_table('document_revisions')
    op.execute("DROP TABLE IF EXISTS documents_fts")
    op.drop_index('ix_documents_owner', table_name='documents')
    op.drop_table('documents')
    op.drop_column('notebook_pages', 'file_hash')
    op.drop_column('projects', 'file_hash')
    op.drop_column('tasks', 'file_hash')
