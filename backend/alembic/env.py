from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Import Base so autogenerate can detect model changes.
# Models must be imported before target_metadata is read.
from app import models  # noqa: F401 — registers all models on Base.metadata
from app.database import Base
from app.config import settings

target_metadata = Base.metadata


def _sync_url() -> str:
    """Return the sync SQLite URL for use by Alembic.

    The app uses sqlite+aiosqlite:// for async access; Alembic uses the
    standard synchronous sqlite:// driver.
    """
    return settings.DATABASE_URL.replace("sqlite+aiosqlite://", "sqlite://")


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # required for SQLite ALTER TABLE support
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
