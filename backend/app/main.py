import jwt
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.requests import Request

from . import database
from .api import auth, setup
from .config import settings
from .services import auth as auth_service

_SETUP_EXEMPT = ("/api/setup", "/api/auth", "/docs", "/openapi.json", "/redoc")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await database.init()
    yield


app = FastAPI(title="Otaki", lifespan=lifespan)
app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")


# Middleware runs in reverse registration order (last registered = outermost = runs first).
# require_setup is registered last so it runs first, blocking unauthenticated routes
# before the auth check even runs.


@app.middleware("http")
async def require_auth_middleware(request: Request, call_next):
    path = request.url.path
    if any(path.startswith(p) for p in _SETUP_EXEMPT):
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
