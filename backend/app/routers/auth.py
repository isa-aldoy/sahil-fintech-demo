import re
import secrets
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, ratelimit
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, current
from ..errors import ApiError
from ..models import Account, AuthSession, Card, RefreshToken, User
from ..schemas import AuthOut, ChangePasswordIn, LoginIn, RefreshIn, RegisterIn, SessionOut, TokensOut, UserOut
from ..security import (
    create_access_token, hash_password, hash_token, needs_rehash, new_refresh_token, now,
    password_problem, verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_BAD_LOGIN = ApiError(401, "invalid_credentials", "E-mail or password is incorrect.")


def new_account_number() -> str:
    """A clearly fictional IBAN-shaped number (bank code SAHL does not exist)."""
    return "BH00SAHL" + "".join(secrets.choice("0123456789") for _ in range(14))


def _device(request: Request) -> str:
    return (request.headers.get("user-agent") or "Unknown device")[:200]


def friendly_device(user_agent: str) -> str:
    """'Mozilla/5.0 (Windows NT 10.0 ...) Chrome/...' -> 'Chrome on Windows'."""
    ua = user_agent.lower()
    browser = next((name for key, name in (("edg/", "Edge"), ("firefox", "Firefox"), ("chrome", "Chrome"),
                                           ("safari", "Safari"), ("dart", "Sahil app")) if key in ua), "App")
    system = next((name for key, name in (("android", "Android"), ("iphone", "iPhone"), ("ipad", "iPad"),
                                          ("windows", "Windows"), ("mac os", "Mac"), ("linux", "Linux")) if key in ua), "")
    return f"{browser} on {system}" if system else browser


def _start_session(db: Session, user: User, request: Request) -> tuple[AuthSession, str]:
    s = get_settings()
    session = AuthSession(user_id=user.id, user_agent=_device(request), ip=ratelimit.client_ip(request),
                          expires_at=now() + timedelta(days=s.session_max_days))
    db.add(session)
    db.flush()
    return session, _issue_refresh(db, session)


def _issue_refresh(db: Session, session: AuthSession) -> str:
    token, digest = new_refresh_token()
    expires = min(now() + timedelta(days=get_settings().refresh_token_days), session.expires_at)
    db.add(RefreshToken(session_id=session.id, token_hash=digest, expires_at=expires))
    return token


def _tokens(user: User, session: AuthSession, refresh: str) -> dict:
    access, ttl = create_access_token(user.id, session.id)
    return {"access_token": access, "refresh_token": refresh, "expires_in": ttl}


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, email=user.email, handle=user.handle, full_name=user.full_name)


def create_user(db: Session, email: str, full_name: str, password: str, handle: str | None = None) -> User:
    base = re.sub(r"[^a-z0-9]", "", full_name.lower().split()[0])[:16] or "user"
    user = User(email=email, full_name=full_name, password_hash=hash_password(password),
                handle=handle or f"{base}{secrets.randbelow(9000) + 1000}")
    db.add(user)
    db.flush()
    current_acc = Account(user_id=user.id, kind="current", name="Everyday", number=new_account_number())
    db.add_all([current_acc, Account(user_id=user.id, kind="savings", name="Savings", number=new_account_number())])
    db.flush()
    db.add(Card(user_id=user.id, account_id=current_acc.id, expiry="11/29",
                last4=f"{secrets.randbelow(10000):04d}"))
    return user


@router.post("/register", response_model=AuthOut, status_code=201,
             dependencies=[Depends(ratelimit.limit_ip("register", 5, 3600))])
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    problem = password_problem(body.password, body.email, body.full_name)
    if problem:
        raise ApiError(422, "weak_password", problem)
    try:
        user = create_user(db, body.email, body.full_name, body.password)
        session, refresh = _start_session(db, user, request)
        audit.record(db, "auth.registered", user.id, ratelimit.client_ip(request))
        db.commit()
    except IntegrityError:
        db.rollback()
        # Deliberately vague so the form cannot be used to discover who has an account.
        raise ApiError(400, "registration_failed", "We couldn't create an account with these details.") from None
    return {**_tokens(user, session, refresh), "user": _user_out(user)}


