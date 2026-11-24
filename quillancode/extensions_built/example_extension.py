"""Bundled example extension: a deterministic echo tool (safe, offline)."""

from __future__ import annotations

from typing import Any

from quillancode.models import ToolResult
from quillancode.tools.base import STR, ToolContext, ok, schema


class EchoTool:
    name = "echo"
    description = "Return the supplied text unchanged (extension demo)."
    input_schema = schema({"text": STR}, ["text"])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        return ok(str(params.get("call_id", "")), str(params.get("text", "")))


def register(registry: Any, config: Any, hooks: Any) -> None:
    registry.register(EchoTool())
