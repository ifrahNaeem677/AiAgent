"""Groq agent tests (no API key needed)."""

import json
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.escalation import EscalationService
from app.groq_agent import GROQ_TOOLS, GroqSupportAgent
from app.orders import MockOrderProvider
from app.tools import ToolBox


@pytest.fixture
def toolbox(tmp_path):
    s = Settings()
    return ToolBox(MockOrderProvider(s.data_dir / "sample_orders.json"),
                   s.knowledge_dir / "products.json", EscalationService(tmp_path / "t.jsonl"))


def call(name, args, id="call_1"):
    return SimpleNamespace(id=id, type="function",
                           function=SimpleNamespace(name=name, arguments=json.dumps(args)))


class FakeGroq:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[SimpleNamespace(id="openai/gpt-oss-120b")]))

    def _create(self, **kw):
        self.calls.append(kw)
        content, tool_calls = self.replies.pop(0)
        msg = SimpleNamespace(content=content, tool_calls=tool_calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def test_tool_format():
    assert {t["function"]["name"] for t in GROQ_TOOLS} == {"get_order_status", "search_products", "escalate_to_human"}
    assert all(t["type"] == "function" for t in GROQ_TOOLS)


def test_order_lookup_loop(toolbox):
    fake = FakeGroq([
        (None, [call("get_order_status", {"order_number": "1002", "email": "alex@example.com"})]),
        ("Your order is with DPD.", None),
    ])
    agent = GroqSupportAgent(Settings(), toolbox, client=fake)
    history = []
    r = agent.reply(history, "where is 1002? alex@example.com", "s")
    assert r.text == "Your order is with DPD." and r.tools_used == ["get_order_status"]
    assert [m["role"] for m in history] == ["user", "assistant", "tool", "assistant"]
    assert '"found": true' in history[2]["content"]
    second = fake.calls[1]["messages"]
    assert second[0]["role"] == "system" and second[-1]["role"] == "tool"


def test_bad_tool_arguments_are_reported_not_crashing(toolbox):
    bad = SimpleNamespace(id="c1", type="function", function=SimpleNamespace(name="search_products", arguments="{not json"))
    fake = FakeGroq([(None, [bad]), ("Sorry, what are you looking for?", None)])
    r = GroqSupportAgent(Settings(), toolbox, client=fake).reply([], "candles", "s")
    assert r.text.startswith("Sorry")


def test_escalation(toolbox):
    fake = FakeGroq([
        (None, [call("escalate_to_human", {"reason": "damaged", "summary": "Broken mug.", "customer_name": "Sam",
                                           "customer_email": "sam@example.com", "priority": "normal"})]),
        ("Passed to the team.", None),
    ])
    r = GroqSupportAgent(Settings(), toolbox, client=fake).reply([], "broken mug", "s")
    assert r.escalated and r.ticket_id.startswith("T-")


def test_error_rolls_back(toolbox):
    agent = GroqSupportAgent(Settings(), toolbox, client=FakeGroq([]))
    history = []
    with pytest.raises(IndexError):
        agent.reply(history, "hi", "s")
    assert history == []


def test_provider_auto_detect(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    assert Settings().provider == "groq"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    assert Settings().provider == "anthropic"
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    assert Settings().provider == "groq"


class ModelGone(Exception):
    status_code = 404


class FakeGroqWithModels(FakeGroq):
    def __init__(self, replies, available, missing=()):
        super().__init__(replies)
        self.missing = set(missing)
        self.models = SimpleNamespace(list=lambda: SimpleNamespace(data=[SimpleNamespace(id=i) for i in available]))

    def _create(self, **kw):
        if kw["model"] in self.missing:
            raise ModelGone("model_not_found")
        return super()._create(**kw)


def test_retired_model_switches_automatically(toolbox):
    s = Settings()
    s.groq_model = "llama-3.3-70b-versatile"
    fake = FakeGroqWithModels([("Hello!", None)], available=["whisper-large-v3", "qwen/qwen3-32b", "openai/gpt-oss-120b"],
                              missing={"llama-3.3-70b-versatile"})
    agent = GroqSupportAgent(s, toolbox, client=fake)
    assert agent.reply([], "hi", "s").text == "Hello!"
    assert agent.model == "openai/gpt-oss-120b" and s.groq_model == "openai/gpt-oss-120b"


def test_auto_model_skips_non_chat_models(toolbox):
    s = Settings()
    s.groq_model = "auto"
    fake = FakeGroqWithModels([("Hi", None)], available=["whisper-large-v3", "some-new/chat-model"])
    agent = GroqSupportAgent(s, toolbox, client=fake)
    agent.reply([], "hi", "s")
    assert fake.calls[0]["model"] == "some-new/chat-model"
