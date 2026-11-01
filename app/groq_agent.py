"""Same support agent, running on Groq (OpenAI-style chat completions + tool calls)."""

from __future__ import annotations

import json
import logging

from .agent import SYSTEM_TEMPLATE, MAX_TOOL_ROUNDS, AgentReply
from .config import Settings
from .tools import TOOL_DEFINITIONS, ToolBox

log = logging.getLogger(__name__)

# Convert our tool definitions into the OpenAI/Groq "function" format.
GROQ_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": t["name"],
            "description": t["description"],
            "parameters": t["input_schema"],
        },
    }
    for t in TOOL_DEFINITIONS
]


# When GROQ_MODEL is "auto" (or the chosen model is retired), use the first of
# these that your key can access. Groq changes its model list often.
PREFERRED_MODELS = [
    "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct-0905",
    "moonshotai/kimi-k2-instruct",
    "meta-llama/llama-4-maverick-17b-128e-instruct",
    "qwen/qwen3-32b",
    "openai/gpt-oss-20b",
    "meta-llama/llama-4-scout-17b-16e-instruct",
    "llama-3.3-70b-versatile",
    "llama-3.1-8b-instant",
]
NOT_CHAT_MODELS = ("whisper", "tts", "guard", "playai", "orpheus", "compound", "embed", "distil")


def _is_model_missing(e: Exception) -> bool:
    return getattr(e, "status_code", None) == 404 or "model_not_found" in str(e)


class GroqSupportAgent:
    def __init__(self, settings: Settings, toolbox: ToolBox, client=None):
        import groq  # imported here so the Claude version doesn't need the package

        self.settings = settings
        self.toolbox = toolbox
        self.client = client or groq.Groq()  # reads GROQ_API_KEY
        self.model = settings.groq_model.strip() or "auto"
        policies = (settings.knowledge_dir / "store_policies.md").read_text()
        self.system = SYSTEM_TEMPLATE.format(
            store_name=settings.store_name,
            policies=policies.strip(),
            support_email=settings.support_email,
        )

    def _pick_model(self) -> str:
        available = [m.id for m in self.client.models.list().data]
        for name in PREFERRED_MODELS:
            if name in available:
                return name
        chat = [m for m in available if not any(x in m.lower() for x in NOT_CHAT_MODELS)]
        if not chat:
            raise RuntimeError("No chat models are available for this Groq key.")
        return chat[0]

    def _use_model(self, name: str) -> None:
        log.warning("Using Groq model %s", name)
        self.model = name
        self.settings.groq_model = name  # so the app shows the model actually in use

    def _complete(self, messages: list[dict]):
        if self.model.lower() == "auto":
            self._use_model(self._pick_model())
        params = dict(messages=messages, tools=GROQ_TOOLS, tool_choice="auto",
                      temperature=0.3, max_completion_tokens=1024)
        try:
            return self.client.chat.completions.create(model=self.model, **params)
        except Exception as e:
            if not _is_model_missing(e):
                raise
            replacement = self._pick_model()
            if replacement == self.model:
                raise
            log.warning("Groq model %s is not available", self.model)
            self._use_model(replacement)
            return self.client.chat.completions.create(model=self.model, **params)

    def reply(self, history: list[dict], user_message: str, session_id: str) -> AgentReply:
        start = len(history)
        try:
            return self._run_turn(history, user_message, session_id)
        except Exception:
            del history[start:]  # never save a half-finished turn
            raise

    def _run_turn(self, history: list[dict], user_message: str, session_id: str) -> AgentReply:
        start = len(history)
        history.append({"role": "user", "content": user_message})
        result = AgentReply(text="")

        for _ in range(MAX_TOOL_ROUNDS):
            response = self._complete([{"role": "system", "content": self.system}, *history])
            msg = response.choices[0].message
            tool_calls = msg.tool_calls or []

            assistant = {"role": "assistant", "content": msg.content or ""}
            if tool_calls:
                assistant["tool_calls"] = [
                    {"id": tc.id, "type": "function",
                     "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                    for tc in tool_calls
                ]
            history.append(assistant)

            if not tool_calls:
                result.text = (msg.content or "").strip() or "Sorry, could you rephrase that?"
                return result

            for tc in tool_calls:
                try:
                    args = json.loads(tc.function.arguments or "{}")
                    if not isinstance(args, dict):
                        raise ValueError("arguments must be an object")
                    output, is_error, ticket_id = self.toolbox.run(tc.function.name, args, session_id)
                except (ValueError, TypeError) as e:  # bad JSON or wrong arguments from the model
                    output, is_error, ticket_id = f"Invalid tool arguments: {e}", True, None
                log.info("tool %s error=%s", tc.function.name, is_error)
                result.tools_used.append(tc.function.name)
                if ticket_id:
                    result.escalated, result.ticket_id = True, ticket_id
                history.append({"role": "tool", "tool_call_id": tc.id, "content": output})

        del history[start:]
        result.text = ("Sorry, I'm having trouble with that one. Please email "
                       f"{self.settings.support_email} and our team will help.")
        return result
