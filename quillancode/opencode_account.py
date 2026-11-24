"""OpenCode-account provider: routes through the user's running OpenCode desktop
session, inheriting its bundled free tier and quota. No API key is supplied.

This is the "middleman" path: quillancode sends prompts to the local OpenCode
API using the desktop app's own service password from ~/.config/opencode/service.json.
Billing/usage stays on the user's OpenCode account; API-key providers remain separate.

Note: the account endpoint is text-only (no native tool-call channel). The agent
loop still executes its own tools locally; the model sees a text transcript.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .models import Message, ProviderSpec
from .providers.base import ProviderAdapter, ProviderError

DEFAULT_PORT = 28894
SERVICE_FILE = Path.home() / ".config" / "opencode" / "service.json"


def discover_base_url() -> str:
    override = os.environ.get("OPENCODE_SERVER_URL")
    if override:
        return override.rstrip("/")
    port = os.environ.get("OPENCODE_SERVER_PORT", str(_detect_port() or DEFAULT_PORT))
    return f"http://127.0.0.1:{port}"


def _detect_port() -> int | None:
    """Find the listening port owned by opencode-cli (Windows netstat fallback)."""
    try:
        out = subprocess.run(
            ["netstat", "-ano", "-p", "TCP"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        ).stdout
        pids = []
        for line in out.splitlines():
            parts = line.split()
            if (
                len(parts) >= 5
                and parts[3].upper() == "LISTENING"
                and parts[1].startswith("127.0.0.1:")
            ):
                pids.append((parts[1].split(":")[-1], parts[4]))
        for port, pid in pids:
            try:
                task = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=8,
                ).stdout.lower()
                if "opencode" in task:
                    return int(port)
            except (OSError, subprocess.TimeoutExpired, ValueError):
                continue
    except (OSError, subprocess.TimeoutExpired):
        return None
    return None


def service_password() -> str:
    if not SERVICE_FILE.is_file():
        raise ProviderError(f"OpenCode service file not found: {SERVICE_FILE}")
    try:
        data = json.loads(SERVICE_FILE.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise ProviderError(f"cannot read OpenCode service file: {exc}") from exc
    return str(data.get("password", ""))


class OpenCodeAccountProvider:
    name = "opencode_account"
    supports_tools = False

    def __init__(self, spec: ProviderSpec) -> None:
        self.spec = spec
        self.base_url = (spec.base_url or discover_base_url()).rstrip("/")
        self.model = spec.model or "hy4-flash-free"

    def _headers(self) -> dict[str, str]:
        pw = service_password()
        token = base64.b64encode(f"opencode:{pw}".encode()).decode()
        return {"Authorization": "Basic " + token, "Content-Type": "application/json"}

    def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> Any:
        data = (
            json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        )
        req = urllib.request.Request(
            self.base_url + path, data=data, headers=self._headers(), method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
            exc.close()
            raise ProviderError(f"opencode-account HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise ProviderError(f"opencode-account connection failed: {exc}") from exc

    @staticmethod
    def _transcript(messages: list[Message]) -> str:
        parts: list[str] = []
        for msg in messages:
            if msg.role == "system":
                parts.append(f"[system] {msg.content}")
            elif msg.tool_result is not None:
                status = "OK" if msg.tool_result.ok else "ERROR"
                parts.append(
                    f"[tool {status}] {msg.tool_result.output or msg.tool_result.error}"
                )
            else:
                parts.append(f"[{msg.role}] {msg.content}")
        return "\n\n".join(parts)

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> Message:
        created = self._request("POST", "/api/session", {"title": "quillancode bridge"})
        session_id = (
            (created.get("data") or {}).get("id") if isinstance(created, dict) else None
        )
        if not session_id:
            raise ProviderError("opencode-account: session creation returned no id")
        text = self._transcript(messages)
        self._request("POST", f"/api/session/{session_id}/prompt", {"text": text})
        deadline = time.monotonic() + 180.0
        while time.monotonic() < deadline:
            data = self._request("GET", f"/api/session/{session_id}/message")
            items = data.get("data", []) if isinstance(data, dict) else []
            assistant = next(
                (m for m in reversed(items) if m.get("type") == "assistant"), None
            )
            if assistant:
                blocks = assistant.get("content") or []
                answer = "\n".join(
                    str(block.get("text", ""))
                    for block in blocks
                    if block.get("type") == "text"
                )
                if answer.strip() or assistant.get("finish"):
                    return Message(role="assistant", content=answer)
            time.sleep(0.5)
        raise ProviderError("opencode-account: timed out waiting for assistant reply")

    def list_models(self) -> list[str]:
        data = self._request("GET", "/api/model")
        items = data.get("data", []) if isinstance(data, dict) else []
        return [
            str(item.get("id"))
            for item in items
            if item.get("providerID") == "opencode" and item.get("id")
        ]


Adapter = OpenCodeAccountProvider
