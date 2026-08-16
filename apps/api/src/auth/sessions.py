"""Session-cookie auth. The cookie holds only an opaque `session_id`
(random UUID) — no user data — looked up against `user_sessions` joined to
`users`. Chosen over JWT so logout/revocation is just deleting a row (see
`srs_core.db.models.UserSession`'s docstring for why).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import User, UserSession
from src.database.session import get_db_session

SESSION_COOKIE_NAME = "session_id"
SESSION_TTL_DAYS = 14


async def create_session(db: AsyncSession, user_id: uuid.UUID) -> UserSession:
    session = UserSession(user_id=user_id, expires_at=datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS))
    db.add(session)
    await db.flush()
    return session


async def get_current_user(request: Request, db: AsyncSession = Depends(get_db_session)) -> User | None:
    raw_session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if not raw_session_id:
        return None
    try:
        session_id = uuid.UUID(raw_session_id)
    except ValueError:
        return None

    result = await db.execute(
        select(UserSession, User).join(User, User.id == UserSession.user_id).where(UserSession.id == session_id)
    )
    row = result.first()
    if row is None:
        return None
    session, user = row
    if session.expires_at < datetime.now(timezone.utc):
        return None
    return user


async def require_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    return user
