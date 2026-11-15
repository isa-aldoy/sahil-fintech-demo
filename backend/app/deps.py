"""Authentication dependency: every protected route gets the user from here and nowhere else."""
import uuid
from dataclasses import dataclass

import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .errors import ApiError
from .models import AuthSession, User
from .ratelimit import client_ip
from .security import decode_access_token, now

_bearer = HTTPBearer(auto_error=False)
_UNAUTH = ApiError(401, "not_signed_in", "Please sign in again.", headers={"WWW-Authenticate": "Bearer"})


@dataclass
class Principal:
    user: User
    session_id: uuid.UUID
    ip: str


def current(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> Principal:
    if creds is None:
        raise _UNAUTH
    try:
        claims = decode_access_token(creds.credentials)
        user_id, session_id = uuid.UUID(claims["sub"]), uuid.UUID(claims["sid"])
    except (jwt.PyJWTError, ValueError, KeyError):
        raise _UNAUTH from None
    # A valid signature is not enough: the session must still be alive in the database,
    # so "sign out" and "sign out everywhere" take effect immediately.
    row = db.execute(
        select(User, AuthSession).join(AuthSession, AuthSession.user_id == User.id)
        .where(AuthSession.id == session_id, User.id == user_id)
    ).first()
    if row is None:
        raise _UNAUTH
    user, session = row
    if session.revoked_at is not None or session.expires_at <= now() or user.is_system:
        raise _UNAUTH
    return Principal(user=user, session_id=session_id, ip=client_ip(request))
