"""Markdown slash-command loader compatible with opencode's command/*.md format."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Command:
    name: str
    description: str
    source: str
    path: Path
    template: str

    def render(self, arguments: str = "") -> str:
        text = self.template
        text = text.replace("$ARGUMENTS", arguments)
        tokens = arguments.split()
        for i, token in enumerate(tokens, 1):
            text = text.replace(f"${i}", token)
        return text.strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "path": str(self.path),
        }


class CommandLoader:
    def roots(self, cwd: str | Path | None = None) -> list[tuple[str, Path]]:
        base = Path(cwd) if cwd else Path.cwd()
        return [
            ("workspace", base / ".quillancode" / "command"),
            ("workspace", base / ".opencode" / "command"),
            ("opencode-user", Path.home() / ".config" / "opencode" / "command"),
            ("project", Path("C:/02_QUILLAN/.opencode/command")),
            ("claude-user", Path.home() / ".claude" / "commands"),
        ]

    def discover(self, cwd: str | Path | None = None) -> list[Command]:
        found: dict[str, Command] = {}
        for source, root in self.roots(cwd):
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.md")):
                text = path.read_text(encoding="utf-8", errors="replace")
                meta: dict[str, str] = {}
                template = text
                match = _FM.match(text)
                if match:
                    for line in match.group(1).splitlines():
                        if ":" in line:
                            key, value = line.split(":", 1)
                            meta[key.strip().lower()] = value.strip().strip("\"'")
                    template = text[match.end() :]
                name = path.stem
                if name not in found:
                    found[name] = Command(
                        name=name,
                        description=meta.get("description", ""),
                        source=source,
                        path=path,
                        template=template,
                    )
        return sorted(found.values(), key=lambda c: c.name)

    def get(self, name: str, cwd: str | Path | None = None) -> Command:
        for command in self.discover(cwd):
            if command.name == name:
                return command
        raise KeyError(f"command not found: {name}")
