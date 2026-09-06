"""Shared LLM construction entry point."""

from app.core.llm.factory import get_chat_model

__all__ = ["get_chat_model"]
