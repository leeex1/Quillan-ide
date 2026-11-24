"""Local plugin catalog with search/install (marketplace surface, no network)."""

from __future__ import annotations

from typing import Any

from .config import Config
from .plugin import add

# Each entry maps to a config-driven hook command using quillancode itself,
# so installs work on any machine with Python and no external downloads.
CATALOG: dict[str, dict[str, Any]] = {
    "audit-trail": {
        "description": "Append every tool result to a local JSONL audit file",
        "event": "tool_result",
        "command": [
            "python",
            "-c",
            "import sys,json,pathlib; p=pathlib.Path('.quillancode/plugin-audit.jsonl'); "
            "p.parent.mkdir(exist_ok=True); "
            "d=json.loads(sys.argv[1]); "
            "p.open('a',encoding='utf-8').write(json.dumps(d)+'\\n')",
        ],
        "tags": ["audit", "telemetry"],
    },
    "trace-logger": {
        "description": "Log assistant turns to a local trace file",
        "event": "assistant_message",
        "command": [
            "python",
            "-c",
            "import sys,json,pathlib; p=pathlib.Path('.quillancode/plugin-trace.jsonl'); "
            "p.parent.mkdir(exist_ok=True); "
            "d=json.loads(sys.argv[1]); "
            "p.open('a',encoding='utf-8').write(json.dumps(d)+'\\n')",
        ],
        "tags": ["trace", "debug"],
    },
}


def search(query: str = "") -> list[dict[str, Any]]:
    q = query.lower().strip()
    out: list[dict[str, Any]] = []
    for name, spec in sorted(CATALOG.items()):
        haystack = " ".join([name, spec["description"], *spec.get("tags", [])]).lower()
        if not q or q in haystack:
            out.append(
                {
                    "name": name,
                    "description": spec["description"],
                    "event": spec["event"],
                    "tags": spec["tags"],
                }
            )
    return out


def install(config: Config, name: str) -> dict[str, Any]:
    spec = CATALOG.get(name)
    if spec is None:
        raise KeyError(f"plugin not found in catalog: {name}")
    return add(config, name, spec["event"], list(spec["command"]))
