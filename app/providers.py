"""Pick the AI provider (Claude or Groq) from the settings."""

from .config import Settings
from .tools import ToolBox


def make_agent(settings: Settings, toolbox: ToolBox):
    if settings.provider == "groq":
        from .groq_agent import GroqSupportAgent
        return GroqSupportAgent(settings, toolbox)
    from .agent import SupportAgent
    return SupportAgent(settings, toolbox)


def model_label(settings: Settings) -> str:
    return f"groq · {settings.groq_model}" if settings.provider == "groq" else f"claude · {settings.model}"


def api_key_present(settings: Settings) -> bool:
    import os
    if settings.provider == "groq":
        return bool(os.getenv("GROQ_API_KEY"))
    return bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


def friendly_error(e: Exception, settings: Settings) -> str:
    """Turn an API error from either provider into a clear message."""
    status = getattr(e, "status_code", None)
    detail = str(getattr(e, "message", "") or e)
    name = type(e).__name__
    key = "GROQ_API_KEY" if settings.provider == "groq" else "ANTHROPIC_API_KEY"
    if name == "AuthenticationError" or status == 401:
        return f"The API key is invalid. Check {key} in your Secrets."
    if name == "RateLimitError" or status == 429:
        return "We're very busy right now - please try again in a minute."
    if name in ("APIConnectionError", "APITimeoutError"):
        return "Connection problem - please try again."
    if "credit balance" in detail.lower():
        return "Your Anthropic account has no API credits. Add credits at https://platform.claude.com/settings/billing."
    if status == 404 or "model" in detail.lower():
        var = "GROQ_MODEL" if settings.provider == "groq" else "AGENT_MODEL"
        return f"The model isn't available for this key. Set {var} in Secrets to another model. Details: {detail}"
    return f"The assistant is unavailable right now (error {status}): {detail}"
