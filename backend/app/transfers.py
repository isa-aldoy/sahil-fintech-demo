"""The money-movement core. Every balance change in the system goes through `move_money`."""
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .errors import ApiError
from .models import Account, IdempotencyKey, LedgerEntry, Transfer, User
from .money import format_bhd
from .security import now


@dataclass
class Moved:
    transfer: Transfer
    source: Account
    destination: Account


def move_money(db: Session, *, from_id: uuid.UUID, to_id: uuid.UUID, amount_fils: int, kind: str,
               initiated_by: uuid.UUID, note: str = "", category: str = "transfer",
               merchant: str | None = None, source: str = "app", daily_limit: int | None = None,
               daily_incoming_limit: int | None = None) -> Moved:
    """Atomically debit one account and credit another.

    Concurrency: both account rows are locked with SELECT ... FOR UPDATE, always in the
    same (sorted) order so two opposite transfers cannot deadlock. The balance check runs
    only after the lock is held, so parallel requests cannot both spend the same money.
    `populate_existing` forces SQLAlchemy to re-read the locked rows instead of reusing
    objects it loaded earlier in the request; without it the check would use a stale balance.
    The caller commits; any exception rolls the whole movement back.
    """
    if amount_fils <= 0:
        raise ApiError(422, "invalid_amount", "Amount must be more than zero.")
    if from_id == to_id:
        raise ApiError(422, "same_account", "Choose a different account to send to.")
    locked = {
        a.id: a for a in db.execute(
            select(Account).where(Account.id.in_([from_id, to_id])).order_by(Account.id).with_for_update().execution_options(populate_existing=True)
        ).scalars()
    }
    if len(locked) != 2:
        raise ApiError(404, "not_found", "Account not found.")
    src, dst = locked[from_id], locked[to_id]

    if src.kind != "system":
        if src.balance_fils < amount_fils:
            raise ApiError(409, "insufficient_funds", "You don't have enough money for this.")
        if daily_limit is not None:
            spent = db.execute(
                select(func.coalesce(func.sum(Transfer.amount_fils), 0)).where(
                    Transfer.from_account_id == src.id, Transfer.kind == kind,
                    Transfer.created_at > now() - timedelta(hours=24))
            ).scalar_one()
            if spent + amount_fils > daily_limit:
                raise ApiError(409, "daily_limit", "This would go over your daily limit.")

    if daily_incoming_limit is not None:
        received = db.execute(
            select(func.coalesce(func.sum(Transfer.amount_fils), 0)).where(
                Transfer.to_account_id == dst.id, Transfer.kind == kind,
                Transfer.created_at > now() - timedelta(hours=24))
        ).scalar_one()
        if received + amount_fils > daily_incoming_limit:
            raise ApiError(409, "daily_limit", "You've reached today's limit.")

    src.balance_fils -= amount_fils
    dst.balance_fils += amount_fils
    transfer = Transfer(from_account_id=src.id, to_account_id=dst.id, amount_fils=amount_fils, kind=kind,
                        note=note, category=category, merchant=merchant, source=source, initiated_by=initiated_by)
    db.add(transfer)
    db.flush()
    db.add_all([
        LedgerEntry(transfer_id=transfer.id, account_id=src.id, amount_fils=-amount_fils,
                    balance_after_fils=src.balance_fils),
        LedgerEntry(transfer_id=transfer.id, account_id=dst.id, amount_fils=amount_fils,
                    balance_after_fils=dst.balance_fils),
    ])
    db.flush()
    return Moved(transfer, src, dst)


def resolve_destination(db: Session, user: User, to: str) -> tuple[Account, User]:
    """Find where the money goes: one of the sender's own accounts, a @handle, or an account number."""
    to = to.strip()
    try:
        own = db.execute(select(Account).where(Account.id == uuid.UUID(to), Account.user_id == user.id)).scalar_one_or_none()
        if own:
            return own, user
    except ValueError:
        pass
    q = select(Account, User).join(User, User.id == Account.user_id).where(User.is_system.is_(False))
    if to.upper().startswith("BH") and len(to) >= 20:
        q = q.where(Account.number == to.upper().replace(" ", ""))
    else:
        q = q.where(User.handle == to.lstrip("@").lower(), Account.kind == "current")
    row = db.execute(q).first()
    if row is None:
        raise ApiError(404, "recipient_not_found", "We couldn't find that person.")
    return row[0], row[1]


def display_name(user: User) -> str:
    """'Layla Al Mansoor' -> 'Layla A.' Enough to confirm the person, not enough to profile them."""
    parts = user.full_name.split()
    return parts[0] if len(parts) == 1 else f"{parts[0]} {parts[-1][0]}."


def send(db: Session, user: User, *, from_account_id: uuid.UUID, to: str, amount_fils: int, note: str,
         ip: str, source: str = "app") -> dict:
    """Validate and perform a customer transfer. Does not commit."""
    s = get_settings()
    src = db.execute(select(Account).where(Account.id == from_account_id, Account.user_id == user.id)).scalar_one_or_none()
    if src is None:
        # Same answer whether the account does not exist or belongs to someone else.
        raise ApiError(404, "not_found", "Account not found.")
    if amount_fils > s.max_transfer_fils:
        raise ApiError(422, "over_limit", f"You can send up to {format_bhd(s.max_transfer_fils)} BHD at a time.")
    dst, owner = resolve_destination(db, user, to)
    internal = owner.id == user.id
    moved = move_money(db, from_id=src.id, to_id=dst.id, amount_fils=amount_fils, initiated_by=user.id,
                       kind="internal" if internal else "p2p", note=note, source=source,
                       daily_limit=None if internal else s.daily_outgoing_limit_fils)
    audit.record(db, "transfer.created", user.id, ip, transfer=str(moved.transfer.id), amount_fils=amount_fils,
                 kind=moved.transfer.kind, source=source)
    return {
        "id": str(moved.transfer.id), "amount_fils": amount_fils, "amount": format_bhd(amount_fils),
        "kind": moved.transfer.kind, "note": note,
        "to_name": dst.name if internal else display_name(owner),
        "from_balance_fils": moved.source.balance_fils, "from_balance": format_bhd(moved.source.balance_fils),
        "created_at": moved.transfer.created_at.isoformat(),
    }


# ---------------------------------------------------------------- idempotency

def request_fingerprint(payload: dict) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def claim_key(db: Session, user_id: uuid.UUID, key: str, fingerprint: str) -> dict | None:
    """Reserve an idempotency key inside the current transaction.

    Returns the stored response if this exact request already completed, otherwise None
    (the caller then performs the work and calls `store_result` before committing).
    A second request racing with the same key blocks on the unique index until the first
    commits, then sees its stored result, so the transfer can never run twice.
    """
    db.execute(insert(IdempotencyKey).values(user_id=user_id, key=key, request_hash=fingerprint)
               .on_conflict_do_nothing())
    row = db.execute(select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)
                     .with_for_update().execution_options(populate_existing=True)).scalar_one()
    if row.request_hash != fingerprint:
        raise ApiError(422, "idempotency_key_reused", "This request id was already used for a different request.")
    if row.response is not None:
        return {"status": row.status_code, "body": row.response}
    return None


def store_result(db: Session, user_id: uuid.UUID, key: str, status: int, body: dict) -> None:
    row = db.execute(select(IdempotencyKey).where(IdempotencyKey.user_id == user_id, IdempotencyKey.key == key)).scalar_one()
    row.status_code, row.response = status, body
