"""Deterministic, cwd-scoped builtin tools (stdlib only)."""

from __future__ import annotations

import difflib
import fnmatch
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from ..models import Checkpoint, Todo, ToolResult
from .base import BOOL, INT, STR, ToolContext, fail, ok, schema

MAX_OUTPUT = 50_000


def _truncate(text: str, limit: int = MAX_OUTPUT) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... [truncated {len(text) - limit} chars]"


class ReadFileTool:
    name = "read_file"
    description = (
        "Read a UTF-8 text file inside the workspace, with optional line range."
    )
    input_schema = schema({"path": STR, "offset": INT, "limit": INT}, ["path"])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            path = ctx.resolve(str(params["path"]))
            if not path.is_file():
                return fail(call_id, f"not a file: {path}")
            offset = max(0, int(params.get("offset", 0)))
            limit = int(params.get("limit", 2000))
            from ..native_core import read as native_read

            fast = native_read(ctx.cwd, str(params["path"]), offset, limit)
            if fast is not None:
                return ok(call_id, _truncate(fast))
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            selected = lines[offset : offset + limit]
            numbered = "\n".join(
                f"{offset + i + 1:>6} | {line}" for i, line in enumerate(selected)
            )
            return ok(call_id, _truncate(numbered))
        except (KeyError, ValueError, OSError, PermissionError) as exc:
            return fail(call_id, str(exc))


class ListDirTool:
    name = "list_dir"
    description = "List a directory inside the workspace."
    input_schema = schema({"path": {"type": "string", "default": "."}}, [])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            path = ctx.resolve(str(params.get("path", ".")))
            if not path.is_dir():
                return fail(call_id, f"not a directory: {path}")
            from ..native_core import list_dir as native_list

            fast = native_list(ctx.cwd, str(params.get("path", ".")))
            if fast is not None:
                return ok(call_id, fast)
            entries = sorted(
                path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())
            )
            lines = [f"{'d' if e.is_dir() else 'f'}  {e.name}" for e in entries[:1000]]
            return ok(call_id, "\n".join(lines) or "(empty)")
        except (OSError, PermissionError) as exc:
            return fail(call_id, str(exc))


class GlobTool:
    name = "glob"
    description = "Find files by glob pattern inside the workspace."
    input_schema = schema(
        {"pattern": STR, "path": {"type": "string", "default": "."}}, ["pattern"]
    )

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            root = ctx.resolve(str(params.get("path", ".")))
            pattern = str(params["pattern"])
            from ..native_core import glob as native_glob

            fast = native_glob(root, pattern, 1000)
            if fast is not None:
                return ok(call_id, _truncate(fast))
            from ..workspace import is_ignored

            ignore = list(ctx.limits.get("ignore", []) or [])
            matches: list[str] = []
            for path in root.rglob("*"):
                if any(
                    part in {".git", "node_modules", "__pycache__", ".venv"}
                    for part in path.parts
                ):
                    continue
                rel = path.relative_to(ctx.cwd.resolve()).as_posix()
                if is_ignored(rel, ignore):
                    continue
                if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(path.name, pattern):
                    matches.append(rel)
                if len(matches) >= 1000:
                    break
            return ok(call_id, "\n".join(sorted(matches)) or "(no matches)")
        except (KeyError, OSError, PermissionError) as exc:
            return fail(call_id, str(exc))


class GrepTool:
    name = "grep"
    description = "Search file contents with a regular expression inside the workspace."
    input_schema = schema(
        {
            "pattern": STR,
            "path": {"type": "string", "default": "."},
            "glob": {"type": "string", "default": "*"},
            "limit": INT,
        },
        ["pattern"],
    )

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            root = ctx.resolve(str(params.get("path", ".")))
            regex = re.compile(str(params["pattern"]))
            name_glob = str(params.get("glob", "*"))
            limit = int(params.get("limit", 200))
            from ..native_core import grep as native_grep

            fast = native_grep(root, str(params["pattern"]), name_glob, limit)
            if fast is not None:
                return ok(call_id, _truncate(fast or "(no matches)"))
            from ..workspace import is_ignored

            ignore = list(ctx.limits.get("ignore", []) or [])
            hits: list[str] = []
            files = root.rglob("*") if root.is_dir() else [root]
            for path in files:
                if not path.is_file():
                    continue
                if any(
                    part in {".git", "node_modules", "__pycache__", ".venv"}
                    for part in path.parts
                ):
                    continue
                rel = path.relative_to(ctx.cwd.resolve()).as_posix()
                if is_ignored(rel, ignore):
                    continue
                if not fnmatch.fnmatch(path.name, name_glob):
                    continue
                try:
                    lines = path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except OSError:
                    continue
                for i, line in enumerate(lines, 1):
                    if regex.search(line):
                        rel = path.relative_to(ctx.cwd.resolve()).as_posix()
                        hits.append(f"{rel}:{i}: {line.strip()}")
                        if len(hits) >= limit:
                            break
                if len(hits) >= limit:
                    break
            return ok(call_id, _truncate("\n".join(hits) or "(no matches)"))
        except (KeyError, re.error, OSError, PermissionError) as exc:
            return fail(call_id, str(exc))


