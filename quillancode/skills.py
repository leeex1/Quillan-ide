"""Filesystem skill loader (Markdown skills with optional simple frontmatter)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .config import Config

_FM = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


@dataclass
class Skill:
    name: str
    description: str
    path: Path
    body: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "path": str(self.path),
        }


class SkillLoader:
    def __init__(self, config: Config) -> None:
        self.config = config

    def default_paths(self) -> list[Path]:
        home = Path.home()
        return [
            home / ".config" / "opencode" / "skills",
            home / ".claude" / "skills",
            Path("C:/02_QUILLAN/.gemini/skills"),
            Path("C:/02_QUILLAN/.windsurf/skills"),
            Path("C:/02_QUILLAN/.claude/skills"),
            Path("C:/02_QUILLAN/04- quillan-sovereign-skills-and-swarm"),
        ]

    def discover(self) -> list[Skill]:
        roots = [
            Path(p).expanduser() for p in (self.config.get("skills.paths", []) or [])
        ]
        roots.extend(self.default_paths())
        found: dict[str, Skill] = {}
        for root in roots:
            if not root.is_dir():
                continue
            for skill_file in sorted(root.rglob("SKILL.md")) + sorted(
                root.rglob("skill.md")
            ):
                try:
                    text = skill_file.read_text(encoding="utf-8", errors="replace")
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
                name = meta.get("name") or skill_file.parent.name
                if name in found:
                    continue
                found[name] = Skill(
                    name=name,
                    description=meta.get("description", "")[:240],
                    path=skill_file,
                    body=body[:20_000],
                )
        return sorted(found.values(), key=lambda s: s.name)

    def load(self, name: str) -> str:
        for skill in self.discover():
            if skill.name == name:
                return f"# Skill: {skill.name}\n\n{skill.body}"
        raise KeyError(f"skill not found: {name}")
