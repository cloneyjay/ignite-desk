"""OpenAI-compatible chat completions with an ordered provider chain.

Providers are tried in ``LLM_PROVIDER_ORDER``. A provider with no key (NIM) or
no model (extra) is skipped rather than attempted. Timeouts are shared across
the whole chain so a slow cloud endpoint cannot eat the skill's budget.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterable

import httpx

from backend.ignite.config import LLMSettings


class LLMError(RuntimeError):
    pass


class LLMUnavailable(LLMError):
    def __init__(self, message: str, attempts: list[str] | None = None) -> None:
        self.attempts = attempts or []
        super().__init__(message)


class ToolCallError(LLMError):
    """Raised when tool call arguments fail validation."""

    def __init__(self, tool: str, reason: str, raw_args: str | None = None) -> None:
        self.tool = tool
        self.reason = reason
        self.raw_args = raw_args
        super().__init__(f"tool {tool}: {reason}")


@dataclass(frozen=True)
class ToolCall:
    """A single tool call from the model."""

    id: str
    name: str
    arguments: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        """Convert to OpenAI tool call format."""
        return {
            "id": self.id,
            "type": "function",
            "function": {
                "name": self.name,
                "arguments": json.dumps(self.arguments),
            },
        }


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    model: str

    @property
    def url(self) -> str:
        return f"{self.base_url.rstrip('/')}/chat/completions"


@dataclass(frozen=True)
class LLMResult:
    text: str
    provider: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    tool_calls: list[ToolCall] | None = None


def _text_of(message: dict[str, Any]) -> str:
    """Extract text from a message, handling both content and reasoning_content (Nemotron)."""
    if not isinstance(message, dict):
        return ""
    # Prefer standard content (Nemotron puts the actual answer here)
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        # Nemotron sometimes puts reasoning in content for correction prompts.
        # Detect and fall back to reasoning_content.
        lower = content.strip().lower()
        if not (lower.startswith("the user wants") or 
                lower.startswith("the user is") or
                lower.startswith("this is") or
                lower.startswith("this user") or
                lower.startswith("let me") or 
                lower.startswith("i need to") or
                lower.startswith("i should") or
                lower.startswith("i will") or
                lower.startswith("first,") or
                lower.startswith("okay") or
                lower.startswith("sure")):
            return content.strip()
    # Fall back to reasoning_content if content is empty or looks like reasoning
    reasoning = message.get("reasoning_content")
    if isinstance(reasoning, str) and reasoning.strip():
        return reasoning.strip()
    # Handle list content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("text"):
                parts.append(str(item["text"]))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts)
    return ""


class LLMClient:
    def __init__(
        self, settings: LLMSettings, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.settings = settings
        self._http = httpx.Client(timeout=None, transport=transport)

    # ------------------------------------------------------------------ chain

    def provider(self, name: str) -> Provider | None:
        s = self.settings
        if name == "nim" and s.nim_api_key and s.nim_base_url and s.nim_model:
            return Provider("nim", s.nim_base_url, s.nim_api_key, s.nim_model)
        if name == "local" and s.local_base_url and s.local_model:
            return Provider("local", s.local_base_url, s.local_api_key, s.local_model)
        if name == "extra" and s.extra_base_url and s.extra_model:
            return Provider("extra", s.extra_base_url, s.extra_api_key, s.extra_model)
        return None

    def providers(self) -> list[Provider]:
        seen: set[str] = set()
        ordered: list[Provider] = []
        for name in (*self.settings.provider_order, "nim", "local", "extra"):
            name = name.lower()
            if name in seen:
                continue
            seen.add(name)
            provider = self.provider(name)
            if provider is not None:
                ordered.append(provider)
        return ordered

    def available(self) -> dict[str, bool]:
        return {name: self.provider(name) is not None for name in ("nim", "local", "extra")}

    # ------------------------------------------------------------------- call

    def complete(
        self,
        messages: Iterable[dict[str, str]],
        *,
        max_tokens: int | None = None,
        temperature: float = 0.2,
        timeout_s: float | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> LLMResult:
        providers = self.providers()
        if not providers:
            raise LLMUnavailable("no LLM provider is configured", [])

        deadline = time.monotonic() + (timeout_s or self.settings.timeout_s)
        attempts: list[str] = []
        for provider in providers:
            remaining = deadline - time.monotonic()
            if remaining <= 0.5:
                attempts.append("chain timeout reached")
                break
            try:
                return self._call(
                    provider,
                    list(messages),
                    max_tokens=max_tokens or self.settings.max_tokens,
                    temperature=temperature,
                    timeout_s=min(self.settings.timeout_s, remaining),
                    tools=tools,
                    tool_choice=tool_choice,
                )
            except (httpx.HTTPError, LLMError, ValueError) as exc:
                attempts.append(f"{provider.name}: {exc}")
        raise LLMUnavailable("all LLM providers failed", attempts)

    def _call(
        self,
        provider: Provider,
        messages: list[dict[str, str]],
        *,
        max_tokens: int,
        temperature: float,
        timeout_s: float,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str | dict[str, Any] | None = "auto",
    ) -> LLMResult:
        # Determine if provider supports native tool calling
        # NIM and local (Ollama v0.1+) support native tools
        native_tools = provider.name in ("nim", "local") and tools is not None

        headers = {"Content-Type": "application/json"}
        if provider.api_key:
            headers["Authorization"] = f"Bearer {provider.api_key}"

        payload = {
            "model": provider.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }

        if native_tools:
            payload["tools"] = tools
            if tool_choice is not None:
                payload["tool_choice"] = tool_choice
        elif tools is not None:
            # JSON fallback: inject tool schemas into system prompt
            payload["messages"] = self._inject_tool_schemas(messages, tools)

        started = time.monotonic()
        response = self._http.post(
            provider.url, headers=headers, json=payload, timeout=timeout_s
        )
        elapsed = int((time.monotonic() - started) * 1000)
        if response.status_code >= 400:
            detail = response.text[:300].replace("\n", " ")
            raise LLMError(f"HTTP {response.status_code}: {detail}")
        try:
            data = response.json()
        except ValueError as exc:
            raise LLMError("response is not JSON") from exc
        choices = data.get("choices") or []
        if not choices:
            raise LLMError("response contains no choices")
        message = choices[0].get("message") or {}
        text = _text_of(message).strip()

        tool_calls = None
        if native_tools:
            tool_calls = self._parse_native_tool_calls(message)
        elif tools is not None:
            tool_calls = self._parse_fallback_tool_calls(text, tools)

        if not text and not tool_calls:
            raise LLMError("response is empty")

        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            provider=provider.name,
            model=str(data.get("model") or provider.model),
            latency_ms=elapsed,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            tool_calls=tool_calls,
        )

    def _inject_tool_schemas(self, messages: list[dict[str, str]], tools: list[dict[str, Any]]) -> list[dict[str, str]]:
        """Inject tool schemas into system prompt for JSON fallback."""
        tool_descriptions = []
        for tool in tools:
            fn = tool.get("function", {})
            name = fn.get("name", "unknown")
            desc = fn.get("description", "")
            params = fn.get("parameters", {})
            tool_descriptions.append(f"- {name}: {desc}\n  Parameters: {json.dumps(params)}")

        system_prompt = (
            "You have access to the following tools. When you need to use a tool, "
            "respond with a JSON object in this format:\n"
            '{"tool": "tool_name", "arguments": {...}}\n\n'
            "Available tools:\n"
            + "\n".join(tool_descriptions)
            + "\n\nOnly output the JSON object when calling a tool. "
            "For normal responses, reply directly without JSON."
        )

        new_messages = [{"role": "system", "content": system_prompt}]
        new_messages.extend(messages)
        return new_messages

    def _parse_native_tool_calls(self, message: dict[str, Any]) -> list[ToolCall] | None:
        """Parse native OpenAI-format tool_calls from response message."""
        raw_calls = message.get("tool_calls") or []
        if not raw_calls:
            return None
        calls = []
        for rc in raw_calls:
            try:
                fn = rc.get("function", {})
                name = fn.get("name")
                args_str = fn.get("arguments", "{}")
                arguments = json.loads(args_str) if isinstance(args_str, str) else args_str
                calls.append(
                    ToolCall(
                        id=rc.get("id", uuid.uuid4().hex),
                        name=name,
                        arguments=arguments,
                    )
                )
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                raise ToolCallError(
                    tool=rc.get("function", {}).get("name", "unknown"),
                    reason=f"invalid arguments: {exc}",
                    raw_args=args_str,
                ) from exc
        return calls

    def _parse_fallback_tool_calls(self, text: str, tools: list[dict[str, Any]]) -> list[ToolCall] | None:
        """Parse JSON fallback tool calls from response text."""
        text = text.strip()
        if not text.startswith("{") or not text.endswith("}"):
            return None
        try:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                return None
            tool_name = parsed.get("tool")
            arguments = parsed.get("arguments", {})
            if not tool_name or not isinstance(arguments, dict):
                return None
            # Validate tool exists
            tool_names = {t.get("function", {}).get("name") for t in tools}
            if tool_name not in tool_names:
                raise ToolCallError(tool=tool_name, reason="unknown tool")
            return [ToolCall(id=uuid.uuid4().hex, name=tool_name, arguments=arguments)]
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise ToolCallError(
                tool="unknown", reason=f"invalid JSON fallback: {exc}", raw_args=text
            ) from exc

    def close(self) -> None:
        self._http.close()
