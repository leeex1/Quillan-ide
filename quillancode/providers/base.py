"""Provider adapter protocol."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from ..models import Message, ProviderSpec


@runtime_checkable
class ProviderAdapter(Protocol):
    name: str

    def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, Any]],
        *,
        stream: bool = False,
    ) -> Message: ...

    def list_models(self) -> list[str]: ...


class ProviderError(RuntimeError):
    """Raised when a provider request fails after all fallbacks are exhausted."""
