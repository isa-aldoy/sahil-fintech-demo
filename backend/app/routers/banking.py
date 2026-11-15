import re
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import JSONResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from .. import audit, ratelimit, transfers
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, current
from ..errors import ApiError
from ..models import Account, AuditLog, Card, LedgerEntry, Transfer, User
from ..money import format_bhd
from ..schemas import (
    AccountOut, AmountIn, CardOut, CardPatch, RecipientOut, TransactionOut, TransferIn, TransferOut,
)
from ..security import now

router = APIRouter(prefix="/api/v1", tags=["banking"])
_KEY = re.compile(r"^[A-Za-z0-9_-]{16,64}$")


def account_out(a: Account) -> AccountOut:
    return AccountOut(id=a.id, kind=a.kind, name=a.name, number=a.number, balance_fils=a.balance_fils,
                      balance=format_bhd(a.balance_fils))


def user_accounts(db: Session, user_id: uuid.UUID) -> list[Account]:
    return list(db.execute(select(Account).where(Account.user_id == user_id).order_by(Account.kind)).scalars())


@router.get("/accounts", response_model=list[AccountOut])
def accounts(p: Principal = Depends(current), db: Session = Depends(get_db)):
    return [account_out(a) for a in user_accounts(db, p.user.id)]


def list_transactions(db: Session, user_id: uuid.UUID, *, limit: int = 30, before: int | None = None,
                      search: str | None = None, direction: str | None = None,
                      account_id: uuid.UUID | None = None) -> list[dict]:
    """Ledger entries for accounts the user owns. The ownership join is the authorization check."""
    mine = aliased(Account)
    other = aliased(Account)
    other_user = aliased(User)
    q = (
        select(LedgerEntry, Transfer, other, other_user)
        .join(mine, and_(mine.id == LedgerEntry.account_id, mine.user_id == user_id))
        .join(Transfer, Transfer.id == LedgerEntry.transfer_id)
        .join(other, other.id == func.coalesce(
            func.nullif(Transfer.from_account_id, LedgerEntry.account_id), Transfer.to_account_id))
        .join(other_user, other_user.id == other.user_id)
        .order_by(LedgerEntry.id.desc()).limit(limit)
    )
    if before:
        q = q.where(LedgerEntry.id < before)
    if account_id:
        q = q.where(LedgerEntry.account_id == account_id)
    if direction == "in":
        q = q.where(LedgerEntry.amount_fils > 0)
    elif direction == "out":
        q = q.where(LedgerEntry.amount_fils < 0)
    if search:
        like = f"%{search.replace('%', '').replace('_', '')}%"  # bound parameter; wildcards stripped
        q = q.where(or_(Transfer.note.ilike(like), Transfer.merchant.ilike(like),
                        other_user.full_name.ilike(like), Transfer.category.ilike(like)))
    out = []
    for entry, tr, counter_acc, counter_user in db.execute(q):
        incoming = entry.amount_fils > 0
        if tr.kind == "internal":
            title = counter_acc.name
        elif tr.kind == "topup":
            title = "Demo money added"
        elif tr.merchant:
            title = tr.merchant
        else:
            title = transfers.display_name(counter_user)
        out.append({
            "id": entry.id, "transfer_id": tr.id, "account_id": entry.account_id,
            "amount_fils": entry.amount_fils, "amount": format_bhd(entry.amount_fils),
            "direction": "in" if incoming else "out", "title": title, "category": tr.category,
            "note": tr.note, "kind": tr.kind, "created_at": tr.created_at,
        })
    return out


@router.get("/transactions", response_model=list[TransactionOut])
def transactions(
    p: Principal = Depends(current), db: Session = Depends(get_db),
    limit: int = Query(30, ge=1, le=100), before: int | None = Query(None, ge=1),
    search: str | None = Query(None, max_length=40), direction: str | None = Query(None, pattern="^(in|out)$"),
    account_id: uuid.UUID | None = None,
):
    return list_transactions(db, p.user.id, limit=limit, before=before, search=search, direction=direction,
                             account_id=account_id)


