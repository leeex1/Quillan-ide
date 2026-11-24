"""Headless HTTP API and minimal ACP stdio server (opencode `serve`/`acp` parity)."""

from __future__ import annotations

import json
import os
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import __version__
from .config import Config
from .providers.registry import ProviderRegistry

AgentFactory = Callable[[Config, str | None], Any]


def _build_handler(
    config: Config, factory: AgentFactory
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: Any) -> None:
            return

        def _send(self, code: int, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _path(self, value: str) -> Path:
            root = Path(config.get("server.workspace", ".")).resolve()
            candidate = Path(value).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            resolved = candidate.resolve()
            if not resolved.is_relative_to(root):
                raise PermissionError("path escapes workspace")
            return resolved

        def do_GET(self) -> None:  # noqa: N802
            if self.path.startswith("/assets/"):
                import mimetypes

                name = self.path.split("/assets/", 1)[1].split("?", 1)[0]
                asset = Path(__file__).parent / "web" / "assets" / name
                if asset.is_file() and asset.parent == (
                    Path(__file__).parent / "web" / "assets"
                ):
                    body = asset.read_bytes()
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        mimetypes.guess_type(asset.name)[0]
                        or "application/octet-stream",
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(404)
                    self.end_headers()
                return
            if self.path.startswith("/api/files") or self.path.startswith("/api/file?"):
                try:
                    query = self.path.split("?", 1)[1] if "?" in self.path else ""
                    raw = dict(
                        part.split("=", 1) for part in query.split("&") if "=" in part
                    )
                    target = self._path(
                        __import__("urllib.parse", fromlist=["unquote"]).unquote(
                            raw.get("path", ".")
                        )
                    )
                    if target.is_dir():
                        items = [
                            {"name": p.name, "dir": p.is_dir()}
                            for p in sorted(
                                target.iterdir(),
                                key=lambda p: (not p.is_dir(), p.name.lower()),
                            )
                        ]
                        self._send(200, {"path": str(target), "items": items[:2000]})
                    elif target.is_file():
                        self._send(
                            200,
                            {
                                "path": str(target),
                                "content": target.read_text(
                                    encoding="utf-8", errors="replace"
                                ),
                            },
                        )
                    else:
                        self._send(404, {"error": "not found"})
                except (PermissionError, OSError, ValueError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if self.path.startswith("/api/artifact") or self.path.startswith(
                "/api/raw"
            ):
                import mimetypes
                from urllib.parse import unquote

                try:
                    query = self.path.split("?", 1)[1] if "?" in self.path else ""
                    raw = dict(
                        part.split("=", 1) for part in query.split("&") if "=" in part
                    )
                    target = self._path(unquote(raw.get("path", "")))
                    if not target.is_file():
                        self._send(404, {"error": "not found"})
                        return
                    if self.path.startswith("/api/artifact"):
                        from .artifacts import inspect

                        self._send(200, inspect(target))
                    else:
                        ctype = (
                            mimetypes.guess_type(target.name)[0]
                            or "application/octet-stream"
                        )
                        import shutil

                        self.send_response(200)
                        self.send_header("Content-Type", ctype)
                        self.send_header("Content-Length", str(target.stat().st_size))
                        self.send_header("Accept-Ranges", "bytes")
                        self.end_headers()
                        with target.open("rb") as fh:
                            shutil.copyfileobj(fh, self.wfile, length=65536)
                except (PermissionError, OSError, ValueError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if self.path.startswith("/api/search"):
                import urllib.parse

                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                terms = dict(
                    part.split("=", 1) for part in query.split("&") if "=" in part
                )
                needle = urllib.parse.unquote(terms.get("q", "")).lower()
                root = Path(config.get("server.workspace", ".")).resolve()
                found: list[str] = []
                if needle:
                    skip = {".git", "node_modules", "__pycache__", ".venv", "dist"}
                    for base, dirs, names in os.walk(root):
                        dirs[:] = [d for d in dirs if d not in skip]
                        for name in names:
                            if needle in name.lower():
                                full = Path(base) / name
                                try:
                                    found.append(str(full.relative_to(root)))
                                except ValueError:
                                    pass
                                if len(found) >= 80:
                                    break
                        if len(found) >= 80:
                            break
                self._send(200, {"results": found})
                return
            if self.path.startswith("/api/check"):
                import subprocess
                import tomllib

                query = self.path.split("?", 1)[1] if "?" in self.path else ""
                terms = dict(
                    part.split("=", 1) for part in query.split("&") if "=" in part
                )
                try:
                    from urllib.parse import unquote

                    target = self._path(unquote(terms.get("path", "")))
                    suffix = target.suffix.lower()
                    result = {
                        "path": str(target),
                        "ok": True,
                        "message": "no checker for this type",
                    }
                    if not target.is_file():
                        raise FileNotFoundError(str(target))
                    if suffix == ".py":
                        proc = subprocess.run(
                            [sys.executable, "-m", "py_compile", str(target)],
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=30,
                        )
                        result = {
                            "path": str(target),
                            "ok": proc.returncode == 0,
                            "message": (proc.stderr or "syntax OK").strip()[:800],
                        }
                    elif suffix == ".json":
                        json.loads(target.read_text(encoding="utf-8", errors="replace"))
                        result = {
                            "path": str(target),
                            "ok": True,
                            "message": "valid JSON",
                        }
                    elif suffix in {".toml", ".ini"}:
                        tomllib.loads(
                            target.read_text(encoding="utf-8", errors="replace")
                        )
                        result = {
                            "path": str(target),
                            "ok": True,
                            "message": "valid TOML",
                        }
                    self._send(200, result)
                except (
                    PermissionError,
                    OSError,
                    ValueError,
                    subprocess.TimeoutExpired,
                ) as exc:
                    self._send(
                        200,
                        {
                            "path": terms.get("path", ""),
                            "ok": False,
                            "message": f"{type(exc).__name__}: {exc}"[:800],
                        },
                    )
                return
            if self.path.startswith("/api/diff"):
                from .github import diff as git_diff

                self._send(
                    200, {"diff": git_diff(Path(config.get("server.workspace", ".")))}
                )
                return
            if self.path.startswith("/api/git/status"):
                from .github import status as git_status

                self._send(200, git_status(Path(config.get("server.workspace", "."))))
                return
            if self.path.startswith("/api/workspace"):
                self._send(
                    200,
                    {"cwd": str(Path(config.get("server.workspace", ".")).resolve())},
                )
                return
            if self.path.startswith("/api/providers"):
                registry = ProviderRegistry(config)
                self._send(
                    200,
                    {
                        "providers": registry.available(),
                        "default": config.default_provider,
                    },
                )
                return
            if self.path.startswith("/api/settings"):
                from .auth import AuthStore

                store = AuthStore()
                specs = config.providers
                self._send(
                    200,
                    {
                        "provider": config.default_provider,
                        "model": (
                            specs[config.default_provider].model
                            if config.default_provider in specs
                            else ""
                        ),
                        "providers": [
                            {
                                "name": name,
                                "model": spec.model,
                                "kind": spec.kind,
                                "key_set": bool(
                                    os.environ.get(spec.api_key_env) or store.get(name)
                                ),
                            }
                            for name, spec in sorted(specs.items())
                        ],
                        "stored_keys": [e["provider"] for e in store.list()],
                    },
                )
                return
            if self.path.startswith("/ide"):
                page = (Path(__file__).parent / "web" / "ide.html").read_text(
                    encoding="utf-8"
                )
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path in {"/", "/index.html"}:
                page = """<!doctype html><html><head><meta charset="utf-8">
<title>quillancode</title></head><body>
<h1>quillancode</h1>
<form id="chat"><textarea id="message" rows="4" cols="60"></textarea><br>
<button type="submit">Send</button></form>
<pre id="answer"></pre>
<script>
document.getElementById('chat').addEventListener('submit', async (e) => {
  e.preventDefault();
  const message = document.getElementById('message').value;
  const r = await fetch('/v1/chat', {method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({message})});
  const d = await r.json();
  document.getElementById('answer').textContent = d.answer || JSON.stringify(d);
});
</script></body></html>"""
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith("/health"):
                self._send(200, {"ok": True, "version": __version__})
            elif self.path.startswith("/tools"):
                agent = factory(config, None)
                self._send(200, {"tools": agent.tools.schemas()})
            else:
                self._send(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path.startswith("/api/council"):
                from .council import Council

                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(size).decode("utf-8"))
                    question = str(payload.get("question", "")).strip()
                    if not question:
                        raise ValueError("question required")
                    result = Council(config).deliberate(
                        question, int(payload.get("agents", 2))
                    )
                    self._send(200, result.to_dict())
                except (ValueError, OSError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if self.path.startswith("/api/git/"):
                from .github import git

                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(size).decode("utf-8"))
                    root = Path(config.get("server.workspace", "."))
                    if self.path.startswith("/api/git/commit"):
                        message = str(
                            payload.get("message", "quillancode update")
                        ).strip()
                        add = git(["add", "-A"], root)
                        commit = git(["commit", "-m", message], root)
                        result = {
                            "ok": add["ok"] and commit["ok"],
                            "output": (
                                commit.get("stdout", "") + commit.get("stderr", "")
                            )[-800:],
                        }
                    else:
                        push = git(["push"], root)
                        result = {
                            "ok": push["ok"],
                            "output": (push.get("stdout", "") + push.get("stderr", ""))[
                                -800:
                            ],
                        }
                    self._send(200, result)
                except (ValueError, OSError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if self.path.startswith("/api/settings"):
                from .auth import AuthStore

                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(size).decode("utf-8"))
                    name = str(payload.get("provider", "")).strip()
                    if not name:
                        raise ValueError("provider required")
                    specs = config.data.setdefault("providers", {})
                    spec = dict(specs.get(name) or {})
                    for key in ("kind", "base_url", "model", "api_key_env"):
                        if payload.get(key):
                            spec[key] = str(payload[key])
                    spec.setdefault("kind", "openai_compat")
                    spec.setdefault("model", "")
                    specs[name] = spec
                    config.data.setdefault("provider", {})["default"] = name
                    if payload.get("api_key"):
                        AuthStore().set(name, str(payload["api_key"]))
                    if payload.get("save"):
                        config.save(
                            str(
                                Path(config.get("server.workspace", "."))
                                / "quillancode.json"
                            )
                        )
                    self._send(
                        200,
                        {
                            "ok": True,
                            "provider": name,
                            "model": spec.get("model", ""),
                            "key_stored": bool(payload.get("api_key")),
                        },
                    )
                except (ValueError, OSError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if self.path.startswith("/api/delete"):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(size).decode("utf-8"))
                    target = self._path(str(payload.get("path", "")))
                    target.unlink()
                    self._send(200, {"ok": True, "deleted": str(target)})
                except (PermissionError, OSError, ValueError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if self.path.startswith("/api/file"):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                    payload = json.loads(self.rfile.read(size).decode("utf-8"))
                    target = self._path(str(payload.get("path", "")))
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if "base64" in payload:
                        import base64

                        data = base64.b64decode(str(payload["base64"]))
                    else:
                        data = str(payload.get("content", "")).encode("utf-8")
                    backup = None
                    if target.is_file() and target.read_bytes() != data:
                        import re as _re
                        import shutil
                        from datetime import datetime

                        bdir = Path.home() / ".quillancode" / "backups"
                        bdir.mkdir(parents=True, exist_ok=True)
                        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        safe = _re.sub(r"[^A-Za-z0-9_.-]", "_", target.name)[:60]
                        backup = bdir / f"{stamp}_{safe}"
                        shutil.copy2(target, backup)
                    target.write_bytes(data)
                    self._send(
                        200,
                        {
                            "ok": True,
                            "path": str(target),
                            "backup": str(backup) if backup else None,
                        },
                    )
                except (PermissionError, OSError, ValueError) as exc:
                    self._send(400, {"error": str(exc)})
                return
            if not self.path.startswith("/v1/chat"):
                self._send(404, {"error": "not found"})
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(size).decode("utf-8"))
                message = str(payload.get("message", ""))
                provider = payload.get("provider")
                if not message:
                    raise ValueError("message is required")
                agent = factory(config, provider)
                answer = agent.run(message)
                self._send(200, {"answer": answer, "session": agent.session.id})
            except (ValueError, KeyError, OSError) as exc:
                self._send(400, {"error": str(exc)})

    return Handler


def serve(
    config: Config,
    factory: AgentFactory,
    *,
    host: str = "127.0.0.1",
    port: int = 4096,
    open_browser: bool = False,
) -> int:
    handler = _build_handler(config, factory)
    server = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{server.server_address[1]}"
    print(f"quillancode serving at {url} (GET /health, GET /tools, POST /v1/chat)")
    if open_browser:
        threading.Thread(target=lambda: webbrowser.open(url), daemon=True).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def ide_selftest() -> str:
    """Start an ephemeral IDE server and verify every IDE endpoint."""
    import tempfile
    import threading
    import urllib.parse
    import urllib.request
    from http.server import ThreadingHTTPServer

    from .config import Config as _Config

    with tempfile.TemporaryDirectory() as td:
        cfg = _Config.from_dict({"server": {"workspace": td}})
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", 0), _build_handler(cfg, lambda c, p: None)
        )
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            html = urllib.request.urlopen(base + "/ide", timeout=5).read().decode()
            workspace = json.loads(
                urllib.request.urlopen(base + "/api/workspace", timeout=5).read()
            )
            listing = json.loads(
                urllib.request.urlopen(base + "/api/files?path=.", timeout=5).read()
            )
            body = json.dumps({"path": "x.txt", "content": "ide-ok"}).encode()
            req = urllib.request.Request(
                base + "/api/file",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            saved = json.loads(urllib.request.urlopen(req, timeout=5).read())
            fetched = json.loads(
                urllib.request.urlopen(
                    base + "/api/file?path=" + urllib.parse.quote("x.txt"), timeout=5
                ).read()
            )
            header = json.dumps(
                {"tensor.a": {"dtype": "F32", "shape": [2, 3], "data_offsets": [0, 24]}}
            ).encode()
            (Path(td) / "m.safetensors").write_bytes(
                len(header).to_bytes(8, "little") + header + b"\0" * 24
            )
            artifact = json.loads(
                urllib.request.urlopen(
                    base + "/api/artifact?path=" + urllib.parse.quote("m.safetensors"),
                    timeout=5,
                ).read()
            )
            raw = urllib.request.urlopen(
                base + "/api/raw?path=" + urllib.parse.quote("x.txt"), timeout=5
            ).read()
            overwrite_req = urllib.request.Request(
                base + "/api/file",
                data=json.dumps({"path": "x.txt", "content": "changed"}).encode(),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            overwrite = json.loads(
                urllib.request.urlopen(overwrite_req, timeout=5).read()
            )
            big = Path(td) / "big.bin"
            big.write_bytes(b"Q" * (1024 * 1024))
            big_raw = urllib.request.urlopen(
                base + "/api/raw?path=" + urllib.parse.quote("big.bin"), timeout=10
            ).read()
            logo = urllib.request.urlopen(
                base + "/assets/quillan-logo.svg", timeout=5
            ).read()
            settings = json.loads(
                urllib.request.urlopen(base + "/api/settings", timeout=5).read()
            )
            search = json.loads(
                urllib.request.urlopen(base + "/api/search?q=x.txt", timeout=5).read()
            )
            ok = (
                "<textarea" in html
                and "items" in listing
                and saved.get("ok")
                and fetched.get("content") == "ide-ok"
                and "cwd" in workspace
                and len(artifact.get("tensors", [])) == 1
                and raw == b"ide-ok"
                and len(big_raw) == 1024 * 1024
                and bool(overwrite.get("backup"))
                and "providers" in settings
                and b"<svg" in logo
                and "x.txt" in search.get("results", [])
            )
        finally:
            httpd.shutdown()
            httpd.server_close()
    return "IDE_SELFTEST_OK" if ok else "IDE_SELFTEST_FAIL"


def acp(config: Config, factory: AgentFactory) -> int:
    """Serve a minimal Agent Client Protocol JSON-RPC loop over stdio."""
    agent = factory(config, None)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except ValueError:
            continue
        method = str(request.get("method", ""))
        req_id = request.get("id")
        params = request.get("params") or {}
        if method == "initialize":
            result = {
                "protocolVersion": 1,
                "agentCapabilities": {"loadSession": True},
                "agentInfo": {"name": "quillancode", "version": __version__},
            }
        elif method in {"session/new", "session/load"}:
            result = {"sessionId": agent.session.id}
        elif method == "session/prompt":
            parts = params.get("prompt") or []
            text = " ".join(
                str(p.get("text", "")) for p in parts if isinstance(p, dict)
            )
            answer = agent.run(text)
            sys.stdout.write(
                json.dumps(
                    {
                        "jsonrpc": "2.0",
                        "method": "session/update",
                        "params": {
                            "sessionId": agent.session.id,
                            "update": {
                                "sessionUpdate": "agent_message_chunk",
                                "content": {"type": "text", "text": answer},
                            },
                        },
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stdout.flush()
            result = {"stopReason": "end_turn"}
        elif method == "session/cancel":
            result = {}
        else:
            if req_id is not None:
                sys.stdout.write(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": req_id,
                            "error": {
                                "code": -32601,
                                "message": f"unknown method: {method}",
                            },
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
                sys.stdout.flush()
            continue
        if req_id is not None:
            sys.stdout.write(
                json.dumps(
                    {"jsonrpc": "2.0", "id": req_id, "result": result},
                    ensure_ascii=False,
                )
                + "\n"
            )
            sys.stdout.flush()
    return 0
