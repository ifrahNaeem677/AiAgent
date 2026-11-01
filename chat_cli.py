"""Chat with your agent in the terminal:  python chat_cli.py"""

import uuid

from app.config import settings
from app.escalation import EscalationService
from app.orders import make_order_provider
from app.providers import make_agent, model_label
from app.tools import ToolBox

toolbox = ToolBox(
    orders=make_order_provider(settings),
    products_path=settings.knowledge_dir / "products.json",
    escalation=EscalationService(settings.data_dir / "tickets.jsonl", settings.escalation_webhook_url),
)
agent = make_agent(settings, toolbox)
history, session_id = [], uuid.uuid4().hex

print(f"{settings.store_name} support (model: {model_label(settings)}). Type 'quit' to exit.\n")
while True:
    try:
        msg = input("You: ").strip()
    except (EOFError, KeyboardInterrupt):
        break
    if msg.lower() in {"quit", "exit"}:
        break
    if not msg:
        continue
    r = agent.reply(history, msg, session_id)
    print(f"\nAgent: {r.text}")
    if r.tools_used:
        print(f"   [tools used: {', '.join(r.tools_used)}]")
    if r.escalated:
        print(f"   [handed to staff - ticket {r.ticket_id}]")
    print()
