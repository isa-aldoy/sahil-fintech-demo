"""Tests run against a real PostgreSQL database and a real HTTP server (uvicorn in a thread)."""
import os
import secrets
import threading
import time
import uuid

os.environ.setdefault("TEST_DATABASE_URL", "postgresql+psycopg://sahil:sahil@localhost:5432/sahil_test")
os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
os.environ["ENVIRONMENT"] = "test"
os.environ["JWT_SECRET"] = secrets.token_urlsafe(48)
os.environ["GEMINI_API_KEY"] = ""
os.environ["SEED_DEMO_DATA"] = "false"

import httpx  # noqa: E402
import pytest  # noqa: E402
import uvicorn  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from sqlalchemy import select, text  # noqa: E402

from app import ratelimit  # noqa: E402
from app.db import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Account  # noqa: E402
from app.routers.auth import create_user  # noqa: E402
from app.seed import ensure_system  # noqa: E402
from app.transfers import move_money  # noqa: E402

PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "Correct-Horse-9-Battery"


@pytest.fixture(scope="session", autouse=True)
def _database():
    with engine.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    command.upgrade(Config("alembic.ini"), "head")
    with SessionLocal() as db:
        ensure_system(db)
        db.commit()
    yield


@pytest.fixture(scope="session", autouse=True)
def _server(_database):
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning", server_header=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            if httpx.get(f"{BASE}/health", timeout=1).status_code == 200:
                break
        except httpx.HTTPError:
            time.sleep(0.1)
    yield
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    ratelimit.store.reset()
    yield


@pytest.fixture
def http():
    with httpx.Client(base_url=BASE, timeout=30) as client:
        yield client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


class Customer:
    """A signed-in test customer with a thin HTTP helper."""

    def __init__(self, name: str, balance_fils: int = 0):
        self.email = f"{name}-{uuid.uuid4().hex[:10]}@test.example"
        with SessionLocal() as db:
            user = create_user(db, self.email, f"{name.title()} Tester", PASSWORD,
                               handle=f"{name}{uuid.uuid4().hex[:8]}")
            db.flush()
            self.id, self.handle = user.id, user.handle
            accounts = {a.kind: a for a in db.execute(select(Account).where(Account.user_id == user.id)).scalars()}
            self.current, self.savings = accounts["current"].id, accounts["savings"].id
            if balance_fils:
                _, funding, _ = ensure_system(db)
                move_money(db, from_id=funding.id, to_id=self.current, amount_fils=balance_fils, kind="opening",
                           category="income", initiated_by=user.id, source="seed")
            db.commit()
        self.login()

    def login(self) -> None:
        r = httpx.post(f"{BASE}/api/v1/auth/login", json={"email": self.email, "password": PASSWORD})
        assert r.status_code == 200, r.text
        self.access, self.refresh = r.json()["access_token"], r.json()["refresh_token"]

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access}"}

    def get(self, path: str, **kw) -> httpx.Response:
        return httpx.get(BASE + path, headers=self.headers, timeout=30, **kw)

    def post(self, path: str, json=None, key: str | None = None, **kw) -> httpx.Response:
        headers = dict(self.headers)
        if key:
            headers["Idempotency-Key"] = key
        return httpx.post(BASE + path, headers=headers, json=json, timeout=30, **kw)

    def send(self, to: str, amount: str, key: str | None = None, note: str = "", source=None) -> httpx.Response:
        return self.post("/api/v1/transfers", key=key or new_key(),
                         json={"from_account_id": str(source or self.current), "to": to, "amount": amount, "note": note})

    def balance(self, kind: str = "current") -> int:
        return next(a["balance_fils"] for a in self.get("/api/v1/accounts").json() if a["kind"] == kind)


def new_key() -> str:
    return uuid.uuid4().hex


@pytest.fixture
def alice():
    return Customer("alice", 100_000)  # 100.000 BHD


@pytest.fixture
def bob():
    return Customer("bob", 50_000)
