"""Web server: chat API + the embeddable widget.

Run:  uvicorn app.main:app --reload
Then open http://localhost:8000
"""

from __future__ import annotations

import logging
import time
import uuid
from collections import defaultdict, deque
from threading import Lock

import anthropic
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .agent import SupportAgent
from .config import ROOT, settings
from .escalation import EscalationService
from .orders import make_order_provider
from .tools import ToolBox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("support")

app = FastAPI(title=f"{settings.store_name} Support Agent")
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type"],
)

toolbox = ToolBox(
    orders=make_order_provider(settings),
    products_path=settings.knowledge_dir / "products.json",
    escalation=EscalationService(settings.data_dir / "tickets.jsonl", settings.escalation_webhook_url),
)
_agent: SupportAgent | None = None


def get_agent() -> SupportAgent:
    global _agent
    if _agent is None:
        _agent = SupportAgent(settings, toolbox)
    return _agent


# ---- Conversation memory (in-process). Step 5: move to Redis/a database. ----
SESSION_TTL_SECONDS = 2 * 60 * 60
MAX_TURNS_PER_SESSION = 40
sessions: dict[str, dict] = {}
session_locks: defaultdict[str, Lock] = defaultdict(Lock)

# ---- Basic abuse protection: N messages per IP per minute ----
RATE_LIMIT = 15
hits: defaultdict[str, deque] = defaultdict(deque)


def rate_limited(ip: str) -> bool:
    now = time.time()
    q = hits[ip]
    while q and now - q[0] > 60:
        q.popleft()
    q.append(now)
    return len(q) > RATE_LIMIT


def cleanup_sessions() -> None:
    cutoff = time.time() - SESSION_TTL_SECONDS
    for sid in [s for s, v in sessions.items() if v["updated"] < cutoff]:
        sessions.pop(sid, None)
        session_locks.pop(sid, None)


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = Field(default=None, max_length=64)


class ChatOut(BaseModel):
    session_id: str
    reply: str
    escalated: bool = False
    ticket_id: str | None = None


@app.post("/api/chat", response_model=ChatOut)
def chat(body: ChatIn, request: Request) -> ChatOut:
    ip = request.client.host if request.client else "unknown"
    if rate_limited(ip):
        raise HTTPException(429, "Too many messages - please wait a moment.")
    cleanup_sessions()

    sid = body.session_id if body.session_id in sessions else uuid.uuid4().hex
    session = sessions.setdefault(sid, {"history": [], "turns": 0, "updated": time.time()})
    if session["turns"] >= MAX_TURNS_PER_SESSION:
        return ChatOut(session_id=sid, reply=(
            "This chat has got quite long! Please email "
            f"{settings.support_email} and our team will help you directly."))

    with session_locks[sid]:  # one message at a time per conversation
        try:
            r = get_agent().reply(session["history"], body.message.strip(), sid)
        except anthropic.RateLimitError:
            raise HTTPException(503, "We're very busy right now - please try again in a minute.")
        except anthropic.APIConnectionError:
            raise HTTPException(503, "Connection problem - please try again.")
        except anthropic.APIStatusError as e:
            log.error("Claude API error %s: %s", e.status_code, e.message)
            raise HTTPException(502, "Sorry, the assistant is unavailable right now.")
        session["turns"] += 1
        session["updated"] = time.time()

    log.info("session=%s tools=%s escalated=%s", sid[:8], r.tools_used, r.escalated)
    return ChatOut(session_id=sid, reply=r.text, escalated=r.escalated, ticket_id=r.ticket_id)


@app.get("/health")
def health() -> dict:
    return {"ok": True, "store": settings.store_name, "orders": settings.order_backend}


@app.get("/widget.js")
def widget() -> FileResponse:
    return FileResponse(ROOT / "static" / "widget.js", media_type="application/javascript")


@app.get("/")
def demo_page() -> FileResponse:
    return FileResponse(ROOT / "static" / "demo.html")
