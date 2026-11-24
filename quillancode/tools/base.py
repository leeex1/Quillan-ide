"""Tool protocol, context and result helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol, runtime_checkable

from ..models import ToolResult


@dataclass
class ToolContext:
    cwd: Path
    session: Any = None
    emit: Callable[[str, dict[str, Any]], None] = lambda event, data: None
    limits: dict[str, Any] = field(default_factory=dict)

    def resolve(self, path: str) -> Path:
        """Resolve a user path against cwd and block traversal outside the workspace."""
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = self.cwd / candidate
        resolved = candidate.resolve()
        root = self.cwd.resolve()
        if resolved != root and root not in resolved.parents:
            raise PermissionError(f"path escapes workspace: {path}")
        return resolved


@runtime_checkable
class Tool(Protocol):
    name: str
    description: str
    input_schema: dict[str, Any]

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult: ...


def ok(call_id: str, output: str) -> ToolResult:
    return ToolResult(call_id=call_id, ok=True, output=output)


def fail(call_id: str, error: str) -> ToolResult:
    return ToolResult(call_id=call_id, ok=False, error=error)


def schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


STR = {"type": "string"}
INT = {"type": "integer", "default": 2000}
BOOL = {"type": "boolean", "default": False}
