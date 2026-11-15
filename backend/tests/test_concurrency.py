"""Race conditions: many real HTTP requests at the same instant."""
from concurrent.futures import ThreadPoolExecutor

import httpx
from sqlalchemy import func, select, text

from app.models import Account, Transfer

from .conftest import BASE, Customer, new_key


def _parallel(n: int, fn):
    with ThreadPoolExecutor(max_workers=n) as pool:
        return list(pool.map(lambda i: fn(i), range(n)))


def test_parallel_transfers_cannot_overspend(db):
    """40 simultaneous 10 BHD transfers from a 100 BHD balance: exactly 10 may succeed."""
    payer, payee = Customer("payer", 100_000), Customer("payee")
    results = _parallel(40, lambda _: payer.send(payee.handle, "10").status_code)
    assert results.count(201) == 10
    # The rest are refused: "not enough money" (409) or the per-customer rate limit (429).
    assert results.count(409) + results.count(429) == 30 and results.count(409) >= 20
    assert payer.balance() == 0 and payee.balance() == 100_000
    assert db.execute(select(func.sum(Account.balance_fils))).scalar_one() == 0


def test_same_idempotency_key_in_parallel_sends_once(db):
    """A double-tap or a network retry storm: 25 identical requests, one transfer."""
    payer, payee = Customer("tapper", 100_000), Customer("shop")
    key = new_key()
    results = _parallel(25, lambda _: payer.send(payee.handle, "15", key=key))
    assert {r.status_code for r in results} == {201}
    assert len({r.json()["id"] for r in results}) == 1
    assert payer.balance() == 85_000 and payee.balance() == 15_000
    n = db.execute(select(func.count()).select_from(Transfer).where(Transfer.from_account_id == payer.current)).scalar_one()
    assert n == 1


def test_opposite_transfers_do_not_deadlock(db):
    a, b = Customer("ping", 200_000), Customer("pong", 200_000)
    results = _parallel(40, lambda i: (a.send(b.handle, "1") if i % 2 else b.send(a.handle, "1")).status_code)
    assert results == [201] * 40
    assert a.balance() == 200_000 and b.balance() == 200_000


def test_refresh_token_can_only_be_used_once_under_race():
    user = Customer("racer")
    results = _parallel(10, lambda _: httpx.post(f"{BASE}/api/v1/auth/refresh", json={"refresh_token": user.refresh}).status_code)
    assert results.count(200) <= 1
    assert results.count(401) >= 9


def test_parallel_top_ups_respect_the_daily_cap():
    user = Customer("saver")
    url = f"/api/v1/accounts/{user.current}/top-up"
    results = _parallel(8, lambda _: user.post(url, json={"amount": "400"}, key=new_key()).status_code)
    assert results.count(201) == 2  # cap is 1000 BHD per day
    assert user.balance() == 800_000


def test_books_still_balance_after_all_races(db):
    assert db.execute(select(func.coalesce(func.sum(Account.balance_fils), 0))).scalar_one() == 0
    negative = db.execute(text("SELECT count(*) FROM accounts WHERE balance_fils < 0 AND kind <> 'system'")).scalar_one()
    assert negative == 0
