"""Local JSONL telemetry with secret redaction (opt-in via config)."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .hooks import HookBus

_SECRET = re.compile(
    r"(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+", re.I
)


class Telemetry:
    def __init__(self, path: str | Path | None = None, enabled: bool = True) -> None:
        self.path = (
            Path(path).expanduser()
            if path
            else (Path.home() / ".quillancode" / "telemetry.jsonl")
        )
        self.enabled = enabled

    def attach(self, bus: HookBus) -> None:
        bus.on("*", self.record)

    def record(self, event: str, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        line = json.dumps(
            {
                "ts": datetime.now(timezone.utc).isoformat(),
                "event": event,
                "data": self._redact(data),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    @staticmethod
    def _redact(value: Any) -> Any:
        if isinstance(value, str):
            return _SECRET.sub("<redacted>", value)
        if isinstance(value, dict):
            return {k: Telemetry._redact(v) for k, v in value.items()}
        if isinstance(value, list):
            return [Telemetry._redact(v) for v in value]
        return value
