"""Customers can only ever see and touch their own data (no IDOR)."""
import uuid

import httpx

from app.main import app

from .conftest import BASE, new_key


def test_cannot_send_from_someone_elses_account(alice, bob):
    r = alice.send(alice.handle, "5", source=bob.current)
    assert r.status_code == 404
    assert bob.balance() == 50_000


def test_cannot_top_up_someone_elses_account(alice, bob):
    r = alice.post(f"/api/v1/accounts/{bob.current}/top-up", json={"amount": "10"}, key=new_key())
    assert r.status_code == 404
    assert bob.balance() == 50_000


def test_transactions_and_accounts_are_isolated(alice, bob):
    alice.send(bob.handle, "7.250", note="private-note-for-bob")
    bob_ids = {a["id"] for a in bob.get("/api/v1/accounts").json()}
    alice_ids = {a["id"] for a in alice.get("/api/v1/accounts").json()}
    assert not bob_ids & alice_ids
    for tx in alice.get("/api/v1/transactions").json():
        assert tx["account_id"] in alice_ids
    # Filtering by another customer's account id returns nothing rather than their data.
    assert alice.get("/api/v1/transactions", params={"account_id": str(bob.current)}).json() == []
    carol_view = bob.get("/api/v1/transactions").json()
    assert all(tx["account_id"] in bob_ids for tx in carol_view)


def test_cannot_revoke_another_customers_session(alice, bob):
    bob_session = bob.get("/api/v1/auth/sessions").json()[0]["id"]
    r = httpx.delete(f"{BASE}/api/v1/auth/sessions/{bob_session}", headers=alice.headers)
    assert r.status_code == 404
    assert bob.get("/api/v1/accounts").status_code == 200


def test_card_and_security_activity_are_per_customer(alice, bob):
    assert alice.get("/api/v1/card").json()["id"] != bob.get("/api/v1/card").json()["id"]
    httpx.patch(f"{BASE}/api/v1/card", headers=alice.headers, json={"frozen": True})
    assert bob.get("/api/v1/card").json()["frozen"] is False
    assert all("Card" not in e["title"] for e in bob.get("/api/v1/security/activity").json())


def test_recipient_lookup_reveals_only_a_short_display_name(alice, bob):
    body = alice.get("/api/v1/recipients/lookup", params={"q": bob.handle}).json()
    assert set(body) == {"handle", "display_name"}
    assert body["display_name"] == "Bob T."
    assert alice.get("/api/v1/recipients/lookup", params={"q": "no-such-person"}).status_code == 404


def test_every_api_route_rejects_anonymous_callers():
    public = {"/api/v1/auth/register", "/api/v1/auth/login", "/api/v1/auth/refresh"}
    checked = 0
    for path, operations in app.openapi()["paths"].items():
        if not path.startswith("/api") or path in public:
            continue
        url = path.replace("{account_id}", str(uuid.uuid4())).replace("{session_id}", str(uuid.uuid4())) \
                  .replace("{action_id}", str(uuid.uuid4()))
        for method in operations:
            r = httpx.request(method.upper(), BASE + url, json={})
            assert r.status_code == 401, f"{method} {path} answered {r.status_code} without a token"
            checked += 1
    assert checked >= 18