def spending_summary(db: Session, user_id: uuid.UUID, days: int = 30) -> dict:
    since = now() - timedelta(days=days)
    base = (
        select(Transfer.category, func.sum(LedgerEntry.amount_fils))
        .join(Account, and_(Account.id == LedgerEntry.account_id, Account.user_id == user_id))
        .join(Transfer, Transfer.id == LedgerEntry.transfer_id)
        .where(Transfer.created_at >= since, Transfer.kind != "internal")
    )
    spent = db.execute(base.where(LedgerEntry.amount_fils < 0).group_by(Transfer.category)).all()
    received = db.execute(base.where(LedgerEntry.amount_fils > 0).group_by(Transfer.category)).all()
    categories = sorted(({"category": c, "amount_fils": int(-v), "amount": format_bhd(int(-v))} for c, v in spent),
                        key=lambda x: -x["amount_fils"])
    total_out = sum(c["amount_fils"] for c in categories)
    total_in = int(sum(v for _, v in received))
    return {"days": days, "spent_fils": total_out, "spent": format_bhd(total_out),
            "received_fils": total_in, "received": format_bhd(total_in), "categories": categories}


@router.get("/insights")
def insights(p: Principal = Depends(current), db: Session = Depends(get_db), days: int = Query(30, ge=1, le=365)):
    return spending_summary(db, p.user.id, days)


@router.get("/recipients/lookup", response_model=RecipientOut)
def lookup(q: str = Query(min_length=2, max_length=40), p: Principal = Depends(current),
           db: Session = Depends(get_db)):
    # Tight limit: this endpoint must not become a way to list customers.
    ratelimit.check("lookup", str(p.user.id), 20, 60)
    _, owner = transfers.resolve_destination(db, p.user, q)
    if owner.id == p.user.id:
        raise ApiError(422, "same_person", "That's you. Pick someone else.")
    return RecipientOut(handle=owner.handle, display_name=transfers.display_name(owner))


@router.get("/recipients/recent", response_model=list[RecipientOut])
def recent_recipients(p: Principal = Depends(current), db: Session = Depends(get_db)):
    src, dst = aliased(Account), aliased(Account)
    rows = db.execute(
        select(User, func.max(Transfer.created_at).label("last"))
        .join(dst, dst.user_id == User.id).join(Transfer, Transfer.to_account_id == dst.id)
        .join(src, and_(src.id == Transfer.from_account_id, src.user_id == p.user.id))
        .where(Transfer.kind == "p2p").group_by(User.id).order_by(func.max(Transfer.created_at).desc()).limit(6)
    ).all()
    return [RecipientOut(handle=u.handle, display_name=transfers.display_name(u)) for u, _ in rows]


def _with_idempotency(db: Session, p: Principal, key: str | None, payload: dict, work) -> JSONResponse:
    if key is None or not _KEY.match(key):
        raise ApiError(400, "idempotency_key_required",
                       "Send an Idempotency-Key header (16-64 letters, digits, - or _).")
    try:
        replay = transfers.claim_key(db, p.user.id, key, transfers.request_fingerprint(payload))
        if replay is not None:
            db.rollback()
            return JSONResponse(replay["body"], status_code=replay["status"], headers={"Idempotent-Replay": "true"})
        body = work()
        transfers.store_result(db, p.user.id, key, 201, body)
        db.commit()
        return JSONResponse(body, status_code=201)
    except ApiError:
        db.rollback()
        raise


@router.post("/transfers", response_model=TransferOut, status_code=201)
def create_transfer(body: TransferIn, p: Principal = Depends(current), db: Session = Depends(get_db),
                    idempotency_key: str | None = Header(None)):
    ratelimit.check("transfer", str(p.user.id), 30, 60)
    payload = {"op": "transfer", **body.model_dump()}
    return _with_idempotency(db, p, idempotency_key, payload, lambda: transfers.send(
        db, p.user, from_account_id=body.from_account_id, to=body.to, amount_fils=body.fils, note=body.note, ip=p.ip))


