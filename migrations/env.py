from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection

from app import models  # noqa: F401  (registers models on Base.metadata)
from app.db import Base, make_migration_engine

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Emit migration SQL without a live database connection."""
    from app.config import get_settings

    context.configure(
        url=f"sqlite:///{get_settings().db_path}",
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def _pointing_nowhere(connection: Connection) -> set[tuple]:
    """The rows whose foreign key points at no row: (table, rowid, the
    table it points at)."""
    return {tuple(row[:3]) for row in connection.exec_driver_sql("PRAGMA foreign_key_check")}


def run_migrations_online() -> None:
    # The app's database on the engine for migrating it (app/db.py): the
    # same URL resolution, foreign keys off and DDL in the transaction.
    connectable = make_migration_engine(config.get_main_option("sqlalchemy.url") or None)

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,  # SQLite ALTERs need batch mode
                # Every migration in the one transaction, rather than
                # Alembic's commit after each on SQLite: an upgrade that
                # fails anywhere leaves the database as it was.
                transactional_ddl=True,
            )

            with context.begin_transaction():
                before = _pointing_nowhere(connection)
                context.run_migrations()
                # With foreign keys off, nothing stopped a migration leaving
                # rows that point nowhere: one that did is undone whole.
                left = _pointing_nowhere(connection) - before
                if left:
                    raise RuntimeError(
                        "The migration left rows pointing nowhere (table, row, the table it "
                        f"points at): {', '.join(map(str, sorted(left, key=str)[:10]))}"
                    )
    finally:
        # Closed now, not when collected: its last connection closing is
        # what checkpoints the write-ahead log into the database file.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
