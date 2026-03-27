import jwt
from fastapi import APIRouter, Cookie, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.user import User
from ..services import auth

router = APIRouter(prefix="/auth", tags=["auth"])


# --- Schemas ---


class LoginRequest(BaseModel):
    username: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: int
    username: str


# --- Dependencies ---


def _extract_token(
    authorization: str | None = Header(default=None),
    otaki_session: str | None = Cookie(default=None),
) -> str:
    """Extract JWT from Authorization: Bearer header or otaki_session cookie."""
    if authorization and authorization.startswith("Bearer "):
        return authorization.removeprefix("Bearer ")
    if otaki_session:
        return otaki_session
    raise HTTPException(status_code=401, detail="Not authenticated")


async def require_auth(
    token: str = Depends(_extract_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Validate JWT and return the active User. Use as a route dependency."""
    try:
        payload = auth.decode_token(token)
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await db.get(User, int(payload["sub"]))
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


# --- Endpoints ---


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
) -> TokenResponse:
    user = await db.scalar(select(User).where(User.username == body.username))
    if not user or not auth.verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return TokenResponse(access_token=auth.create_token(user.id))


@router.post("/logout")
async def logout() -> None:
    pass


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(require_auth)) -> UserResponse:
    return UserResponse(id=user.id, username=user.username)
