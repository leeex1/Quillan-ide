"""Import provider/agent configuration from installed assistants.

Security invariant (C13-WARDEN): literal API keys found in upstream configs are
never copied into quillancode config, logs, or CLI output. Only the fact that a
key existed is reported; the imported spec references an environment variable.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config

_LINE_COMMENT = re.compile(r"^\s*//.*$", re.M)
_TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def parse_jsonc(text: str) -> dict[str, Any]:
    """Parse JSON-with-comments and tolerant trailing commas."""
    cleaned = _LINE_COMMENT.sub("", text)
    cleaned = _TRAILING_COMMA.sub(r"\1", cleaned)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def _env_name(source: str, name: str) -> str:
    safe = re.sub(r"[^A-Z0-9]+", "_", f"{source}_{name}".upper()).strip("_")
    return f"QUILLANCODE_KEY_{safe}"


@dataclass
class ImportReport:
    source: str
    path: str
    imported: list[str] = field(default_factory=list)
    env_vars: dict[str, str] = field(default_factory=dict)
    redacted_secrets: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "path": self.path,
            "imported": self.imported,
            "env_vars": self.env_vars,
            "redacted_secrets": self.redacted_secrets,
            "notes": self.notes,
        }


def import_opencode(config: Config, path: str | Path | None = None) -> ImportReport:
    target = (
        Path(path).expanduser()
        if path
        else (Path.home() / ".config" / "opencode" / "opencode.jsonc")
    )
    if not target.is_file():
        raise FileNotFoundError(f"opencode config not found: {target}")
    data = parse_jsonc(target.read_text(encoding="utf-8", errors="replace"))
    report = ImportReport(source="opencode", path=str(target))
    providers = data.get("provider") or {}
    for name, raw in providers.items():
        if not isinstance(raw, dict):
            continue
        options = raw.get("options") or {}
        base_url = str(options.get("baseURL") or "")
        has_key = bool(options.get("apiKey"))
        models = list((raw.get("models") or {}).keys())
        if not base_url:
            report.notes.append(f"{name}: no baseURL, skipped")
            continue
        key_name = _env_name("opencode", str(name))
        spec = {
            "kind": "openai_compat",
            "base_url": base_url,
            "model": str(models[0])
            if models
            else str(data.get("model", "")).split("/", 1)[-1],
            "api_key_env": key_name,
        }
        config.data.setdefault("providers", {})[str(name)] = spec
        config.data.setdefault("provider", {})["default"] = str(name)
        report.imported.append(str(name))
        report.env_vars[key_name] = "<set this environment variable>"
        if has_key:
            report.redacted_secrets += 1
    if not report.imported:
        report.notes.append("no importable providers found")
    return report


def import_qwen(config: Config, path: str | Path | None = None) -> ImportReport:
    target = (
        Path(path).expanduser() if path else Path("C:/02_QUILLAN/.qwen/config.yaml")
    )
    if not target.is_file():
        raise FileNotFoundError(f"qwen config not found: {target}")
    text = target.read_text(encoding="utf-8", errors="replace")
    model = re.search(r"^\s*name:\s*[\"']?([^\"'\n]+)", text, re.M)
    base = re.search(r"^\s*base_url:\s*[\"']?([^\"'\n]+)", text, re.M)
    if not model:
        raise ValueError("qwen config has no model.name")
    key_name = _env_name("qwen", "dashscope")
    config.data.setdefault("providers", {})["qwen-imported"] = {
        "kind": "openai_compat",
        "base_url": (
            base.group(1).strip()
            if base
            else "https://dashscope.aliyuncs.com/compatible-mode/v1"
        ),
        "model": model.group(1).strip(),
        "api_key_env": key_name,
    }
    return ImportReport(
        source="qwen",
        path=str(target),
        imported=["qwen-imported"],
        env_vars={key_name: "<set this environment variable>"},
        notes=["source API keys were never read"],
    )


def import_gemini(config: Config, path: str | Path | None = None) -> ImportReport:
    target = (
        Path(path).expanduser() if path else Path("C:/02_QUILLAN/.gemini/settings.json")
    )
    if not target.is_file():
        raise FileNotFoundError(f"gemini config not found: {target}")
    data = json.loads(target.read_text(encoding="utf-8", errors="replace"))
    report = ImportReport(source="gemini", path=str(target))
    report.notes.append(
        "Gemini CLI uses OAuth-personal auth; no portable API endpoint to import. "
        "Use the 'gemini' adapter bridge instead."
    )
    report.notes.append(
        f"approval mode: {data.get('general', {}).get('defaultApprovalMode', 'unknown')}"
    )
    return report


IMPORTERS = {
    "opencode": import_opencode,
    "qwen": import_qwen,
    "gemini": import_gemini,
}


def import_config(
    config: Config, source: str, path: str | Path | None = None
) -> ImportReport:
    fn = IMPORTERS.get(source)
    if fn is None:
        raise KeyError(f"unknown import source: {source}")
    return fn(config, path)
