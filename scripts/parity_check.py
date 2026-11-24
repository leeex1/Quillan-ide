#!/usr/bin/env python3
"""Executable feature-by-feature parity checklist for quillancode.

Each check invokes the installed CLI and records a PASS/FAIL with an evidence
snippet. Run: python scripts/parity_check.py
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = Path(tempfile.mkdtemp(prefix="qc-parity-"))


@dataclass
class Check:
    name: str
    args: list[str]
    expect: str
    live: bool = False


CHECKS: list[Check] = [
    Check("help/subcommands", ["--help"], "council"),
    Check("version", ["--version"], "quillancode 1.0.0"),
    Check("doctor", ["doctor"], '"council_seats"'),
    Check("tools", ["tools"], "git_status"),
    Check("agents", ["agents", "list"], "c1-astra"),
    Check("skills", ["skills", "list"], ""),
    Check("commands", ["commands", "list"], "audit"),
    Check("seats", ["seats"], "C34"),
    Check("models", ["models", "--json"], '"models"'),
    Check("mcp", ["mcp", "list"], ""),
    Check("adapters", ["adapters", "list"], "opencode"),
    Check("config show", ["config", "show"], '"config"'),
    Check(
        "config import (secret-safe)",
        ["config", "import", "--from", "opencode"],
        "redacted_secrets",
    ),
    Check("session list", ["session", "list"], ""),
    Check("council", ["council", "which path?", "--agents", "2"], "confidence="),
    Check("run", ["run", "hello"], "[mock:mock]"),
    Check("run --json", ["run", "hello", "--json"], '"answer"'),
    Check("stats", ["stats", "--json"], '"estimated_total_tokens"'),
    Check("free tiers", ["free", "list"], "opencode-account"),
    Check("auth", ["auth", "list"], "["),
    Check("plugins", ["plugin", "list"], "["),
    Check("plugin catalog", ["plugin", "search", "audit"], "audit-trail"),
    Check("completion", ["completion", "powershell"], "Register-ArgumentCompleter"),
    Check("serve", ["serve", "--help"], "--port"),
    Check("acp", ["acp", "--help"], ""),
    Check("lsp", ["lsp", "servers"], "{"),
    Check("github", ["github", "status"], '"branch"'),
    Check("git workflow", ["--cwd", str(WORK), "github", "workflow"], '"ok": true'),
    Check("db status", ["db", "status"], '"tables"'),
    Check("diff", ["diff"], ""),
    Check("local runtime", ["local", "status"], "local_ready"),
    Check("opencode command matrix", ["matrix"], "gaps=0"),
    Check("debug runtime", ["debug"], '"executable"'),
    Check("upgrade check", ["upgrade", "--check"], '"up_to_date"'),
    Check("uninstall plan", ["uninstall", "--dry-run"], '"dry_run": true'),
    Check("opencode live model comparison", ["compare"], '"ok": true'),
    Check("opencode side-by-side matrix", ["sbs"], "mismatched=0"),
    Check("BYO key/model smoke", ["byo"], '"ok": true'),
    Check("BYO login guide", ["guide", "deepseek"], "DEEPSEEK_API_KEY"),
    Check("dsh runtime probe", ["external", "dsh"], '"ok": true'),
    Check("qwen runtime probe", ["external", "qwen"], '"ok": true'),
    Check("agentic IDE backend", ["ide", "selftest"], "IDE_SELFTEST_OK"),
    Check("artifact/tensor inspector", ["artifact", "README.md"], "kind="),
    Check("Electron desktop shell", ["desktop", "check"], "DESKTOP_CHECK_OK"),
    Check("Electron IDE UI (live CDP)", ["desktop", "ui"], '"ok": true'),
    Check("IDE unsaved tab buffers", ["ide", "buffers"], '"ok": true'),
    Check("native C++ core", ["native", "info"], '"enabled": true'),
    Check("native file I/O selftest", ["native", "selftest"], "NATIVE_SELFTEST_OK"),
    Check(
        "native benchmark",
        ["--cwd", str(ROOT), "native", "bench", "--rounds", "1"],
        "ms=",
    ),
    Check("extensions", ["extensions", "list"], "example_extension"),
    Check("profiles", ["profile", "list"], "default"),
    Check("schedule", ["schedule", "list"], "["),
    Check("review", ["review", "list"], "["),
    Check(
        "plug any model",
        [
            "plug",
            "parity-model",
            "--base-url",
            "https://example.invalid/v1",
            "--model",
            "vendor/model",
        ],
        "parity-model",
    ),
    Check(
        "live OpenCode-account route",
        ["-p", "opencode-account", "run", "Reply with exactly: QC_PARITY_OK"],
        "QC_PARITY_OK",
        live=True,
    ),
]


def main() -> int:
    failures: list[str] = []
    print(f"{'CAPABILITY':<34} {'RESULT':<6} EVIDENCE")
    print("-" * 100)
    for check in CHECKS:
        try:
            proc = subprocess.run(
                [sys.executable, "-m", "quillancode", *check.args],
                cwd=str(ROOT),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=180,
            )
        except subprocess.TimeoutExpired:
            print(f"{check.name:<34} {'FAIL':<6} timeout")
            failures.append(check.name)
            continue
        combined = (proc.stdout + proc.stderr).strip()
        ok = proc.returncode == 0 and (not check.expect or check.expect in combined)
        first = next(
            (line.strip() for line in combined.splitlines() if line.strip()), ""
        )
        print(f"{check.name:<34} {'PASS' if ok else 'FAIL':<6} {first[:58]}")
        if not ok:
            failures.append(
                f"{check.name} (exit={proc.returncode}, expected={check.expect!r})"
            )
    print("-" * 100)
    print(
        f"checks={len(CHECKS)} passed={len(CHECKS) - len(failures)} failed={len(failures)}"
    )
    if failures:
        for failure in failures:
            print("FAILED:", failure)
        return 1
    print("PARITY_CHECKLIST_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
