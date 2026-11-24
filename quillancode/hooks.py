"""Lightweight event bus for pre/post tool hooks and telemetry."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[[str, dict[str, Any]], None]


class HookBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self.history: list[tuple[str, dict[str, Any]]] = []

    def on(self, event: str, handler: Handler) -> None:
        self._handlers[event].append(handler)

    def emit(self, event: str, data: dict[str, Any] | None = None) -> None:
        payload = dict(data or {})
        self.history.append((event, payload))
        for handler in self._handlers.get(event, []):
            handler(event, payload)
        for handler in self._handlers.get("*", []):
            handler(event, payload)
