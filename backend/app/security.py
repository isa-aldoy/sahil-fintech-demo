"""Password hashing and token primitives."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

from .config import get_settings

# Argon2id (the library default variant) with OWASP-recommended cost parameters.
_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=2)
# Verified against when the e-mail is unknown so both paths cost the same time.
_DUMMY_HASH = _hasher.hash(secrets.token_urlsafe(16))

_COMMON = {
    "password123", "1234567890", "qwertyuiop", "password1234", "iloveyou123",
    "12345678910", "qwerty12345", "letmein12345", "passwordpassword", "0123456789",
    "administrator", "welcome12345", "sahil12345", "bahrain12345",
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def password_problem(password: str, email: str = "", name: str = "") -> str | None:
    """Return a human-readable reason the password is unacceptable, or None."""
    if len(password) < 10:
        return "Use at least 10 characters."
    if len(password) > 128:
        return "Use at most 128 characters."
    lowered = password.lower()
    if lowered in _COMMON or len(set(password)) < 5:
        return "That password is too easy to guess."
    local = email.split("@")[0].lower()
    if len(local) >= 4 and local in lowered:
        return "Don't use your e-mail in your password."
    return None


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, stored: str | None) -> bool:
    try:
        return _hasher.verify(stored or _DUMMY_HASH, password) and stored is not None
    except (VerificationError, InvalidHashError):
        return False


def needs_rehash(stored: str) -> bool:
    return _hasher.check_needs_rehash(stored)


def new_refresh_token() -> tuple[str, str]:
    """Return (token for the client, hash for the database)."""
    token = secrets.token_urlsafe(48)
    return token, hash_token(token)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_access_token(user_id: uuid.UUID, session_id: uuid.UUID) -> tuple[str, int]:
    s = get_settings()
    ttl = s.access_token_minutes * 60
    issued = now()
    payload = {
        "sub": str(user_id), "sid": str(session_id), "typ": "access",
        "iss": s.jwt_issuer, "aud": s.jwt_audience,
        "iat": issued, "exp": issued + timedelta(seconds=ttl), "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm="HS256"), ttl


def decode_access_token(token: str) -> dict:
    """Raises jwt.PyJWTError on any problem. The algorithm is pinned (no 'none', no RS/HS mix-up)."""
    s = get_settings()
    claims = jwt.decode(
        token, s.jwt_secret, algorithms=["HS256"], audience=s.jwt_audience, issuer=s.jwt_issuer,
        options={"require": ["exp", "iat", "sub", "sid", "aud", "iss"]},
    )
    if claims.get("typ") != "access":
        raise jwt.InvalidTokenError("wrong token type")
    return claims
