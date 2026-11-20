"""Money requests: ask someone for money; they pay with one tap or decline.

Security properties (all tested in tests/test_requests.py):
  * only the payer can pay or decline, only the requester can cancel; anyone else gets 404
  * paying goes through the same locked, idempotent, limit-checked path as a normal transfer
  * a request can be paid at most once, even with parallel taps on different devices
  * spam control: rate limit plus a cap on open requests per requester
"""
import csv
import io
import uuid
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, aliased

from .. import audit, ratelimit, transfers
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, current
from ..errors import ApiError
from ..models import Account, PaymentRequest, User
from ..money import format_bhd
from ..schemas import RequestIn
from ..security import now
from .banking import _with_idempotency, list_transactions

router = APIRouter(prefix="/api/v1", tags=["requests"])
MAX_OPEN_REQUESTS = 20


def _out(r: PaymentRequest, requester: User, payer: User, me: uuid.UUID) -> dict:
    mine = r.requester_id == me
    other = payer if mine else requester
    return {"id": str(r.id), "direction": "outgoing" if mine else "incoming",
            "other_name": transfers.display_name(other), "other_handle": other.handle,
            "amount_fils": r.amount_fils, "amount": format_bhd(r.amount_fils), "note": r.note,
            "status": r.status, "created_at": r.created_at.isoformat()}


def _load(db: Session, request_id: uuid.UUID, user_id: uuid.UUID, lock: bool = False) -> PaymentRequest:
    """Fetch a request the caller is part of. Strangers get the same 404 as a missing id."""
    q = select(PaymentRequest).where(PaymentRequest.id == request_id,
                                     or_(PaymentRequest.requester_id == user_id, PaymentRequest.payer_id == user_id))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    r = db.execute(q).scalar_one_or_none()
    if r is None:
        raise ApiError(404, "not_found", "That request no longer exists.")
    return r


@router.post("/requests", status_code=201)
def create_request(body: RequestIn, p: Principal = Depends(current), db: Session = Depends(get_db)):
    ratelimit.check("request", str(p.user.id), 10, 60)
    note = body.note
    if body.fils > get_settings().max_transfer_fils:
        raise ApiError(422, "over_limit", f"You can request up to {format_bhd(get_settings().max_transfer_fils)} BHD.")
    _, payer = transfers.resolve_destination(db, p.user, body.to)
    if payer.id == p.user.id:
        raise ApiError(422, "same_person", "You can't request money from yourself.")
    open_count = db.execute(select(func.count()).select_from(PaymentRequest).where(
        PaymentRequest.requester_id == p.user.id, PaymentRequest.status == "pending")).scalar_one()
    if open_count >= MAX_OPEN_REQUESTS:
        raise ApiError(409, "too_many_open", "You have too many open requests. Cancel some first.")
    r = PaymentRequest(requester_id=p.user.id, payer_id=payer.id, amount_fils=body.fils, note=note)
    db.add(r)
    db.flush()
    audit.record(db, "request.created", p.user.id, p.ip, request=str(r.id), amount_fils=body.fils)
    db.commit()
    return _out(r, p.user, payer, p.user.id)


@router.get("/requests")
def list_requests(p: Principal = Depends(current), db: Session = Depends(get_db)):
    """Pending requests waiting on me, plus my own recent requests."""
    req_user, pay_user = aliased(User), aliased(User)
    rows = db.execute(
        select(PaymentRequest, req_user, pay_user)
        .join(req_user, req_user.id == PaymentRequest.requester_id)
        .join(pay_user, pay_user.id == PaymentRequest.payer_id)
        .where(or_(PaymentRequest.payer_id == p.user.id, PaymentRequest.requester_id == p.user.id))
        .where(or_(PaymentRequest.status == "pending", PaymentRequest.created_at > now() - timedelta(days=30)))
        .order_by(PaymentRequest.created_at.desc()).limit(50)
    ).all()
    items = [_out(r, a, b, p.user.id) for r, a, b in rows]
    return {"incoming": [i for i in items if i["direction"] == "incoming" and i["status"] == "pending"],
            "outgoing": [i for i in items if i["direction"] == "outgoing"]}


@router.post("/requests/{request_id}/pay", status_code=201)
def pay_request(request_id: uuid.UUID, p: Principal = Depends(current), db: Session = Depends(get_db),
                idempotency_key: str | None = Header(None)):
    ratelimit.check("transfer", str(p.user.id), 30, 60)

    def work() -> dict:
        r = _load(db, request_id, p.user.id, lock=True)  # row lock: parallel taps queue up here
        if r.payer_id != p.user.id:
            raise ApiError(404, "not_found", "That request no longer exists.")
        if r.status != "pending":
            raise ApiError(409, "not_pending", "This request was already handled.")
        requester = db.get(User, r.requester_id)
        source = db.execute(select(Account).where(Account.user_id == p.user.id, Account.kind == "current")).scalar_one()
        result = transfers.send(db, p.user, from_account_id=source.id, to=requester.handle, amount_fils=r.amount_fils,
                                note=r.note or "Payment request", ip=p.ip, source="request")
        r.status, r.transfer_id, r.decided_at = "paid", uuid.UUID(result["id"]), now()
        audit.record(db, "request.paid", p.user.id, p.ip, request=str(r.id), transfer=result["id"])
        return result

    return _with_idempotency(db, p, idempotency_key, {"op": "pay-request", "request": request_id}, work)


def _close(db: Session, p: Principal, request_id: uuid.UUID, status: str) -> None:
    r = _load(db, request_id, p.user.id, lock=True)
    allowed = r.payer_id if status == "declined" else r.requester_id
    if allowed != p.user.id:
        raise ApiError(404, "not_found", "That request no longer exists.")
    if r.status != "pending":
        raise ApiError(409, "not_pending", "This request was already handled.")
    r.status, r.decided_at = status, now()
    audit.record(db, f"request.{status}", p.user.id, p.ip, request=str(r.id))
    db.commit()


@router.post("/requests/{request_id}/decline", status_code=204)
def decline_request(request_id: uuid.UUID, p: Principal = Depends(current), db: Session = Depends(get_db)):
    _close(db, p, request_id, "declined")


@router.post("/requests/{request_id}/cancel", status_code=204)
def cancel_request(request_id: uuid.UUID, p: Principal = Depends(current), db: Session = Depends(get_db)):
    _close(db, p, request_id, "cancelled")


# ------------------------------------------------------------------ statement

def _cell(value: str) -> str:
    """Neutralise spreadsheet formulas (CSV injection): another customer controls the note text."""
    return "'" + value if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


@router.get("/statement.csv", response_class=Response,
            responses={200: {"content": {"text/csv": {}}, "description": "Everyday account statement"}})
def statement(p: Principal = Depends(current), db: Session = Depends(get_db), days: int = Query(30, ge=1, le=365)):
    ratelimit.check("statement", str(p.user.id), 10, 60)
    since = now() - timedelta(days=days)
    rows = [r for r in list_transactions(db, p.user.id, limit=1000, kind="current") if r["created_at"] >= since]
    buf = io.StringIO()
    out = csv.writer(buf)
    out.writerow(["Date", "Description", "Category", "Note", "Amount (BHD)"])
    for r in rows:
        out.writerow([r["created_at"].date().isoformat(), _cell(r["title"]), r["category"], _cell(r["note"]), r["amount"]])
    audit.record(db, "statement.downloaded", p.user.id, p.ip, days=days)
    db.commit()
    return Response(buf.getvalue().encode("utf-8-sig"), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="sahil-statement-{days}d.csv"'})
