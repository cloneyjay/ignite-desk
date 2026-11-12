"""OpenAI-compatible chat completions with an ordered provider chain.

Providers are tried in ``LLM_PROVIDER_ORDER``. A provider with no key (NIM) or
no model (extra) is skipped rather than attempted. Timeouts are shared across
the whole chain so a slow cloud endpoint cannot eat the skill's budget.
"""

from __future__ import annotations

import time
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


def _text_of(content: Any) -> str:
    if isinstance(content, str):
        return content
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
    ) -> LLMResult:
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
        text = _text_of((choices[0].get("message") or {}).get("content")).strip()
        if not text:
            raise LLMError("response is empty")
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            provider=provider.name,
            model=str(data.get("model") or provider.model),
            latency_ms=elapsed,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
        )

    def close(self) -> None:
        self._http.close()
