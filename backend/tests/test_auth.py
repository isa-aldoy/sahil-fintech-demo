"""Authentication, password storage and session management."""
import time
import uuid
from datetime import timedelta

import httpx
import jwt
from sqlalchemy import select, update

from app.config import get_settings
from app.models import AuditLog, AuthSession, RefreshToken, User
from app.security import create_access_token, hash_token, now

from .conftest import BASE, PASSWORD, Customer


def _register(http, email=None, password=PASSWORD, name="Sara Tester"):
    email = email or f"sara-{uuid.uuid4().hex[:8]}@test.example"
    return http.post("/api/v1/auth/register", json={"email": email, "full_name": name, "password": password}), email


def test_register_creates_accounts_and_signs_in(http):
    r, email = _register(http)
    assert r.status_code == 201
    body = r.json()
    assert body["user"]["email"] == email
    accounts = http.get("/api/v1/accounts", headers={"Authorization": f"Bearer {body['access_token']}"}).json()
    assert sorted(a["kind"] for a in accounts) == ["current", "savings"]
    assert all(a["balance_fils"] == 0 for a in accounts)


def test_password_is_stored_as_argon2id_never_plaintext(http, db):
    r, email = _register(http)
    stored = db.execute(select(User.password_hash).where(User.email == email)).scalar_one()
    assert stored.startswith("$argon2id$")
    assert PASSWORD not in stored
    assert "password" not in r.text.lower().replace("password_hash", "") or PASSWORD not in r.text


def test_weak_passwords_are_rejected(http):
    for bad in ["short", "password123", "aaaaaaaaaaaa", "1234567890"]:
        r, _ = _register(http, password=bad)
        assert r.status_code == 422, bad
    r, _ = _register(http, email="fatima.ali@test.example", password="xx-fatima.ali-2026")
    assert r.status_code == 422


def test_duplicate_registration_gives_no_hint(http):
    _, email = _register(http)
    r, _ = _register(http, email=email)
    assert r.status_code == 400
    assert "already" not in r.text.lower() and "exists" not in r.text.lower()


def test_login_errors_do_not_reveal_whether_email_exists(http, alice):
    wrong_pw = http.post("/api/v1/auth/login", json={"email": alice.email, "password": "Wrong-Password-1"})
    unknown = http.post("/api/v1/auth/login", json={"email": "nobody@test.example", "password": "Wrong-Password-1"})
    assert wrong_pw.status_code == unknown.status_code == 401
    assert wrong_pw.json() == unknown.json()


def test_account_locks_after_repeated_failures_even_with_right_password(http, db):
    victim = Customer("victim")
    for _ in range(get_settings().max_failed_logins):
        assert http.post("/api/v1/auth/login", json={"email": victim.email, "password": "nope-nope-nope"}).status_code == 401
    r = http.post("/api/v1/auth/login", json={"email": victim.email, "password": PASSWORD})
    assert r.status_code == 423
    events = db.execute(select(AuditLog.event).where(AuditLog.user_id == victim.id)).scalars().all()
    assert "auth.account_locked" in events and "auth.login_blocked" in events
    # After the lock window passes, the customer can sign in again.
    db.execute(update(User).where(User.id == victim.id).values(locked_until=now() - timedelta(seconds=1)))
    db.commit()
    assert http.post("/api/v1/auth/login", json={"email": victim.email, "password": PASSWORD}).status_code == 200


def test_system_user_cannot_sign_in_or_be_paid(http, alice):
    r = http.post("/api/v1/auth/login", json={"email": "system@sahil.invalid", "password": "anything-at-all"})
    assert r.status_code == 401
    assert alice.send("sahil-system", "1").status_code == 404


def test_protected_routes_require_a_token(http):
    assert http.get("/api/v1/accounts").status_code == 401
    assert http.get("/api/v1/accounts", headers={"Authorization": "Bearer nonsense"}).status_code == 401


