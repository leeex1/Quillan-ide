"""Command-line entry point for quillancode."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .adapters import delegate, detect, report as adapter_report
from .agent import AgentLoop
from .agents import AgentLoader
from .auth import AuthStore, login as auth_login
from .commands import CommandLoader
from .completion import generate as generate_completion
from .config import Config
from .importers import IMPORTERS, import_config
from .council import Council, SEATS
from .free_tiers import discover as discover_free
from .github import diff as git_diff, pr_checkout, status as git_status
from .hooks import HookBus
from .plugin import (
    add as plugin_add,
    listing as plugin_list,
    load_plugins,
    remove as plugin_remove,
)
from .mcp import MCPConnection, MCPError, MCPServerSpec
from .models import Session
from .providers.registry import ProviderError, ProviderRegistry
from .server import acp as serve_acp, serve as serve_http
from .skills import SkillLoader
from .stats import collect as collect_stats
from .telemetry import Telemetry
from .tools.registry import ToolRegistry
from .tui.plain import PlainTUI, preferred_tui

SESSIONS_DIR = Path.home() / ".quillancode" / "sessions"


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def _save_session(session: Session) -> Path:
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    path = SESSIONS_DIR / f"{session.id}.json"
    path.write_text(
        json.dumps(session.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return path


def _load_session(session_id: str) -> Session:
    path = SESSIONS_DIR / f"{session_id}.json"
    if not path.is_file():
        raise KeyError(f"session not found: {session_id}")
    return Session.from_dict(json.loads(path.read_text(encoding="utf-8")))


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="quillancode",
        description="Sovereign multi-provider code assistant CLI/TUI",
    )
    parser.add_argument(
        "--version", action="version", version=f"quillancode {__version__}"
    )
    parser.add_argument("-c", "--config", help="config file path (TOML or JSON)")
    parser.add_argument("--cwd", default=".", help="workspace directory")
    parser.add_argument("-p", "--provider", help="provider name (overrides config)")
    parser.add_argument(
        "--free", action="store_true", help="use the best available free tier"
    )
    parser.add_argument("--session", help="session id to resume")
    parser.add_argument("--fork", action="store_true", help="fork the resumed session")
    parser.add_argument(
        "-y", "--yes", action="store_true", help="auto-allow permission prompts"
    )
    parser.add_argument(
        "--no-telemetry", action="store_true", help="disable JSONL telemetry"
    )
    sub = parser.add_subparsers(dest="command")

    chat = sub.add_parser("chat", help="interactive REPL")
    chat.add_argument("--plain", action="store_true", help="force stdlib TUI")

    run = sub.add_parser("run", help="run one prompt and exit")
    run.add_argument("prompt")
    run.add_argument("--json", action="store_true", help="emit structured JSON")
    run.add_argument("--trace", action="store_true", help="include tool trace")

    council = sub.add_parser("council", help="multi-seat council deliberation")
    council.add_argument("prompt")
    council.add_argument("--agents", type=int, default=None)
    council.add_argument("--json", action="store_true")

    cfg = sub.add_parser("config", help="inspect configuration")
    cfg.add_argument("action", choices=["show", "init", "validate", "import"])
    cfg.add_argument("--path")
    cfg.add_argument(
        "--from",
        dest="source",
        choices=sorted(IMPORTERS),
        help="source tool for config import",
    )
    cfg.add_argument("--save", action="store_true", help="persist imported config")

    agents = sub.add_parser("agents", help="discover reusable agent definitions")
    agents.add_argument("action", choices=["list", "show"])
    agents.add_argument("name", nargs="?")
    agents.add_argument("--json", action="store_true")

    tools = sub.add_parser("tools", help="list available tools")
    tools.add_argument("--json", action="store_true")

    skills = sub.add_parser("skills", help="discover filesystem skills")
    skills.add_argument("action", choices=["list", "show"])
    skills.add_argument("name", nargs="?")
    skills.add_argument("--json", action="store_true")

    mcp = sub.add_parser("mcp", help="inspect MCP servers")
    mcp.add_argument("action", choices=["list", "probe"])

    adapters = sub.add_parser("adapters", help="bridge to installed assistant CLIs")
    adapters.add_argument("action", choices=["list", "run"])
    adapters.add_argument("name", nargs="?")
    adapters.add_argument("--prompt", default="")

    sub.add_parser("doctor", help="environment and readiness report")

    models = sub.add_parser("models", help="list models from a provider")
    models.add_argument("--json", action="store_true")

    cmds = sub.add_parser("commands", help="markdown slash commands")
    cmds.add_argument("action", choices=["list", "show", "run"])
    cmds.add_argument("name", nargs="?")
    cmds.add_argument("args", nargs="*")
    cmds.add_argument("--json", action="store_true")

    ses = sub.add_parser("session", help="session inspection and resume")
    ses.add_argument("action", choices=["list", "show", "resume", "export", "import"])
    ses.add_argument("id", nargs="?")
    ses.add_argument("--file", help="file path for import/export")

    sub.add_parser("seats", help="list the 34 council seats")

    stats = sub.add_parser("stats", help="local usage and token statistics")
    stats.add_argument("--json", action="store_true")
    stats.add_argument("--file", help="telemetry JSONL path")

    auth = sub.add_parser("auth", help="manage stored provider credentials")
    auth.add_argument("action", choices=["list", "login", "logout"])
    auth.add_argument("provider", nargs="?")

    plug = sub.add_parser("plugin", help="manage config-driven event plugins")
    plug.add_argument("action", choices=["list", "add", "remove", "search", "install"])
    plug.add_argument("name", nargs="?")
    plug.add_argument("--event", default="tool_result")
    plug.add_argument("--command", dest="cmd_args", nargs="*", default=[])

    serve = sub.add_parser("serve", help="headless HTTP API server")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=4096)

    web = sub.add_parser("web", help="start HTTP API server and open browser")
    web.add_argument("--host", default="127.0.0.1")
    web.add_argument("--port", type=int, default=3080)

    sub.add_parser("acp", help="serve minimal ACP over stdio")

    diff = sub.add_parser("diff", help="show git diff")
    diff.add_argument("--staged", action="store_true")

    dbp = sub.add_parser("db", help="local SQLite session/telemetry store")
    dbp.add_argument("action", choices=["init", "status", "ingest", "query"])
    dbp.add_argument(
        "--sql", default="SELECT event, COUNT(*) AS n FROM events GROUP BY event"
    )
    dbp.add_argument("--path")
    dbp.add_argument("--source", help="telemetry JSONL for ingest")

    gh = sub.add_parser("github", help="GitHub local + REST workflows")
    gh.add_argument(
        "action", choices=["status", "pr", "issues", "prs", "comment", "workflow"]
    )
    gh.add_argument("number", nargs="?")
    gh.add_argument("--repo", default="")
    gh.add_argument("--text", default="")
    gh.add_argument("--api", default="https://api.github.com")

    lsp = sub.add_parser("lsp", help="language-server diagnostics")
    lsp.add_argument("action", choices=["check", "servers"])
    lsp.add_argument("file", nargs="?")
    lsp.add_argument("--command", dest="cmd_args", nargs="*", default=[])

    att = sub.add_parser("attach", help="attach to a running quillancode server")
    att.add_argument("url")
    att.add_argument("message", nargs="*")

    comp = sub.add_parser("completion", help="generate shell completion")
    comp.add_argument("shell", choices=["bash", "zsh", "powershell", "pwsh"])

    prof = sub.add_parser("profile", help="compose ordered bundles and patch overlays")
    prof.add_argument("action", choices=["list", "compose", "create"])
    prof.add_argument("name", nargs="?")
    prof.add_argument("--bundles", nargs="*", default=[])
    prof.add_argument("--patches", nargs="*", default=[])
    prof.add_argument("--json", action="store_true")

    sched = sub.add_parser("schedule", help="local scheduled prompts")
    sched.add_argument("action", choices=["add", "list", "due", "remove"])
    sched.add_argument("value", nargs="?")
    sched.add_argument("--every", type=int)
    sched.add_argument("--at")

    rev = sub.add_parser("review", help="review checkpoints and restore edits")
    rev.add_argument("action", choices=["list", "reject"])
    rev.add_argument("id", nargs="?")

    sub.add_parser("compare", help="live opencode vs quillancode model comparison")
    sub.add_parser("byo", help="BYO key/model smoke test with a mocked credential")
    guide = sub.add_parser("guide", help="BYO login instructions for external plans")
    guide.add_argument("provider", choices=["qwen", "deepseek", "opencode"])
    sub.add_parser("sbs", help="independent side-by-side opencode command matrix")

    external = sub.add_parser("external", help="probe installed external runtimes")
    external.add_argument("runtime", choices=["dsh", "qwen"])

    uninstall = sub.add_parser(
        "uninstall", help="show removal plan (dry-run by default)"
    )
    uninstall.add_argument("--dry-run", action="store_true", default=True)

    upgrade = sub.add_parser("upgrade", help="check installed version against source")
    upgrade.add_argument("--check", action="store_true", default=True)

    sub.add_parser("debug", help="runtime diagnostics dump")

    matrix = sub.add_parser(
        "matrix", help="independent opencode command equivalence matrix"
    )

    desktop = sub.add_parser("desktop", help="Electron desktop shell checks")
    desktop.add_argument("action", choices=["check", "ui"])

    artifact = sub.add_parser("artifact", help="inspect model tensors/checkpoints")
    artifact.add_argument("path")
    artifact.add_argument("--json", action="store_true")

    ide = sub.add_parser("ide", help="agentic IDE shell and self-test")
    ide.add_argument("action", choices=["selftest"])

    native = sub.add_parser("native", help="compiled C++ hot-path core")
    native.add_argument("action", choices=["info", "bench", "selftest"])
    native.add_argument("--pattern", default="quillan")
    native.add_argument("--rounds", type=int, default=3)

    local = sub.add_parser("local", help="local model runtime (Ollama)")
    local.add_argument("action", choices=["status", "models", "pull"])
    local.add_argument("model", nargs="?")

    ext = sub.add_parser("extensions", help="discover drop-in Python extensions")
    ext.add_argument("action", choices=["list", "load"])
    ext.add_argument("--json", action="store_true")

    free = sub.add_parser("free", help="discover and install free-tier providers")
    free.add_argument("action", choices=["list", "install"])
    free.add_argument("--name", help="name to install the selected free tier under")
    free.add_argument("--save", action="store_true", help="persist to quillancode.toml")

    plug = sub.add_parser("plug", help="plug in any OpenAI-compatible/Anthropic model")
    plug.add_argument("name")
    plug.add_argument("--base-url", required=True)
    plug.add_argument("--model", required=True)
    plug.add_argument("--api-key-env", default="")
    plug.add_argument("--kind", default="openai_compat")
    plug.add_argument("--save", action="store_true")
    return parser


def _agent(args: argparse.Namespace, config: Config) -> AgentLoop:
    if getattr(args, "free", False):
        from .free_tiers import install

        chosen = install(config)
        provider_name = chosen.name
    else:
        provider_name = args.provider
    hooks = HookBus()
    telemetry = Telemetry(
        enabled=not args.no_telemetry and bool(config.get("settings.telemetry", True))
    )
    telemetry.attach(hooks)
    load_plugins(hooks, config)
    ask = (lambda prompt: True) if args.yes else (lambda prompt: _ask(prompt))
    session = _load_session(args.session) if getattr(args, "session", None) else None
    if session is not None:
        return AgentLoop.from_session(
            session,
            config,
            provider_name=provider_name,
            hooks=hooks,
            ask_fn=ask,
            fork=getattr(args, "fork", False),
        )
    return AgentLoop(
        config,
        provider_name=provider_name,
        cwd=args.cwd,
        hooks=hooks,
        ask_fn=ask,
    )


def _server_agent(config: Config, provider: str | None) -> AgentLoop:
    hooks = HookBus()
    Telemetry(enabled=bool(config.get("settings.telemetry", True))).attach(hooks)
    load_plugins(hooks, config)
    return AgentLoop(
        config, provider_name=provider, hooks=hooks, ask_fn=lambda prompt: False
    )


def _ask(prompt: str) -> bool:
    try:
        return input(prompt).strip().lower() in {"y", "yes", "a", "always"}
    except (EOFError, KeyboardInterrupt):
        return False


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        config = Config.load(args.config, cwd=args.cwd)
    except (ValueError, OSError) as exc:
        print(f"[config error] {exc}", file=sys.stderr)
        return 2
    if args.no_telemetry:
        config.data.setdefault("settings", {})["telemetry"] = False

    command = args.command or "chat"
    try:
        if command == "chat":
            agent = _agent(args, config)
            tui = PlainTUI() if args.plain else preferred_tui()()
            code = tui.run(agent, config)
            _save_session(agent.session)
            return code

        if command == "run":
            agent = _agent(args, config)
            answer = agent.run(args.prompt)
            if args.json:
                _print_json(
                    {
                        "answer": answer,
                        "session": agent.session.id,
                        "tool_trace": [
                            e for e in agent.hooks.history if e[0] == "tool_result"
                        ],
                        "audit": agent.gate.audit,
                    }
                )
            else:
                print(answer)
            if args.trace:
                print("\n--- trace ---\n" + agent.render_trace())
            _save_session(agent.session)
            return 0

        if command == "council":
            council = Council(config)
            result = council.deliberate(args.prompt, args.agents)
            if args.json:
                _print_json(result.to_dict())
            else:
                print(result.synthesis)
                print(f"\nconfidence={result.confidence} seats={len(result.proposals)}")
            return 0

        if command == "config":
            if args.action == "show":
                _print_json({"source": str(config.path), "config": config.redacted()})
            elif args.action == "init":
                path = config.save(args.path)
                print(f"wrote {path}")
            elif args.action == "import":
                if not args.source:
                    print("--from is required (opencode|qwen|gemini)", file=sys.stderr)
                    return 2
                report = import_config(config, args.source, args.path)
                if args.save:
                    report.path = str(
                        config.save(str(Path(args.cwd) / "quillancode.toml"))
                    )
                _print_json(report.to_dict())
            else:
                registry = ProviderRegistry(config)
                problems = [n for n, ok in registry.ready().items() if not ok]
                print(
                    "config valid; providers without credentials: "
                    + (", ".join(problems) or "none")
                )
            return 0

        if command == "agents":
            loader = AgentLoader()
            agents = loader.discover()
            if args.action == "show":
                if not args.name:
                    print("agent name required", file=sys.stderr)
                    return 2
                try:
                    print(loader.load(args.name))
                except KeyError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                return 0
            if args.json:
                _print_json([a.to_dict() for a in agents])
            else:
                for agent in agents:
                    print(f"{agent.id:<34} [{agent.source}] {agent.description[:80]}")
                if not agents:
                    print("(no agent definitions discovered)")
            return 0

        if command == "tools":
            registry = ToolRegistry(args.cwd)
            if args.json:
                _print_json(registry.schemas())
            else:
                print(registry.describe())
            return 0

        if command == "skills":
            loader = SkillLoader(config)
            skills = loader.discover()
            if args.action == "show":
                if not args.name:
                    print("skill name required", file=sys.stderr)
                    return 2
                try:
                    print(loader.load(args.name))
                except KeyError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                return 0
            if args.json:
                _print_json([s.to_dict() for s in skills])
            else:
                for skill in skills:
                    print(f"{skill.name}: {skill.description[:100]}")
                if not skills:
                    print("(no skills discovered)")
            return 0

        if command == "mcp":
            servers = config.get("mcp.servers", {}) or {}
            if args.action == "list":
                for name, spec in servers.items():
                    print(
                        f"{name}: {spec.get('command')} {' '.join(spec.get('args', []))}"
                    )
                if not servers:
                    print("(no MCP servers configured)")
                return 0
            for name, raw in servers.items():
                spec = MCPServerSpec.from_dict(str(name), raw)
                try:
                    with MCPConnection(spec) as conn:
                        print(
                            f"{name}: {len(conn.tools)} tools: "
                            f"{[t.get('name') for t in conn.tools]}"
                        )
                except Exception as exc:
                    print(f"{name}: ERROR {exc}")
            return 0

        if command == "adapters":
            if args.action == "list":
                print(adapter_report())
                return 0
            if not args.name:
                print("adapter name required", file=sys.stderr)
                return 2
            cli = __import__("quillancode.adapters", fromlist=["get"]).get(args.name)
            result = delegate(cli, args.prompt, cwd=args.cwd)
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return 0 if result.get("ok") else 1

        if command == "doctor":
            registry = ProviderRegistry(config)
            ready = registry.ready()
            _print_json(
                {
                    "version": __version__,
                    "python": sys.version.split()[0],
                    "platform": sys.platform,
                    "cwd": str(Path(args.cwd).resolve()),
                    "config": str(config.path),
                    "providers": ready,
                    "tools": ToolRegistry(args.cwd).names(),
                    "adapters": [c.to_dict() for c in detect()],
                    "skills": len(SkillLoader(config).discover()),
                    "agents": len(AgentLoader().discover()),
                    "mcp_servers": list((config.get("mcp.servers", {}) or {}).keys()),
                    "council_seats": len(SEATS),
                    "free_tiers": [
                        {
                            "name": t.name,
                            "available": t.available,
                            "model": t.spec.model,
                            "reason": t.reason,
                        }
                        for t in discover_free(config)
                    ],
                }
            )
            return 0

        if command == "models":
            registry = ProviderRegistry(config)
            adapter = registry.get(args.provider)
            models = adapter.list_models()
            if args.json:
                _print_json(
                    {
                        "provider": getattr(adapter, "name", args.provider),
                        "models": models,
                    }
                )
            else:
                print("\n".join(models))
            return 0

        if command == "commands":
            loader = CommandLoader()
            commands = loader.discover(args.cwd)
            if args.action == "list":
                if args.json:
                    _print_json([c.to_dict() for c in commands])
                else:
                    for cmd in commands:
                        print(f"/{cmd.name:<16} [{cmd.source}] {cmd.description[:80]}")
                return 0
            if not args.name:
                print("command name required", file=sys.stderr)
                return 2
            cmd = loader.get(args.name, args.cwd)
            if args.action == "show":
                print(cmd.template)
                return 0
            agent = _agent(args, config)
            answer = agent.run(cmd.render(" ".join(args.args)))
            print(answer)
            _save_session(agent.session)
            return 0

        if command == "session":
            if args.action == "list":
                SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
                for path in sorted(SESSIONS_DIR.glob("*.json")):
                    print(path.stem)
                return 0
            if args.action == "import":
                if not args.file:
                    print("--file is required", file=sys.stderr)
                    return 2
                source = Path(args.file).expanduser()
                session = Session.from_dict(
                    json.loads(source.read_text(encoding="utf-8"))
                )
                path = _save_session(session)
                print(f"imported {session.id} -> {path}")
                return 0
            if not args.id:
                print("session id required", file=sys.stderr)
                return 2
            path = SESSIONS_DIR / f"{args.id}.json"
            if not path.is_file():
                print(f"session not found: {args.id}", file=sys.stderr)
                return 1
            if args.action == "export":
                target = (
                    Path(args.file).expanduser()
                    if args.file
                    else Path(f"{args.id}.json")
                )
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
                print(f"exported -> {target}")
                return 0
            if args.action == "resume":
                args.session = args.id
                agent = _agent(args, config)
                from .tui.plain import preferred_tui

                tui = PlainTUI() if getattr(args, "plain", False) else preferred_tui()()
                code = tui.run(agent, config)
                _save_session(agent.session)
                return code
            print(path.read_text(encoding="utf-8"))
            return 0

        if command == "seats":
            for sid, name, domain in SEATS:
                print(f"{sid:<5} {name:<12} {domain}")
            return 0

        if command == "stats":
            stats = collect_stats(args.file)
            if args.json:
                _print_json(stats.to_dict())
            else:
                print(
                    f"turns={stats.turns} tool_calls={sum(stats.tool_calls.values())} "
                    f"failures={stats.tool_failures} "
                    f"est_tokens={stats.estimated_total_tokens}"
                )
            return 0

        if command == "auth":
            store = AuthStore()
            if args.action == "list":
                _print_json(store.list())
            elif args.action == "login":
                if not args.provider:
                    print("provider required", file=sys.stderr)
                    return 2
                print(auth_login(args.provider, store))
            else:
                if not args.provider or not store.remove(args.provider):
                    print("provider not found in auth store", file=sys.stderr)
                    return 1
                print(f"removed credentials for {args.provider}")
            return 0

        if command == "plugin":
            from .plugin_market import (
                install as market_install,
                search as market_search,
            )

            if args.action == "list":
                _print_json(plugin_list(config))
            elif args.action == "search":
                _print_json(market_search(args.name or ""))
            elif args.action == "install":
                if not args.name:
                    print("plugin name required", file=sys.stderr)
                    return 2
                try:
                    _print_json(market_install(config, args.name))
                except KeyError as exc:
                    print(str(exc), file=sys.stderr)
                    return 1
                config.save(str(Path(args.cwd) / "quillancode.toml"))
            elif args.action == "add":
                if not args.name or not args.cmd_args:
                    print("name and --command required", file=sys.stderr)
                    return 2
                _print_json(plugin_add(config, args.name, args.event, args.cmd_args))
                config.save(str(Path(args.cwd) / "quillancode.toml"))
            else:
                if not args.name or not plugin_remove(config, args.name):
                    print("plugin not found", file=sys.stderr)
                    return 1
                config.save(str(Path(args.cwd) / "quillancode.toml"))
                print(f"removed plugin {args.name}")
            return 0

        if command in {"serve", "web", "acp"}:
            if command == "acp":
                return serve_acp(config, _server_agent)
            return serve_http(
                config,
                _server_agent,
                host=args.host,
                port=args.port,
                open_browser=(command == "web"),
            )

        if command == "diff":
            print(git_diff(args.cwd, staged=args.staged))
            return 0

        if command == "db":
            from .db import (
                ingest_telemetry,
                init as db_init,
                query as db_query,
                status as db_status,
            )

            if args.action == "init":
                _print_json(db_init(args.path))
            elif args.action == "ingest":
                _print_json(ingest_telemetry(telemetry=args.source, path=args.path))
            elif args.action == "query":
                _print_json(db_query(args.sql, args.path))
            else:
                _print_json(db_status(args.path))
            return 0

        if command == "github":
            if args.action == "workflow":
                from .github import workflow as git_workflow

                _print_json(git_workflow(args.cwd))
                return 0
            if args.action == "status":
                _print_json(git_status(args.cwd))
                return 0
            if args.action == "issues":
                from .github_api import issues

                _print_json(issues(args.repo or args.cwd, api=args.api))
                return 0
            if args.action == "prs":
                from .github_api import pull_requests

                _print_json(pull_requests(args.repo or args.cwd, api=args.api))
                return 0
            if args.action == "comment":
                from .github_api import comment

                if not args.repo or args.number is None or not args.text:
                    print("--repo, number and --text required", file=sys.stderr)
                    return 2
                _print_json(
                    comment(args.repo, int(args.number), args.text, api=args.api)
                )
                return 0
            if args.number is None:
                print("PR number required", file=sys.stderr)
                return 2
            _print_json(pr_checkout(int(args.number), args.cwd))
            return 0

        if command == "lsp":
            from .lsp import check as lsp_check

            servers = config.get("lsp.servers", {}) or {}
            if args.action == "servers":
                _print_json(servers)
                return 0
            if not args.file:
                print("file required", file=sys.stderr)
                return 2
            target = Path(args.file).resolve()
            command_line = args.cmd_args or list(
                servers.get(target.suffix, {}).get("command", [])
            )
            if not command_line:
                print(f"no LSP server configured for {target.suffix}", file=sys.stderr)
                return 2
            _print_json(lsp_check(target, command_line, cwd=args.cwd))
            return 0

        if command == "attach":
            from .attach import AttachError, chat as attach_chat, health

            try:
                info = health(args.url)
                answer = attach_chat(args.url, " ".join(args.message))
            except AttachError as exc:
                print(f"[error] {exc}", file=sys.stderr)
                return 1
            _print_json({"server": info, "answer": answer})
            return 0

        if command == "completion":
            print(generate_completion(args.shell), end="")
            return 0

        if command == "profile":
            from .profiles import compose, create, discover

            if args.action == "list":
                items = [p.to_dict() for p in discover()]
                if args.json:
                    _print_json(items)
                else:
                    for item in items:
                        print(
                            f"{item['name']}: bundles={item['bundles']} patches={item['patches']}"
                        )
                return 0
            if args.action == "create":
                if not args.name:
                    print("name required", file=sys.stderr)
                    return 2
                _print_json(create(args.name, args.bundles, args.patches).to_dict())
                return 0
            _print_json(compose(config, args.name))
            return 0

        if command == "schedule":
            from .schedule import (
                add as sched_add,
                due as sched_due,
                listing as sched_list,
            )
            from .schedule import remove as sched_remove

            if args.action == "add":
                if not args.value:
                    print("prompt required", file=sys.stderr)
                    return 2
                _print_json(sched_add(args.value, args.every, args.at))
            elif args.action == "list":
                _print_json(sched_list())
            elif args.action == "due":
                _print_json(sched_due())
            else:
                if not args.value or not sched_remove(args.value):
                    print("schedule id not found", file=sys.stderr)
                    return 1
                print(f"removed {args.value}")
            return 0

        if command == "review":
            agent = _agent(args, config)
            if args.action == "list":
                _print_json([c.to_dict() for c in agent.session.checkpoints])
                return 0
            if not args.id:
                print("checkpoint id required", file=sys.stderr)
                return 2
            from .models import ToolCall

            result = agent.tools.execute_call(
                ToolCall(id="cli_reject", name="rewind", arguments={"id": args.id}),
                agent.ctx,
                agent.gate,
                force=True,
            )
            print(result.output or result.error)
            return 0 if result.ok else 1

        if command == "uninstall":
            import shutil

            package_dir = Path(__file__).parent.parent
            _print_json(
                {
                    "dry_run": True,
                    "package": str(package_dir),
                    "console_script": shutil.which("quillancode"),
                    "state_dirs": [str(Path.home() / ".quillancode")],
                    "note": "no files removed; pass --apply in a future release",
                }
            )
            return 0

        if command == "upgrade":
            import tomllib
            import importlib.metadata as metadata

            pyproject = Path(__file__).parent.parent / "pyproject.toml"
            source_version = __version__
            if pyproject.is_file():
                source_version = str(
                    tomllib.loads(pyproject.read_text(encoding="utf-8"))
                    .get("project", {})
                    .get("version", __version__)
                )
            try:
                installed = metadata.version("quillancode")
            except metadata.PackageNotFoundError:
                installed = "unknown"
            _print_json(
                {
                    "installed": installed,
                    "source": source_version,
                    "up_to_date": installed == source_version,
                }
            )
            return 0

        if command == "debug":
            from .native_core import info as native_info
            import platform

            _print_json(
                {
                    "python": sys.version.split()[0],
                    "executable": sys.executable,
                    "platform": platform.platform(),
                    "package": str(Path(__file__).parent),
                    "tools": ToolRegistry(args.cwd).names(),
                    "providers": ProviderRegistry(config).ready(),
                    "native": native_info(),
                }
            )
            return 0

        if command == "sbs":
            script = Path(__file__).parent.parent / "scripts" / "side_by_side.py"
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=600,
            )
            print((proc.stdout + proc.stderr).strip())
            return proc.returncode

        if command == "guide":
            guides = {
                "qwen": [
                    "Qwen Code (BYO plan)",
                    "1. Run: qwen   (interactive first launch)",
                    "2. Choose Qwen Account with Subscription, QwenCloud, ModelStudio,",
                    "   a third-party provider, or Custom Provider, and sign in there.",
                    "3. In quillancode: quillancode plug my-qwen --base-url <endpoint>",
                    "   --model <model-id> --api-key-env QWEN_API_KEY --save",
                    "4. Or: quillancode auth login my-qwen   (key stored masked, never printed).",
                    "quillancode does not perform the Qwen OAuth flow for you.",
                ],
                "deepseek": [
                    "DeepSeek (BYO API key)",
                    "1. Export DEEPSEEK_API_KEY in your shell (or: quillancode auth login deepseek).",
                    "2. dsh --profile headless <task> will use that key for generation.",
                    "3. In quillancode: quillancode plug my-deepseek",
                    "   --base-url https://api.deepseek.com/v1 --model deepseek-chat",
                    "   --api-key-env DEEPSEEK_API_KEY --save",
                    "No live generation is claimed here until you supply the key.",
                ],
                "opencode": [
                    "OpenCode free tier (no user credential)",
                    "1. Keep the OpenCode desktop app running; quillancode detects its local API.",
                    "2. quillancode free list  -> opencode-account available",
                    "3. quillancode -p opencode-account run 'hello'  (usage stays on OpenCode).",
                ],
            }
            print("\n".join(guides[args.provider]))
            return 0

        if command == "byo":
            from .external_checks import byo_smoke

            _print_json(byo_smoke())
            return 0

        if command == "compare":
            from .external_checks import compare_live

            _print_json(compare_live())
            return 0

        if command == "external":
            from .external_checks import check_dsh, check_qwen

            result = check_dsh() if args.runtime == "dsh" else check_qwen()
            _print_json(result)
            return 0 if result["ok"] else 1

        if command == "matrix":
            script = Path(__file__).parent.parent / "scripts" / "opencode_matrix.py"
            proc = subprocess.run(
                [sys.executable, str(script)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
            )
            print((proc.stdout + proc.stderr).strip())
            return proc.returncode

        if command == "desktop":
            if args.action == "ui":
                script = (
                    Path(__file__).parent.parent / "scripts" / "electron_ui_check.js"
                )
                proc = subprocess.run(
                    ["node", str(script)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=120,
                )
                print(proc.stdout.strip() or proc.stderr.strip())
                return proc.returncode
            desktop_dir = Path(__file__).parent.parent / "desktop"
            ok = True
            for name in ("main.js", "preload.js"):
                source = desktop_dir / name
                if not source.is_file():
                    ok = False
                    continue
                proc = subprocess.run(
                    ["node", "--check", str(source)],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                ok = ok and proc.returncode == 0
            electron = (
                desktop_dir / "node_modules" / "electron" / "dist" / "electron.exe"
            )
            version = ""
            if electron.is_file():
                probe = subprocess.run(
                    [str(electron), "--version"],
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=30,
                )
                version = (
                    (probe.stdout or probe.stderr).strip().splitlines()[0]
                    if (probe.stdout or probe.stderr)
                    else ""
                )
            ok = ok and bool(version)
            print("DESKTOP_CHECK_OK" if ok else "DESKTOP_CHECK_FAIL")
            if version:
                print(f"electron={version}")
            packaged = desktop_dir / "dist" / "win-unpacked" / "quillancode-desktop.exe"
            if packaged.is_file():
                print(f"packaged={packaged} size={packaged.stat().st_size}")
            return 0 if ok else 1

        if command == "artifact":
            from .artifacts import inspect

            target = Path(args.path)
            if not target.is_absolute():
                target = Path(args.cwd) / target
            data = inspect(target.resolve())
            if args.json:
                _print_json(data)
            else:
                print(f"{data['name']}  kind={data['kind']}  size={data['size']}")
                for note in data["notes"]:
                    print(f"  {note}")
                for tensor in data["tensors"][:20]:
                    print(
                        f"  tensor {tensor['name']} {tensor.get('dtype', '')} "
                        f"{tensor.get('shape', '')} {tensor.get('bytes', '')}"
                    )
            return 0

        if command == "ide":
            from .server import ide_selftest

            print(ide_selftest())
            return 0

        if command == "native":
            from .native_core import bench, info, selftest

            if args.action == "selftest":
                print(selftest())
                return 0
            if args.action == "info":
                _print_json(info())
            else:
                result = bench(Path(args.cwd), args.pattern, args.rounds)
                print(
                    result or "native core unavailable (run scripts/build_native.ps1)"
                )
            return 0

        if command == "local":
            from .local import (
                models as local_models,
                pull as local_pull,
                status as local_status,
            )

            if args.action == "pull":
                if not args.model:
                    print("model name required", file=sys.stderr)
                    return 2
                _print_json(local_pull(args.model))
            elif args.action == "models":
                print("\n".join(local_models()) or "(no local models)")
            else:
                _print_json(local_status())
            return 0

        if command == "extensions":
            from .extensions import ExtensionManager

            manager = ExtensionManager()
            found = manager.discover(args.cwd)
            if args.action == "load":
                loaded = manager.load(
                    ToolRegistry(args.cwd), config, HookBus(), cwd=args.cwd
                )
                _print_json({"loaded": loaded})
                return 0
            if args.json:
                _print_json([e.to_dict() for e in found])
            else:
                for item in found:
                    print(f"{item.name} [{item.source}] {item.path}")
            return 0

        if command == "free":
            from .free_tiers import discover, install

            tiers = discover(config)
            if args.action == "list":
                for tier in tiers:
                    status = (
                        "available"
                        if tier.available
                        else f"unavailable ({tier.reason})"
                    )
                    print(f"{tier.name:<18} {status:<40} {tier.spec.model}")
                return 0
            chosen = install(config, args.name)
            if args.save:
                config.save(str(Path(args.cwd) / "quillancode.toml"))
            print(f"installed {args.name or chosen.name}: {chosen.spec.model}")
            return 0

        if command == "plug":
            from .free_tiers import plug as plug_provider

            spec = plug_provider(
                config,
                args.name,
                args.base_url,
                args.model,
                args.api_key_env,
                args.kind,
            )
            if args.save:
                config.save(str(Path(args.cwd) / "quillancode.toml"))
            _print_json(spec.to_dict())
            return 0

        parser.print_help()
        return 0
    except (ProviderError, KeyError, MCPError) as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
