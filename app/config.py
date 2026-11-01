"""Settings loaded from environment variables (or a .env file)."""

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader so beginners don't need an extra package."""
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


_load_dotenv(ROOT / ".env")


@dataclass
class Settings:
    store_name: str = os.getenv("STORE_NAME", "Demo Store")
    support_email: str = os.getenv("SUPPORT_EMAIL", "support@example.com")

    # "anthropic" or "groq". If not set: Groq when only GROQ_API_KEY is present.
    provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER") or (
        "groq" if os.getenv("GROQ_API_KEY") and not os.getenv("ANTHROPIC_API_KEY") else "anthropic"
    ))
    groq_model: str = os.getenv("GROQ_MODEL", "auto")
    model: str = os.getenv("AGENT_MODEL", "claude-opus-5-5")
    effort: str = os.getenv("AGENT_EFFORT", "low")

    order_backend: str = os.getenv("ORDER_BACKEND", "mock")
    shopify_domain: str = os.getenv("SHOPIFY_STORE_DOMAIN", "")
    shopify_token: str = os.getenv("SHOPIFY_ADMIN_TOKEN", "")
    wc_url: str = os.getenv("WC_STORE_URL", "")
    wc_key: str = os.getenv("WC_CONSUMER_KEY", "")
    wc_secret: str = os.getenv("WC_CONSUMER_SECRET", "")

    escalation_webhook_url: str = os.getenv("ESCALATION_WEBHOOK_URL", "")
    allowed_origins: list[str] = field(
        default_factory=lambda: [
            o.strip()
            for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:8000").split(",")
            if o.strip()
        ]
    )

    knowledge_dir: Path = ROOT / "knowledge"
    data_dir: Path = ROOT / "data"


settings = Settings()
