"""Tests that run WITHOUT an API key, using a fake Claude client."""

import json
from types import SimpleNamespace

import pytest

from app.agent import SupportAgent
from app.config import Settings
from app.escalation import EscalationService
from app.orders import MockOrderProvider
from app.tools import TOOL_DEFINITIONS, ToolBox


@pytest.fixture
def toolbox(tmp_path):
    s = Settings()
    return ToolBox(
        orders=MockOrderProvider(s.data_dir / "sample_orders.json"),
        products_path=s.knowledge_dir / "products.json",
        escalation=EscalationService(tmp_path / "tickets.jsonl"),
    )


# ---------- tools ----------
def test_order_lookup_requires_matching_email(toolbox):
    ok = json.loads(toolbox.get_order_status("#1002", "ALEX@example.com "))
    assert ok["found"] and ok["order"]["status"].startswith("Shipped")
    assert "email" not in ok["order"]  # never echo the email back

    wrong_email = json.loads(toolbox.get_order_status("1002", "someone@else.com"))
    missing = json.loads(toolbox.get_order_status("9999", "alex@example.com"))
    assert wrong_email == missing and not missing["found"]  # indistinguishable


def test_product_search(toolbox):
    res = json.loads(toolbox.search_products("vegan candles"))
    assert res["results"][0]["sku"] == "CNDL-202"
    assert json.loads(toolbox.search_products("laptop"))["count"] == 0


def test_escalation_writes_ticket(toolbox, tmp_path):
    out, is_err, tid = toolbox.run("escalate_to_human", {
        "reason": "damaged item", "summary": "Mug arrived broken, order 1001.",
        "customer_name": "Sam", "customer_email": "sam@example.com", "priority": "normal",
    }, "sess1")
    assert not is_err and tid.startswith("T-")
    ticket = json.loads((tmp_path / "tickets.jsonl").read_text().splitlines()[0])
    assert ticket["ticket_id"] == tid and ticket["session_id"] == "sess1"


def test_tool_schemas_are_strict():
    for t in TOOL_DEFINITIONS:
        assert t["strict"] is True
        assert t["input_schema"]["additionalProperties"] is False
        assert set(t["input_schema"]["required"]) == set(t["input_schema"]["properties"])


# ---------- agent loop with a fake Claude ----------
class Block(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


def text(t):
    return Block(type="text", text=t)


def tool(name, args, id="tu_1"):
    return Block(type="tool_use", id=id, name=name, input=args)


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(json.loads(json.dumps(kwargs["messages"], default=str)))
        stop, content = self.responses.pop(0)
        return SimpleNamespace(stop_reason=stop, content=content)


def make_agent(toolbox, responses):
    client = FakeClient(responses)
    return SupportAgent(Settings(), toolbox, client=client), client


def test_order_status_tool_loop(toolbox):
    agent, client = make_agent(toolbox, [
        ("tool_use", [tool("get_order_status", {"order_number": "1002", "email": "alex@example.com"})]),
        ("end_turn", [text("Your order is with DPD and should arrive on 3 November.")]),
    ])
    history = []
    r = agent.reply(history, "where is order 1002? alex@example.com", "s1")
    assert "DPD" in r.text and r.tools_used == ["get_order_status"]
    # second call to Claude must include the tool result
    tool_result = client.calls[1][-1]["content"][0]
    assert tool_result["type"] == "tool_result" and '"found": true' in tool_result["content"]
    assert [m["role"] for m in history] == ["user", "assistant", "user", "assistant"]


def test_escalation_flag(toolbox):
    agent, _ = make_agent(toolbox, [
        ("tool_use", [tool("escalate_to_human", {
            "reason": "cancel order", "summary": "Wants to cancel 1003.", "customer_name": "Jo",
            "customer_email": "jo@example.com", "priority": "urgent"})]),
        ("end_turn", [text("I've passed this to our team.")]),
    ])
    r = agent.reply([], "cancel my order please", "s2")
    assert r.escalated and r.ticket_id.startswith("T-")


def test_refusal_rolls_back_history(toolbox):
    agent, _ = make_agent(toolbox, [("refusal", [])])
    history = [{"role": "user", "content": "hi"}, {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]}]
    r = agent.reply(history, "something odd", "s3")
    assert len(history) == 2 and "support@example.com" in r.text


def test_api_error_rolls_back_history(toolbox):
    agent, client = make_agent(toolbox, [])  # pop from empty list -> raises
    history = []
    with pytest.raises(IndexError):
        agent.reply(history, "hello", "s4")
    assert history == []
