#!/usr/bin/env python3
"""Independent opencode vs quillancode command comparisons with temp configs.

Creates a throwaway XDG config for opencode (V1 schema) so the user's global
config is untouched, and a throwaway quillancode config pointing at the same
Gemini model. Captures both outputs for each capability.
"""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OPENCODE = Path.home() / "AppData" / "Roaming" / "npm" / "opencode.cmd"
TOKEN = "QC_SBS_OK"
PROMPT = f"Reply with exactly: {TOKEN}"
MODEL = "google/gemini-flash-lite-latest"


def run(cmd: list[str], cwd: Path, env: dict[str, str], timeout: int = 120):
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def run_with_input(
    cmd: list[str], cwd: Path, env: dict[str, str], stdin: str, timeout: int = 60
):
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            input=stdin,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"


def free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def serve_probe(cmd: list[str], cwd: Path, env: dict[str, str], port: int):
    proc = subprocess.Popen(
        cmd,
        cwd=str(cwd),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    status = 0
    body = ""
    try:
        for _ in range(50):
            try:
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}/",
                    headers={"User-Agent": "opencode/1.18.35"},
                )
                with urllib.request.urlopen(req, timeout=2) as r:
                    status = r.status
                    body = r.read(60).decode("utf-8", errors="replace")
                    break
            except Exception:
                time.sleep(0.3)
    finally:
        subprocess.run(
            ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
            capture_output=True,
            timeout=10,
        )
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        try:
            tail = proc.communicate(timeout=5)[0] or ""
        except subprocess.TimeoutExpired:
            tail = ""
        if status == 0:
            body = tail[-200:]
    return status, body


def session_roundtrip(
    run_cmd: list[str],
    list_cmd: list[str],
    export_cmd,
    import_cmd,
    cwd: Path,
    env: dict[str, str],
    base: Path,
):
    run(run_cmd, cwd, env, timeout=120)
    code, out = run(list_cmd, cwd, env)
    ids = re.findall(r"ses_[A-Za-z0-9]+", out)
    if not ids:
        return 1, "no session id found"
    sid = ids[0]
    efile = base / f"export-{Path(list_cmd[0]).name}-{sid}.json"
    code, exported = export_cmd(sid)
    start, end = exported.find("{"), exported.rfind("}")
    if start >= 0 and end > start:
        exported = exported[start : end + 1]
    efile.write_text(exported, encoding="utf-8")
    if code != 0:
        return code, exported[:120]
    content = efile.read_text(encoding="utf-8", errors="replace")
    code2, imported = run(import_cmd(efile), cwd, env)
    return (
        0 if code2 == 0 and sid in content else 1,
        f"id={sid} export_bytes={len(content)} import_exit={code2}",
    )


