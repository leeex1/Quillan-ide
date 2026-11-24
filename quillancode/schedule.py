"""Local scheduled prompts (offline replacement for hosted scheduling UI)."""

from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STORE = Path.home() / ".quillancode" / "schedule.json"


def _read() -> list[dict[str, Any]]:
    if not STORE.is_file():
        return []
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    return data if isinstance(data, list) else []


def _write(items: list[dict[str, Any]]) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(
        json.dumps(items, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def add(prompt: str, every: int | None = None, at: str | None = None) -> dict[str, Any]:
    if not every and not at:
        raise ValueError("provide --every <seconds> or --at <ISO timestamp>")
    now = time.time()
    if at:
        due_at = datetime.fromisoformat(at).replace(tzinfo=timezone.utc).timestamp()
    else:
        due_at = now + int(every or 60)
    item = {
        "id": "sch_" + uuid.uuid4().hex[:8],
        "prompt": prompt,
        "every": every,
        "next_due": due_at,
    }
    items = _read() + [item]
    _write(items)
    return item


def listing() -> list[dict[str, Any]]:
    return _read()


def remove(item_id: str) -> bool:
    items = _read()
    kept = [i for i in items if i.get("id") != item_id]
    if len(kept) == len(items):
        return False
    _write(kept)
    return True


def due() -> list[dict[str, Any]]:
    now = time.time()
    ready: list[dict[str, Any]] = []
    updated: list[dict[str, Any]] = []
    for item in _read():
        if float(item.get("next_due", 0)) <= now:
            ready.append(item)
            if item.get("every"):
                item["next_due"] = now + int(item["every"])
            else:
                continue
        updated.append(item)
    _write(updated)
    return ready
