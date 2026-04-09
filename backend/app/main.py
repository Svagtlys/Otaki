import asyncio
import contextlib
import logging
from logging.config import dictConfig
import jwt
from contextlib import asynccontextmanager

from fastapi import FastAPI

from fastapi.responses import JSONResponse
from starlette.requests import Request

from . import database
from .api import auth, health, requests, search, settings as settings_api, setup, sources
from .config import settings
from .database import AsyncSessionLocal
from .services import auth as auth_service
from .services import download_scanner
from .workers import download_listener, scheduler

LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "%(asctime)s | %(name)-15s | %(levelname)-8s | %(message)s",
            "datefmt": "%Y-%m-%d %H:%M:%S",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
            "stream": "ext://sys.stdout",
        },
    },
    "loggers": {
        # The Root Logger: Catch-all for Alembic, libraries, etc.
        "": {
            "handlers": ["console"],
            "level": "INFO",
        },
        "otaki": {"handlers": ["console"], "level": "INFO", "propagate": False},
        # SQLALCHEMY: Controls SQL echo.
        # "INFO" shows queries, "DEBUG" shows queries + results.
        "sqlalchemy.engine": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        # GQL / GRAPHQL:
        # Use "gql" for the GQL transport library or "strawberry"/"ariadne"
        # depending on your specific GraphQL framework.
        "gql": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        # HTTPX: Very chatty by default.
        "httpx": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": False,
        },
        "uvicorn": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "uvicorn.access": {
            "handlers": ["console"],
            "level": "INFO",
            "propagate": False,
        },
        "alembic": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}

# Apply the config immediately!
dictConfig(LOGGING_CONFIG)

# Create the logger instance for this specific file
logger = logging.getLogger("otaki")


_SETUP_EXEMPT = ("/api/setup", "/api/auth", "/api/health", "/docs", "/openapi.json", "/redoc")
# <img> tags cannot send JWT — these paths must be publicly accessible
_AUTH_EXEMPT = ("/api/search/thumbnail", "/api/health")


def _auth_required(path: str) -> bool:
    if any(path.startswith(p) for p in _SETUP_EXEMPT):
        return False
    if any(path.startswith(p) for p in _AUTH_EXEMPT):
        return False
    if path.endswith("/cover"):  # /api/requests/{id}/cover
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Otaki...")

    logger.info("Initializing database...")
    await database.init()

    logger.info("Starting scheduler...")
    async with AsyncSessionLocal() as db:
        await scheduler.start(db)

    logger.info("Starting download listener...")
    task = asyncio.create_task(download_listener.run())

    if settings.SUWAYOMI_DOWNLOAD_PATH and settings.LIBRARY_PATH:
        logger.info("Scanning for existing downloads...")
        async with AsyncSessionLocal() as db:
            result = await download_scanner.scan_existing_downloads(db)
            logger.info("Startup scan complete: %s", result)

    yield

    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    if scheduler.scheduler.running:
        scheduler.scheduler.shutdown(wait=False)


app = FastAPI(title="Otaki", lifespan=lifespan)
app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(search.router, prefix="/api")
app.include_router(requests.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(sources.router, prefix="/api")


# Middleware runs in reverse registration order (last registered = outermost = runs first).
# require_setup is registered last so it runs first, blocking unauthenticated routes
# before the auth check even runs.


@app.middleware("http")
async def require_auth_middleware(request: Request, call_next):
    path = request.url.path
    if not _auth_required(path):
        return await call_next(request)

    token = None
    authorization = request.headers.get("Authorization")
    if authorization and authorization.startswith("Bearer "):
        token = authorization.removeprefix("Bearer ")
    elif "otaki_session" in request.cookies:
        token = request.cookies["otaki_session"]

    if not token:
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)

    try:
        auth_service.decode_token(token)
    except jwt.InvalidTokenError:
        return JSONResponse({"detail": "Invalid or expired token"}, status_code=401)

    return await call_next(request)


@app.middleware("http")
async def require_setup(request: Request, call_next):
    path = request.url.path
    setup_complete = (
        settings.SUWAYOMI_URL is not None
        and settings.SUWAYOMI_DOWNLOAD_PATH is not None
        and settings.LIBRARY_PATH is not None
    )
    if not setup_complete and not any(path.startswith(p) for p in _SETUP_EXEMPT):
        return JSONResponse({"detail": "Setup required"}, status_code=503)
    return await call_next(request)
