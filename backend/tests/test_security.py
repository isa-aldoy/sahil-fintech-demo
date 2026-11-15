"""Rate limiting, injection, headers, configuration, and the tamper-evident audit log."""
import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import audit
from app.config import Settings
from app.models import AuditLog, User

from .conftest import BASE, PASSWORD, Customer


def test_login_is_rate_limited_per_ip(http):
    codes = [http.post("/api/v1/auth/login", json={"email": f"x{i}@test.example", "password": "whatever-123"}).status_code
             for i in range(25)]
    assert codes[:20] == [401] * 20
    assert codes[20:] == [429] * 5
    r = http.post("/api/v1/auth/login", json={"email": "y@test.example", "password": "whatever-123"})
    assert int(r.headers["Retry-After"]) >= 1


def test_password_guessing_against_one_account_is_throttled(http):
    target = f"target-{id(http)}@test.example"
    codes = [http.post("/api/v1/auth/login", json={"email": target, "password": f"guess-number-{i}"}).status_code
             for i in range(12)]
    assert 429 in codes[10:]


def test_registration_and_chat_are_rate_limited(http, alice):
    codes = [http.post("/api/v1/auth/register", json={"email": f"r{i}-{id(http)}@test.example", "full_name": "Rate Test",
                                                      "password": PASSWORD}).status_code for i in range(7)]
    assert codes.count(201) == 5 and codes[-1] == 429
    chat = [alice.post("/api/chat", json={"message": "balance"}).status_code for _ in range(22)]
    assert chat.count(200) == 20 and chat[-1] == 429


SQLI = ["' OR '1'='1", "'; DROP TABLE users; --", "\" OR \"\"=\"", "admin'--", "%' UNION SELECT password_hash FROM users --"]


@pytest.mark.parametrize("payload", SQLI)
def test_sql_injection_attempts_are_inert(http, alice, db, payload):
    assert http.post("/api/v1/auth/login", json={"email": payload, "password": payload}).status_code in (401, 422)
    assert http.post("/api/v1/auth/login", json={"email": alice.email, "password": payload}).status_code == 401
    r = alice.get("/api/v1/transactions", params={"search": payload[:40]})
    assert r.status_code == 200 and r.json() == []
    assert alice.get("/api/v1/recipients/lookup", params={"q": payload[:40]}).status_code == 404
    assert "argon2" not in r.text
    assert db.execute(select(User.id).where(User.id == alice.id)).scalar_one() == alice.id  # table still there


def test_security_headers_on_every_response(http, alice):
    for r in (http.get("/health"), alice.get("/api/v1/accounts"), http.get("/api/v1/accounts"), http.get("/nope")):
        assert r.headers["X-Content-Type-Options"] == "nosniff"
        assert r.headers["X-Frame-Options"] == "DENY"
        assert r.headers["Referrer-Policy"] == "no-referrer"
        assert "server" not in {k.lower() for k in r.headers} or "uvicorn" not in r.headers.get("server", "")
    api = alice.get("/api/v1/accounts")
    assert api.headers["Cache-Control"] == "no-store"
    assert "default-src 'none'" in api.headers["Content-Security-Policy"]


def test_cors_only_allows_the_configured_origin(http):
    def preflight(origin):
        return http.options("/api/v1/accounts", headers={"Origin": origin, "Access-Control-Request-Method": "GET"})
    assert preflight("http://localhost:5173").headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = preflight("https://evil.example")
    assert "access-control-allow-origin" not in evil.headers
    assert "access-control-allow-credentials" not in preflight("http://localhost:5173").headers


