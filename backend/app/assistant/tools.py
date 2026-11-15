"""The only things the assistant can do.

Every tool is bound to the authenticated user when the toolbox is created. The model
never supplies a user id or account id, so it has no way to ask for someone else's data.
There is no tool that moves money: `propose_transfer` only writes a draft that the user
must confirm in the app.
"""
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, transfers
from ..config import get_settings
from ..errors import ApiError
from ..models import Account, PendingAction, User
from ..money import format_bhd, parse_bhd
from ..routers.banking import list_transactions, spending_summary, user_accounts
from ..security import now

PROPOSAL_TTL_MINUTES = 5


def _mask(number: str) -> str:
    return "…" + number[-4:]


class Toolbox:
    def __init__(self, db: Session, user: User, ip: str):
        self.db, self.user, self.ip = db, user, ip
        self.proposal: dict | None = None

    # ---- read-only tools -------------------------------------------------
    def get_accounts(self) -> dict:
        return {"accounts": [
            {"name": a.name, "type": a.kind, "number": _mask(a.number), "balance_bhd": format_bhd(a.balance_fils)}
            for a in user_accounts(self.db, self.user.id)
        ]}

    def get_recent_transactions(self, limit: int = 8, search: str = "") -> dict:
        limit = max(1, min(int(limit or 8), 20))
        rows = list_transactions(self.db, self.user.id, limit=limit, search=(search or "")[:40] or None)
        return {"transactions": [
            {"date": r["created_at"].date().isoformat(), "title": r["title"], "amount_bhd": r["amount"],
             "category": r["category"], "note": r["note"]}
            for r in rows
        ]}

    def get_spending_summary(self, days: int = 30) -> dict:
        s = spending_summary(self.db, self.user.id, max(1, min(int(days or 30), 365)))
        return {"days": s["days"], "spent_bhd": s["spent"], "received_bhd": s["received"],
                "by_category": {c["category"]: c["amount"] for c in s["categories"]}}

    # ---- the single write-adjacent tool ---------------------------------
    def propose_transfer(self, to: str, amount: str, note: str = "") -> dict:
        """Draft a transfer. Returns a summary; nothing is sent."""
        try:
            fils = parse_bhd(str(amount))
        except ValueError:
            return {"error": "The amount is not valid. Ask the user for an amount like 5 or 12.500."}
        if fils > get_settings().max_transfer_fils:
            return {"error": "That is above the single-transfer limit."}
        try:
            dst, owner = transfers.resolve_destination(self.db, self.user, str(to))
        except ApiError:
            return {"error": "No Sahil user matches that name. Ask the user for the person's @handle."}
        src = self.db.execute(select(Account).where(Account.user_id == self.user.id, Account.kind == "current")).scalar_one()
        if dst.id == src.id:
            return {"error": "Source and destination are the same account."}
        if src.balance_fils < fils:
            return {"error": f"Not enough money. Available: {format_bhd(src.balance_fils)} BHD."}
        internal = owner.id == self.user.id
        to_name = dst.name if internal else transfers.display_name(owner)
        action = PendingAction(
            user_id=self.user.id, kind="transfer", expires_at=now() + timedelta(minutes=PROPOSAL_TTL_MINUTES),
            payload={"from_account_id": str(src.id), "to": str(dst.id) if internal else owner.handle,
                     "amount_fils": fils, "note": str(note or "")[:140], "to_name": to_name},
        )
        self.db.add(action)
        self.db.flush()
        audit.record(self.db, "assistant.transfer_proposed", self.user.id, self.ip, action=str(action.id), amount_fils=fils)
        self.proposal = {"id": str(action.id), "kind": "transfer", "to_name": to_name,
                         "to_handle": None if internal else owner.handle, "amount_fils": fils,
                         "amount": format_bhd(fils), "note": action.payload["note"],
                         "expires_at": action.expires_at.isoformat()}
        return {"status": "awaiting_user_confirmation", "to": to_name, "amount_bhd": format_bhd(fils),
                "instruction": "Tell the user to review and press Confirm. Do not say the money was sent."}

    def call(self, name: str, args: dict) -> dict:
        fn = {"get_accounts": self.get_accounts, "get_recent_transactions": self.get_recent_transactions,
              "get_spending_summary": self.get_spending_summary, "propose_transfer": self.propose_transfer}.get(name)
        if fn is None:
            return {"error": "Unknown tool."}
        try:
            return fn(**{k: v for k, v in (args or {}).items() if k in fn.__code__.co_varnames})
        except TypeError:
            return {"error": "Missing or invalid arguments."}


def confirm(db: Session, user: User, action_id: uuid.UUID, ip: str) -> dict:
    """Execute a drafted transfer after the user pressed Confirm. Safe to call twice."""
    action = db.execute(
        select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user.id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if action is None:
        raise ApiError(404, "not_found", "That request no longer exists.")
    key = f"assistant-{action.id}"
    payload = {"op": "assistant-confirm", "action": str(action.id)}
    replay = transfers.claim_key(db, user.id, key, transfers.request_fingerprint(payload))
    if replay is not None:
        return replay["body"]
    if action.status != "pending":
        raise ApiError(409, "not_pending", "That request was already handled.")
    if action.expires_at <= now():
        action.status = "expired"
        db.commit()
        raise ApiError(410, "expired", "That request expired. Please ask again.")
    body = transfers.send(db, user, from_account_id=uuid.UUID(action.payload["from_account_id"]),
                          to=action.payload["to"], amount_fils=action.payload["amount_fils"],
                          note=action.payload["note"], ip=ip, source="assistant")
    action.status = "confirmed"
    audit.record(db, "assistant.transfer_confirmed", user.id, ip, action=str(action.id))
    transfers.store_result(db, user.id, key, 201, body)
    return body


def cancel(db: Session, user: User, action_id: uuid.UUID, ip: str) -> None:
    action = db.execute(
        select(PendingAction).where(PendingAction.id == action_id, PendingAction.user_id == user.id).with_for_update().execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if action is None:
        raise ApiError(404, "not_found", "That request no longer exists.")
    if action.status == "pending":
        action.status = "cancelled"
        audit.record(db, "assistant.transfer_cancelled", user.id, ip, action=str(action.id))
