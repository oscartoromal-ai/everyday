from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401  (registers models on Base.metadata)
from app.db import Base, make_engine

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


def run_migrations_online() -> None:
    # The app's own engine: same URL resolution, same SQLite pragmas.
    connectable = make_engine(config.get_main_option("sqlalchemy.url") or None)

    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,  # SQLite ALTERs need batch mode
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Closed now, not when collected: its last connection closing is
        # what checkpoints the write-ahead log into the database file.
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
