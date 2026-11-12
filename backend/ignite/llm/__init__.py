"""LLM access: one OpenAI-compatible client, one ordered fallback chain.

The client knows nothing about trading. It sends messages, returns text, and
reports which provider answered. Skills decide what is safe to ask and validate
what comes back; a failed chain is a normal outcome, not an exception the caller
must crash on.
"""

from backend.ignite.llm.client import (
    LLMClient,
    LLMError,
    LLMResult,
    LLMUnavailable,
    Provider,
)

__all__ = ["LLMClient", "LLMError", "LLMResult", "LLMUnavailable", "Provider"]
