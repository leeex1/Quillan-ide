"""Optional enhanced TUI: prompt_toolkit input + rich markdown output."""

from __future__ import annotations

from typing import Any

from prompt_toolkit import PromptSession
from prompt_toolkit.history import InMemoryHistory
from rich.console import Console
from rich.markdown import Markdown

from ..config import Config
from .base import TUIBase


class RichTUI(TUIBase):
    name = "rich"

    def __init__(self) -> None:
        self.console = Console()
        self.session: PromptSession[str] = PromptSession(history=InMemoryHistory())

    def banner(self, agent: Any, config: Config) -> None:
        self.console.print("[bold cyan]quillancode 1.0.0[/bold cyan] — rich mode")
        self.console.print(
            f"provider={getattr(agent.provider, 'name', '?')} cwd={agent.cwd}"
        )

    def run(self, agent: Any, config: Config) -> int:
        from .plain import PlainTUI

        fallback = PlainTUI(use_color=False)
        self.banner(agent, config)
        while True:
            try:
                raw = self.session.prompt("qc> ")
            except (EOFError, KeyboardInterrupt):
                return 0
            line = raw.strip()
            if not line:
                continue
            if line.startswith("/"):
                if fallback.command(agent, config, line) == "exit":
                    return 0
                continue
            answer = agent.run(line)
            self.console.print(Markdown(answer or "(no output)"))
