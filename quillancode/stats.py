"""Local token/cost-style telemetry aggregation (opencode `stats` equivalent)."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class UsageStats:
    events: dict[str, int] = field(default_factory=dict)
    tool_calls: dict[str, int] = field(default_factory=dict)
    tool_failures: int = 0
    turns: int = 0
    estimated_input_tokens: int = 0
    estimated_output_tokens: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "turns": self.turns,
            "events": dict(sorted(self.events.items())),
            "tool_calls": dict(sorted(self.tool_calls.items())),
            "tool_failures": self.tool_failures,
            "estimated_input_tokens": self.estimated_input_tokens,
            "estimated_output_tokens": self.estimated_output_tokens,
            "estimated_total_tokens": self.estimated_input_tokens
            + self.estimated_output_tokens,
        }


def collect(path: str | Path | None = None) -> UsageStats:
    target = (
        Path(path).expanduser()
        if path
        else (Path.home() / ".quillancode" / "telemetry.jsonl")
    )
    stats = UsageStats()
    if not target.is_file():
        return stats
    counts: Counter[str] = Counter()
    tools: Counter[str] = Counter()
    for line in target.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue
        event = str(record.get("event", ""))
        data = record.get("data") or {}
        counts[event] += 1
        if event == "turn_start":
            stats.turns += 1
            stats.estimated_input_tokens += int(data.get("input_chars", 0)) // 4
        elif event == "assistant_message":
            stats.estimated_output_tokens += len(str(data.get("content", ""))) // 4
        elif event == "tool_result":
            if not data.get("ok"):
                stats.tool_failures += 1
            else:
                tools[str(data.get("name", "unknown"))] += 1
    stats.events = dict(counts)
    stats.tool_calls = dict(tools)
    return stats
