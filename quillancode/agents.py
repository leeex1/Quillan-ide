"""Load reusable agent definitions from opencode / Claude Code markdown files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class AgentDef:
    id: str
    name: str
    description: str
    source: str
    path: Path
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "source": self.source,
            "path": str(self.path),
        }


class AgentLoader:
    ROOTS = [
        ("opencode-user", Path.home() / ".config" / "opencode" / "agent"),
        ("opencode-project", Path("C:/02_QUILLAN/.opencode/agent")),
        ("claude-user", Path.home() / ".claude" / "agents"),
        ("windsurf", Path("C:/02_QUILLAN/.windsurf/agents")),
    ]

    def discover(self) -> list[AgentDef]:
        found: dict[str, AgentDef] = {}
        for source, root in self.ROOTS:
            if not root.is_dir():
                continue
            for path in sorted(root.rglob("*.md")):
                try:
                    text = path.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    continue
                meta: dict[str, str] = {}
                body = text
                match = _FM.match(text)
                if match:
                    for line in match.group(1).splitlines():
                        if ":" in line:
                            key, value = line.split(":", 1)
                            meta[key.strip().lower()] = value.strip().strip("\"'")
                    body = text[match.end() :]
                agent_id = path.stem
                if agent_id in found:
                    continue
                found[agent_id] = AgentDef(
                    id=agent_id,
                    name=meta.get("name", agent_id),
                    description=meta.get("description", "")[:240],
                    source=source,
                    path=path,
                    body=body[:30_000],
                )
        return sorted(found.values(), key=lambda a: a.id)

    def load(self, agent_id: str) -> str:
        for agent in self.discover():
            if agent.id == agent_id:
                return agent.body
        raise KeyError(f"agent not found: {agent_id}")
