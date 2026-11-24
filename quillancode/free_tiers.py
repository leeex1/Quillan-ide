"""Free-tier provider presets and automatic fallback selection.

Design goal: quillancode should use whatever free access the user already has,
and any model can be plugged in without editing a config file by hand.
"""

from __future__ import annotations

import os
import urllib.request
from dataclasses import dataclass
from typing import Any

from .auth import AuthStore
from .config import Config
from .models import ProviderSpec

# (name, base_url, model, api_key_env, probe path)
FREE_TIERS: list[dict[str, Any]] = [
    {
        "name": "opencode-account",
        "kind": "opencode_account",
        "base_url": "",
        "model": "hy4-flash-free",
        "api_key_env": "",
        "note": "user's running OpenCode account/session (no API key needed)",
    },
    {
        "name": "gemini-free",
        "kind": "openai_compat",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "model": "gemini-flash-lite-latest",
        "api_key_env": "GEMINI_API_KEY",
        "note": "Google AI Studio free tier, OpenAI-compatible endpoint",
    },
    {
        "name": "openrouter-free",
        "kind": "openai_compat",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "inclusionai/ling-3.2-flash:free",
        "api_key_env": "OPENROUTER_API_KEY",
        "note": "OpenRouter :free models",
    },
    {
        "name": "ollama-local",
        "kind": "openai_compat",
        "base_url": "http://localhost:11434/v1",
        "model": "qwen2.5-coder",
        "api_key_env": "",
        "note": "local Ollama, no key required",
    },
]


@dataclass
class FreeProvider:
    name: str
    spec: ProviderSpec
    note: str
    available: bool
    reason: str = ""


def _key_available(spec: ProviderSpec) -> bool:
    if not spec.api_key_env:
        return True
    return bool(os.environ.get(spec.api_key_env) or AuthStore().get(spec.name))


def _local_up(base_url: str) -> bool:
    import urllib.error

    try:
        with urllib.request.urlopen(
            base_url.rstrip("/") + "/models", timeout=2
        ) as resp:
            resp.read(1)
        return True
    except urllib.error.HTTPError as exc:
        exc.close()
        return False
    except Exception:
        return False


def discover(config: Config | None = None) -> list[FreeProvider]:
    """Return free-tier presets with availability, merged with user overrides."""
    config = config or Config.from_dict({})
    out: list[FreeProvider] = []
    for preset in FREE_TIERS:
        override = (config.get("providers", {}) or {}).get(preset["name"], {})
        spec = ProviderSpec.from_dict(preset["name"], {**preset, **override})
        available = _key_available(spec)
        reason = ""
        if available and spec.kind == "opencode_account":
            from .opencode_account import SERVICE_FILE, discover_base_url

            if not SERVICE_FILE.is_file():
                available, reason = False, "OpenCode desktop service not detected"
            else:
                try:
                    import urllib.error
                    import urllib.request

                    try:
                        urllib.request.urlopen(
                            discover_base_url() + "/api/project", timeout=3
                        ).read(1)
                    except urllib.error.HTTPError as exc:
                        exc.close()  # server answered; auth is handled by the adapter
                except Exception:
                    available, reason = False, "OpenCode desktop server not reachable"
        if available and spec.api_key_env == "" and "localhost" in spec.base_url:
            available = _local_up(spec.base_url)
            reason = "" if available else "local server not running"
        if not available:
            reason = (
                f"missing credential {spec.api_key_env}"
                if spec.api_key_env
                else reason or "unavailable"
            )
        out.append(
            FreeProvider(preset["name"], spec, preset["note"], available, reason)
        )
    return out


def preferred(config: Config | None = None) -> FreeProvider | None:
    """First available free tier, in preference order."""
    for provider in discover(config):
        if provider.available:
            return provider
    return None


def install(config: Config, name: str | None = None) -> FreeProvider:
    """Write a free-tier preset into the config and return it."""
    chosen = preferred(config)
    if chosen is None:
        raise RuntimeError(
            "no free tier available: set GEMINI_API_KEY or OPENROUTER_API_KEY, or start Ollama"
        )
    target = name or chosen.name
    config.data.setdefault("providers", {})[target] = chosen.spec.to_dict()
    config.data.setdefault("provider", {})["default"] = target
    return chosen


def plug(
    config: Config,
    name: str,
    base_url: str,
    model: str,
    api_key_env: str = "",
    kind: str = "openai_compat",
) -> ProviderSpec:
    """Register an arbitrary OpenAI-compatible/Anthropic model endpoint."""
    spec = ProviderSpec(
        name=name,
        kind=kind,
        base_url=base_url,
        model=model,
        api_key_env=api_key_env,
    )
    config.data.setdefault("providers", {})[name] = spec.to_dict()
    config.data.setdefault("provider", {})["default"] = name
    return spec
