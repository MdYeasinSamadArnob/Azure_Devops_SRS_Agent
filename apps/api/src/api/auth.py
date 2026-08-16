"""Login/logout/me — see src.auth.sessions for the cookie mechanism."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from srs_core.auth.passwords import verify_password

from src.auth.sessions import SESSION_COOKIE_NAME, SESSION_TTL_DAYS, create_session, require_user
from src.database.models import User, UserSession
from src.database.session import get_db_session

router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    email: str
    password: str


class UserResponse(BaseModel):
    email: str
    is_superuser: bool


@router.post("/login", response_model=UserResponse)
async def login(body: LoginRequest, response: Response, db: AsyncSession = Depends(get_db_session)) -> UserResponse:
    result = await db.execute(select(User).where(User.email == body.email.strip().lower()))
    user = result.scalar_one_or_none()
    # Same 401 regardless of whether the email exists — never confirm which
    # part was wrong to an unauthenticated caller.
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="invalid email or password")

    session = await create_session(db, user.id)
    await db.commit()

    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=str(session.id),
        max_age=SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=False,  # dev runs over plain http; flip to True once served over https
        path="/",
    )
    return UserResponse(email=user.email, is_superuser=user.is_superuser)


@router.post("/logout")
async def logout(request: Request, response: Response, db: AsyncSession = Depends(get_db_session)) -> dict:
    raw_session_id = request.cookies.get(SESSION_COOKIE_NAME)
    if raw_session_id:
        try:
            session_id = uuid.UUID(raw_session_id)
        except ValueError:
            session_id = None
        if session_id is not None:
            await db.execute(delete(UserSession).where(UserSession.id == session_id))
            await db.commit()
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return {"status": "ok"}


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(require_user)) -> UserResponse:
    return UserResponse(email=user.email, is_superuser=user.is_superuser)
