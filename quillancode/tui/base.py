"""Shared TUI interface."""

from __future__ import annotations

from typing import Any

from ..config import Config


class TUIBase:
    name = "base"

    def banner(self, agent: Any, config: Config) -> None:
        raise NotImplementedError

    def run(self, agent: Any, config: Config) -> int:
        raise NotImplementedError
