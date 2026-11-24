"""Risk-tiered permission gate: allow / ask / deny, with session allowlists."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from ..config import Config

TIER_RANK = {"low": 0, "medium": 1, "high": 2, "blocked": 3}

TOOL_TIERS: dict[str, str] = {
    "read_file": "low",
    "list_dir": "low",
    "glob": "low",
    "grep": "low",
    "todo_write": "low",
    "checkpoint": "low",
    "session_info": "low",
    "write_file": "medium",
    "edit_file": "medium",
    "apply_patch": "medium",
    "rewind": "high",
    "bash": "high",
    "mcp_call": "medium",
    "webfetch": "medium",
    "git_status": "low",
    "git_diff": "low",
    "git_log": "low",
    "git_add": "medium",
    "git_commit": "high",
}

AskFn = Callable[[str], bool]


@dataclass
class Decision:
    action: str  # allow | ask | deny
    tier: str
    reason: str


@dataclass
class PermissionGate:
    config: Config
    ask_fn: AskFn = lambda prompt: False
    session_allowed: set[str] = field(default_factory=set)
    audit: list[dict[str, Any]] = field(default_factory=list)

    def tier(self, tool_name: str, params: dict[str, Any]) -> str:
        tier = TOOL_TIERS.get(tool_name, "medium")
        rendered = f"{tool_name}:{' '.join(str(v) for v in params.values() if isinstance(v, str))}"
        patterns = self.config.get("permissions.blocked_patterns", []) or []
        for pattern in patterns:
            try:
                if re.search(str(pattern), rendered, flags=re.IGNORECASE):
                    return "blocked"
            except re.error:
                continue
        return tier

    def decide(self, tool_name: str, params: dict[str, Any]) -> Decision:
        tier = self.tier(tool_name, params)
        if tier == "blocked":
            decision = Decision("deny", tier, "matches blocked pattern")
        elif (
            f"{tool_name}:*" in self.session_allowed
            or tool_name in self.session_allowed
        ):
            decision = Decision("allow", tier, "session allowlist")
        else:
            rules = self.config.get("permissions.rules", {}) or {}
            action = str(
                rules.get(tool_name, self.config.get("permissions.default", "ask"))
            )
            if action == "ask":
                prompt = f"Allow {tool_name} ({tier} risk) args={params}? [y/N]: "
                if self.ask_fn(prompt):
                    action = "allow"
                    self.session_allowed.add(tool_name)
            decision = Decision(action, tier, "policy")
        self.audit.append(
            {
                "tool": tool_name,
                "tier": tier,
                "action": decision.action,
                "reason": decision.reason,
            }
        )
        return decision