class WriteFileTool:
    name = "write_file"
    description = "Create or overwrite a UTF-8 text file inside the workspace."
    input_schema = schema({"path": STR, "content": STR}, ["path", "content"])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            path = ctx.resolve(str(params["path"]))
            content = str(params["content"])
            from ..native_core import write as native_write

            fast = native_write(ctx.cwd, str(params["path"]), content)
            if fast is not None:
                ctx.emit(
                    "file_written",
                    {"path": str(path), "bytes": len(content.encode("utf-8"))},
                )
                return ok(call_id, fast)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
            ctx.emit(
                "file_written",
                {"path": str(path), "bytes": len(content.encode("utf-8"))},
            )
            return ok(
                call_id,
                f"wrote {len(content)} chars to {path.relative_to(ctx.cwd.resolve())}",
            )
        except (KeyError, OSError, PermissionError) as exc:
            return fail(call_id, str(exc))


class EditFileTool:
    name = "edit_file"
    description = (
        "Replace an exact text occurrence in a file; fails on ambiguous matches."
    )
    input_schema = schema(
        {
            "path": STR,
            "old": STR,
            "new": STR,
            "replace_all": {"type": "boolean", "default": False},
        },
        ["path", "old", "new"],
    )

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            path = ctx.resolve(str(params["path"]))
            old, new = str(params["old"]), str(params["new"])
            text = path.read_text(encoding="utf-8")
            replace_all = bool(params.get("replace_all", False))
            from ..native_core import edit as native_edit

            fast = native_edit(ctx.cwd, str(params["path"]), old, new, replace_all)
            if fast is not None:
                updated_preview = (
                    text.replace(old, new) if replace_all else text.replace(old, new, 1)
                )
                diff_preview = "".join(
                    difflib.unified_diff(
                        text.splitlines(True),
                        updated_preview.splitlines(True),
                        fromfile=str(path.name),
                        tofile=str(path.name) + " (edited)",
                    )
                )
                ctx.emit(
                    "file_edited",
                    {"path": str(path), "diff": _truncate(diff_preview, 8000)},
                )
                return ok(call_id, _truncate(diff_preview or fast))
            count = text.count(old)
            if count == 0:
                return fail(call_id, "old text not found")
            replace_all = bool(params.get("replace_all", False))
            if count > 1 and not replace_all:
                return fail(
                    call_id, f"old text occurs {count} times; set replace_all=true"
                )
            updated = (
                text.replace(old, new) if replace_all else text.replace(old, new, 1)
            )
            diff = "".join(
                difflib.unified_diff(
                    text.splitlines(True),
                    updated.splitlines(True),
                    fromfile=str(path.name),
                    tofile=str(path.name) + " (edited)",
                )
            )
            path.write_text(updated, encoding="utf-8")
            ctx.emit("file_edited", {"path": str(path), "diff": _truncate(diff, 8000)})
            return ok(call_id, _truncate(diff or f"replaced {count} occurrence(s)"))
        except (KeyError, OSError, PermissionError) as exc:
            return fail(call_id, str(exc))


