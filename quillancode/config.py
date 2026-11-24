"""Configuration loading: TOML (primary) and JSON (fallback), zero dependencies."""

from __future__ import annotations

import copy
import json
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .models import ProviderSpec

DEFAULT_PROVIDERS: dict[str, dict[str, Any]] = {
    "mock": {"kind": "mock", "model": "mock", "temperature": 0.0},
    "opencode-account": {"kind": "opencode_account", "model": "hy4-flash-free"},
    "opencode": {
        "kind": "openai_compat",
        "base_url": "https://api.opencode.ai/v1",
        "model": "opencode/general",
        "api_key_env": "OPENCODE_API_KEY",
    },
    "openai": {
        "kind": "openai_compat",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "api_key_env": "OPENAI_API_KEY",
    },
    "deepseek": {
        "kind": "openai_compat",
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "kind": "openai_compat",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen2.5-coder",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "anthropic": {
        "kind": "anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "model": "claude-sonnet-4-20250514",
        "api_key_env": "ANTHROPIC_API_KEY",
    },
    "ollama": {
        "kind": "openai_compat",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder",
    },
}

DEFAULT_CONFIG: dict[str, Any] = {
    "provider": {"default": "mock"},
    "providers": copy.deepcopy(DEFAULT_PROVIDERS),
    "permissions": {
        "default": "ask",
        "rules": {
            "read_file": "allow",
            "list_dir": "allow",
            "glob": "allow",
            "grep": "allow",
            "write_file": "ask",
            "edit_file": "ask",
            "bash": "ask",
            "todo_write": "allow",
            "checkpoint": "allow",
            "rewind": "ask",
        },
        "blocked_patterns": ["bash:rm -rf", "bash:format", "bash:del /s"],
    },
    "mcp": {"servers": {}},
    "council": {"agents": 3, "judge": "default", "rounds": 1},
    "skills": {"paths": []},
    "lsp": {"servers": {}},
    "server": {"workspace": "."},
    "settings": {
        "compact_threshold": 0.8,
        "checkpoint_on_write": True,
        "max_tool_steps": 20,
        "auto_fallback": True,
        "telemetry": True,
        "theme": "auto",
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def _to_toml(data: dict[str, Any], prefix: str = "") -> str:
    """Minimal deterministic TOML serializer for nested config dicts."""
    lines: list[str] = []
    tables: list[str] = []
    for key, value in data.items():
        if isinstance(value, dict):
            if not value:
                lines.append(f"{key} = {{}}")
                continue
            tables.append(f"[{prefix}{key}]" if not prefix else f"[{prefix}.{key}]")
            tables.append(_to_toml(value, f"{prefix}.{key}" if prefix else str(key)))
        elif isinstance(value, bool):
            lines.append(f"{key} = {str(value).lower()}")
        elif isinstance(value, (int, float)):
            lines.append(f"{key} = {value}")
        else:
            lines.append(f"{key} = {json.dumps(value, ensure_ascii=False)}")
    parts: list[str] = []
    if lines:
        parts.append("\n".join(lines))
    for table in tables:
        parts.append(table.rstrip())
    return "\n\n".join(p for p in parts if p.strip()) + "\n"


def _expand_env(value: Any) -> Any:
    if isinstance(value, str):
        return os.path.expandvars(value)
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    return value


@dataclass
class Config:
    data: dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULT_CONFIG))
    path: Path | None = None

    @classmethod
    def load(
        cls, path: str | Path | None = None, cwd: str | Path | None = None
    ) -> "Config":
        base = Path(cwd).expanduser() if cwd is not None else Path.cwd()
        candidates: list[Path] = []
        if path:
            candidates.append(Path(path).expanduser())
        else:
            env = os.environ.get("QUILLANCODE_CONFIG")
            if env:
                candidates.append(Path(env).expanduser())
            candidates.extend(
                [
                    base / "quillancode.toml",
                    base / "quillancode.json",
                    base / ".quillancode" / "config.toml",
                    base / ".quillancode" / "config.json",
                    Path.home() / ".quillancode" / "config.toml",
                    Path.home() / ".quillancode" / "config.json",
                ]
            )
        raw: dict[str, Any] = {}
        used: Path | None = None
        for candidate in candidates:
            if candidate.is_file():
                text = candidate.read_text(encoding="utf-8")
                if candidate.suffix.lower() == ".json":
                    raw = json.loads(text)
                else:
                    raw = tomllib.loads(text)
                used = candidate
                break
        return cls(data=_deep_merge(DEFAULT_CONFIG, _expand_env(raw)), path=used)

    def save(self, path: str | Path | None = None) -> Path:
        target = (
            Path(path).expanduser()
            if path
            else (self.path or Path.home() / ".quillancode" / "config.toml")
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = _expand_env(self.data)
        if target.suffix.lower() == ".json":
            text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        else:
            text = _to_toml(payload)
        target.write_text(text, encoding="utf-8")
        self.path = target
        return target

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    @property
    def providers(self) -> dict[str, ProviderSpec]:
        result: dict[str, ProviderSpec] = {}
        for name, spec in self.get("providers", {}).items():
            result[str(name)] = ProviderSpec.from_dict(str(name), spec)
        return result

    @property
    def default_provider(self) -> str:
        return str(self.get("provider.default", "mock"))

    def redacted(self) -> dict[str, Any]:
        """Config safe to print: API key values never appear, only env var names."""
        data = copy.deepcopy(self.data)
        for spec in data.get("providers", {}).values():
            if isinstance(spec, dict):
                spec.pop("api_key", None)
                spec.pop("token", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        return cls(data=_deep_merge(DEFAULT_CONFIG, _expand_env(data)))
