"""Provider factory: spec -> adapter, with BYO-key validation."""

from __future__ import annotations

import os
from typing import Any

from ..config import Config
from ..models import ProviderSpec
from .anthropic import AnthropicProvider
from .base import ProviderAdapter, ProviderError
from .mock import MockProvider
from ..opencode_account import OpenCodeAccountProvider
from .openai_compat import OpenAICompatProvider

_BUILDERS = {
    "mock": MockProvider,
    "openai_compat": OpenAICompatProvider,
    "openai-compatible": OpenAICompatProvider,
    "anthropic": AnthropicProvider,
    "opencode": OpenAICompatProvider,
    "opencode_account": OpenCodeAccountProvider,
}


def build_provider(spec: ProviderSpec) -> ProviderAdapter:
    kind = spec.kind.lower()
    builder = _BUILDERS.get(kind)
    if builder is None:
        raise ProviderError(f"unknown provider kind '{kind}' for '{spec.name}'")
    adapter = builder(spec)
    if not isinstance(adapter, ProviderAdapter):
        raise ProviderError(
            f"provider '{spec.name}' does not implement ProviderAdapter"
        )
    return adapter


class ProviderRegistry:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._cache: dict[str, ProviderAdapter] = {}

    def get(self, name: str | None = None) -> ProviderAdapter:
        name = name or self.config.default_provider
        if name in self._cache:
            return self._cache[name]
        specs = self.config.providers
        if name not in specs:
            raise ProviderError(
                f"unknown provider '{name}'. Available: {', '.join(sorted(specs)) or '(none)'}"
            )
        adapter = build_provider(specs[name])
        self._cache[name] = adapter
        return adapter

    def available(self) -> list[str]:
        return sorted(self.config.providers)

    def ready(self) -> dict[str, bool]:
        """Report which providers have credentials, without leaking values."""
        out: dict[str, bool] = {}
        for name, spec in self.config.providers.items():
            if spec.kind == "mock" or not spec.api_key_env:
                out[name] = True
            else:
                from ..auth import AuthStore

                out[name] = bool(
                    os.environ.get(spec.api_key_env) or AuthStore().get(name)
                )
        return out

    def spec(self, name: str | None = None) -> ProviderSpec:
        name = name or self.config.default_provider
        return self.config.providers[name]


__all__ = ["ProviderRegistry", "build_provider", "ProviderError", "ProviderAdapter"]
