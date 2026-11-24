"""Anthropic Messages API adapter (stdlib-only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from ..models import Message, ProviderSpec, ToolCall
from .base import ProviderError


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec

    def _headers(self) -> dict[str, str]:
        key = os.environ.get(self.spec.api_key_env, "") if self.spec.api_key_env else ""
        headers = {
            "Content-Type": "application/json",
            "x-api-key": key,
            "anthropic-version": "2023-06-01",
        }
        headers.update(self.spec.extra_headers)
        return headers

    @staticmethod
    def _split(messages: list[Message]) -> tuple[str, list[dict[str, Any]]]:
        system_parts: list[str] = []
        wire: list[dict[str, Any]] = []
        for msg in messages:
            if msg.role == "system":
                system_parts.append(msg.content)
                continue
            if msg.tool_result is not None:
                wire.append(
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "tool_result",
                                "tool_use_id": msg.tool_result.call_id,
                                "content": (
                                    msg.tool_result.output
                                    if msg.tool_result.ok
                                    else f"ERROR: {msg.tool_result.error}"
                                ),
                            }
                        ],
                    }
                )
                continue
            blocks: list[dict[str, Any]] = []
            if msg.content:
                blocks.append({"type": "text", "text": msg.content})
            for call in msg.tool_calls:
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call.id,
                        "name": call.name,
                        "input": call.arguments,
                    }
                )
            wire.append(
                {
                    "role": msg.role if msg.role in ("user", "assistant") else "user",
                    "content": blocks or [{"type": "text", "text": ""}],
                }
            )
        return "\n\n".join(system_parts), wire

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> Message:
        system, wire = self._split(messages)
        payload: dict[str, Any] = {
            "model": self.spec.model,
            "messages": wire,
            "max_tokens": self.spec.max_tokens,
            "temperature": self.spec.temperature,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "input_schema": t.get(
                        "input_schema", {"type": "object", "properties": {}}
                    ),
                }
                for t in tools
            ]
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            self.spec.base_url.rstrip("/") + "/messages",
            data=body,
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.spec.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            raise ProviderError(f"anthropic HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"anthropic connection failed: {exc}") from exc
        content = "".join(
            str(block.get("text", ""))
            for block in data.get("content", [])
            if block.get("type") == "text"
        )
        calls = [
            ToolCall(
                id=str(block.get("id", f"call_{i}")),
                name=str(block.get("name", "")),
                arguments=dict(block.get("input") or {}),
            )
            for i, block in enumerate(data.get("content", []))
            if block.get("type") == "tool_use"
        ]
        return Message(role="assistant", content=content, tool_calls=calls)

    def list_models(self) -> list[str]:
        req = urllib.request.Request(
            self.spec.base_url.rstrip("/") + "/models", headers=self._headers()
        )
        try:
            with urllib.request.urlopen(req, timeout=self.spec.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", errors="replace"))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"anthropic model listing failed: {exc}") from exc
        return [str(m.get("id", "")) for m in data.get("data", []) if m.get("id")]


Adapter = AnthropicProvider
