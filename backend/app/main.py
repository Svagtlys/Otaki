from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from . import database
from .api import auth, setup
from .config import settings

_SETUP_EXEMPT = ("/api/setup", "/api/auth", "/docs", "/openapi.json", "/redoc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init()
    yield


app = FastAPI(title="Otaki", lifespan=lifespan)
app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")


@app.middleware("http")
async def require_setup(request: Request, call_next):
    path = request.url.path
    if settings.SUWAYOMI_URL is None and not any(
        path.startswith(p) for p in _SETUP_EXEMPT
    ):
        return JSONResponse({"detail": "Setup required"}, status_code=503)
    return await call_next(request)
