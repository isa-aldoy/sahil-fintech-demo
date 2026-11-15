"""Hash-chained audit log.

Each row stores SHA-256(previous hash + its own content). Changing or deleting any
row breaks every later hash, and database triggers additionally reject UPDATE and
DELETE on the table. `verify_chain` recomputes the whole chain.
"""
import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from .models import AuditLog
from .security import now

GENESIS = "0" * 64
_CHAIN_LOCK = 7_241_001  # advisory lock id: one writer extends the chain at a time


def _digest(prev: str, at: datetime, user_id, event: str, ip: str, detail: dict) -> str:
    material = json.dumps(
        [prev, at.isoformat(timespec="microseconds"), str(user_id) if user_id else None, event, ip, detail],
        sort_keys=True, separators=(",", ":"),
    )
    return hashlib.sha256(material.encode()).hexdigest()


def record(db: Session, event: str, user_id: uuid.UUID | None = None, ip: str = "", **detail) -> None:
    """Append an event inside the caller's transaction (commits or rolls back with it)."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _CHAIN_LOCK})
    prev = db.execute(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1)).scalar() or GENESIS
    at = now()
    db.add(AuditLog(at=at, user_id=user_id, event=event, ip=ip, detail=detail, prev_hash=prev,
                    hash=_digest(prev, at, user_id, event, ip, detail)))
    db.flush()


def verify_chain(db: Session) -> tuple[bool, int, int | None]:
    """Return (intact, rows checked, id of first broken row)."""
    prev, count = GENESIS, 0
    for row in db.execute(select(AuditLog).order_by(AuditLog.id)).scalars():
        count += 1
        if row.prev_hash != prev or row.hash != _digest(prev, row.at, row.user_id, row.event, row.ip, row.detail):
            return False, count, row.id
        prev = row.hash
    return True, count, None