def test_forged_and_malformed_tokens_are_rejected(http, alice):
    s = get_settings()
    claims = jwt.decode(alice.access, options={"verify_signature": False})
    forged = {
        "wrong key": jwt.encode(claims, "x" * 48, algorithm="HS256"),
        "alg none": jwt.encode(claims, None, algorithm="none"),
        "wrong audience": jwt.encode({**claims, "aud": "other-app"}, s.jwt_secret, algorithm="HS256"),
        "wrong issuer": jwt.encode({**claims, "iss": "evil"}, s.jwt_secret, algorithm="HS256"),
        "expired": jwt.encode({**claims, "exp": int(time.time()) - 5}, s.jwt_secret, algorithm="HS256"),
        "refresh typ": jwt.encode({**claims, "typ": "refresh"}, s.jwt_secret, algorithm="HS256"),
        "no session": jwt.encode({k: v for k, v in claims.items() if k != "sid"}, s.jwt_secret, algorithm="HS256"),
        "other user's id on my session": jwt.encode({**claims, "sub": str(uuid.uuid4())}, s.jwt_secret, algorithm="HS256"),
    }
    for label, token in forged.items():
        r = http.get("/api/v1/accounts", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, label


def test_refresh_rotates_and_old_token_stops_working(http, alice):
    r = http.post("/api/v1/auth/refresh", json={"refresh_token": alice.refresh})
    assert r.status_code == 200
    new = r.json()
    assert new["refresh_token"] != alice.refresh
    assert http.get("/api/v1/accounts", headers={"Authorization": f"Bearer {new['access_token']}"}).status_code == 200


def test_reusing_a_refresh_token_revokes_the_whole_session(http, alice, db):
    first = http.post("/api/v1/auth/refresh", json={"refresh_token": alice.refresh}).json()
    # An attacker replays the stolen (already used) token:
    replay = http.post("/api/v1/auth/refresh", json={"refresh_token": alice.refresh})
    assert replay.status_code == 401
    # ...which kills the session, including the legitimately rotated tokens.
    assert http.post("/api/v1/auth/refresh", json={"refresh_token": first["refresh_token"]}).status_code == 401
    assert http.get("/api/v1/accounts", headers={"Authorization": f"Bearer {first['access_token']}"}).status_code == 401
    events = db.execute(select(AuditLog.event).where(AuditLog.user_id == alice.id)).scalars().all()
    assert "auth.refresh_reuse_detected" in events


def test_refresh_tokens_are_stored_hashed(alice, db):
    hashes = db.execute(select(RefreshToken.token_hash)).scalars().all()
    assert alice.refresh not in hashes
    assert hash_token(alice.refresh) in hashes


def test_logout_invalidates_the_access_token_immediately(http, alice):
    assert alice.post("/api/v1/auth/logout").status_code == 204
    assert alice.get("/api/v1/accounts").status_code == 401
    assert http.post("/api/v1/auth/refresh", json={"refresh_token": alice.refresh}).status_code == 401


def test_logout_all_signs_out_every_device(alice):
    phone = (alice.access, alice.refresh)
    alice.login()  # second device
    assert len(alice.get("/api/v1/auth/sessions").json()) == 2
    assert alice.post("/api/v1/auth/logout-all").status_code == 204
    for access in (phone[0], alice.access):
        assert httpx.get(f"{BASE}/api/v1/accounts", headers={"Authorization": f"Bearer {access}"}).status_code == 401


def test_change_password_requires_current_and_signs_out_other_devices(alice):
    other_device = alice.access
    alice.login()
    bad = alice.post("/api/v1/auth/change-password", json={"current_password": "wrong", "new_password": "New-Password-77-Long"})
    assert bad.status_code == 403
    ok = alice.post("/api/v1/auth/change-password", json={"current_password": PASSWORD, "new_password": "New-Password-77-Long"})
    assert ok.status_code == 204
    assert alice.get("/api/v1/accounts").status_code == 200
    assert httpx.get(f"{BASE}/api/v1/accounts", headers={"Authorization": f"Bearer {other_device}"}).status_code == 401
    assert httpx.post(f"{BASE}/api/v1/auth/login", json={"email": alice.email, "password": PASSWORD}).status_code == 401


def test_expired_session_is_rejected_even_with_valid_signature(alice, db):
    sid = jwt.decode(alice.access, options={"verify_signature": False})["sid"]
    db.execute(update(AuthSession).where(AuthSession.id == uuid.UUID(sid)).values(expires_at=now() - timedelta(minutes=1)))
    db.commit()
    token, _ = create_access_token(alice.id, uuid.UUID(sid))
    assert httpx.get(f"{BASE}/api/v1/accounts", headers={"Authorization": f"Bearer {token}"}).status_code == 401
