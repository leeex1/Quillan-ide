"""Config-driven plugin hooks and plugin registry (local, no installer network)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from .config import Config
from .hooks import HookBus


def load_plugins(bus: HookBus, config: Config) -> list[str]:
    """Register configured plugin commands as event handlers.

    Plugin entry format:
        [plugin.<name>]
        event = "tool_result"
        command = ["python", "hook.py"]   # or a single string
    """
    loaded: list[str] = []
    for name, spec in (config.get("plugin", {}) or {}).items():
        if not isinstance(spec, dict):
            continue
        event = str(spec.get("event", ""))
        command = spec.get("command")
        if not event or not command:
            continue
        parts = (
            [str(p) for p in command] if isinstance(command, list) else [str(command)]
        )

        def handler(ev: str, data: dict[str, Any], cmd: list[str] = parts) -> None:
            try:
                subprocess.run(
                    [*cmd, json.dumps({"event": ev, "data": data}, ensure_ascii=False)],
                    capture_output=True,
                    timeout=30,
                    check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                return

        bus.on(event, handler)
        loaded.append(f"{name}->{event}")
    return loaded


def add(config: Config, name: str, event: str, command: list[str]) -> dict[str, Any]:
    config.data.setdefault("plugin", {})[name] = {"event": event, "command": command}
    return config.data["plugin"][name]


def remove(config: Config, name: str) -> bool:
    return config.data.setdefault("plugin", {}).pop(name, None) is not None


def listing(config: Config) -> list[dict[str, Any]]:
    return [
        {
            "name": str(name),
            "event": str(spec.get("event", "")),
            "command": spec.get("command", []),
        }
        for name, spec in (config.get("plugin", {}) or {}).items()
        if isinstance(spec, dict)
    ]
