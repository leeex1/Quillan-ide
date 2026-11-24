"""Minimal GitHub workflow helpers via local git (opencode `pr`/github parity)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any


def git(args: list[str], cwd: str | Path) -> dict[str, Any]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "error": str(exc)}
    return {
        "ok": proc.returncode == 0,
        "stdout": proc.stdout[-50_000:],
        "stderr": proc.stderr[-10_000:],
    }


def status(cwd: str | Path) -> dict[str, Any]:
    branch = git(["branch", "--show-current"], cwd)
    changes = git(["status", "--short"], cwd)
    return {
        "ok": branch["ok"] and changes["ok"],
        "branch": branch.get("stdout", "").strip(),
        "changes": changes.get("stdout", ""),
    }


def pr_checkout(number: int, cwd: str | Path, remote: str = "origin") -> dict[str, Any]:
    branch = f"quillancode-pr-{number}"
    fetch = git(["fetch", remote, f"pull/{number}/head:{branch}"], cwd)
    if not fetch["ok"]:
        return {"ok": False, "error": fetch.get("stderr") or "fetch failed"}
    checkout = git(["checkout", branch], cwd)
    return {
        "ok": checkout["ok"],
        "branch": branch,
        "stdout": checkout.get("stdout", ""),
        "stderr": checkout.get("stderr", ""),
    }


def workflow(cwd: str | Path) -> dict[str, Any]:
    """Self-contained local git workflow: init, commit, branch, status, log."""
    from pathlib import Path

    target = Path(cwd)
    (target / "quillancode_workflow.txt").write_text(
        "workflow probe\n", encoding="utf-8"
    )
    steps = {
        "init": git(["init", "-q"], target)["ok"],
        "email": git(["config", "user.email", "qc@local"], target)["ok"],
        "name": git(["config", "user.name", "quillancode"], target)["ok"],
        "add": git(["add", "quillancode_workflow.txt"], target)["ok"],
        "commit": git(["commit", "-q", "-m", "quillancode workflow"], target)["ok"],
        "branch": git(["checkout", "-q", "-b", "qc/workflow"], target)["ok"],
    }
    info = status(target)
    history = git(["log", "--oneline", "-n", "1"], target)
    result = {
        "ok": all(steps.values()) and info["ok"] and history["ok"],
        "steps": steps,
        "branch": info.get("branch", ""),
        "commit": history.get("stdout", "").strip(),
        "diff": diff(target, staged=False),
    }
    return result


def diff(cwd: str | Path, staged: bool = False) -> str:
    args = ["diff", "--no-color"] + (["--cached"] if staged else [])
    result = git(args, cwd)
    return (
        result.get("stdout", "") if result["ok"] else result.get("error", "diff failed")
    )
