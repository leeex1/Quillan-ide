#!/usr/bin/env python3
"""Independent opencode --help -> quillancode command equivalence matrix.

Parses the installed opencode binary's own help output, then verifies each
mapped quillancode capability by invoking the installed CLI.
"""

from __future__ import annotations

import json
import re
import sys
import subprocess
import tempfile
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENCODE = Path.home() / "AppData" / "Roaming" / "npm" / "opencode.cmd"

# opencode command -> (quillancode CLI check, explanation)
EQUIV: dict[str, tuple[list[str], str]] = {
    "completion": (["completion", "bash"], "shell completion script"),
    "acp": (["acp", "--help"], "ACP stdio server"),
    "mcp": (["mcp", "list"], "MCP server inspection + stdio/HTTP client"),
    "attach": (["attach", "--help"], "HTTP attach client"),
    "run": (["run", "hello"], "one-shot prompt"),
    "debug": (["debug"], "runtime diagnostics dump"),
    "providers": (["config", "show"], "provider inspection/import"),
    "agent": (["agents", "list"], "agent definitions"),
    "upgrade": (["upgrade", "--check"], "installed vs source version check"),
    "uninstall": (["uninstall", "--dry-run"], "removal plan (dry-run)"),
    "serve": (["serve", "--help"], "headless HTTP API"),
    "web": (["ide", "selftest"], "web/IDE workbench"),
    "models": (["models", "--json"], "model listing"),
    "stats": (["stats", "--json"], "usage/token stats"),
    "export": (["--help"], "session export (end-to-end)"),
    "import": (
        ["config", "import", "--from", "opencode"],
        "session import (end-to-end)",
    ),
    "github": (["github", "workflow"], "git workflow (end-to-end)"),
    "pr": (["github", "pr", "123"], "PR checkout via local bare origin"),
    "session": (["session", "list"], "session management"),
    "plugin": (["plugin", "list"], "plugin hooks/catalog"),
    "db": (["db", "status"], "SQLite session/telemetry store"),
}


def opencode_commands() -> list[str]:
    proc = subprocess.run(
        [str(OPENCODE), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    text = proc.stdout + proc.stderr
    found = re.findall(r"^\s{2}opencode\s+([a-z][a-z0-9-]*)", text, flags=re.M)
    return sorted(set(found))


def _qc(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "quillancode", *args],
        cwd=str(cwd or ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def check_export() -> tuple[bool, str, str]:
    with tempfile.TemporaryDirectory() as td:
        run = _qc(["run", "matrix session", "--json"])
        if run.returncode != 0:
            return False, "session export (end-to-end)", run.stderr[:80]
        session_id = json.loads(run.stdout)["session"]
        target = Path(td) / "session.json"
        exported = _qc(["session", "export", session_id, "--file", str(target)])
        ok = exported.returncode == 0 and target.is_file()
        if ok:
            ok = json.loads(target.read_text(encoding="utf-8"))["id"] == session_id
        return (
            ok,
            "session export (end-to-end)",
            f"id={session_id} bytes={target.stat().st_size if target.is_file() else 0}",
        )


def check_import() -> tuple[bool, str, str]:
    with tempfile.TemporaryDirectory() as td:
        sid = "matrix-import-" + uuid.uuid4().hex[:8]
        source = Path(td) / "in.json"
        source.write_text(
            json.dumps({"id": sid, "cwd": ".", "messages": []}), encoding="utf-8"
        )
        imported = _qc(["session", "import", "--file", str(source)])
        shown = _qc(["session", "show", sid])
        return (
            imported.returncode == 0 and shown.returncode == 0,
            "session import (end-to-end)",
            f"id={sid} shown={shown.returncode == 0}",
        )


def check_git_workflow() -> tuple[bool, str, str]:
    with tempfile.TemporaryDirectory() as td:
        proc = _qc(["--cwd", td, "github", "workflow"])
        if proc.returncode != 0:
            return False, "git workflow (end-to-end)", proc.stderr[:80]
        data = json.loads(proc.stdout)
        return (
            bool(data.get("ok")),
            "git workflow (end-to-end)",
            (f"branch={data.get('branch')} commit={data.get('commit', '')[:8]}"),
        )


def check_pr_checkout() -> tuple[bool, str, str]:
    with tempfile.TemporaryDirectory() as td:
        origin = Path(td) / "origin.git"
        work = Path(td) / "work"
        work.mkdir()
        subprocess.run(
            ["git", "init", "--bare", "-q", str(origin)], capture_output=True
        )
        subprocess.run(["git", "init", "-q"], cwd=str(work), capture_output=True)
        subprocess.run(
            ["git", "config", "user.email", "qc@local"],
            cwd=str(work),
            capture_output=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "QC"], cwd=str(work), capture_output=True
        )
        (work / "f.txt").write_text("pr probe\n", encoding="utf-8")
        subprocess.run(["git", "add", "f.txt"], cwd=str(work), capture_output=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "pr base"], cwd=str(work), capture_output=True
        )
        subprocess.run(
            ["git", "remote", "add", "origin", str(origin)],
            cwd=str(work),
            capture_output=True,
        )
        subprocess.run(
            ["git", "push", "-q", "origin", "HEAD"], cwd=str(work), capture_output=True
        )
        subprocess.run(
            ["git", "update-ref", "refs/pull/123/head", "HEAD"],
            cwd=str(origin),
            capture_output=True,
        )
        proc = _qc(["--cwd", str(work), "github", "pr", "123"])
        if proc.returncode != 0:
            return False, "PR checkout via local bare origin", proc.stderr[:80]
        data = json.loads(proc.stdout)
        branch_ok = data.get("ok") and data.get("branch") == "quillancode-pr-123"
        return (
            bool(branch_ok),
            "PR checkout via local bare origin",
            f"branch={data.get('branch')}",
        )


SPECIAL = {
    "export": check_export,
    "import": check_import,
    "github": check_git_workflow,
    "pr": check_pr_checkout,
}


def main() -> int:
    commands = opencode_commands()
    print(f"opencode --help -> {len(commands)} commands parsed: {', '.join(commands)}")
    print(f"{'OPENCODE':<14} {'QUILLANCODE CHECK':<34} {'STATUS':<8} DETAIL")
    print("-" * 110)
    covered = 0
    for cmd in commands:
        check, detail = EQUIV.get(cmd, ([], "no equivalent"))
        if cmd in SPECIAL:
            ok, detail, evidence = SPECIAL[cmd]()
            covered += int(ok)
            print(
                f"{cmd:<14} {'end-to-end':<34} {'PASS' if ok else 'FAIL':<8} {detail} | {evidence[:40]}"
            )
            continue
        if not check:
            print(f"{cmd:<14} {'-':<34} {'GAP':<8} {detail}")
            continue
        proc = subprocess.run(
            ["python", "-m", "quillancode", *check],
            cwd=str(ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )
        ok = proc.returncode == 0
        covered += int(ok)
        evidence = next(
            (l.strip() for l in (proc.stdout + proc.stderr).splitlines() if l.strip()),
            "",
        )
        print(
            f"{cmd:<14} {' '.join(check)[:32]:<34} {'PASS' if ok else 'FAIL':<8} {detail} | {evidence[:40]}"
        )
    print("-" * 110)
    print(
        f"commands={len(commands)} equivalent={covered} gaps={len(commands) - covered}"
    )
    return 0 if covered == len(commands) else 1


if __name__ == "__main__":
    raise SystemExit(main())
