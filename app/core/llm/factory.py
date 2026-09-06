from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from app.core.config import Settings, get_settings


def get_chat_model(settings: Settings | None = None) -> BaseChatModel:
    """Build the configured chat model without making a model request."""
    resolved_settings = settings or get_settings()

    if resolved_settings.ai_provider != "openai":
        raise ValueError(
            f"Unsupported AI provider: {resolved_settings.ai_provider}"
        )

    return ChatOpenAI(
        model=resolved_settings.ai_model,
        base_url=resolved_settings.ai_base_url,
        api_key=resolved_settings.ai_api_key,
        timeout=resolved_settings.ai_timeout_seconds,
    )