@router.post("/login", response_model=AuthOut, dependencies=[Depends(ratelimit.limit_ip("login-ip", 20, 60))])
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    ip = ratelimit.client_ip(request)
    ratelimit.check("login-email", body.email, 10, 300)
    user = db.execute(select(User).where(User.email == body.email).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if user is not None and user.is_system:
        user = None
    locked = bool(user and user.locked_until and user.locked_until > now())
    # Always run the hash so unknown e-mails and wrong passwords take the same time.
    ok = verify_password(body.password, user.password_hash if user else None)

    if user is None:
        audit.record(db, "auth.login_failed", None, ip, reason="unknown_email")
        db.commit()
        raise _BAD_LOGIN
    if locked:
        audit.record(db, "auth.login_blocked", user.id, ip, reason="locked")
        db.commit()
        raise ApiError(423, "account_locked", "Too many wrong attempts. Try again in a few minutes.")
    if not ok:
        user.failed_logins += 1
        if user.failed_logins >= s.max_failed_logins:
            user.locked_until = now() + timedelta(minutes=s.lockout_minutes)
            user.failed_logins = 0
            audit.record(db, "auth.account_locked", user.id, ip, minutes=s.lockout_minutes)
        audit.record(db, "auth.login_failed", user.id, ip, reason="wrong_password")
        db.commit()
        raise _BAD_LOGIN

    user.failed_logins, user.locked_until = 0, None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    session, refresh = _start_session(db, user, request)
    audit.record(db, "auth.login", user.id, ip, session=str(session.id))
    db.commit()
    return {**_tokens(user, session, refresh), "user": _user_out(user)}


@router.post("/refresh", response_model=TokensOut, dependencies=[Depends(ratelimit.limit_ip("refresh", 60, 60))])
def refresh(body: RefreshIn, request: Request, db: Session = Depends(get_db)):
    """Rotate the refresh token. Presenting an already-used token is treated as theft."""
    invalid = ApiError(401, "session_expired", "Please sign in again.")
    ip = ratelimit.client_ip(request)
    token = db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token)).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if token is None:
        raise invalid
    session = db.execute(select(AuthSession).where(AuthSession.id == token.session_id).with_for_update().execution_options(populate_existing=True)).scalar_one()
    if token.used_at is not None:
        if session.revoked_at is None:
            session.revoked_at, session.revoked_reason = now(), "refresh_reuse"
            audit.record(db, "auth.refresh_reuse_detected", session.user_id, ip, session=str(session.id))
            db.commit()
        raise invalid
    if session.revoked_at is not None or token.expires_at <= now() or session.expires_at <= now():
        raise invalid
    user = db.get(User, session.user_id)
    token.used_at = now()
    session.last_seen_at = now()
    new_refresh = _issue_refresh(db, session)
    db.commit()
    return _tokens(user, session, new_refresh)


def _revoke(db: Session, user_id: uuid.UUID, reason: str, only: uuid.UUID | None = None,
            keep: uuid.UUID | None = None) -> int:
    q = update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
    if only:
        q = q.where(AuthSession.id == only)
    if keep:
        q = q.where(AuthSession.id != keep)
    return db.execute(q.values(revoked_at=now(), revoked_reason=reason)).rowcount


@router.post("/logout", status_code=204)
def logout(p: Principal = Depends(current), db: Session = Depends(get_db)):
    _revoke(db, p.user.id, "logout", only=p.session_id)
    audit.record(db, "auth.logout", p.user.id, p.ip)
    db.commit()


@router.post("/logout-all", status_code=204)
def logout_all(p: Principal = Depends(current), db: Session = Depends(get_db)):
    n = _revoke(db, p.user.id, "logout_all")
    audit.record(db, "auth.logout_all", p.user.id, p.ip, sessions=n)
    db.commit()


@router.get("/me", response_model=UserOut)
def me(p: Principal = Depends(current)):
    return _user_out(p.user)


@router.get("/sessions", response_model=list[SessionOut])
def sessions(p: Principal = Depends(current), db: Session = Depends(get_db)):
    rows = db.execute(
        select(AuthSession).where(AuthSession.user_id == p.user.id, AuthSession.revoked_at.is_(None),
                                  AuthSession.expires_at > now()).order_by(AuthSession.last_seen_at.desc())
    ).scalars()
    return [SessionOut(id=r.id, device=friendly_device(r.user_agent), created_at=r.created_at, last_seen_at=r.last_seen_at,
                       current=r.id == p.session_id) for r in rows]


@router.delete("/sessions/{session_id}", status_code=204)
def revoke_session(session_id: uuid.UUID, p: Principal = Depends(current), db: Session = Depends(get_db)):
    if _revoke(db, p.user.id, "revoked_by_user", only=session_id) == 0:
        raise ApiError(404, "not_found", "That device is no longer signed in.")
    audit.record(db, "auth.session_revoked", p.user.id, p.ip, session=str(session_id))
    db.commit()


@router.post("/change-password", status_code=204,
             dependencies=[Depends(ratelimit.limit_ip("change-password", 10, 600))])
def change_password(body: ChangePasswordIn, p: Principal = Depends(current), db: Session = Depends(get_db)):
    user = db.execute(select(User).where(User.id == p.user.id).with_for_update().execution_options(populate_existing=True)).scalar_one()
    if not verify_password(body.current_password, user.password_hash):
        audit.record(db, "auth.password_change_failed", user.id, p.ip)
        db.commit()
        raise ApiError(403, "wrong_password", "Your current password is incorrect.")
    problem = password_problem(body.new_password, user.email, user.full_name)
    if problem:
        raise ApiError(422, "weak_password", problem)
    user.password_hash = hash_password(body.new_password)
    n = _revoke(db, user.id, "password_changed", keep=p.session_id)
    audit.record(db, "auth.password_changed", user.id, p.ip, other_sessions_signed_out=n)
    db.commit()
