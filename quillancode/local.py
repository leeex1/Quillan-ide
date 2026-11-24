"""Local model management (Ollama) for offline-first operation."""

from __future__ import annotations

import json
import shutil
import subprocess
import urllib.error
import urllib.request
from typing import Any


def ollama_binary() -> str:
    return shutil.which("ollama") or (
        r"C:\Users\Admin\AppData\Local\Programs\Ollama\ollama.exe"
    )


def status() -> dict[str, Any]:
    installed = (
        bool(ollama_binary()) and __import__("pathlib").Path(ollama_binary()).is_file()
    )
    models: list[str] = []
    running = False
    try:
        with urllib.request.urlopen(
            "http://localhost:11434/api/tags", timeout=3
        ) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        running = True
        models = [str(m.get("name", "")) for m in data.get("models", [])]
    except (urllib.error.URLError, OSError, ValueError, urllib.error.HTTPError):
        pass
    return {
        "installed": installed,
        "binary": ollama_binary() if installed else "",
        "server_running": running,
        "models": models,
        "local_ready": running and bool(models),
    }


def models() -> list[str]:
    return list(status()["models"])


def pull(model: str) -> dict[str, Any]:
    binary = ollama_binary()
    if not binary or not __import__("pathlib").Path(binary).is_file():
        return {"ok": False, "error": "ollama binary not found"}
    try:
        proc = subprocess.run(
            [binary, "pull", model],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "model": model,
        "output": (proc.stdout + proc.stderr)[-2000:],
    }
