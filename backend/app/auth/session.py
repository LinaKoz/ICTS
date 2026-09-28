"""Signed HttpOnly SameSite=Lax session cookie (§6 "Auth") and the
`require_role()` dependency (P12).

The cookie holds only the signed user id (itsdangerous), so no server-
side session store is needed. The secret is resolved once per process
at import time: per §2, an empty `SESSION_SECRET` gets a random value,
and sessions reset on restart.
"""
from __future__ import annotations

from itsdangerous import BadSignature, URLSafeTimedSerializer
from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.config import settings
from app.db import get_session
from app.errors import ForbiddenError, UnauthorizedError

COOKIE_NAME = "session"
_MAX_AGE_S = 60 * 60 * 24 * 7  # 7 days

_serializer = URLSafeTimedSerializer(settings.resolved_session_secret(), salt="icts-session")


def set_session_cookie(response: Response, user_id: int) -> None:
    token = _serializer.dumps(user_id)
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=_MAX_AGE_S,
        httponly=True,
        samesite="lax",
        secure=False,  # same-origin over nginx in local demo (§6); no TLS
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def _read_user_id(request: Request) -> int | None:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        return None
    try:
        return _serializer.loads(token, max_age=_MAX_AGE_S)
    except BadSignature:
        return None


async def get_current_user(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User:
    user_id = _read_user_id(request)
    if user_id is None:
        raise UnauthorizedError("not authenticated")
    user = await session.get(User, user_id)
    if user is None:
        raise UnauthorizedError("not authenticated")
    return user


async def get_current_user_optional(
    request: Request, session: AsyncSession = Depends(get_session)
) -> User | None:
    user_id = _read_user_id(request)
    if user_id is None:
        return None
    return await session.get(User, user_id)


def require_role(*roles: str):
    """FastAPI dependency factory: 403 if the current user's `app_role`
    is not one of `roles` (P12). 401 if not authenticated."""

    async def _dependency(user: User = Depends(get_current_user)) -> User:
        if user.app_role not in roles:
            raise ForbiddenError(f"requires role {roles}, has {user.app_role}")
        return user

    return _dependency
