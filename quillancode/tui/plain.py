"""Stdlib-only interactive REPL with slash commands and ANSI-light output."""

from __future__ import annotations

import importlib.util
import sys
from typing import Any

from ..adapters import report as adapter_report
from ..config import Config
from ..models import Message
from ..skills import SkillLoader
from .base import TUIBase


class PlainTUI(TUIBase):
    name = "plain"

    def __init__(self, use_color: bool = True) -> None:
        self.use_color = use_color and sys.stdout.isatty()

    def _paint(self, text: str, code: str) -> str:
        if not self.use_color:
            return text
        return f"\033[{code}m{text}\033[0m"

    def banner(self, agent: Any, config: Config) -> None:
        provider = getattr(agent.provider, "name", type(agent.provider).__name__)
        print(self._paint("quillancode 1.0.0 — sovereign code assistant", "1;36"))
        print(
            f"  provider={provider}  cwd={agent.cwd}  tools={len(agent.tools.names())}"
        )
        print("  /help for commands · /exit to leave")

    def run(self, agent: Any, config: Config) -> int:
        self.banner(agent, config)
        while True:
            try:
                raw = input(self._paint("qc> ", "36"))
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            line = raw.strip()
            if not line:
                continue
            if line.startswith("/"):
                result = self.command(agent, config, line)
                if result == "exit":
                    return 0
                continue
            try:
                answer = agent.run(line)
            except Exception as exc:  # REPL boundary: keep the session alive
                print(self._paint(f"[error] {type(exc).__name__}: {exc}", "31"))
                continue
            print(self._paint(answer or "(no output)", "32"))
            print(
                self._paint(
                    f"--- {len(agent.messages)} messages / "
                    f"{len(agent.session.checkpoints)} checkpoints",
                    "90",
                )
            )

    def command(self, agent: Any, config: Config, line: str) -> str:
        parts = line[1:].split(maxsplit=1)
        cmd = parts[0].lower() if parts else ""
        arg = parts[1] if len(parts) > 1 else ""
        if cmd in {"exit", "quit", "q"}:
            return "exit"
        if cmd in {"help", "?"}:
            print(
                "/help  /exit  /provider <name>  /agent <id>  /agents  /tools  "
                "/todos  /trace  /checkpoint  /rewind [id]  /skills  /mcp  "
                "/adapters  /clear"
            )
        elif cmd in {"agent", "agents"}:
            from ..agents import AgentLoader

            loader = AgentLoader()
            if cmd == "agents" or not arg:
                for item in loader.discover():
                    print(f"{item.id} [{item.source}] {item.description[:70]}")
            else:
                try:
                    agent.system_prompt = loader.load(arg)
                    agent.messages = [m for m in agent.messages if m.role == "system"]
                    agent.messages.insert(
                        0,
                        Message(role="system", content=agent.system_prompt),
                    )
                    print(f"agent -> {arg}")
                except KeyError as exc:
                    print(f"[error] {exc}")
        elif cmd == "provider":
            try:
                agent.provider = agent.registry.get(arg or None)
                print(f"provider -> {getattr(agent.provider, 'name', arg)}")
            except Exception as exc:
                print(f"[error] {exc}")
        elif cmd == "tools":
            print(agent.tools.describe())
        elif cmd == "todos":
            for todo in agent.session.todos:
                print(f"[{todo.status}] {todo.step} -> verify: {todo.verify}")
            if not agent.session.todos:
                print("(no todos)")
        elif cmd == "trace":
            print(agent.render_trace()[-8000:])
        elif cmd == "checkpoint":
            print(f"checkpoints: {[c.id for c in agent.session.checkpoints]}")
        elif cmd == "rewind":
            from ..models import ToolCall

            result = agent.tools.execute_call(
                ToolCall(id="repl_rewind", name="rewind", arguments={"id": arg}),
                agent.ctx,
                agent.gate,
                force=True,
            )
            print(result.output or result.error)
        elif cmd == "skills":
            skills = SkillLoader(config).discover()
            for skill in skills:
                print(f"{skill.name}: {skill.description[:100]}")
            if not skills:
                print("(no skills discovered)")
        elif cmd == "mcp":
            servers = config.get("mcp.servers", {}) or {}
            print(
                "\n".join(
                    f"{k}: {v.get('command')} {v.get('args', [])}"
                    for k, v in servers.items()
                )
                or "(no MCP servers)"
            )
        elif cmd == "adapters":
            print(adapter_report())
        elif cmd == "clear":
            agent.messages = [m for m in agent.messages if m.role == "system"]
            agent.session.messages = []
            print("context cleared")
        else:
            from ..commands import CommandLoader

            try:
                custom = CommandLoader().get(cmd, str(agent.cwd))
                answer = agent.run(custom.render(arg))
                print(answer)
            except KeyError:
                print(f"unknown command: /{cmd} (try /help)")
        return "continue"


def preferred_tui() -> type[TUIBase]:
    """Return rich_tui when optional deps exist, else the stdlib REPL."""
    have_rich = bool(importlib.util.find_spec("rich")) and bool(
        importlib.util.find_spec("prompt_toolkit")
    )
    if have_rich:
        try:
            from .rich_tui import RichTUI

            return RichTUI
        except Exception:
            return PlainTUI
    return PlainTUI
