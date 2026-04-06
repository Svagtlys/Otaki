import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

import logging

logger = logging.getLogger(f"otaki.{__name__}")

logger.info("Initializing database...")

_is_sqlite = settings.DATABASE_URL.startswith("sqlite")

# On SQLite, serialise concurrent worker writes via a process-wide asyncio.Lock.
# On Postgres, concurrent writes are handled natively — no lock needed.
_write_lock: asyncio.Lock | None = asyncio.Lock() if _is_sqlite else None

engine = create_async_engine(
    settings.DATABASE_URL,
    **{"connect_args": {"timeout": 30}} if _is_sqlite else {},
)

if _is_sqlite:
    @event.listens_for(engine.sync_engine, "connect")
    def _set_wal_mode(dbapi_conn, connection_record):
        """Enable WAL journal mode for every new SQLite connection.

        WAL allows concurrent readers and serialises writers at the SQLite level,
        greatly reducing 'database is locked' errors under concurrent async access.
        The PRAGMA is idempotent and persists on the database file.
        """
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


@asynccontextmanager
async def write_session():
    """Async context manager for sessions that write to the database.

    On SQLite: acquires a process-wide asyncio.Lock before opening the session,
    serialising concurrent worker writes and eliminating 'database is locked' errors.
    On Postgres: no lock — the database handles concurrent writes natively.

    Workers that open their own sessions (not via get_db) must use this instead
    of AsyncSessionLocal() directly. To switch backends, change _write_lock here.
    """
    if _write_lock is not None:
        async with _write_lock:
            async with AsyncSessionLocal() as session:
                yield session
    else:
        async with AsyncSessionLocal() as session:
            yield session


def _run_migrations() -> None:
    """Run all pending Alembic migrations synchronously.

    Called from init() via run_in_executor so the async event loop is not
    blocked. Uses the sync SQLite driver; the app uses the async driver at
    runtime.
    """
    from alembic.config import Config
    from alembic import command

    cfg = Config(Path(__file__).parent.parent / "alembic.ini")
    command.upgrade(cfg, "head")


async def init() -> None:
    from . import models  # noqa: F401 — registers all models on Base.metadata

    loop = asyncio.get_event_loop()
    logger.info("Running database migrations...")
    await loop.run_in_executor(None, _run_migrations)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session
