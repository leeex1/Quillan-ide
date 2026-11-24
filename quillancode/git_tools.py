"""First-class git tools available to the agent loop."""

from __future__ import annotations

from typing import Any

from .github import diff, git, status
from .models import ToolResult
from .tools.base import INT, STR, ToolContext, fail, ok, schema


class GitStatusTool:
    name = "git_status"
    description = "Show branch and short working-tree status for the workspace."
    input_schema = schema({}, [])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        info = status(ctx.cwd)
        if not info["ok"]:
            return fail(call_id, str(info))
        return ok(call_id, f"branch: {info['branch']}\n{info['changes'] or '(clean)'}")


class GitDiffTool:
    name = "git_diff"
    description = "Show unified git diff (optionally staged)."
    input_schema = schema({"staged": {"type": "boolean", "default": False}}, [])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        return ok(
            call_id, diff(ctx.cwd, staged=bool(params.get("staged"))) or "(no changes)"
        )


class GitAddTool:
    name = "git_add"
    description = "Stage files in the workspace (paths are workspace-relative)."
    input_schema = schema({"paths": {"type": "array", "items": STR}}, ["paths"])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        paths: list[str] = []
        for raw in params.get("paths", []):
            try:
                paths.append(str(ctx.resolve(str(raw)).relative_to(ctx.cwd.resolve())))
            except (PermissionError, ValueError) as exc:
                return fail(call_id, str(exc))
        result = git(["add", "--", *paths], ctx.cwd)
        return (
            ok(call_id, result.get("stdout", ""))
            if result["ok"]
            else fail(call_id, str(result))
        )


class GitCommitTool:
    name = "git_commit"
    description = "Commit staged changes with a message."
    input_schema = schema({"message": STR}, ["message"])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        result = git(["commit", "-m", str(params["message"])], ctx.cwd)
        if not result["ok"]:
            return fail(call_id, str(result.get("stderr") or result))
        return ok(
            call_id, (result.get("stdout", "") + result.get("stderr", ""))[-4000:]
        )


class GitLogTool:
    name = "git_log"
    description = "Show recent commit history."
    input_schema = schema({"limit": INT}, [])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        limit = min(int(params.get("limit", 10)), 100)
        result = git(["log", "--oneline", "-n", str(limit)], ctx.cwd)
        return (
            ok(call_id, result.get("stdout", ""))
            if result["ok"]
            else fail(call_id, str(result))
        )


GIT_TOOLS = [GitStatusTool, GitDiffTool, GitAddTool, GitCommitTool, GitLogTool]
