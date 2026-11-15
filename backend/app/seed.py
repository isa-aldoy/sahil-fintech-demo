"""Create the system accounts and (optionally) fictional demo customers. Safe to run repeatedly."""
import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .db import SessionLocal
from .models import Account, Transfer, User
from .routers.auth import create_user, new_account_number
from .security import hash_password, now
from .transfers import move_money

DEMO_PASSWORD = "Sahil-Demo-2026"  # fictional demo accounts only; printed by the setup script
DEMO_USERS = [
    ("demo@sahil.example", "Noor Al Khalifa", "noor"),
    ("layla@sahil.example", "Layla Al Mansoor", "layla"),
    ("yusuf@sahil.example", "Yusuf Haddad", "yusuf"),
]
# (days ago, merchant, category, BHD fils)
PURCHASES = [
    (1, "Coffee Corner", "food", 1_800), (2, "City Market", "groceries", 14_350),
    (3, "Batelco Top-up", "bills", 6_000), (4, "Karak House", "food", 900),
    (6, "Seef Cinema", "fun", 7_000), (8, "City Market", "groceries", 22_100),
    (9, "Fuel Station", "transport", 5_500), (12, "Bookshop", "shopping", 9_250),
    (15, "Electricity & Water", "bills", 18_400), (19, "Shawarma Stop", "food", 2_700),
]


def ensure_system(db: Session) -> tuple[User, Account, Account]:
    system = db.execute(select(User).where(User.is_system.is_(True))).scalar_one_or_none()
    if system is None:
        # The system user cannot sign in: its hash is of a random value nobody knows, and
        # the auth layer rejects is_system users regardless.
        system = User(email="system@sahil.invalid", handle="sahil-system", full_name="Sahil System",
                      password_hash=hash_password(secrets.token_urlsafe(32)), is_system=True)
        db.add(system)
        db.flush()
        db.add_all([
            Account(user_id=system.id, kind="system", name="Demo funding", number=new_account_number()),
            Account(user_id=system.id, kind="system", name="Card settlements", number=new_account_number()),
        ])
        db.flush()
    accounts = {a.name: a for a in db.execute(select(Account).where(Account.user_id == system.id)).scalars()}
    return system, accounts["Demo funding"], accounts["Card settlements"]


def _backdate(db: Session, transfer_id: uuid.UUID, days: int) -> None:
    db.execute(update(Transfer).where(Transfer.id == transfer_id).values(created_at=now() - timedelta(days=days, hours=3)))


def seed_demo(db: Session) -> bool:
    _, funding, settlements = ensure_system(db)
    if db.execute(select(User).where(User.email == DEMO_USERS[0][0])).scalar_one_or_none():
        return False
    users = [create_user(db, email, name, DEMO_PASSWORD, handle=handle) for email, name, handle in DEMO_USERS]
    db.flush()
    current = {u.handle: db.execute(select(Account).where(Account.user_id == u.id, Account.kind == "current")).scalar_one()
               for u in users}
    savings = db.execute(select(Account).where(Account.user_id == users[0].id, Account.kind == "savings")).scalar_one()
    for handle, amount in (("noor", 650_000), ("layla", 300_000), ("yusuf", 300_000)):
        t = move_money(db, from_id=funding.id, to_id=current[handle].id, amount_fils=amount, kind="topup",
                       category="income", note="Salary", merchant="Salary", initiated_by=users[0].id, source="seed")
        _backdate(db, t.transfer.id, 25)
    noor = current["noor"]
    for days, merchant, category, fils in PURCHASES:
        t = move_money(db, from_id=noor.id, to_id=settlements.id, amount_fils=fils, kind="card", category=category,
                       merchant=merchant, initiated_by=users[0].id, source="seed")
        _backdate(db, t.transfer.id, days)
    for days, src, dst, fils, note, kind in (
        (20, noor.id, savings.id, 120_000, "Monthly saving", "internal"),
        (7, current["layla"].id, noor.id, 12_500, "Dinner split", "p2p"),
        (5, noor.id, current["yusuf"].id, 20_000, "Football pitch", "p2p"),
    ):
        t = move_money(db, from_id=src, to_id=dst, amount_fils=fils, kind=kind, note=note,
                       initiated_by=users[0].id, source="seed")
        _backdate(db, t.transfer.id, days)
    return True


def main() -> None:
    with SessionLocal() as db:
        ensure_system(db)
        created = seed_demo(db) if get_settings().seed_demo_data else False
        db.commit()
    print("seed: demo customers created" if created else "seed: nothing to do")


if __name__ == "__main__":
    main()
