"""Transfer correctness, validation, idempotency and database-level integrity."""
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.config import get_settings
from app.models import Account, LedgerEntry, Transfer

from .conftest import Customer, new_key


def test_transfer_moves_money_and_writes_double_entry(alice, bob, db):
    r = alice.send(bob.handle, "12.500", note="Lunch")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["amount_fils"] == 12_500 and body["to_name"] == "Bob T."
    assert alice.balance() == 87_500 and bob.balance() == 62_500
    entries = db.execute(select(LedgerEntry).where(LedgerEntry.transfer_id == body["id"])).scalars().all()
    assert sorted(e.amount_fils for e in entries) == [-12_500, 12_500]
    assert {e.balance_after_fils for e in entries} == {87_500, 62_500}
    assert bob.get("/api/v1/transactions").json()[0]["title"] == "Alice T."


def test_internal_transfer_to_own_savings(alice):
    r = alice.send(str(alice.savings), "40")
    assert r.status_code == 201 and r.json()["kind"] == "internal"
    assert alice.balance() == 60_000 and alice.balance("savings") == 40_000


def test_activity_can_be_limited_to_one_account_and_is_newest_first(alice, bob):
    alice.send(str(alice.savings), "40")
    alice.send(bob.handle, "1", note="latest")
    everyday = alice.get("/api/v1/transactions", params={"kind": "current"}).json()
    assert [t["note"] for t in everyday][:1] == ["latest"]
    assert all(t["account_id"] == str(alice.current) for t in everyday)
    assert [t["title"] for t in everyday if t["kind"] == "internal"] == ["Savings"]
    assert alice.get("/api/v1/transactions", params={"kind": "everything"}).status_code == 422


def test_cannot_overdraw(alice, bob):
    r = alice.send(bob.handle, "100.001")
    assert r.status_code == 409 and r.json()["error"]["code"] == "insufficient_funds"
    assert alice.balance() == 100_000 and bob.balance() == 50_000


@pytest.mark.parametrize("amount", ["0", "-5", "1.2345", "1e3", "abc", "", "5,000", " ", "0x10", "99999999", "NaN", "١٢"])
def test_invalid_amounts_are_rejected_by_the_server(alice, bob, amount):
    r = alice.send(bob.handle, amount)
    assert r.status_code == 422
    assert alice.balance() == 100_000


def test_amount_must_be_text_not_a_float(alice, bob):
    r = alice.post("/api/v1/transfers", key=new_key(),
                   json={"from_account_id": str(alice.current), "to": bob.handle, "amount": 0.1 + 0.2})
    assert r.status_code == 422


def test_unknown_fields_are_rejected(alice, bob):
    r = alice.post("/api/v1/transfers", key=new_key(), json={
        "from_account_id": str(alice.current), "to": bob.handle, "amount": "1", "kind": "topup", "initiated_by": str(bob.id)})
    assert r.status_code == 422


