"""Minimal stdio LSP client for diagnostics (Content-Length framed JSON-RPC)."""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
from pathlib import Path
from typing import Any


class LSPError(RuntimeError):
    pass


class LSPClient:
    """Language-server client: initialize, didOpen, pull diagnostics."""

    def __init__(
        self, command: list[str], cwd: str | Path = ".", timeout: float = 15.0
    ) -> None:
        self.command = command
        self.cwd = str(cwd)
        self.timeout = timeout
        self._id = 0
        self._proc: subprocess.Popen[bytes] | None = None
        self._queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._published: dict[str, list[dict[str, Any]]] = {}

    def __enter__(self) -> "LSPClient":
        try:
            self._proc = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
        except OSError as exc:
            raise LSPError(f"cannot start language server: {exc}") from exc
        threading.Thread(target=self._drain, daemon=True).start()
        root = Path(self.cwd).resolve().as_uri()
        self.request(
            "initialize",
            {
                "processId": os.getpid(),
                "rootUri": root,
                "capabilities": {},
            },
        )
        self.notify("initialized", {})
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _drain(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        while True:
            header = b""
            while b"\r\n\r\n" not in header:
                chunk = self._proc.stdout.read(1)
                if not chunk:
                    return
                header += chunk
            length = 0
            for line in header.decode("ascii", errors="replace").split("\r\n"):
                if line.lower().startswith("content-length:"):
                    length = int(line.split(":", 1)[1].strip())
            body = self._proc.stdout.read(length)
            if not body:
                return
            try:
                self._queue.put(json.loads(body.decode("utf-8", errors="replace")))
            except ValueError:
                continue

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._proc.stdin.write(
            f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body
        )
        self._proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        req_id = self._id
        self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                msg = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if msg.get("method") == "textDocument/publishDiagnostics":
                params_data = msg.get("params") or {}
                self._published[str(params_data.get("uri", ""))] = list(
                    params_data.get("diagnostics", [])
                )
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise LSPError(f"LSP {method}: {msg['error']}")
                return dict(msg.get("result") or {})
        raise LSPError(f"LSP {method} timed out")

    def open_file(self, path: str | Path) -> str:
        target = Path(path).resolve()
        uri = target.as_uri()
        text = target.read_text(encoding="utf-8", errors="replace")
        self.notify(
            "textDocument/didOpen",
            {
                "textDocument": {
                    "uri": uri,
                    "languageId": target.suffix.lstrip(".") or "plaintext",
                    "version": 1,
                    "text": text,
                }
            },
        )
        return uri

    def diagnostics(self, uri: str) -> list[dict[str, Any]]:
        result = self.request("textDocument/diagnostic", {"textDocument": {"uri": uri}})
        items = result.get("items") if isinstance(result, dict) else None
        if items is not None:
            return list(items)
        return self._published.get(uri, [])

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            self.request("shutdown", {})
            self.notify("exit", {})
        except (LSPError, OSError):
            pass
        try:
            self._proc.terminate()
            self._proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, OSError):
            try:
                self._proc.kill()
            except OSError:
                pass
        if self._proc.stdout is not None:
            self._proc.stdout.close()
        if self._proc.stdin is not None:
            self._proc.stdin.close()
        self._proc = None


def check(
    path: str | Path, command: list[str], cwd: str | Path = "."
) -> list[dict[str, Any]]:
    with LSPClient(command, cwd) as client:
        uri = client.open_file(path)
        return client.diagnostics(uri)
