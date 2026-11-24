"""Formatter execution and watcher-ignore helpers (opencode-compatible config)."""

from __future__ import annotations

import fnmatch
import shlex
import subprocess
from pathlib import Path
from typing import Any

from .config import Config


def is_ignored(rel_path: str, patterns: list[str] | None) -> bool:
    """Match opencode-style watcher.ignore glob patterns against a workspace-relative path."""
    for raw in patterns or []:
        pattern = str(raw)
        candidates = (rel_path, Path(rel_path).name, rel_path.replace("\\", "/"))
        for candidate in candidates:
            if fnmatch.fnmatch(candidate, pattern) or fnmatch.fnmatch(
                candidate, pattern.strip("/")
            ):
                return True
            if pattern.startswith("**/") and fnmatch.fnmatch(candidate, pattern[3:]):
                return True
    return False


def format_file(config: Config, path: Path) -> dict[str, Any]:
    """Run the configured formatter for a file's extension, if any."""
    suffix = path.suffix.lower()
    for name, spec in (config.get("formatter", {}) or {}).items():
        if not isinstance(spec, dict):
            continue
        extensions = [str(e).lower() for e in spec.get("extensions", [])]
        if suffix not in extensions:
            continue
        command = spec.get("command")
        if isinstance(command, str):
            parts = shlex.split(command)
        elif isinstance(command, list):
            parts = [str(p) for p in command]
        else:
            continue
        parts = [str(path) if part == "$FILE" else part for part in parts]
        if not parts:
            continue
        try:
            proc = subprocess.run(
                parts,
                cwd=str(path.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"formatter": name, "ok": False, "error": str(exc)}
        return {
            "formatter": name,
            "ok": proc.returncode == 0,
            "output": (proc.stdout + proc.stderr)[-4000:],
        }
    return {"formatter": None, "ok": True, "output": ""}
