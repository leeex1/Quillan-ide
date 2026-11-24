"""OpenAI-compatible HTTP adapter (OpenAI, OpenCode gateway, DeepSeek, Qwen, Ollama).

Uses only urllib.request. Supports non-streaming and SSE streaming responses,
parallel tool calls, and environment-sourced API keys.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Iterator

from ..models import Message, ProviderSpec, ToolCall
from .base import ProviderAdapter, ProviderError


def _api_key(spec: ProviderSpec) -> str:
    from ..auth import AuthStore

    env_value = os.environ.get(spec.api_key_env, "") if spec.api_key_env else ""
    return env_value or AuthStore().get(spec.name)


def _headers(spec: ProviderSpec) -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = _api_key(spec)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    headers.update(spec.extra_headers)
    return headers


def _url(spec: ProviderSpec, suffix: str) -> str:
    return spec.base_url.rstrip("/") + suffix


def _message_to_wire(msg: Message) -> dict[str, Any]:
    out: dict[str, Any] = {"role": msg.role, "content": msg.content}
    if msg.tool_calls:
        out["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=False),
                },
            }
            for call in msg.tool_calls
        ]
    if msg.tool_result is not None:
        out["role"] = "tool"
        out["tool_call_id"] = msg.tool_result.call_id
        out["content"] = (
            msg.tool_result.output
            if msg.tool_result.ok
            else f"ERROR: {msg.tool_result.error}"
        )
    return out


def _parse_tool_calls(raw: list[dict[str, Any]] | None) -> list[ToolCall]:
    result: list[ToolCall] = []
    for item in raw or []:
        fn = item.get("function") or {}
        args = fn.get("arguments") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        result.append(
            ToolCall(
                id=str(item.get("id") or f"call_{len(result)}"),
                name=str(fn.get("name") or ""),
                arguments=dict(args) if isinstance(args, dict) else {},
            )
        )
    return result


class OpenAICompatProvider:
    name = "openai_compat"

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec

    def _request(self, payload: dict[str, Any], *, stream: bool = False) -> Any:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            _url(self.spec, "/chat/completions"),
            data=body,
            headers=_headers(self.spec),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.spec.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise ProviderError(f"{self.spec.name} HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise ProviderError(f"{self.spec.name} connection failed: {exc}") from exc
        if stream:
            return raw.decode("utf-8", errors="replace")
        try:
            return json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as exc:
            raise ProviderError(f"{self.spec.name} returned non-JSON response") from exc

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> Message:
        payload: dict[str, Any] = {
            "model": self.spec.model,
            "messages": [_message_to_wire(m) for m in messages],
            "temperature": self.spec.temperature,
            "max_tokens": self.spec.max_tokens,
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t.get("description", ""),
                        "parameters": t.get(
                            "input_schema", {"type": "object", "properties": {}}
                        ),
                    },
                }
                for t in tools
            ]
        if stream:
            text = self._request(payload, stream=True)
            return self._parse_sse(text)
        data = self._request(payload)
        try:
            choice = data["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ProviderError(
                f"{self.spec.name} malformed completion response"
            ) from exc
        return Message(
            role="assistant",
            content=str(choice.get("content") or ""),
            tool_calls=_parse_tool_calls(choice.get("tool_calls")),
        )

    def _parse_sse(self, text: str) -> Message:
        content_parts: list[str] = []
        calls: dict[int, dict[str, Any]] = {}
        for line in text.splitlines():
            if not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload in ("", "[DONE]"):
                continue
            try:
                data = json.loads(payload)
            except ValueError:
                continue
            try:
                delta = data["choices"][0]["delta"]
            except (KeyError, IndexError, TypeError):
                continue
            if delta.get("content"):
                content_parts.append(str(delta["content"]))
            for frag in delta.get("tool_calls") or []:
                idx = int(frag.get("index", 0))
                slot = calls.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                if frag.get("id"):
                    slot["id"] = str(frag["id"])
                fn = frag.get("function") or {}
                if fn.get("name"):
                    slot["name"] += str(fn["name"])
                if fn.get("arguments"):
                    slot["arguments"] += str(fn["arguments"])
        tool_calls: list[ToolCall] = []
        for idx in sorted(calls):
            slot = calls[idx]
            try:
                args = json.loads(slot["arguments"]) if slot["arguments"] else {}
            except ValueError:
                args = {}
            tool_calls.append(
                ToolCall(
                    id=slot["id"] or f"call_{idx}",
                    name=slot["name"],
                    arguments=args if isinstance(args, dict) else {},
                )
            )
        return Message(
            role="assistant", content="".join(content_parts), tool_calls=tool_calls
        )

    def list_models(self) -> list[str]:
        req = urllib.request.Request(
            _url(self.spec, "/models"), headers=_headers(self.spec)
        )
        try:
            with urllib.request.urlopen(req, timeout=self.spec.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(
                f"{self.spec.name} model listing failed: {exc}"
            ) from exc
        return [
            str(item.get("id", "")) for item in data.get("data", []) if item.get("id")
        ]


# Exported alias used by the registry.
Adapter = OpenAICompatProvider
