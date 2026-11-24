"""Local probes for externally installed assistant runtimes (dsh, qwen)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def _dsh_binary() -> Path | None:
    candidates = [
        Path.home() / "node_modules" / ".bin" / "dsh.cmd",
        Path.home() / "node_modules" / ".bin" / "dsh",
    ]
    for path in candidates:
        if path.is_file():
            return path
    found = shutil.which("dsh")
    return Path(found) if found else None


def check_dsh() -> dict[str, Any]:
    binary = _dsh_binary()
    if binary is None:
        return {"ok": False, "error": "dsh not installed"}
    help_proc = subprocess.run(
        [str(binary), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    home = Path(tempfile.gettempdir()) / "qc-dsh-home"
    home.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["DSH_HOME"] = str(home)
    init = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientInfo": {"name": "quillancode", "version": "1.0.0"},
            },
        }
    )
    acp = subprocess.run(
        [str(binary), "--profile", "acp"],
        input=init + "\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        env=env,
        cwd=str(home),
    )
    combined = help_proc.stdout + help_proc.stderr + acp.stdout
    return {
        "ok": help_proc.returncode == 0 and "deepseek-harness-acp" in combined,
        "binary": str(binary),
        "help": help_proc.returncode == 0,
        "acp": "deepseek-harness-acp" in combined,
        "evidence": next((l for l in acp.stdout.splitlines() if "agentInfo" in l), "")[
            :300
        ],
    }


def byo_smoke(prompt: str = "Reply with exactly: QC_BYO_OK") -> dict[str, Any]:
    """Prove a user-supplied key/model works against an OpenAI-compatible endpoint."""
    import json as _json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    token = "QC_BYO_OK"

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            return

        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            auth = self.headers.get("Authorization", "")
            answer = token if auth == "Bearer QC_MOCK_USER_KEY" else "BAD_KEY"
            payload = _json.dumps(
                {"choices": [{"message": {"role": "assistant", "content": answer}}]}
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "quillancode.json"
            cfg.write_text(
                _json.dumps(
                    {
                        "provider": {"default": "byo-mock"},
                        "providers": {
                            "byo-mock": {
                                "kind": "openai_compat",
                                "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                                "model": "user-chosen-model",
                                "api_key_env": "QC_BYO_KEY",
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            env = os.environ.copy()
            env["QC_BYO_KEY"] = "QC_MOCK_USER_KEY"
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "quillancode",
                    "-c",
                    str(cfg),
                    "-p",
                    "byo-mock",
                    "run",
                    prompt,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                env=env,
                cwd=str(Path(__file__).parent.parent),
            )
    finally:
        server.shutdown()
        server.server_close()
    return {
        "ok": token in proc.stdout,
        "response": (proc.stdout + proc.stderr).strip()[-200:],
        "credential": "mocked QC_MOCK_USER_KEY (never printed by app)",
    }


def compare_live(
    prompt: str = "Reply with exactly: QC_LIVE_COMPARE_OK",
) -> dict[str, Any]:
    """Drive opencode and quillancode on the same prompt/model and compare output."""
    opencode = Path.home() / "AppData" / "Roaming" / "npm" / "opencode.cmd"
    if not opencode.is_file() or not os.environ.get("GEMINI_API_KEY"):
        return {"ok": False, "error": "opencode or GEMINI_API_KEY unavailable"}
    with tempfile.TemporaryDirectory() as td:
        xdg = Path(td) / "xdg" / "opencode"
        xdg.mkdir(parents=True)
        (xdg / "opencode.jsonc").write_text(
            '{"$schema":"https://opencode.ai/config.json",'
            '"model":"google/gemini-flash-lite-latest","permission":{"*":"allow"}}',
            encoding="utf-8",
        )
        env = os.environ.copy()
        env["XDG_CONFIG_HOME"] = str(Path(td) / "xdg")
        env["GOOGLE_GENERATIVE_AI_API_KEY"] = env["GEMINI_API_KEY"]
        oc = subprocess.run(
            [str(opencode), "run", "-m", "google/gemini-flash-lite-latest", prompt],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=env,
            cwd=td,
        )
        qc_config = Path(td) / "quillancode.json"
        qc_config.write_text(
            json.dumps(
                {
                    "provider": {"default": "compare-gemini"},
                    "providers": {
                        "compare-gemini": {
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
        qc = subprocess.run(
            [
                sys.executable,
                "-m",
                "quillancode",
                "--cwd",
                td,
                "-c",
                str(qc_config),
                "-p",
                "compare-gemini",
                "run",
                prompt,
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=env,
            cwd=str(Path(__file__).parent.parent),
        )
    token = "QC_LIVE_COMPARE_OK"
    a, b = (oc.stdout + oc.stderr).strip(), (qc.stdout + qc.stderr).strip()
    return {
        "ok": token in a and token in b,
        "opencode": a[-200:],
        "quillancode": b[-200:],
        "model": "google/gemini-flash-lite-latest",
    }


def check_qwen() -> dict[str, Any]:
    binary = Path.home() / "AppData" / "Roaming" / "npm" / "qwen.cmd"
    if not binary.is_file():
        found = shutil.which("qwen")
        binary = Path(found) if found else binary
    if not binary.is_file():
        return {"ok": False, "error": "qwen not installed"}
    version = subprocess.run(
        [str(binary), "--version"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    help_proc = subprocess.run(
        [str(binary), "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
    )
    text = version.stdout + help_proc.stdout
    return {
        "ok": version.returncode == 0 and "-p, --prompt" in text,
        "binary": str(binary),
        "version": version.stdout.strip(),
        "prompt_flag": "-p, --prompt" in text,
        "note": "non-interactive prompt requires a signed-in Qwen account (not available here)",
    }
