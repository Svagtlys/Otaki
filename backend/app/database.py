import asyncio
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from .config import settings

import logging

logger = logging.getLogger(f"otaki.{__name__}")

logger.info("Initializing database...")

engine = create_async_engine(settings.DATABASE_URL)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


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
