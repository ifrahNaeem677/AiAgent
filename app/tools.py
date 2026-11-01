"""The tools the AI agent is allowed to use.

Each tool has (1) a JSON schema Claude sees and (2) a Python function that runs it.
All tools are read-only except `escalate_to_human`, which only creates a ticket.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .escalation import EscalationService
from .orders import OrderProvider

log = logging.getLogger(__name__)

TOOL_DEFINITIONS = [
    {
        "name": "get_order_status",
        "description": (
            "Look up the status, items, tracking and estimated delivery of a customer's order. "
            "Requires BOTH the order number and the email address used at checkout; ask the "
            "customer for whichever is missing before calling. Never guess either value."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "order_number": {"type": "string", "description": "Order number, e.g. 1001 or #1001"},
                "email": {"type": "string", "description": "Email address used on the order"},
            },
            "required": ["order_number", "email"],
            "additionalProperties": False,
        },
    },
    {
        "name": "search_products",
        "description": (
            "Search the store's product catalogue by keywords (name, type, colour, use). "
            "Returns matching products with price, stock and description. Use for any "
            "question about what we sell, prices, sizes, materials or availability."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search keywords"}},
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Hand the conversation to a human staff member by creating a support ticket. "
            "Use when the customer asks for a person; when they are upset or the issue is "
            "complex; for damaged/faulty items, missing parcels, refund disputes, order "
            "changes or cancellations; or when the answer is not in the store information. "
            "Collect the customer's name and email first if you can do so naturally."
        ),
        "strict": True,
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Short category, e.g. 'damaged item', 'cancel order'"},
                "summary": {
                    "type": "string",
                    "description": "2-4 sentences for staff: what the customer needs, order number, what was already tried",
                },
                "customer_name": {"type": "string", "description": "Customer name, or empty string if unknown"},
                "customer_email": {"type": "string", "description": "Customer email, or empty string if unknown"},
                "priority": {"type": "string", "enum": ["low", "normal", "urgent"]},
            },
            "required": ["reason", "summary", "customer_name", "customer_email", "priority"],
            "additionalProperties": False,
        },
    },
]


class ToolBox:
    def __init__(self, orders: OrderProvider, products_path: Path, escalation: EscalationService):
        self.orders = orders
        self.products = json.loads(products_path.read_text())
        self.escalation = escalation

    # Returns (result_text, is_error, ticket_id_or_None)
    def run(self, name: str, args: dict, session_id: str) -> tuple[str, bool, str | None]:
        try:
            if name == "get_order_status":
                return self.get_order_status(**args), False, None
            if name == "search_products":
                return self.search_products(**args), False, None
            if name == "escalate_to_human":
                ticket_id = self.escalation.create_ticket(session_id=session_id, **args)
                return json.dumps({"ticket_id": ticket_id, "created": True}), False, ticket_id
            return f"Unknown tool: {name}", True, None
        except Exception as e:  # tool failures go back to Claude, not to the customer as a crash
            log.exception("Tool %s failed", name)
            return f"Tool error: {type(e).__name__}. The system is unavailable right now.", True, None

    def get_order_status(self, order_number: str, email: str) -> str:
        order = self.orders.get_order(order_number)
        # Privacy: only reveal an order when the email matches. Give the same
        # answer for "no such order" and "wrong email" so nobody can probe numbers.
        if not order or order.get("email", "").strip().lower() != email.strip().lower():
            return json.dumps({
                "found": False,
                "message": "No order matches that order number and email combination.",
            })
        safe = {k: v for k, v in order.items() if k != "email"}
        return json.dumps({"found": True, "order": safe})

    def search_products(self, query: str) -> str:
        words = [w for w in query.lower().split() if len(w) > 1]
        scored = []
        for p in self.products:
            haystack = " ".join([p["name"], p["description"], " ".join(p.get("tags", []))]).lower()
            score = sum(1 for w in words if w.rstrip("s") in haystack)
            if score:
                scored.append((score, p))
        scored.sort(key=lambda x: -x[0])
        results = [p for _, p in scored[:5]]
        return json.dumps({"results": results, "count": len(results)})