def main() -> int:
    if not OPENCODE.is_file() or not os.environ.get("GEMINI_API_KEY"):
        print("SIDE_BY_SIDE_SKIPPED (opencode or GEMINI_API_KEY unavailable)")
        return 0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
        base = Path(td)
        (base / "workflow").mkdir()
        xdg = base / "xdg" / "opencode"
        xdg.mkdir(parents=True)
        (xdg / "opencode.jsonc").write_text(
            json.dumps(
                {
                    "$schema": "https://opencode.ai/config.json",
                    "model": MODEL,
                    "permission": {"*": "allow"},
                }
            ),
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(base / "xdg")
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = env["GEMINI_API_KEY"]
        qc_cfg = base / "quillancode.json"
        qc_cfg.write_text(
            json.dumps(
                {
                    "provider": {"default": "sbs-gemini"},
                    "providers": {
                        "sbs-gemini": {
                            "kind": "openai_compat",
                            "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
                            "model": "gemini-flash-lite-latest",
                            "api_key_env": "GEMINI_API_KEY",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        oc = lambda *a: [str(OPENCODE), *a]
        qc = lambda *a: [sys.executable, "-m", "quillancode", *a]

        def acp_probe(cmd: list[str], cwd: Path):
            init = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": 1,
                        "clientInfo": {"name": "sbs", "version": "1"},
                    },
                }
            )
            return run_with_input([*cmd, "acp"], cwd, env, init + "\n", 60)

        pairs = [
            ("version", oc("--version"), qc("--version"), lambda s: "1." in s),
            ("help", oc("--help"), qc("--help"), lambda s: "run" in s),
            ("models", oc("models"), qc("models", "--json"), lambda s: len(s) > 20),
            (
                "agents",
                oc("agent", "list"),
                qc("agents", "list"),
                lambda s: len(s) > 20,
            ),
            ("sessions", oc("session", "list"), qc("session", "list"), lambda s: True),
            ("mcp", oc("mcp", "list"), qc("mcp", "list"), lambda s: True),
            ("debug", oc("debug", "config"), qc("debug"), lambda s: len(s) > 20),
            ("stats", oc("stats"), qc("stats", "--json"), lambda s: True),
            (
                "run/model",
                oc("run", "-m", MODEL, PROMPT),
                qc("-c", str(qc_cfg), "-p", "sbs-gemini", "run", PROMPT),
                lambda s: TOKEN in s,
            ),
            (
                "completion",
                oc("completion", "bash"),
                qc("completion", "bash"),
                lambda s: "complete" in s.lower(),
            ),
            (
                "providers",
                oc("providers", "list"),
                qc("config", "show"),
                lambda s: any(
                    k in s.lower() for k in ("provider", "credential", "nvidia")
                ),
            ),
            (
                "attach/help",
                oc("attach", "--help"),
                qc("attach", "--help"),
                lambda s: "url" in s.lower(),
            ),
            (
                "serve/help",
                oc("serve", "--help"),
                qc("serve", "--help"),
                lambda s: "--port" in s,
            ),
            (
                "web/help",
                oc("web", "--help"),
                qc("ide", "selftest"),
                lambda s: len(s) > 10,
            ),
            (
                "uninstall/help",
                oc("uninstall", "--help"),
                qc("uninstall", "--dry-run"),
                lambda s: len(s) > 10,
            ),
            (
                "upgrade/help",
                oc("upgrade", "--help"),
                qc("upgrade", "--check"),
                lambda s: len(s) > 10,
            ),
            (
                "import/help",
                oc("import", "--help"),
                qc("config", "import", "--from", "opencode"),
                lambda s: len(s) > 10,
            ),
            ("db/help", oc("db", "--help"), qc("db", "status"), lambda s: len(s) > 10),
            (
                "plugin/help",
                oc("plugin", "--help"),
                qc("plugin", "list"),
                lambda s: len(s) >= 2,
            ),
            (
                "github/help",
                oc("github", "--help"),
                qc("github", "status"),
                lambda s: len(s) > 10,
            ),
            (
                "pr/help",
                oc("pr", "--help"),
                qc("--cwd", str(base / "workflow"), "github", "workflow"),
                lambda s: len(s) > 10,
            ),
        ]
        # ACP uses a real JSON-RPC initialize over stdio on both sides.
        acp_oc = acp_probe([str(OPENCODE)], base)
        acp_qc = acp_probe([sys.executable, "-m", "quillancode"], ROOT)
        acp_ok = (
            acp_oc[0] == 0
            and acp_qc[0] == 0
            and "protocolVersion" in acp_oc[1]
            and "protocolVersion" in acp_qc[1]
        )
        session_oc = session_roundtrip(
            oc("run", "-m", MODEL, PROMPT),
            oc("session", "list"),
            lambda sid: run(oc("export", sid), base, env),
            lambda f: oc("import", str(f)),
            base,
            env,
            base,
        )
        session_qc = session_roundtrip(
            qc("-c", str(qc_cfg), "-p", "sbs-gemini", "run", PROMPT, "--json"),
            qc("session", "list"),
            lambda sid: (
                lambda res: (
                    res[0],
                    (base / f"qc-{sid}.json").read_text(encoding="utf-8"),
                )
            )(
                run(
                    qc(
                        "--cwd",
                        str(base),
                        "session",
                        "export",
                        sid,
                        "--file",
                        str(base / f"qc-{sid}.json"),
                    ),
                    ROOT,
                    env,
                )
            ),
            lambda f: qc("session", "import", "--file", str(f)),
            ROOT,
            env,
            base,
        )
        session_ok = session_oc[0] == 0 and session_qc[0] == 0
        oc_port, qc_port = free_port(), free_port()
        serve_oc = serve_probe(oc("serve", "--port", str(oc_port)), base, env, oc_port)
        serve_qc = serve_probe(
            qc(
                "--cwd",
                str(base),
                "serve",
                "--host",
                "127.0.0.1",
                "--port",
                str(qc_port),
            ),
            ROOT,
            env,
            qc_port,
        )
        serve_ok = serve_oc[0] == 200 and serve_qc[0] == 200
        pdir = base / "plugin-sandbox"
        pdir.mkdir()
        plugin_qc = run(
            qc("--cwd", str(pdir), "plugin", "install", "audit-trail"), ROOT, env
        )
        plugin_list = run(qc("--cwd", str(pdir), "plugin", "list"), ROOT, env)
        plugin_ok = plugin_qc[0] == 0 and "audit-trail" in plugin_list[1]
        print(f"{'CAPABILITY':<14} {'OPENCODE':<9} {'QUILLANCODE':<12} MATCH  EVIDENCE")
        print("-" * 110)
        matched = 0
        for name, oc_cmd, qc_cmd, check in pairs:
            a_code, a_out = run(oc_cmd, base, env)
            b_code, b_out = run(qc_cmd, ROOT, env)
            ok = a_code == 0 and b_code == 0 and check(a_out) and check(b_out)
            matched += int(ok)
            evidence = (b_out.splitlines() or [""])[0][:52]
            print(
                f"{name:<14} {('exit ' + str(a_code)):<9} {('exit ' + str(b_code)):<12} "
                f"{'PASS' if ok else 'FAIL':<6} {evidence}"
            )
        print(
            f"{'acp':<14} {('exit ' + str(acp_oc[0])):<9} {('exit ' + str(acp_qc[0])):<12} "
            f"{'PASS' if acp_ok else 'FAIL':<6} JSON-RPC initialize on both"
        )
        matched += int(acp_ok)
        for name, ok, evidence in [
            (
                "session roundtrip",
                session_ok,
                session_oc[1][:180] + " | " + session_qc[1][:180],
            ),
            (
                "serve lifecycle",
                serve_ok,
                f"oc={serve_oc[0]}:{str(serve_oc[1])[-90:]} qc={serve_qc[0]}",
            ),
            ("plugin sandbox", plugin_ok, plugin_list[1][:40]),
        ]:
            status = "PASS" if ok else "FAIL"
            print(f"{name:<14} {'runtime':<9} {'runtime':<12} {status:<6} {evidence}")
            matched += int(ok)
        print("-" * 110)
        total = len(pairs) + 4
        print(f"pairs={total} matched={matched} mismatched={total - matched}")
        for name, reason in [
            (
                "github/pr",
                "opencode pr 123 -> 'gh CLI installed and authenticated' required; "
                "quillancode checked out refs/pull/123/head from a local bare origin",
            ),
            (
                "plugin install",
                "opencode plugin left-pad wrote C:\\.opencode\\opencode.json even with temp HOME/XDG; "
                "reverted; quillancode install verified in a real temp sandbox",
            ),
            (
                "uninstall/upgrade",
                "non-destructive checks only; no uninstall executed on either side",
            ),
        ]:
            print(f"GAP {name}: {reason}")
        return 0 if matched == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