class BashTool:
    name = "bash"
    description = (
        "Run a shell command in the workspace with a timeout; output is captured."
    )
    input_schema = schema(
        {
            "command": STR,
            "timeout": {"type": "integer", "default": 60},
            "cwd": {"type": "string", "default": "."},
        },
        ["command"],
    )

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            command = str(params["command"])
            workdir = ctx.resolve(str(params.get("cwd", ".")))
            timeout = min(int(params.get("timeout", 60)), 600)
            started = time.monotonic()
            proc = subprocess.run(
                command,
                cwd=str(workdir),
                shell=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=timeout,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            elapsed = time.monotonic() - started
            ctx.emit(
                "command",
                {
                    "command": command,
                    "returncode": proc.returncode,
                    "seconds": round(elapsed, 3),
                },
            )
            body = f"exit={proc.returncode}\n{_truncate(proc.stdout)}"
            return ToolResult(
                call_id=call_id,
                ok=proc.returncode == 0,
                output=body,
                error="" if proc.returncode == 0 else f"exit {proc.returncode}",
            )
        except subprocess.TimeoutExpired:
            return fail(
                call_id, f"command timed out after {params.get('timeout', 60)}s"
            )
        except (KeyError, ValueError, OSError) as exc:
            return fail(call_id, str(exc))


class WebFetchTool:
    name = "webfetch"
    description = "Fetch a public http(s) URL and return readable text (SSRF-guarded)."
    input_schema = schema({"url": STR, "max_chars": INT}, ["url"])

    _BLOCKED_HOSTS = {"localhost", "127.0.0.1", "::1", "169.254.169.254", "0.0.0.0"}

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        try:
            url = str(params["url"])
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"}:
                return fail(call_id, "only http/https URLs are allowed")
            host = (parsed.hostname or "").lower()
            if host in self._BLOCKED_HOSTS or host.endswith(".localhost"):
                return fail(call_id, f"private/metadata host blocked: {host}")
            limit = min(int(params.get("max_chars", 20_000)), 100_000)
            req = urllib.request.Request(url, headers={"User-Agent": "quillancode/1.0"})
            with urllib.request.urlopen(req, timeout=20) as response:
                raw = response.read(limit * 2).decode("utf-8", errors="replace")
            return ok(call_id, _truncate(raw, limit))
        except urllib.error.HTTPError as exc:
            return fail(call_id, f"HTTP {exc.code}")
        except (KeyError, ValueError, OSError) as exc:
            return fail(call_id, str(exc))


class TodoWriteTool:
    name = "todo_write"
    description = "Set the session TODO list. Each item is a step paired with a verification check."
    input_schema = schema(
        {
            "todos": {
                "type": "array",
                "items": schema(
                    {
                        "step": STR,
                        "verify": STR,
                        "status": {"type": "string", "default": "pending"},
                    },
                    ["step", "verify"],
                ),
            }
        },
        ["todos"],
    )

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        session = ctx.session
        if session is None:
            return fail(call_id, "no active session")
        try:
            session.todos = [
                Todo(
                    step=str(t["step"]),
                    verify=str(t["verify"]),
                    status=str(t.get("status", "pending")),
                )
                for t in params["todos"]
            ]
            lines = [
                f"[{t.status}] {t.step}  ->  verify: {t.verify}" for t in session.todos
            ]
            return ok(call_id, "\n".join(lines) or "(cleared)")
        except (KeyError, TypeError, ValueError) as exc:
            return fail(call_id, str(exc))


class CheckpointTool:
    name = "checkpoint"
    description = "Snapshot named workspace files and message count for later rewind."
    input_schema = schema(
        {
            "paths": {"type": "array", "items": STR},
            "label": {"type": "string", "default": ""},
        },
        [],
    )

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        session = ctx.session
        if session is None:
            return fail(call_id, "no active session")
        files: dict[str, str] = {}
        for raw in params.get("paths", []):
            try:
                path = ctx.resolve(str(raw))
                if path.is_file():
                    rel = path.relative_to(ctx.cwd.resolve()).as_posix()
                    files[rel] = path.read_text(encoding="utf-8", errors="replace")
                else:
                    files[str(raw)] = ""
            except (OSError, PermissionError) as exc:
                return fail(call_id, str(exc))
        cp = Checkpoint(
            files=files,
            messages_len=len(session.messages),
            label=str(params.get("label", "")),
        )
        session.checkpoints.append(cp)
        return ok(call_id, f"checkpoint {cp.id} ({len(files)} files)")


class RewindTool:
    name = "rewind"
    description = (
        "Restore workspace files from a checkpoint. Omit id to use the latest."
    )
    input_schema = schema({"id": {"type": "string", "default": ""}}, [])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        session = ctx.session
        if session is None:
            return fail(call_id, "no active session")
        if not session.checkpoints:
            return fail(call_id, "no checkpoints available")
        wanted = str(params.get("id", ""))
        cp = (
            next((c for c in session.checkpoints if c.id == wanted), None)
            if wanted
            else session.checkpoints[-1]
        )
        if cp is None:
            return fail(call_id, f"checkpoint not found: {wanted}")
        restored: list[str] = []
        for rel, content in cp.files.items():
            try:
                path = ctx.resolve(rel)
                if content == "":
                    if path.exists():
                        path.unlink()
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(content, encoding="utf-8")
                restored.append(rel)
            except (OSError, PermissionError) as exc:
                return fail(call_id, str(exc))
        del session.messages[cp.messages_len :]
        ctx.emit("rewound", {"id": cp.id, "files": restored})
        return ok(
            call_id,
            f"rewound {cp.id}: {len(restored)} files, messages truncated to {cp.messages_len}",
        )


class SessionInfoTool:
    name = "session_info"
    description = "Report session id, cwd, message count, TODOs and checkpoint count."
    input_schema = schema({}, [])

    def execute(self, params: dict[str, Any], ctx: ToolContext) -> ToolResult:
        call_id = str(params.get("call_id", ""))
        session = ctx.session
        info = {
            "cwd": str(ctx.cwd),
            "session": session.id if session else None,
            "messages": len(session.messages) if session else 0,
            "todos": len(session.todos) if session else 0,
            "checkpoints": len(session.checkpoints) if session else 0,
            "platform": os.name,
        }
        return ok(call_id, json.dumps(info, indent=2))


BUILTIN_CLASSES = [
    ReadFileTool,
    ListDirTool,
    GlobTool,
    GrepTool,
    WriteFileTool,
    EditFileTool,
    BashTool,
    WebFetchTool,
    TodoWriteTool,
    CheckpointTool,
    RewindTool,
    SessionInfoTool,
]
