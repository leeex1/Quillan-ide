"""Tool registry: builtin + MCP tools with OpenAI-style schemas."""

from __future__ import annotations

from typing import Any

from .base import Tool, ToolContext
from .builtin import BUILTIN_CLASSES
from ..git_tools import GIT_TOOLS
from .permissions import PermissionGate, Decision
from ..models import ToolCall, ToolResult


class ToolRegistry:
    def __init__(self, cwd: str | None = None) -> None:
        from pathlib import Path

        self.cwd = Path(cwd or ".").resolve()
        self._tools: dict[str, Tool] = {}
        for cls in BUILTIN_CLASSES:
            self.register(cls())
        for cls in GIT_TOOLS:
            self.register(cls())

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def unregister(self, name: str) -> None:
        self._tools.pop(name, None)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.input_schema,
            }
            for tool in self._tools.values()
        ]

    def describe(self) -> str:
        return "\n".join(
            f"- {name}: {self._tools[name].description}" for name in self.names()
        )

    def execute_call(
        self,
        call: ToolCall,
        ctx: ToolContext,
        gate: PermissionGate,
        *,
        force: bool = False,
    ) -> ToolResult:
        tool = self._tools.get(call.name)
        if tool is None:
            return ToolResult(
                call_id=call.id, ok=False, error=f"unknown tool: {call.name}"
            )
        params = dict(call.arguments)
        params["call_id"] = call.id
        if not force:
            decision: Decision = gate.decide(call.name, call.arguments)
            if decision.action == "deny":
                return ToolResult(
                    call_id=call.id,
                    ok=False,
                    error=f"denied by permission gate ({decision.reason})",
                )
        try:
            result = tool.execute(params, ctx)
        except Exception as exc:  # tool boundary: never crash the agent loop
            result = ToolResult(
                call_id=call.id, ok=False, error=f"tool exception: {exc}"
            )
        result.call_id = call.id
        return result
