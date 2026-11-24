"""Deterministic context budgeting and compaction."""

from __future__ import annotations

from typing import Any

from .models import Message


def estimate_tokens(text: str) -> int:
    """Conservative estimate: ~4 characters per token."""
    return max(1, len(text) // 4)


def context_usage(messages: list[Message], budget: int = 128_000) -> float:
    total = sum(estimate_tokens(m.content) for m in messages)
    return min(1.0, total / max(1, budget))


def compact(
    messages: list[Message],
    threshold: float = 0.8,
    budget: int = 128_000,
    keep_recent: int = 8,
) -> tuple[list[Message], bool]:
    """Collapse older turns into one summary message when usage crosses threshold.

    Returns (messages, changed). Deterministic, no network required.
    """
    if context_usage(messages, budget) < threshold or len(messages) <= keep_recent + 2:
        return messages, False
    head = [m for m in messages if m.role == "system"]
    tail = messages[-keep_recent:]
    middle = messages[len(head) : len(messages) - keep_recent]
    if not middle:
        return messages, False
    lines = [f"- {m.role}: {m.content[:280].replace(chr(10), ' ')}" for m in middle]
    summary = (
        "[context compaction] Earlier turns condensed for continuity:\n"
        + "\n".join(lines[:60])
        + f"\n({len(middle)} messages condensed)"
    )
    return head + [Message(role="system", content=summary)] + tail, True