@router.post("/accounts/{account_id}/top-up", response_model=AccountOut, status_code=201)
def top_up(account_id: uuid.UUID, body: AmountIn, p: Principal = Depends(current), db: Session = Depends(get_db),
           idempotency_key: str | None = Header(None)):
    """Add fictional money from the demo funding account (still a real double-entry transfer)."""
    s = get_settings()
    ratelimit.check("topup", str(p.user.id), 10, 60)

    def work() -> dict:
        acc = db.execute(select(Account).where(Account.id == account_id, Account.user_id == p.user.id)).scalar_one_or_none()
        if acc is None:
            raise ApiError(404, "not_found", "Account not found.")
        if body.fils > s.max_topup_fils:
            raise ApiError(422, "over_limit", f"You can add up to {format_bhd(s.max_topup_fils)} BHD at a time.")
        funding = db.execute(select(Account).where(Account.kind == "system", Account.name == "Demo funding")).scalar_one()
        moved = transfers.move_money(db, from_id=funding.id, to_id=acc.id, amount_fils=body.fils, kind="topup",
                                     category="income", initiated_by=p.user.id,
                                     daily_incoming_limit=s.daily_topup_limit_fils)
        audit.record(db, "account.topup", p.user.id, p.ip, amount_fils=body.fils)
        return account_out(moved.destination).model_dump(mode="json")

    return _with_idempotency(db, p, idempotency_key, {"op": "topup", "account": account_id, **body.model_dump()}, work)


def _card_out(card: Card, user: User) -> CardOut:
    return CardOut(id=card.id, last4=card.last4, expiry=card.expiry, holder=user.full_name, frozen=card.frozen,
                   online_payments=card.online_payments)


@router.get("/card", response_model=CardOut)
def card(p: Principal = Depends(current), db: Session = Depends(get_db)):
    c = db.execute(select(Card).where(Card.user_id == p.user.id)).scalar_one_or_none()
    if c is None:
        raise ApiError(404, "not_found", "No card yet.")
    return _card_out(c, p.user)


@router.patch("/card", response_model=CardOut)
def update_card(body: CardPatch, p: Principal = Depends(current), db: Session = Depends(get_db)):
    c = db.execute(select(Card).where(Card.user_id == p.user.id).with_for_update().execution_options(populate_existing=True)).scalar_one_or_none()
    if c is None:
        raise ApiError(404, "not_found", "No card yet.")
    changes = body.model_dump(exclude_none=True)
    for field, value in changes.items():
        setattr(c, field, value)
    if changes:
        audit.record(db, "card.updated", p.user.id, p.ip, **changes)
    db.commit()
    return _card_out(c, p.user)


_FRIENDLY = {
    "auth.login": "Signed in", "auth.logout": "Signed out", "auth.logout_all": "Signed out everywhere",
    "auth.login_failed": "Wrong password attempt", "auth.account_locked": "Account temporarily locked",
    "auth.login_blocked": "Sign-in blocked while locked", "auth.registered": "Account created",
    "auth.password_changed": "Password changed", "auth.password_change_failed": "Password change failed",
    "auth.session_revoked": "Device signed out", "auth.refresh_reuse_detected": "Suspicious session stopped",
    "transfer.created": "Money sent", "account.topup": "Demo money added", "card.updated": "Card settings changed",
    "assistant.transfer_proposed": "Assistant drafted a transfer", "assistant.transfer_confirmed": "You confirmed an assistant transfer",
    "assistant.transfer_cancelled": "You cancelled an assistant transfer",
}


@router.get("/security/activity")
def security_activity(p: Principal = Depends(current), db: Session = Depends(get_db),
                      limit: int = Query(20, ge=1, le=50)):
    """The signed-in user's own security events (never anyone else's)."""
    rows = db.execute(select(AuditLog).where(AuditLog.user_id == p.user.id).order_by(AuditLog.id.desc()).limit(limit)).scalars()
    return [{"id": r.id, "event": r.event, "title": _FRIENDLY.get(r.event, r.event), "at": r.at} for r in rows]
