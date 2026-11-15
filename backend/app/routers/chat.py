import logging
import uuid

from fastapi import APIRouter, Depends
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import ratelimit
from ..assistant import local, tools
from ..config import get_settings
from ..db import get_db
from ..deps import Principal, current
from ..models import ChatMessage
from ..schemas import ChatIn, TransferOut

log = logging.getLogger("sahil.assistant")
router = APIRouter(tags=["assistant"])
HISTORY_TURNS = 10
MAX_REPLY_CHARS = 1500


def _history(db: Session, user_id: uuid.UUID, limit: int) -> list[dict]:
    rows = db.execute(select(ChatMessage).where(ChatMessage.user_id == user_id)
                      .order_by(ChatMessage.id.desc()).limit(limit)).scalars().all()
    return [{"role": r.role, "content": r.content, "at": r.created_at} for r in reversed(rows)]


@router.post("/api/chat")
def chat(body: ChatIn, p: Principal = Depends(current), db: Session = Depends(get_db)):
    """Send a message to the signed-in user's personal assistant and get its text reply."""
    ratelimit.check("chat", str(p.user.id), 20, 60)
    box = tools.Toolbox(db, p.user, p.ip)
    engine, text = "local", ""
    if get_settings().gemini_api_key:
        try:
            from ..assistant import gemini
            text = gemini.reply(body.message, _history(db, p.user.id, HISTORY_TURNS), box)
            engine = "gemini"
        except Exception as exc:  # quota (429), network, SDK errors: degrade, never fail the user
            log.warning("gemini unavailable, using built-in assistant: %s", type(exc).__name__)
            box.proposal = None
            db.rollback()
    if not text:
        text = local.reply(body.message, box)
        engine = "local" if engine != "gemini" else engine
    text = text[:MAX_REPLY_CHARS]
    db.add_all([ChatMessage(user_id=p.user.id, role="user", content=body.message),
                ChatMessage(user_id=p.user.id, role="assistant", content=text)])
    db.commit()
    return {"reply": text, "proposal": box.proposal, "engine": engine}


@router.get("/api/chat/history")
def history(p: Principal = Depends(current), db: Session = Depends(get_db)):
    return _history(db, p.user.id, 50)


@router.delete("/api/chat/history", status_code=204)
def clear_history(p: Principal = Depends(current), db: Session = Depends(get_db)):
    db.execute(delete(ChatMessage).where(ChatMessage.user_id == p.user.id))
    db.commit()


@router.post("/api/v1/assistant/actions/{action_id}/confirm", response_model=TransferOut, status_code=201)
def confirm_action(action_id: uuid.UUID, p: Principal = Depends(current), db: Session = Depends(get_db)):
    """The explicit, human confirmation step. Only this call can turn a draft into a transfer."""
    ratelimit.check("transfer", str(p.user.id), 30, 60)
    try:
        body = tools.confirm(db, p.user, action_id, p.ip)
        db.commit()
        return body
    except Exception:
        db.rollback()
        raise


@router.post("/api/v1/assistant/actions/{action_id}/cancel", status_code=204)
def cancel_action(action_id: uuid.UUID, p: Principal = Depends(current), db: Session = Depends(get_db)):
    tools.cancel(db, p.user, action_id, p.ip)
    db.commit()
