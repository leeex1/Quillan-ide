"""Core data models for quillancode.

All models are plain dataclasses with deterministic serialization so sessions,
checkpoints and telemetry can be persisted without third-party dependencies.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any


def _uid(prefix: str = "") -> str:
    return prefix + uuid.uuid4().hex[:12]


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(
            id=str(data.get("id", _uid("call_"))),
            name=str(data.get("name", "")),
            arguments=dict(data.get("arguments") or {}),
        )


@dataclass
class ToolResult:
    call_id: str
    ok: bool
    output: str = ""
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "ok": self.ok,
            "output": self.output,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(
            call_id=str(data.get("call_id", "")),
            ok=bool(data.get("ok", False)),
            output=str(data.get("output", "")),
            error=str(data.get("error", "")),
        )


@dataclass
class Message:
    role: str  # system | user | assistant | tool
    content: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_result: ToolResult | None = None
    trace_id: str = field(default_factory=lambda: _uid("tr_"))
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "role": self.role,
            "content": self.content,
            "trace_id": self.trace_id,
            "timestamp": self.timestamp,
        }
        if self.tool_calls:
            out["tool_calls"] = [c.to_dict() for c in self.tool_calls]
        if self.tool_result is not None:
            out["tool_result"] = self.tool_result.to_dict()
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Message":
        return cls(
            role=str(data.get("role", "user")),
            content=str(data.get("content", "")),
            tool_calls=[ToolCall.from_dict(c) for c in data.get("tool_calls", [])],
            tool_result=(
                ToolResult.from_dict(data["tool_result"])
                if data.get("tool_result")
                else None
            ),
            trace_id=str(data.get("trace_id", _uid("tr_"))),
            timestamp=float(data.get("timestamp", time.time())),
        )


@dataclass
class ProviderSpec:
    name: str
    kind: str = "mock"  # mock | openai_compat | anthropic
    base_url: str = ""
    model: str = "mock"
    api_key_env: str = ""
    temperature: float = 0.3
    max_tokens: int = 4096
    timeout: float = 120.0
    extra_headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "base_url": self.base_url,
            "model": self.model,
            "api_key_env": self.api_key_env,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "timeout": self.timeout,
            "extra_headers": dict(self.extra_headers),
        }

    @classmethod
    def from_dict(cls, name: str, data: dict[str, Any]) -> "ProviderSpec":
        return cls(
            name=name,
            kind=str(data.get("kind", "mock")),
            base_url=str(data.get("base_url", "")),
            model=str(data.get("model", "mock")),
            api_key_env=str(data.get("api_key_env", "")),
            temperature=float(data.get("temperature", 0.3)),
            max_tokens=int(data.get("max_tokens", 4096)),
            timeout=float(data.get("timeout", 120.0)),
            extra_headers={
                str(k): str(v) for k, v in (data.get("extra_headers") or {}).items()
            },
        )


@dataclass
class Todo:
    step: str
    verify: str
    status: str = "pending"  # pending | in_progress | done | blocked

    def to_dict(self) -> dict[str, Any]:
        return {"step": self.step, "verify": self.verify, "status": self.status}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Todo":
        return cls(
            step=str(data.get("step", "")),
            verify=str(data.get("verify", "")),
            status=str(data.get("status", "pending")),
        )


@dataclass
class Checkpoint:
    id: str = field(default_factory=lambda: _uid("ck_"))
    timestamp: float = field(default_factory=time.time)
    files: dict[str, str] = field(default_factory=dict)
    messages_len: int = 0
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "files": dict(self.files),
            "messages_len": self.messages_len,
            "label": self.label,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Checkpoint":
        return cls(
            id=str(data.get("id", _uid("ck_"))),
            timestamp=float(data.get("timestamp", time.time())),
            files={str(k): str(v) for k, v in (data.get("files") or {}).items()},
            messages_len=int(data.get("messages_len", 0)),
            label=str(data.get("label", "")),
        )


@dataclass
class Session:
    id: str = field(default_factory=lambda: _uid("ses_"))
    cwd: str = "."
    messages: list[Message] = field(default_factory=list)
    todos: list[Todo] = field(default_factory=list)
    checkpoints: list[Checkpoint] = field(default_factory=list)
    allowed_tools: set[str] = field(default_factory=set)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "cwd": self.cwd,
            "messages": [m.to_dict() for m in self.messages],
            "todos": [t.to_dict() for t in self.todos],
            "checkpoints": [c.to_dict() for c in self.checkpoints],
            "allowed_tools": sorted(self.allowed_tools),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Session":
        return cls(
            id=str(data.get("id", _uid("ses_"))),
            cwd=str(data.get("cwd", ".")),
            messages=[Message.from_dict(m) for m in data.get("messages", [])],
            todos=[Todo.from_dict(t) for t in data.get("todos", [])],
            checkpoints=[Checkpoint.from_dict(c) for c in data.get("checkpoints", [])],
            allowed_tools={str(t) for t in data.get("allowed_tools", [])},
            created_at=float(data.get("created_at", time.time())),
        )
