"""Static shell completion script generation (no external dependency)."""

from __future__ import annotations

COMMANDS = [
    "chat",
    "run",
    "council",
    "config",
    "agents",
    "commands",
    "tools",
    "skills",
    "mcp",
    "adapters",
    "doctor",
    "models",
    "session",
    "seats",
    "stats",
    "auth",
    "plugin",
    "serve",
    "web",
    "acp",
    "diff",
    "github",
    "completion",
]


def generate(shell: str) -> str:
    if shell == "bash":
        return (
            "_quillancode() { COMPREPLY=( $(compgen -W '"
            + " ".join(COMMANDS)
            + '\' -- "${COMP_WORDS[COMP_CWORD]}") ); }\n'
            "complete -F _quillancode quillancode\n"
        )
    if shell == "zsh":
        return "#compdef quillancode\n_arguments '1: :(" + " ".join(COMMANDS) + ")'\n"
    if shell in {"powershell", "pwsh"}:
        body = "\n".join(f"    '{cmd}'" for cmd in COMMANDS)
        return (
            "Register-ArgumentCompleter -Native -CommandName quillancode -ScriptBlock {\n"
            "  param($wordToComplete)\n"
            "  @(\n" + body + '\n  ) | Where-Object { $_ -like "$wordToComplete*" }\n'
            "}\n"
        )
    raise ValueError(f"unsupported shell: {shell}")