def test_single_transfer_and_daily_limits(bob):
    s = get_settings()
    rich = Customer("rich", 5_000_000)
    assert rich.send(bob.handle, "1000.001").status_code == 422
    for _ in range(s.daily_outgoing_limit_fils // s.max_transfer_fils):
        assert rich.send(bob.handle, "1000").status_code == 201
    r = rich.send(bob.handle, "1")
    assert r.status_code == 409 and r.json()["error"]["code"] == "daily_limit"


def test_cannot_send_to_yourself(alice):
    assert alice.send(alice.handle, "5").status_code == 422
    assert alice.send(str(alice.current), "5").status_code == 422


def test_idempotency_key_is_required(alice, bob):
    r = alice.post("/api/v1/transfers", json={"from_account_id": str(alice.current), "to": bob.handle, "amount": "1"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "idempotency_key_required"
    bad = alice.post("/api/v1/transfers", key="short", json={"from_account_id": str(alice.current), "to": bob.handle, "amount": "1"})
    assert bad.status_code == 400


def test_retrying_with_the_same_key_does_not_send_twice(alice, bob, db):
    key = new_key()
    first = alice.send(bob.handle, "10", key=key)
    second = alice.send(bob.handle, "10", key=key)
    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()
    assert second.headers["Idempotent-Replay"] == "true"
    assert alice.balance() == 90_000 and bob.balance() == 60_000
    count = db.execute(select(func.count()).select_from(Transfer).where(Transfer.from_account_id == alice.current)).scalar_one()
    assert count == 1


def test_same_key_with_different_details_is_refused(alice, bob):
    key = new_key()
    assert alice.send(bob.handle, "10", key=key).status_code == 201
    r = alice.send(bob.handle, "99", key=key)
    assert r.status_code == 422 and r.json()["error"]["code"] == "idempotency_key_reused"
    assert alice.balance() == 90_000


def test_idempotency_keys_are_scoped_per_customer(alice, bob):
    key = new_key()
    assert alice.send(bob.handle, "1", key=key).status_code == 201
    r = bob.send(alice.handle, "2", key=key)  # same key, different customer: an independent request
    assert r.status_code == 201 and "Idempotent-Replay" not in r.headers


def test_failed_transfer_can_be_retried_with_same_key_after_funding(bob):
    poor = Customer("poor")
    key = new_key()
    assert poor.send(bob.handle, "5", key=key).status_code == 409
    assert poor.post(f"/api/v1/accounts/{poor.current}/top-up", json={"amount": "20"}, key=new_key()).status_code == 201
    assert poor.send(bob.handle, "5", key=key).status_code == 201
    assert poor.balance() == 15_000


def test_top_up_limits_and_idempotency(alice):
    key = new_key()
    a = alice.post(f"/api/v1/accounts/{alice.current}/top-up", json={"amount": "50"}, key=key)
    b = alice.post(f"/api/v1/accounts/{alice.current}/top-up", json={"amount": "50"}, key=key)
    assert a.status_code == b.status_code == 201 and alice.balance() == 150_000
    assert alice.post(f"/api/v1/accounts/{alice.current}/top-up", json={"amount": "500.001"}, key=new_key()).status_code == 422
    for amount in ("500", "450"):
        assert alice.post(f"/api/v1/accounts/{alice.current}/top-up", json={"amount": amount}, key=new_key()).status_code == 201
    assert alice.post(f"/api/v1/accounts/{alice.current}/top-up", json={"amount": "1"}, key=new_key()).status_code == 409


def test_search_and_direction_filters(alice, bob):
    alice.send(bob.handle, "3", note="Cinema tickets")
    bob.send(alice.handle, "1", note="Change")
    assert [t["note"] for t in alice.get("/api/v1/transactions", params={"search": "cinema"}).json()] == ["Cinema tickets"]
    incoming = alice.get("/api/v1/transactions", params={"direction": "in"}).json()
    assert incoming and all(t["amount_fils"] > 0 for t in incoming)
    assert alice.get("/api/v1/insights").json()["spent_fils"] == 3_000


# ---- guarantees enforced by PostgreSQL itself, below the application ----

def test_database_refuses_a_negative_customer_balance(alice, db):
    with pytest.raises(IntegrityError):
        db.execute(text("UPDATE accounts SET balance_fils = -1 WHERE id = :id"), {"id": alice.current})
    db.rollback()


def test_ledger_is_append_only(alice, bob, db):
    alice.send(bob.handle, "1")
    for statement in ("UPDATE ledger_entries SET amount_fils = 0", "DELETE FROM ledger_entries", "TRUNCATE ledger_entries"):
        with pytest.raises(DBAPIError):
            db.execute(text(statement))
        db.rollback()


def test_database_rejects_an_unbalanced_ledger_write(alice, bob, db):
    transfer = Transfer(from_account_id=alice.current, to_account_id=bob.current, amount_fils=5, kind="p2p", initiated_by=alice.id)
    db.add(transfer)
    db.flush()
    db.add(LedgerEntry(transfer_id=transfer.id, account_id=alice.current, amount_fils=-5, balance_after_fils=0))
    with pytest.raises(DBAPIError):  # deferred constraint trigger fires at commit
        db.commit()
    db.rollback()


def test_no_money_is_created_or_destroyed(db):
    # Runs after the other tests in this file: across every account, balances net to zero,
    # and every stored balance equals the sum of that account's ledger entries.
    assert db.execute(select(func.coalesce(func.sum(Account.balance_fils), 0))).scalar_one() == 0
    drift = db.execute(text("""
        SELECT count(*) FROM accounts a
        WHERE a.balance_fils <> COALESCE((SELECT SUM(amount_fils) FROM ledger_entries l WHERE l.account_id = a.id), 0)
    """)).scalar_one()
    assert drift == 0
