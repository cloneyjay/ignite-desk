"""Minimal MCP client for the MetaTrader 5 Streamable HTTP server.

Deliberately small: initialize, tools/list, tools/call. The MT5 server speaks
protocol 2025-06-18 and returns either application/json or text/event-stream.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import httpx

PROTOCOL_VERSION = "2025-06-18"


class MCPError(RuntimeError):
    """Raised when the server returns a JSON-RPC error or an error result."""


class MCPClient:
    def __init__(self, url: str, headers: dict[str, str], timeout_s: float = 60.0) -> None:
        self._url = url
        self._headers = dict(headers)
        self._client = httpx.Client(timeout=timeout_s)
        self._session_id: str | None = None
        self._next_id = 0
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ plumbing

    def __enter__(self) -> "MCPClient":
        self.initialize()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _request_headers(self) -> dict[str, str]:
        headers = dict(self._headers)
        if self._session_id:
            headers["Mcp-Session-Id"] = self._session_id
        return headers

    def _parse_body(self, response: httpx.Response) -> dict[str, Any]:
        ctype = response.headers.get("content-type", "")
        if not response.content:
            return {}
        if "text/event-stream" in ctype:
            payload = None
            for line in response.text.splitlines():
                if line.startswith("data:"):
                    chunk = line[5:].strip()
                    if chunk:
                        try:
                            payload = json.loads(chunk)
                        except json.JSONDecodeError:
                            continue
            if payload is None:
                raise MCPError("SSE response contained no JSON payload")
            return payload
        return response.json()

    def _post(self, payload: dict[str, Any], *, retry: bool = True) -> dict[str, Any]:
        response = self._client.post(self._url, headers=self._request_headers(), json=payload)

        # Session expired: re-initialise once, then replay the call.
        if response.status_code in (404, 410) and retry:
            self.initialize()
            return self._post(payload, retry=False)

        if response.status_code == 202:
            return {}

        if response.status_code >= 400:
            raise MCPError(f"HTTP {response.status_code}: {response.text[:500]}")

        body = self._parse_body(response)
        if "error" in body:
            raise MCPError(f"{body['error'].get('code')}: {body['error'].get('message')}")
        return body

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            request_id = self._next_id
        body = self._post(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}}
        )
        result = body.get("result")
        if result is None:
            raise MCPError(f"no result for {method}: {body}")
        return result

    def _notify(self, method: str) -> None:
        # Notifications carry no id and the server answers 202.
        self._post({"jsonrpc": "2.0", "method": method}, retry=False)

    # ------------------------------------------------------------------- protocol

    def initialize(self) -> dict[str, Any]:
        response = self._client.post(
            self._url,
            headers=self._headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "ignite-desk", "version": "0.1"},
                },
            },
        )
        if response.status_code >= 400:
            raise MCPError(f"initialize failed: HTTP {response.status_code} {response.text[:300]}")
        session = response.headers.get("mcp-session-id")
        if session:
            self._session_id = session
        self._notify("notifications/initialized")
        self._next_id = 1
        return self._parse_body(response).get("result", {})

    def list_tools(self) -> list[dict[str, Any]]:
        return self._rpc("tools/list").get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        result = self._rpc("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
            raise MCPError(f"{name} failed: {' '.join(texts)[:1000]}")
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        raw = "\n".join(t for t in texts if t)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"text": raw}
