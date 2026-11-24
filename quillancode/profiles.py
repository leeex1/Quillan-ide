"""Profile/bundle composition: ordered layers with patch overlays (DSH-style)."""

from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import Config

PROFILES_DIR = Path.home() / ".quillancode" / "profiles"


@dataclass
class Profile:
    name: str
    bundles: list[str] = field(default_factory=list)
    patches: list[str] = field(default_factory=list)
    path: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "bundles": self.bundles,
            "patches": self.patches,
            "path": str(self.path) if self.path else "",
        }


def _merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def discover() -> list[Profile]:
    result: list[Profile] = []
    if PROFILES_DIR.is_dir():
        for path in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            result.append(
                Profile(
                    name=str(data.get("name", path.stem)),
                    bundles=[str(b) for b in data.get("bundles", [])],
                    patches=[str(p) for p in data.get("patches", [])],
                    path=path,
                )
            )
    if not result:
        result.append(Profile(name="default", bundles=["base"], patches=[]))
    return result


def compose(config: Config, name: str | None = None) -> dict[str, Any]:
    """Compose config from ordered bundles then patch overlays; no network."""
    profile = next((p for p in discover() if p.name == (name or "default")), None)
    if profile is None:
        raise KeyError(f"profile not found: {name}")
    merged: dict[str, Any] = {}
    for bundle in profile.bundles:
        path = Path(bundle)
        if not path.is_absolute():
            path = PROFILES_DIR / f"{bundle}.json"
        if path.is_file():
            try:
                merged = _merge(merged, json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
    if not merged:
        merged = copy.deepcopy(config.redacted())
    for patch in profile.patches:
        path = Path(patch)
        if path.is_file():
            try:
                merged = _merge(merged, json.loads(path.read_text(encoding="utf-8")))
            except (ValueError, OSError):
                continue
    return merged


def create(name: str, bundles: list[str], patches: list[str] | None = None) -> Profile:
    PROFILES_DIR.mkdir(parents=True, exist_ok=True)
    path = PROFILES_DIR / f"{name}.json"
    profile = Profile(name=name, bundles=bundles, patches=patches or [], path=path)
    path.write_text(json.dumps(profile.to_dict(), indent=2), encoding="utf-8")
    return profile
