"""Hand-off to human staff.

Every hand-off is saved to data/tickets.jsonl. If ESCALATION_WEBHOOK_URL is
set (e.g. a Slack incoming webhook), staff also get an instant message.
Later you can swap this for Gorgias, Zendesk, Freshdesk, email, etc.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

import httpx

log = logging.getLogger(__name__)


class EscalationService:
    def __init__(self, tickets_path: Path, webhook_url: str = ""):
        self.tickets_path = tickets_path
        self.webhook_url = webhook_url

    def create_ticket(self, *, session_id: str, reason: str, summary: str,
                      customer_name: str, customer_email: str, priority: str) -> str:
        ticket_id = "T-" + secrets.token_hex(3).upper()
        ticket = {
            "ticket_id": ticket_id,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "session_id": session_id,
            "priority": priority,
            "reason": reason,
            "summary": summary,
            "customer_name": customer_name,
            "customer_email": customer_email,
            "status": "open",
        }
        self.tickets_path.parent.mkdir(parents=True, exist_ok=True)
        with self.tickets_path.open("a") as f:
            f.write(json.dumps(ticket) + "\n")

        if self.webhook_url:
            text = (f":rotating_light: *New support hand-off {ticket_id}* ({priority})\n"
                    f"*Reason:* {reason}\n*Customer:* {customer_name or '-'} <{customer_email or 'no email'}>\n"
                    f"*Summary:* {summary}")
            try:
                httpx.post(self.webhook_url, json={"text": text}, timeout=10)
            except httpx.HTTPError:
                log.exception("Escalation webhook failed (ticket %s still saved)", ticket_id)
        return ticket_id
