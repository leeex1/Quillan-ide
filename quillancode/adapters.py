"""Bridge layer: detect and delegate to installed code-assistant CLIs.

Their npm shim directory is intentionally not assumed to be on PATH; absolute
paths are probed so quillancode works in shells where PATH differs.
"""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

NPM_BIN = (
    Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "npm"
)

# name -> (shim filename, prompt flags)
CLI_SPECS: dict[str, tuple[str, list[str]]] = {
    "opencode": ("opencode.cmd", ["run"]),
    "claude": ("claude.cmd", ["-p"]),
    "gemini": ("gemini.cmd", ["-p"]),
    "qwen": ("qwen.cmd", ["-p"]),
    "copilot": ("copilot.cmd", ["-p"]),
    "kilo": ("kilo.cmd", ["run"]),
    "kilocode": ("kilocode.cmd", ["run"]),
    "jules": ("jules.cmd", ["-p"]),
}


@dataclass
class DetectedCLI:
    name: str
    path: Path
    prompt_flags: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": str(self.path),
            "prompt_flags": self.prompt_flags,
        }


def detect(*, npm_bin: Path | None = None) -> list[DetectedCLI]:
    root = npm_bin or NPM_BIN
    found: list[DetectedCLI] = []
    for name, (shim, flags) in CLI_SPECS.items():
        path = root / shim
        if path.is_file():
            found.append(DetectedCLI(name=name, path=path, prompt_flags=flags))
        else:
            which = _which(shim)
            if which is not None:
                found.append(DetectedCLI(name=name, path=which, prompt_flags=flags))
    return sorted(found, key=lambda c: c.name)


def _which(name: str) -> Path | None:
    for part in os.environ.get("PATH", "").split(os.pathsep):
        if not part:
            continue
        candidate = Path(part) / name
        if candidate.is_file():
            return candidate
    return None


def get(name: str, *, npm_bin: Path | None = None) -> DetectedCLI:
    for cli in detect(npm_bin=npm_bin):
        if cli.name == name:
            return cli
    raise KeyError(f"CLI not detected: {name}")


def delegate(
    cli: DetectedCLI,
    prompt: str,
    *,
    cwd: str | None = None,
    timeout: float = 300.0,
    extra_args: list[str] | None = None,
) -> dict[str, Any]:
    """Run a detected CLI in prompt mode and return structured output."""
    command = [str(cli.path), *cli.prompt_flags, prompt, *(extra_args or [])]
    try:
        proc = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return {"ok": False, "cli": cli.name, "error": f"timeout after {timeout}s"}
    except OSError as exc:
        return {"ok": False, "cli": cli.name, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "cli": cli.name,
        "returncode": proc.returncode,
        "stdout": proc.stdout[-50_000:],
        "stderr": proc.stderr[-10_000:],
    }


def report(*, npm_bin: Path | None = None) -> str:
    found = detect(npm_bin=npm_bin)
    lines = [f"detected {len(found)} assistant CLIs:"]
    lines.extend(f"  {c.name:<10} {c.path}" for c in found)
    return "\n".join(lines)
