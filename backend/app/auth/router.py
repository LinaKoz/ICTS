"""`POST /auth/login`, `POST /auth/logout`, `GET /auth/me` (§6)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import LoginIn, LogoutOut, UserOut
from app.auth.security import verify_password
from app.auth.session import clear_session_cookie, get_current_user, set_session_cookie
from app.api_schemas.common import error_responses
from app.db import get_session
from app.errors import UnauthorizedError

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login", response_model=UserOut, responses=error_responses(401, 422))
async def login(
    body: LoginIn, response: Response, session: AsyncSession = Depends(get_session)
) -> UserOut:
    user = (
        await session.execute(select(User).where(User.username == body.username))
    ).scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise UnauthorizedError("invalid username or password")
    set_session_cookie(response, user.id)
    return UserOut.model_validate(user, from_attributes=True)


@router.post("/logout", response_model=LogoutOut)
async def logout(response: Response) -> LogoutOut:
    """Always 200 `{"status": "ok"}`, also when no session exists; clears the cookie."""
    clear_session_cookie(response)
    return LogoutOut(status="ok")


@router.get("/me", response_model=UserOut, responses=error_responses(401))
async def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)
