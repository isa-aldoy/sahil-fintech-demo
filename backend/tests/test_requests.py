"""Money requests and the CSV statement."""
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import func, select

from app.models import PaymentRequest, Transfer

from .conftest import BASE, Customer, new_key


def _ask(requester, payer, amount="7.500", note="Cinema"):
    return requester.post("/api/v1/requests", json={"to": payer.handle, "amount": amount, "note": note})


def test_request_then_pay_moves_money_once(alice, bob, db):
    r = _ask(bob, alice)
    assert r.status_code == 201 and r.json()["other_name"] == "Alice T."
    incoming = alice.get("/api/v1/requests").json()["incoming"]
    assert [i["amount"] for i in incoming] == ["7.500"] and incoming[0]["other_name"] == "Bob T."
    key = new_key()
    first = alice.post(f"/api/v1/requests/{r.json()['id']}/pay", key=key)
    again = alice.post(f"/api/v1/requests/{r.json()['id']}/pay", key=key)
    assert first.status_code == again.status_code == 201 and again.headers["Idempotent-Replay"] == "true"
    assert alice.balance() == 92_500 and bob.balance() == 57_500
    assert alice.get("/api/v1/requests").json()["incoming"] == []
    assert bob.get("/api/v1/requests").json()["outgoing"][0]["status"] == "paid"
    row = db.execute(select(PaymentRequest).where(PaymentRequest.id == r.json()["id"])).scalar_one()
    assert str(row.transfer_id) == first.json()["id"]


def test_parallel_pay_taps_with_different_keys_pay_only_once(db):
    payer, asker = Customer("payer2", 100_000), Customer("asker")
    rid = _ask(asker, payer, "30").json()["id"]
    with ThreadPoolExecutor(8) as pool:
        codes = list(pool.map(lambda _: payer.post(f"/api/v1/requests/{rid}/pay", key=new_key()).status_code, range(8)))
    assert codes.count(201) == 1 and codes.count(409) == 7
    assert payer.balance() == 70_000 and asker.balance() == 30_000
    n = db.execute(select(func.count()).select_from(Transfer).where(Transfer.source == "request",
                                                                    Transfer.from_account_id == payer.current)).scalar_one()
    assert n == 1


def test_only_the_right_person_can_act_on_a_request(alice, bob):
    mallory = Customer("mallory2", 100_000)
    rid = _ask(bob, alice).json()["id"]
    for path in ("pay", "decline", "cancel"):
        assert mallory.post(f"/api/v1/requests/{rid}/{path}", key=new_key()).status_code == 404
    assert bob.post(f"/api/v1/requests/{rid}/pay", key=new_key()).status_code == 404       # requester can't pay own
    assert bob.post(f"/api/v1/requests/{rid}/decline").status_code == 404                  # only the payer declines
    assert alice.post(f"/api/v1/requests/{rid}/cancel").status_code == 404                 # only the requester cancels
    assert mallory.get("/api/v1/requests").json() == {"incoming": [], "outgoing": []}
    assert alice.balance() == 100_000


def test_declined_and_cancelled_requests_cannot_be_paid(alice, bob):
    r1 = _ask(bob, alice).json()["id"]
    assert alice.post(f"/api/v1/requests/{r1}/decline").status_code == 204
    assert alice.post(f"/api/v1/requests/{r1}/pay", key=new_key()).status_code == 409
    r2 = _ask(bob, alice).json()["id"]
    assert bob.post(f"/api/v1/requests/{r2}/cancel").status_code == 204
    assert alice.post(f"/api/v1/requests/{r2}/pay", key=new_key()).status_code == 409
    assert alice.balance() == 100_000


def test_paying_respects_balance_and_limits(bob):
    broke = Customer("broke", 1_000)
    rid = _ask(bob, broke, "5").json()["id"]
    r = broke.post(f"/api/v1/requests/{rid}/pay", key=new_key())
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_funds"
    assert broke.get("/api/v1/requests").json()["incoming"][0]["status"] == "pending"  # still payable later


def test_request_validation(alice, bob):
    assert _ask(alice, alice).status_code == 422
    assert alice.post("/api/v1/requests", json={"to": "nobody-here", "amount": "5"}).status_code == 404
    for amount in ("0", "-1", "1000.001", "1e2"):
        assert _ask(alice, bob, amount).status_code == 422, amount
    assert alice.post("/api/v1/requests", json={"to": bob.handle, "amount": "5", "status": "paid"}).status_code == 422


def test_request_spam_is_limited(alice, bob):
    codes = [_ask(alice, bob, "1").status_code for _ in range(12)]
    assert codes.count(201) == 10 and codes[-1] == 429


def test_statement_csv_is_mine_only_and_formula_safe(alice, bob):
    attacker = Customer("csv", 5_000)
    attacker.send(alice.handle, "1", note="=HYPERLINK(\"http://evil.example\",\"click\")")
    alice.send(bob.handle, "2", note="Rent")
    r = alice.get("/api/v1/statement.csv")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    text = r.content.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "Date,Description,Category,Note,Amount (BHD)"
    assert "'=HYPERLINK" in text and ",=HYPERLINK" not in text
    assert "Rent" in text and "-2.000" in text
    assert bob.get("/api/v1/statement.csv").content.decode("utf-8-sig").count("Rent") == 1  # bob sees his side only
    assert httpx.get(f"{BASE}/api/v1/statement.csv").status_code == 401