def test_oversized_request_is_refused(http):
    r = http.post("/api/v1/auth/login", content=b'{"email":"a@b.co","password":"' + b"x" * 40_000 + b'"}',
                  headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_errors_never_leak_internals(http, alice):
    for r in (http.post("/api/v1/auth/login", content=b"{not json", headers={"Content-Type": "application/json"}),
              alice.get("/api/v1/transactions", params={"limit": "100000"}),
              alice.get("/api/v1/accounts/not-a-uuid/top-up")):
        assert r.status_code in (404, 405, 422)
        for leak in ("Traceback", "sqlalchemy", "psycopg", "File \"", "app/"):
            assert leak not in r.text


def test_unexpected_failures_stay_generic_and_keep_their_headers(alice, monkeypatch):
    from app.routers import banking

    def explode(*args, **kwargs):
        raise RuntimeError("database password is hunter2")
    monkeypatch.setattr(banking, "user_accounts", explode)
    r = alice.get("/api/v1/accounts", headers={**alice.headers, "Origin": "http://localhost:5173"})
    assert r.status_code == 500
    assert r.json() == {"error": {"code": "server_error", "message": "Something went wrong on our side."}}
    assert "hunter2" not in r.text
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_responses_never_contain_password_hashes_or_secrets(alice):
    from app.config import get_settings
    for path in ("/api/v1/auth/me", "/api/v1/accounts", "/api/v1/auth/sessions", "/api/v1/security/activity", "/api/v1/card"):
        body = alice.get(path).text
        assert "argon2" not in body and "password" not in body.lower()
        assert get_settings().jwt_secret not in body


def test_card_number_is_never_exposed_beyond_last_four(alice):
    card = alice.get("/api/v1/card").json()
    assert set(card) == {"id", "last4", "expiry", "holder", "frozen", "online_payments"}
    assert len(card["last4"]) == 4


# ---- configuration -----------------------------------------------------

def test_app_refuses_to_start_with_a_missing_or_weak_secret():
    for bad in ("", "change-me", "short-secret"):
        with pytest.raises(ValidationError):
            Settings(jwt_secret=bad, _env_file=None)


def test_production_mode_is_locked_down():
    strong = "s" * 48
    with pytest.raises(ValidationError):
        Settings(jwt_secret=strong, environment="production", seed_demo_data=True, cors_origins="https://app.example", _env_file=None)
    with pytest.raises(ValidationError):
        Settings(jwt_secret=strong, environment="production", cors_origins="http://localhost:5173", _env_file=None)
    prod = Settings(jwt_secret=strong, environment="production", cors_origins="https://app.example", _env_file=None)
    assert prod.docs_enabled is False


# ---- audit log ---------------------------------------------------------

def test_security_events_are_audited(alice, bob, db):
    alice.send(bob.handle, "1")
    httpx.patch(f"{BASE}/api/v1/card", headers=alice.headers, json={"frozen": True})
    events = db.execute(select(AuditLog.event).where(AuditLog.user_id == alice.id)).scalars().all()
    assert {"auth.login", "transfer.created", "card.updated"} <= set(events)
    details = db.execute(select(AuditLog.detail).where(AuditLog.user_id == alice.id)).scalars().all()
    assert PASSWORD not in str(details) and alice.access not in str(details)


def test_audit_log_cannot_be_edited_or_deleted(db):
    for statement in ("UPDATE audit_log SET event = 'x'", "DELETE FROM audit_log", "TRUNCATE audit_log"):
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()


def test_audit_chain_verifies_and_detects_tampering(db):
    Customer("auditor")
    intact, rows, broken = audit.verify_chain(db)
    assert intact and rows > 0 and broken is None
    victim = db.execute(select(AuditLog.id).order_by(AuditLog.id).offset(rows // 2).limit(1)).scalar_one()
    # Simulate a database administrator who switches the protection off and edits history.
    db.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    original = db.execute(text("SELECT event FROM audit_log WHERE id = :i"), {"i": victim}).scalar_one()
    try:
        db.execute(text("UPDATE audit_log SET event = 'auth.nothing_happened' WHERE id = :i"), {"i": victim})
        db.commit()
        intact, _, broken = audit.verify_chain(db)
        assert not intact and broken == victim
    finally:
        db.execute(text("UPDATE audit_log SET event = :e WHERE id = :i"), {"e": original, "i": victim})
        db.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
        db.commit()
    assert audit.verify_chain(db)[0]
