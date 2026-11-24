"""Local SQLite store for sessions, telemetry events and file hashes."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

DB_PATH = Path.home() / ".quillancode" / "quillancode.db"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    target = Path(path).expanduser() if path else DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(target))
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init(path: str | Path | None = None) -> dict[str, Any]:
    with connect(path) as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY, cwd TEXT, created REAL
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT, event TEXT, data TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_events_event ON events(event);
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY, hash TEXT, updated REAL
            );
        """)
        counts = {
            "sessions": conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0],
            "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
            "files": conn.execute("SELECT COUNT(*) FROM files").fetchone()[0],
        }
    return {"ok": True, "path": str(path or DB_PATH), "tables": counts}


def ingest_telemetry(
    telemetry: str | Path | None = None, path: str | Path | None = None
) -> dict[str, Any]:
    source = (
        Path(telemetry).expanduser()
        if telemetry
        else (Path.home() / ".quillancode" / "telemetry.jsonl")
    )
    init(path)
    added = 0
    if source.is_file():
        with connect(path) as conn:
            for line in source.read_text(
                encoding="utf-8", errors="replace"
            ).splitlines():
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                conn.execute(
                    "INSERT INTO events(ts,event,data) VALUES(?,?,?)",
                    (
                        str(record.get("ts", "")),
                        str(record.get("event", "")),
                        json.dumps(record.get("data") or {}, ensure_ascii=False),
                    ),
                )
                added += 1
    return {"ok": True, "ingested": added, "source": str(source)}


def query(sql: str, path: str | Path | None = None) -> list[dict[str, Any]]:
    if not sql.strip().lower().startswith("select"):
        raise ValueError("only SELECT queries are allowed")
    with connect(path) as conn:
        cursor = conn.execute(sql)
        columns = [c[0] for c in cursor.description or []]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def status(path: str | Path | None = None) -> dict[str, Any]:
    return init(path)
