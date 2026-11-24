"""Deterministic offline provider. Used for tests and zero-key demos."""

from __future__ import annotations

import json
import os
from typing import Any

from ..models import Message, ProviderSpec, ToolCall
from .base import ProviderAdapter

_SCRIPT_ENV = "QUILLANCODE_MOCK_SCRIPT"


class MockProvider:
    """Replays a JSON script of assistant turns, or emits a deterministic answer.

    Script format (JSON list): each entry is either a string (final text) or a
    dict with ``content`` and optional ``tool_calls`` [{name, arguments}].
    """

    name = "mock"

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self._script: list[dict[str, Any]] | None = None
        self._index = 0
        raw = os.environ.get(_SCRIPT_ENV)
        if raw:
            try:
                parsed = json.loads(raw)
                self._script = [self._normalize(item) for item in parsed]
            except (ValueError, TypeError):
                self._script = None

    @staticmethod
    def _normalize(item: Any) -> dict[str, Any]:
        if isinstance(item, str):
            return {"content": item, "tool_calls": []}
        if not isinstance(item, dict):
            return {"content": str(item), "tool_calls": []}
        return {
            "content": str(item.get("content", "")),
            "tool_calls": list(item.get("tool_calls") or []),
        }

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> Message:
        if self._script is not None and self._index < len(self._script):
            step = self._script[self._index]
            self._index += 1
            calls = [
                ToolCall(
                    id=f"mock_call_{self._index}_{i}",
                    name=str(c.get("name", "")),
                    arguments=dict(c.get("arguments") or {}),
                )
                for i, c in enumerate(step["tool_calls"])
            ]
            return Message(role="assistant", content=step["content"], tool_calls=calls)
        user_text = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return Message(
            role="assistant", content=f"[mock:{self.spec.model}] {user_text}".strip()
        )

    def list_models(self) -> list[str]:
        return ["mock"]

    def set_script(self, script: list[dict[str, Any]]) -> None:
        """Programmatic script injection for tests; bypasses environment parsing."""
        self._script = [self._normalize(item) for item in script]
        self._index = 0


# Structural conformance check (Protocol is runtime_checkable for methods only).
assert isinstance(MockProvider.__new__(MockProvider), ProviderAdapter)
