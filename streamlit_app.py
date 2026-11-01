"""Streamlit version of the support agent.

Local:  streamlit run streamlit_app.py
Cloud:  deploy this repo on share.streamlit.io and add your secrets
        (GROQ_API_KEY or ANTHROPIC_API_KEY) under App settings -> Secrets.
"""

import json
import os
import uuid

import streamlit as st

st.set_page_config(page_title="Store Support Agent", page_icon="💬", layout="centered")

# Streamlit Cloud keeps keys in st.secrets; copy them into environment
# variables BEFORE importing app.config, which reads settings from the environment.
try:
    for key, value in st.secrets.items():
        if isinstance(value, (str, int, float, bool)):
            os.environ.setdefault(key, str(value))
except Exception:  # no secrets file locally - fine, .env is used instead
    pass

from app.config import settings  # noqa: E402
from app.escalation import EscalationService  # noqa: E402
from app.orders import make_order_provider  # noqa: E402
from app.providers import api_key_present, friendly_error, make_agent, model_label  # noqa: E402
from app.tools import ToolBox  # noqa: E402

TICKETS = settings.data_dir / "tickets.jsonl"
EXAMPLES = [
    "How long does delivery to Germany take?",
    "Can I return a personalised mug?",
    "Where is order 1002? My email is alex@example.com",
    "Do you have any vegan candles?",
    "My mug arrived broken, I want to speak to someone",
]


def show(text: str) -> None:
    st.markdown(text.replace("$", "\\$"))  # "$5 ... $10" would otherwise render as maths


@st.cache_resource
def load_agent():
    toolbox = ToolBox(
        orders=make_order_provider(settings),
        products_path=settings.knowledge_dir / "products.json",
        escalation=EscalationService(TICKETS, settings.escalation_webhook_url),
    )
    return make_agent(settings, toolbox)


def new_conversation() -> None:
    st.session_state.session_id = uuid.uuid4().hex
    st.session_state.api_history = []  # full history sent to Claude (incl. tool calls)
    st.session_state.display = [{
        "role": "assistant",
        "text": "Hi! I can help with delivery, returns, products or your order status. What can I do for you?",
    }]


if "session_id" not in st.session_state:
    new_conversation()

# ---------------- Sidebar ----------------
with st.sidebar:
    st.subheader(settings.store_name)
    st.caption(f"Model: `{model_label(settings)}` · orders: `{settings.order_backend}`")
    if st.button("New conversation", use_container_width=True):
        new_conversation()
        st.rerun()

    st.markdown("**Try asking**")
    for ex in EXAMPLES:
        if st.button(ex, key=ex, use_container_width=True):
            st.session_state.pending = ex
            st.rerun()

    st.markdown("**Staff tickets**")
    tickets = []
    if TICKETS.exists():
        tickets = [json.loads(line) for line in TICKETS.read_text().splitlines() if line.strip()]
    if not tickets:
        st.caption("No hand-offs yet.")
    for t in reversed(tickets[-10:]):
        with st.expander(f"{t['ticket_id']} · {t['reason']} ({t['priority']})"):
            st.write(t["summary"])
            st.caption(f"{t['customer_name'] or '-'} · {t['customer_email'] or 'no email'} · {t['created_at']}")

# ---------------- Chat ----------------
st.title("💬 Customer support")

if not api_key_present(settings):
    st.error(
        "No API key found. On Streamlit Cloud, open **App settings -> Secrets** and add ONE of:\n\n"
        '```toml\nGROQ_API_KEY = "gsk_..."\n```\n'
        '```toml\nANTHROPIC_API_KEY = "sk-ant-..."\n```\n'
        "Locally, put the same line in `.env` (without quotes)."
    )
    st.stop()

for msg in st.session_state.display:
    with st.chat_message(msg["role"]):
        show(msg["text"])
        if msg.get("note"):
            st.info(msg["note"], icon="🧑‍💼")

typed = st.chat_input("Type your message...", max_chars=2000)
user_text = typed or st.session_state.pop("pending", None)

if user_text:
    st.session_state.display.append({"role": "user", "text": user_text})
    with st.chat_message("user"):
        show(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                r = load_agent().reply(st.session_state.api_history, user_text, st.session_state.session_id)
                text = r.text
                note = f"Passed to our team - ticket {r.ticket_id}" if r.escalated else None
            except Exception as e:  # API errors from Groq or Anthropic
                text, note = friendly_error(e, settings), None
        show(text)
        if note:
            st.info(note, icon="🧑‍💼")
    st.session_state.display.append({"role": "assistant", "text": text, "note": note})
    if note:
        st.rerun()  # refresh the sidebar ticket list
