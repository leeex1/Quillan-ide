"""Minimal stdio MCP client (JSON-RPC 2.0): initialize, tools/list, tools/call.

Cross-platform: a reader thread drains stdout so reads have deterministic timeouts
on Windows (where select() cannot wait on pipes).
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ToolResult
from .tools.base import ToolContext, schema

STR = {"type": "string"}


@dataclass
class MCPServerSpec:
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    type: str = "stdio"
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "MCPServerSpec":
        return cls(
            name=name,
            command=str(data.get("command", "")),
            args=[str(a) for a in data.get("args", [])],
            env={str(k): str(v) for k, v in (data.get("env") or {}).items()},
            cwd=(str(data["cwd"]) if data.get("cwd") else None),
            type=str(data.get("type", "http" if data.get("url") else "stdio")),
            url=str(data.get("url", "")),
            headers={str(k): str(v) for k, v in (data.get("headers") or {}).items()},
        )


class MCPError(RuntimeError):
    pass


class MCPConnection:
    def __init__(self, spec: MCPServerSpec, timeout: float = 30.0) -> None:
        self.spec = spec
        self.timeout = timeout
        self._id = 0
        self._queue: queue.Queue[str] = queue.Queue()
        self._proc: subprocess.Popen[str] | None = None
        self._reader: threading.Thread | None = None
        self.tools: list[dict[str, Any]] = []
        self._http = self.spec.type.lower() in {
            "http",
            "sse",
            "streamable-http",
        } or bool(self.spec.url)

    def __enter__(self) -> "MCPConnection":
        if self._http:
            result = self.request("tools/list", {})
            self.tools = list(result.get("tools", []))
            return self
        env = os.environ.copy()
        env.update(self.spec.env)
        try:
            self._proc = subprocess.Popen(
                [self.spec.command, *self.spec.args],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                cwd=self.spec.cwd,
                env=env,
            )
        except OSError as exc:
            raise MCPError(f"cannot start MCP server {self.spec.name}: {exc}") from exc
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        self.request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "quillancode", "version": "1.0.0"},
            },
        )
        self.notify("notifications/initialized", {})
        result = self.request("tools/list", {})
        self.tools = list(result.get("tools", []))
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()

    def _drain(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        for line in self._proc.stdout:
            self._queue.put(line)

    def _send(self, payload: dict[str, Any]) -> None:
        assert self._proc is not None and self._proc.stdin is not None
        self._proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._proc.stdin.flush()

    def notify(self, method: str, params: dict[str, Any]) -> None:
        if self._http:
            return
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _http_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.spec.url:
            raise MCPError(f"MCP server {self.spec.name} has no url")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        headers.update(self.spec.headers)
        req = urllib.request.Request(
            self.spec.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            raise MCPError(f"MCP {self.spec.name} HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise MCPError(f"MCP {self.spec.name} connection failed: {exc}") from exc
        wanted = payload.get("id")
        for line in body.splitlines():
            if not line.startswith("data:"):
                continue
            try:
                msg = json.loads(line[5:].strip())
            except ValueError:
                continue
            if msg.get("id") == wanted:
                if "error" in msg:
                    raise MCPError(f"MCP {self.spec.name}: {msg['error']}")
                return dict(msg.get("result") or {})
        try:
            msg = json.loads(body)
        except ValueError as exc:
            raise MCPError(f"MCP {self.spec.name} returned invalid JSON-RPC") from exc
        if "error" in msg:
            raise MCPError(f"MCP {self.spec.name}: {msg['error']}")
        return dict(msg.get("result") or {})

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._id += 1
        req_id = self._id
        payload = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        if self._http:
            return self._http_request(payload)
        self._send(payload)
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            try:
                line = self._queue.get(timeout=0.25)
            except queue.Empty:
                if self._proc is not None and self._proc.poll() is not None:
                    raise MCPError(
                        f"MCP server {self.spec.name} exited during {method}"
                    )
                continue
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if msg.get("id") == req_id:
                if "error" in msg:
                    raise MCPError(f"MCP {self.spec.name} {method}: {msg['error']}")
                return dict(msg.get("result") or {})
        raise MCPError(f"MCP {self.spec.name} {method} timed out")

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return self.request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        if self._http:
            return
        if self._proc is not None:
            try:
                if self._proc.stdin is not None:
                    self._proc.stdin.close()
            except OSError:
                pass
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._proc.kill()
                except OSError:
                    pass
            for stream in (self._proc.stdout, self._proc.stderr):
                if stream is not None:
                    try:
                        stream.close()
                    except OSError:
                        pass
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                try:
                    self._proc.kill()
                except OSError:
                    pass
            self._proc = None


class MCPTool:
    """Adapts a remote MCP tool into the local Tool protocol."""

    def __init__(
        self, connection: MCPConnection, server: str, definition: dict[str, Any]
    ) -> None:
        self._conn = connection
        self.server = server
        self.definition = definition
        self.name = f"mcp__{server}__{definition.get('name', 'tool')}"
        self.description = f"[MCP:{server}] {definition.get('description', '')}"
        self.input_schema = definition.get("inputSchema") or schema({"input": STR})

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.pop("call_id", ""))
        try:
            result = self._conn.call_tool(str(self.definition.get("name")), params)
            parts = [
                str(block.get("text", ""))
                for block in result.get("content", [])
                if isinstance(block, dict)
            ]
            text = "\n".join(parts) or json.dumps(result, ensure_ascii=False)
            return ToolResult(
                call_id=call_id,
                ok=not bool(result.get("isError")),
                output=text,
                error="" if not result.get("isError") else text,
            )
        except MCPError as exc:
            return ToolResult(call_id=call_id, ok=False, error=str(exc))


def load_mcp_tools(config: Any, registry: Any) -> list[MCPTool]:
    """Connect all configured stdio servers and register their tools.

    Returns the live connections so the caller can close them at session end.
    """
    servers = config.get("mcp.servers", {}) or {}
    loaded: list[MCPTool] = []
    for name, data in servers.items():
        spec = MCPServerSpec.from_dict(str(name), data)
        if not spec.command and not spec.url:
            continue
        conn = MCPConnection(spec)
        try:
            conn.__enter__()
        except MCPError:
            conn.close()
            continue
        for definition in conn.tools:
            tool = MCPTool(conn, spec.name, definition)
            registry.register(tool)
            loaded.append(tool)
    return loaded
