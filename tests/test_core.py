"""Offline verification suite for quillancode. No network, no API keys."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
import urllib.request
import warnings
from pathlib import Path
from unittest import mock

warnings.filterwarnings(
    "ignore", message="Implicitly cleaning up <HTTPError", category=ResourceWarning
)
os.environ.setdefault("PYTHONWARNINGS", "ignore::ResourceWarning")

PKG = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PKG))

from quillancode.agent import AgentLoop  # noqa: E402
from quillancode.config import Config  # noqa: E402
from quillancode.context import compact  # noqa: E402
from quillancode.council import Council, SEATS  # noqa: E402
from quillancode.hooks import HookBus  # noqa: E402
from quillancode.mcp import MCPConnection, MCPServerSpec  # noqa: E402
from quillancode.models import Message, ProviderSpec, ToolCall  # noqa: E402
from quillancode.providers.mock import MockProvider  # noqa: E402
from quillancode.telemetry import Telemetry  # noqa: E402
from quillancode.tools.permissions import PermissionGate  # noqa: E402
from quillancode.tools.registry import ToolRegistry  # noqa: E402

ECHO_SERVER = """
import sys, json
for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
    except ValueError:
        continue
    if "id" not in msg:
        continue
    method = msg.get("method")
    if method == "initialize":
        result = {"capabilities": {}, "serverInfo": {"name": "echo", "version": "1"}}
    elif method == "tools/list":
        result = {"tools": [{"name": "echo", "description": "echo text",
                             "inputSchema": {"type": "object",
                                             "properties": {"text": {"type": "string"}}}}]}
    elif method == "tools/call":
        result = {"content": [{"type": "text",
                               "text": msg["params"]["arguments"]["text"]}]}
    else:
        result = {}
    sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}) + "\\n")
    sys.stdout.flush()
"""


class ConfigTests(unittest.TestCase):
    def test_roundtrip_and_redaction(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.json"
            data = Config.from_dict(
                {
                    "provider": {"default": "openai"},
                    "providers": {
                        "openai": {"kind": "openai_compat", "api_key": "SUPERSECRET"}
                    },
                }
            )
            data.save(path)
            loaded = Config.load(str(path))
            self.assertEqual(loaded.default_provider, "openai")
            self.assertEqual(loaded.providers["openai"].kind, "openai_compat")
            self.assertNotIn("SUPERSECRET", json.dumps(loaded.redacted()))

    def test_toml_init_is_parseable(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "config.toml"
            Config.from_dict({}).save(path)
            loaded = Config.load(str(path))
            self.assertEqual(loaded.get("settings.max_tool_steps"), 20)


class ProviderTests(unittest.TestCase):
    def test_mock_never_opens_socket(self) -> None:
        with mock.patch.object(
            urllib.request, "urlopen", side_effect=AssertionError("network!")
        ):
            provider = MockProvider(ProviderSpec(name="mock"))
            reply = provider.complete([Message(role="user", content="hello")], [])
            self.assertIn("hello", reply.content)

    def test_mock_script_produces_tool_calls(self) -> None:
        provider = MockProvider(ProviderSpec(name="mock"))
        provider.set_script(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"path": "a.txt"}}
                    ],
                },
                {"content": "done"},
            ]
        )
        first = provider.complete([], [])
        self.assertEqual(first.tool_calls[0].name, "read_file")
        second = provider.complete([], [])
        self.assertEqual(second.content, "done")


class ToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.registry = ToolRegistry(str(self.root))
        from quillancode.tools.base import ToolContext

        self.ctx = ToolContext(cwd=self.root)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _run(self, name: str, **params: object):
        from quillancode.tools.permissions import Decision

        call = ToolCall(id="t1", name=name, arguments=params)
        gate = mock.MagicMock()
        gate.decide.return_value = Decision("allow", "low", "test")
        return self.registry.execute_call(call, self.ctx, gate)

    def test_write_read_edit_glob_grep(self) -> None:
        self.assertTrue(
            self._run("write_file", path="sub/a.txt", content="alpha beta").ok
        )
        self.assertIn("alpha beta", self._run("read_file", path="sub/a.txt").output)
        self.assertIn("a.txt", self._run("glob", pattern="*.txt").output)
        self.assertIn("beta", self._run("grep", pattern="beta").output)
        self.assertTrue(
            self._run("edit_file", path="sub/a.txt", old="alpha", new="gamma").ok
        )
        self.assertIn("gamma", self._run("read_file", path="sub/a.txt").output)

    def test_path_traversal_blocked(self) -> None:
        result = self._run("read_file", path=str(self.root.parent / "outside.txt"))
        self.assertFalse(result.ok)
        self.assertIn("escapes workspace", result.error)

    def test_webfetch_blocks_private_hosts(self) -> None:
        for url in (
            "http://localhost:8000/x",
            "http://169.254.169.254/latest/meta-data",
            "file:///etc/passwd",
        ):
            result = self._run("webfetch", url=url)
            self.assertFalse(result.ok, url)
            self.assertTrue(result.error)

    def test_bash_runs_in_cwd(self) -> None:
        result = self._run("bash", command="echo qc-ok", timeout=10)
        self.assertTrue(result.ok, result.error)
        self.assertIn("qc-ok", result.output)


class PermissionTests(unittest.TestCase):
    def test_tiers_and_patterns(self) -> None:
        config = Config.from_dict(
            {
                "permissions": {"blocked_patterns": ["bash:rm -rf"]},
            }
        )
        gate = PermissionGate(config, ask_fn=lambda prompt: False)
        self.assertEqual(gate.decide("read_file", {}).action, "allow")
        self.assertEqual(gate.decide("bash", {"command": "echo hi"}).action, "ask")
        denied = gate.decide("bash", {"command": "rm -rf /"})
        self.assertEqual(denied.action, "deny")
        self.assertEqual(denied.tier, "blocked")


class AgentTests(unittest.TestCase):
    def test_tool_then_final_with_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            provider = MockProvider(ProviderSpec(name="mock"))
            provider.set_script(
                [
                    {
                        "content": "writing",
                        "tool_calls": [
                            {
                                "name": "write_file",
                                "arguments": {"path": "note.txt", "content": "payload"},
                            }
                        ],
                    },
                    {"content": "verified"},
                ]
            )
            agent = AgentLoop(
                Config.from_dict({}),
                provider=provider,
                cwd=td,
                ask_fn=lambda prompt: True,
            )
            answer = agent.run("write and verify")
            self.assertEqual(answer, "verified")
            self.assertEqual(
                (Path(td) / "note.txt").read_text(encoding="utf-8"), "payload"
            )
            self.assertTrue(agent.session.checkpoints, "checkpoint_on_write must fire")
            self.assertTrue(any(e[0] == "tool_result" for e in agent.hooks.history))

    def test_step_limit_is_bounded(self) -> None:
        provider = MockProvider(ProviderSpec(name="mock"))
        provider.set_script(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {"name": "read_file", "arguments": {"path": "missing.txt"}}
                    ],
                }
                for _ in range(50)
            ]
        )
        with tempfile.TemporaryDirectory() as td:
            agent = AgentLoop(
                Config.from_dict({"settings": {"max_tool_steps": 3}}),
                provider=provider,
                cwd=td,
                ask_fn=lambda p: True,
            )
            answer = agent.run("loop")
            self.assertIn("step limit", answer)


class CouncilTests(unittest.TestCase):
    def test_deliberation_and_synthesis(self) -> None:
        answers = ["proposal A", "proposal B", "proposal C"]

        def factory(i: int, seat: tuple[str, str, str]) -> MockProvider:
            provider = MockProvider(ProviderSpec(name="mock"))
            provider.set_script([{"content": answers[i]}])
            return provider

        judge = MockProvider(ProviderSpec(name="mock"))
        judge.set_script([{"content": "SYNTHESIS: adopt B"}])
        council = Council(
            Config.from_dict({}), provider_factory=factory, judge_provider=judge
        )
        result = council.deliberate("which path?", agents=3)
        self.assertEqual(len(result.proposals), 3)
        self.assertIn("SYNTHESIS", result.synthesis)
        self.assertEqual(len(SEATS), 34)


class MCPTests(unittest.TestCase):
    def test_stdio_jsonrpc_echo(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "echo_mcp.py"
            script.write_text(ECHO_SERVER, encoding="utf-8")
            spec = MCPServerSpec(
                name="echo", command=sys.executable, args=[str(script)]
            )
            with MCPConnection(spec, timeout=15) as conn:
                names = [t.get("name") for t in conn.tools]
                self.assertIn("echo", names)
                result = conn.call_tool("echo", {"text": "quillancode"})
                self.assertIn("quillancode", json.dumps(result))
            self.assertIsNone(conn._proc)


class CLITests(unittest.TestCase):
    def _invoke(
        self, *args: str, inp: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            input=inp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_help_version_and_subcommands(self) -> None:
        help_proc = self._invoke("--help")
        self.assertEqual(help_proc.returncode, 0, help_proc.stderr)
        for name in (
            "chat",
            "run",
            "council",
            "config",
            "tools",
            "skills",
            "mcp",
            "adapters",
            "doctor",
        ):
            self.assertIn(name, help_proc.stdout)
        version = self._invoke("--version")
        self.assertIn("quillancode 1.0.0", version.stdout + version.stderr)

    def test_cwd_config_discovery(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "quillancode.toml").write_text(
                '[provider]\ndefault = "deepseek"\n', encoding="utf-8"
            )
            proc = self._invoke("--cwd", td, "config", "show")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn('"default": "deepseek"', proc.stdout)

    def test_run_mock_and_repl_exit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env = os.environ.copy()
            os.environ["QUILLANCODE_MOCK_SCRIPT"] = json.dumps(["offline answer"])
            try:
                proc = self._invoke("--cwd", td, "run", "hello")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("offline answer", proc.stdout)
            finally:
                os.environ.pop("QUILLANCODE_MOCK_SCRIPT", None)
            repl = subprocess.run(
                [sys.executable, "-m", "quillancode", "--cwd", td, "chat", "--plain"],
                input="/exit\n",
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                cwd=str(PKG),
            )
            self.assertEqual(repl.returncode, 0, repl.stderr)


class MiscTests(unittest.TestCase):
    def test_compaction_and_telemetry_redaction(self) -> None:
        messages = [Message(role="user", content="x" * 5000) for _ in range(6)]
        compacted, changed = compact(
            messages, threshold=0.0, budget=1000, keep_recent=2
        )
        self.assertTrue(changed)
        self.assertLess(len(compacted), len(messages))
        redacted = Telemetry._redact({"Authorization: Bearer abc123": "api_key=XYZ"})
        self.assertIn("<redacted>", json.dumps(redacted))
        self.assertNotIn("XYZ", json.dumps(redacted))


class EcosystemTests(unittest.TestCase):
    def test_import_opencode_redacts_literal_keys(self) -> None:
        from quillancode.importers import import_opencode

        with tempfile.TemporaryDirectory() as td:
            source = Path(td) / "opencode.jsonc"
            source.write_text(
                json.dumps(
                    {
                        "model": "opencode/example",
                        "provider": {
                            "nvidia": {
                                "options": {
                                    "baseURL": "https://integrate.api.nvidia.com/v1",
                                    "apiKey": "nvapi-LITERAL_SECRET",
                                },
                                "models": {"meta/llama": {}},
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            config = Config.from_dict({})
            report = import_opencode(config, source)
            self.assertEqual(report.redacted_secrets, 1)
            self.assertEqual(report.imported, ["nvidia"])
            self.assertNotIn("nvapi-LITERAL_SECRET", json.dumps(config.data))
            self.assertNotIn("nvapi-LITERAL_SECRET", json.dumps(report.to_dict()))
            spec = config.providers["nvidia"]
            self.assertTrue(spec.api_key_env.startswith("QUILLANCODE_KEY_"))
            self.assertEqual(spec.base_url, "https://integrate.api.nvidia.com/v1")
            self.assertEqual(spec.model, "meta/llama")

    def test_agent_and_skill_discovery(self) -> None:
        from quillancode.agents import AgentLoader

        agents = AgentLoader().discover()
        self.assertGreater(
            len(agents), 0, "expected installed opencode agent definitions"
        )
        self.assertTrue(any(a.id == "c1-astra" for a in agents))


class ParityTests(unittest.TestCase):
    def _invoke(
        self, *args: str, inp: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            input=inp,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_custom_command_loading_and_substitution(self) -> None:
        from quillancode.commands import CommandLoader

        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / ".quillancode" / "command"
            root.mkdir(parents=True)
            (root / "greet.md").write_text(
                "---\ndescription: Greet a target\n---\n\nHello $ARGUMENTS / $1\n",
                encoding="utf-8",
            )
            loader = CommandLoader()
            cmd = loader.get("greet", td)
            self.assertEqual(cmd.description, "Greet a target")
            self.assertIn("Hello world / world", cmd.render("world"))
        self.assertGreater(
            len(CommandLoader().discover()), 0, "opencode commands should be inherited"
        )

    def test_watcher_ignore_and_formatter(self) -> None:
        from quillancode.workspace import format_file, is_ignored

        self.assertTrue(is_ignored("build/out.txt", ["build/**"]))
        self.assertTrue(is_ignored("sub/a.tmp", ["**/*.tmp"]))
        self.assertFalse(is_ignored("src/main.py", ["build/**"]))
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "a.txt"
            target.write_text("raw", encoding="utf-8")
            script = Path(td) / "fmt.py"
            script.write_text(
                "import sys,pathlib; p=pathlib.Path(sys.argv[1]); p.write_text(p.read_text()+'#FMT')\n",
                encoding="utf-8",
            )
            config = Config.from_dict(
                {
                    "formatter": {
                        "marker": {
                            "command": [sys.executable, str(script), "$FILE"],
                            "extensions": [".txt"],
                        },
                    }
                }
            )
            result = format_file(config, target)
            self.assertTrue(result["ok"], result)
            self.assertEqual(target.read_text(encoding="utf-8"), "raw#FMT")

    def test_session_export_import_and_resume(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            env_script = json.dumps(["first answer"])
            os.environ["QUILLANCODE_MOCK_SCRIPT"] = env_script
            try:
                proc = self._invoke("--cwd", td, "run", "hello")
                self.assertEqual(proc.returncode, 0, proc.stderr)
            finally:
                os.environ.pop("QUILLANCODE_MOCK_SCRIPT", None)
            session_dir = Path.home() / ".quillancode" / "sessions"
            files = sorted(
                session_dir.glob("ses_*.json"), key=lambda p: p.stat().st_mtime
            )
            self.assertTrue(files)
            latest = files[-1]
            os.environ["QUILLANCODE_MOCK_SCRIPT"] = json.dumps(["resumed answer"])
            try:
                resumed = self._invoke(
                    "--cwd", td, "--session", latest.stem, "run", "again"
                )
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                self.assertIn("resumed answer", resumed.stdout)
            finally:
                os.environ.pop("QUILLANCODE_MOCK_SCRIPT", None)
            exported = self._invoke(
                "--cwd",
                td,
                "session",
                "export",
                latest.stem,
                "--file",
                str(Path(td) / "export.json"),
            )
            self.assertEqual(exported.returncode, 0, exported.stderr)
            self.assertTrue((Path(td) / "export.json").is_file())

    def test_plugin_cli_dispatch(self) -> None:
        proc = self._invoke("plugin", "list")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIsInstance(json.loads(proc.stdout), list)

    def test_models_command(self) -> None:
        proc = self._invoke("models", "--json")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("mock", proc.stdout)


class GapClosureTests(unittest.TestCase):
    def test_stats_auth_completion(self) -> None:
        from quillancode.auth import AuthStore
        from quillancode.completion import generate
        from quillancode.stats import collect

        with tempfile.TemporaryDirectory() as td:
            telemetry = Path(td) / "telemetry.jsonl"
            telemetry.write_text(
                json.dumps({"event": "turn_start", "data": {"input_chars": 40}})
                + "\n"
                + json.dumps(
                    {"event": "tool_result", "data": {"name": "read_file", "ok": True}}
                )
                + "\n"
                + json.dumps(
                    {"event": "tool_result", "data": {"name": "bash", "ok": False}}
                )
                + "\n",
                encoding="utf-8",
            )
            stats = collect(telemetry)
            self.assertEqual(stats.turns, 1)
            self.assertEqual(stats.tool_calls["read_file"], 1)
            self.assertEqual(stats.tool_failures, 1)
            self.assertGreater(stats.to_dict()["estimated_total_tokens"], 0)
            store = AuthStore(Path(td) / "auth.json")
            store.set("demo", "abcdef123456")
            self.assertEqual(store.get("demo"), "abcdef123456")
            self.assertEqual(store.list()[0]["key"], "****3456")
            self.assertTrue(store.remove("demo"))
        self.assertIn("complete -F", generate("bash"))
        self.assertIn("Register-ArgumentCompleter", generate("powershell"))

    def test_plugin_hook_fires(self) -> None:
        from quillancode.hooks import HookBus
        from quillancode.plugin import load_plugins

        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "hook.json"
            script = Path(td) / "hook.py"
            script.write_text(
                "import sys,pathlib; pathlib.Path(sys.argv[1]).write_text(sys.argv[2])\n",
                encoding="utf-8",
            )
            config = Config.from_dict(
                {
                    "plugin": {
                        "p1": {
                            "event": "custom_event",
                            "command": [sys.executable, str(script), str(marker)],
                        }
                    }
                }
            )
            bus = HookBus()
            self.assertEqual(load_plugins(bus, config), ["p1->custom_event"])
            bus.emit("custom_event", {"value": 7})
            self.assertIn("custom_event", marker.read_text(encoding="utf-8"))

    def test_http_mcp_transport(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from quillancode.mcp import MCPConnection, MCPServerSpec
        import threading

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                req = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])).decode()
                )
                if req["method"] == "tools/list":
                    result = {
                        "tools": [
                            {
                                "name": "echo",
                                "description": "d",
                                "inputSchema": {"type": "object"},
                            }
                        ]
                    }
                else:
                    result = {
                        "content": [
                            {"type": "text", "text": req["params"]["arguments"]["text"]}
                        ]
                    }
                body = json.dumps(
                    {"jsonrpc": "2.0", "id": req["id"], "result": result}
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.server_address[1]
            spec = MCPServerSpec.from_dict(
                "remote",
                {
                    "type": "http",
                    "url": f"http://127.0.0.1:{port}/mcp",
                },
            )
            with MCPConnection(spec, timeout=10) as conn:
                self.assertEqual([t["name"] for t in conn.tools], ["echo"])
                out = conn.call_tool("echo", {"text": "remote-ok"})
                self.assertIn("remote-ok", json.dumps(out))
        finally:
            server.shutdown()
            server.server_close()

    def test_http_server_and_acp(self) -> None:
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from quillancode import server as qserver

        with tempfile.TemporaryDirectory() as td:
            config = Config.from_dict({})

            def factory(cfg, provider):
                p = MockProvider(ProviderSpec(name="mock"))
                p.set_script([{"content": "http-answer"}])
                return AgentLoop(cfg, provider=p, cwd=td, ask_fn=lambda prompt: True)

            handler = qserver._build_handler(config, factory)
            httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                health = json.loads(
                    urllib.request.urlopen(base + "/health", timeout=5).read()
                )
                self.assertTrue(health["ok"])
                req = urllib.request.Request(
                    base + "/v1/chat",
                    data=json.dumps({"message": "hi"}).encode(),
                    headers={"Content-Type": "application/json"},
                )
                body = json.loads(urllib.request.urlopen(req, timeout=10).read())
                self.assertEqual(body["answer"], "http-answer")
            finally:
                httpd.shutdown()
                httpd.server_close()
            os.environ["QUILLANCODE_MOCK_SCRIPT"] = json.dumps(
                [{"content": "acp-answer"}]
            )
            try:
                acp = subprocess.run(
                    [sys.executable, "-m", "quillancode", "acp"],
                    cwd=str(PKG),
                    input=(
                        '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}\n'
                        '{"jsonrpc":"2.0","id":2,"method":"session/prompt",'
                        '"params":{"prompt":[{"type":"text","text":"hi"}]}}\n'
                    ),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    timeout=30,
                )
            finally:
                os.environ.pop("QUILLANCODE_MOCK_SCRIPT", None)
            self.assertIn("end_turn", acp.stdout, acp.stderr)
            self.assertIn("acp-answer", acp.stdout)

    def test_opencode_compatible_gateway_path(self) -> None:
        """Exercise the real `openai_compat` HTTP path used by the OpenCode preset."""
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        import threading

        class Gateway(BaseHTTPRequestHandler):
            def log_message(self, fmt, *args):
                return

            def do_POST(self):
                req = json.loads(
                    self.rfile.read(int(self.headers["Content-Length"])).decode()
                )
                assert self.headers.get("Authorization") == "Bearer QC_TEST_KEY"
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "role": "assistant",
                                    "content": "OPENCODE_PATH_OK",
                                }
                            }
                        ]
                    }
                ).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(("127.0.0.1", 0), Gateway)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as td:
                config = Config.from_dict(
                    {
                        "providers": {
                            "opencode-test": {
                                "kind": "openai_compat",
                                "base_url": f"http://127.0.0.1:{server.server_address[1]}/v1",
                                "model": "opencode/test",
                                "api_key_env": "QC_GATEWAY_KEY",
                            }
                        },
                        "provider": {"default": "opencode-test"},
                    }
                )
                agent = AgentLoop(
                    config,
                    provider_name="opencode-test",
                    cwd=td,
                    ask_fn=lambda prompt: True,
                )
                os.environ["QC_GATEWAY_KEY"] = "QC_TEST_KEY"
                try:
                    answer = agent.run("ping")
                finally:
                    os.environ.pop("QC_GATEWAY_KEY", None)
                self.assertEqual(answer, "OPENCODE_PATH_OK")
        finally:
            server.shutdown()
            server.server_close()

    def test_git_helpers(self) -> None:
        from quillancode.github import diff as git_diff, status

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=False)
            result = status(td)
            self.assertTrue(result["ok"], result)
            Path(td, "a.txt").write_text("a", encoding="utf-8")
            subprocess.run(["git", "add", "a.txt"], cwd=td, check=False)
            self.assertIn("a.txt", git_diff(td, staged=True))


class FreeTierTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_free_tier_discovery_plug_and_install(self) -> None:
        from quillancode.free_tiers import discover, install, plug

        config = Config.from_dict({})
        tiers = {t.name: t for t in discover(config)}
        self.assertIn("gemini-free", tiers)
        self.assertIn("openrouter-free", tiers)
        self.assertIn("ollama-local", tiers)
        self.assertTrue(
            any(t.available for t in tiers.values()),
            "at least one free tier should be usable on this host",
        )
        spec = plug(
            config, "my-model", "https://example.invalid/v1", "any/model", "MY_KEY"
        )
        self.assertEqual(config.providers["my-model"].model, "any/model")
        self.assertEqual(spec.kind, "openai_compat")
        chosen = install(config)
        self.assertIn(config.default_provider, (chosen.name, "my-model"))

    def test_automatic_provider_fallback(self) -> None:
        from quillancode.providers.base import ProviderError

        class FailingProvider:
            name = "failing"

            def complete(self, messages, tools, *, stream=False):
                raise ProviderError("primary down")

            def list_models(self):
                return []

        config = Config.from_dict(
            {
                "provider": {"default": "failing"},
                "providers": {"fallback": {"kind": "mock", "model": "mock"}},
            }
        )
        with tempfile.TemporaryDirectory() as td:
            agent = AgentLoop(
                config, provider=FailingProvider(), cwd=td, ask_fn=lambda prompt: True
            )
            agent.fallback_names = ["fallback"]  # isolate from live account tiers
            answer = agent.run("ping")
            self.assertIn("ping", answer)
            self.assertTrue(
                any(e[0] == "provider_fallback" for e in agent.hooks.history)
            )

    def test_free_cli_commands(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc = self._invoke("free", "list")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("gemini-free", proc.stdout)
            plugged = self._invoke(
                "plug",
                "custom-x",
                "--base-url",
                "http://127.0.0.1:9/v1",
                "--model",
                "custom/model",
            )
            self.assertEqual(plugged.returncode, 0, plugged.stderr)
            self.assertIn("custom-x", plugged.stdout)


class FinalGapTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_lsp_diagnostics(self) -> None:
        from quillancode.lsp import check

        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / "sample.py"
            target.write_text("x = 1\n", encoding="utf-8")
            server = Path(td) / "fake_lsp.py"
            server.write_text(
                """
import sys, json
while True:
    header = b""
    while b"\\r\\n\\r\\n" not in header:
        c = sys.stdin.buffer.read(1)
        if not c: sys.exit(0)
        header += c
    n = int([l for l in header.decode().split("\\r\\n") if l.lower().startswith("content-length")][0].split(":")[1])
    msg = json.loads(sys.stdin.buffer.read(n))
    if "id" not in msg: continue
    result = {}
    if msg["method"] == "textDocument/diagnostic":
        result = {"items": [{"range": {"start": {"line":0,"character":0},"end":{"line":0,"character":1}},
                             "message": "sample diagnostic", "severity": 1}]}
    body = json.dumps({"jsonrpc":"2.0","id":msg["id"],"result":result}).encode()
    sys.stdout.buffer.write(f"Content-Length: {len(body)}\\r\\n\\r\\n".encode()+body)
    sys.stdout.buffer.flush()
""",
                encoding="utf-8",
            )
            items = check(target, [sys.executable, str(server)], cwd=td)
            self.assertEqual(items[0]["message"], "sample diagnostic")

    def test_attach_and_web_ui(self) -> None:
        import threading
        import urllib.request
        from http.server import ThreadingHTTPServer
        from quillancode import server as qserver

        with tempfile.TemporaryDirectory() as td:
            config = Config.from_dict({})

            def factory(cfg, provider):
                p = MockProvider(ProviderSpec(name="mock"))
                p.set_script([{"content": "attached-answer"}])
                return AgentLoop(cfg, provider=p, cwd=td, ask_fn=lambda prompt: True)

            httpd = ThreadingHTTPServer(
                ("127.0.0.1", 0), qserver._build_handler(config, factory)
            )
            threading.Thread(target=httpd.serve_forever, daemon=True).start()
            try:
                base = f"http://127.0.0.1:{httpd.server_address[1]}"
                html = urllib.request.urlopen(base + "/", timeout=5).read().decode()
                self.assertIn("<textarea", html)
                self.assertIn("/v1/chat", html)
                proc = self._invoke("attach", base, "hello")
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertIn("attached-answer", proc.stdout)
            finally:
                httpd.shutdown()
                httpd.server_close()

    def test_github_api_and_plugin_market(self) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from quillancode.github_api import issues, pull_requests
        from quillancode.plugin_market import install, search
        import threading

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def do_GET(self):
                data = (
                    [{"number": 7, "title": "sample"}]
                    if "/issues" in self.path or "/pulls" in self.path
                    else []
                )
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            api = f"http://127.0.0.1:{httpd.server_address[1]}"
            self.assertEqual(issues("o/r", api=api)[0]["number"], 7)
            self.assertEqual(pull_requests("o/r", api=api)[0]["title"], "sample")
        finally:
            httpd.shutdown()
            httpd.server_close()
        self.assertTrue(search("audit"))
        config = Config.from_dict({})
        self.assertEqual(install(config, "audit-trail")["event"], "tool_result")
        self.assertEqual(self._invoke("plugin", "search", "trace").returncode, 0)
        lsp = self._invoke("lsp", "servers")
        self.assertEqual(lsp.returncode, 0, lsp.stderr)
        self.assertIsInstance(json.loads(lsp.stdout), dict)


class LocalFirstTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )

    def test_extension_loader_registers_tool(self) -> None:
        from quillancode.extensions import ExtensionManager

        manager = ExtensionManager()
        names = [e.name for e in manager.discover()]
        self.assertIn("example_extension", names)
        registry = ToolRegistry()
        loaded = manager.load(
            registry,
            Config.from_dict({}),
            HookBus(),
        )
        self.assertIn("example_extension", loaded)
        self.assertIn("echo", registry.names())

    def test_git_tools_end_to_end(self) -> None:
        from quillancode.git_tools import GIT_TOOLS
        from quillancode.tools.permissions import Decision

        with tempfile.TemporaryDirectory() as td:
            subprocess.run(["git", "init", "-q"], cwd=td, check=False)
            subprocess.run(
                ["git", "config", "user.email", "qc@local"], cwd=td, check=False
            )
            subprocess.run(["git", "config", "user.name", "QC"], cwd=td, check=False)
            Path(td, "f.txt").write_text("hello\n", encoding="utf-8")
            from quillancode.tools.base import ToolContext

            registry = ToolRegistry(td)
            ctx = ToolContext(cwd=Path(td).resolve())
            gate = mock.MagicMock()
            gate.decide.return_value = Decision("allow", "low", "test")

            def call(name, **kwargs):
                return registry.execute_call(
                    ToolCall(id="g1", name=name, arguments=kwargs), ctx, gate
                )

            self.assertTrue(call("git_status").ok)
            self.assertTrue(call("git_add", paths=["f.txt"]).ok)
            self.assertIn("f.txt", call("git_diff", staged=True).output)
            self.assertTrue(
                call("git_commit", message="init").ok,
                call("git_commit", message="init").error,
            )
            self.assertIn("init", call("git_log").output)
            self.assertTrue(any(cls.name == "git_commit" for cls in GIT_TOOLS))

    def test_local_status_and_cli(self) -> None:
        from quillancode.local import status

        info = status()
        self.assertIn("installed", info)
        self.assertIn("local_ready", info)
        proc = self._invoke("local", "status")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("local_ready", proc.stdout)
        ext = self._invoke("extensions", "list")
        self.assertEqual(ext.returncode, 0, ext.stderr)
        self.assertIn("example_extension", ext.stdout)


class OpenCodeAccountTests(unittest.TestCase):
    def test_account_adapter_uses_local_session_no_api_key(self) -> None:
        import threading
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
        from unittest import mock
        from quillancode.opencode_account import OpenCodeAccountProvider

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                return

            def _json(self, payload):
                body = json.dumps(payload).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", "0")))
                if self.path == "/api/session":
                    self._json({"data": {"id": "s1"}})
                elif self.path.endswith("/prompt"):
                    self._json({"data": {"id": "m1"}})
                else:
                    self.send_response(404)
                    self.end_headers()

            def do_GET(self):
                self._json(
                    {
                        "data": [
                            {
                                "type": "assistant",
                                "content": [
                                    {"type": "text", "text": "ACCOUNT_MOCK_OK"}
                                ],
                                "finish": "stop",
                            }
                        ]
                    }
                )

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}"
            with (
                mock.patch(
                    "quillancode.opencode_account.service_password", return_value="pw"
                ),
                mock.patch(
                    "quillancode.opencode_account.discover_base_url", return_value=base
                ),
            ):
                adapter = OpenCodeAccountProvider(
                    ProviderSpec(
                        name="opencode-account",
                        kind="opencode_account",
                        model="hy4-flash-free",
                    )
                )
                reply = adapter.complete([Message(role="user", content="hi")], [])
                self.assertEqual(reply.content, "ACCOUNT_MOCK_OK")
        finally:
            server.shutdown()
            server.server_close()


class CompositionTests(unittest.TestCase):
    def test_profile_bundles_and_patch_overlays(self) -> None:
        from quillancode import profiles

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            old = profiles.PROFILES_DIR
            profiles.PROFILES_DIR = root
            try:
                (root / "base.json").write_text(
                    json.dumps({"settings": {"a": 1, "b": 2}}), encoding="utf-8"
                )
                profile = profiles.create("qc", ["base"], [str(root / "patch.json")])
                (root / "patch.json").write_text(
                    json.dumps({"settings": {"b": 3}}), encoding="utf-8"
                )
                merged = profiles.compose(Config.from_dict({}), "qc")
                self.assertEqual(merged["settings"], {"a": 1, "b": 3})
                self.assertEqual(profile.name, "qc")
            finally:
                profiles.PROFILES_DIR = old

    def test_local_schedule_due_advances(self) -> None:
        from quillancode import schedule

        with tempfile.TemporaryDirectory() as td:
            old = schedule.STORE
            schedule.STORE = Path(td) / "schedule.json"
            try:
                item = schedule.add("qc task", every=60)
                self.assertTrue(schedule.listing())
                self.assertEqual(schedule.due(), [])
                payload = json.loads(schedule.STORE.read_text(encoding="utf-8"))
                payload[0]["next_due"] = 0
                schedule.STORE.write_text(json.dumps(payload), encoding="utf-8")
                ready = schedule.due()
                self.assertEqual(ready[0]["id"], item["id"])
                self.assertGreater(ready[0]["next_due"], 0)
                self.assertTrue(schedule.remove(item["id"]))
            finally:
                schedule.STORE = old

    def test_parity_script_present(self) -> None:
        script = PKG / "scripts" / "parity_check.py"
        self.assertTrue(script.is_file())
        self.assertGreater(script.read_text(encoding="utf-8").count("Check("), 30)


class NativeCoreTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_native_glob_and_grep_match_python(self) -> None:
        from quillancode import native_core

        if not native_core.enabled():
            self.skipTest("native core not built")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for i in range(20):
                (root / f"f{i}.txt").write_text(
                    f"quillan line {i}\nother {i}\n", encoding="utf-8"
                )
            native = native_core.glob(root, "*.txt", 1000) or ""
            self.assertIn("f0.txt", native)
            self.assertIn("f19.txt", native)
            hits = native_core.grep(root, "quillan", "*.txt", 200) or ""
            self.assertIn("f0.txt:1", hits)
            self.assertEqual(len([l for l in hits.splitlines() if l.strip()]), 20)

    def test_native_file_io_commands(self) -> None:
        from quillancode import native_core

        if not native_core.enabled():
            self.skipTest("native core not built")
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.assertIn(
                "wrote", native_core.write(root, "sub/a.txt", "alpha beta\n") or ""
            )
            self.assertIn(
                "alpha beta", native_core.read(root, "sub/a.txt", 0, 10) or ""
            )
            self.assertIn("a.txt", native_core.list_dir(root, "sub") or "")
            self.assertIn(
                "replaced", native_core.edit(root, "sub/a.txt", "alpha", "gamma") or ""
            )
            self.assertIn(
                "gamma beta", (root / "sub" / "a.txt").read_text(encoding="utf-8")
            )
            self.assertEqual(
                len((native_core.file_hash(root, "sub/a.txt") or "").strip()), 16
            )
            self.assertIn(
                "BLOCKED",
                native_core.validate(root, str(root.parent / "escape.txt")) or "",
            )

    def test_native_cli_and_benchmark(self) -> None:
        from quillancode import native_core

        if not native_core.enabled():
            self.skipTest("native core not built")
        info = self._invoke("native", "info")
        self.assertEqual(info.returncode, 0, info.stderr)
        self.assertIn('"enabled": true', info.stdout)
        bench = self._invoke("--cwd", str(PKG), "native", "bench", "--rounds", "1")
        self.assertEqual(bench.returncode, 0, bench.stderr)
        self.assertIn("ms=", bench.stdout)


class DesktopIdeTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_ide_backend_endpoints(self) -> None:
        from quillancode.server import ide_selftest

        self.assertEqual(ide_selftest(), "IDE_SELFTEST_OK")
        proc = self._invoke("ide", "selftest")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("IDE_SELFTEST_OK", proc.stdout)

    def test_electron_shell_sources(self) -> None:
        desktop = PKG / "desktop"
        self.assertTrue((desktop / "package.json").is_file())
        for name in ("main.js", "preload.js"):
            proc = subprocess.run(
                ["node", "--check", str(desktop / name)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=30,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self._invoke("desktop", "check")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DESKTOP_CHECK_OK", proc.stdout)


class MatrixTests(unittest.TestCase):
    def test_opencode_matrix_artifact(self) -> None:
        script = PKG / "scripts" / "opencode_matrix.py"
        self.assertTrue(script.is_file())
        text = script.read_text(encoding="utf-8")
        self.assertIn("opencode --help", text)
        self.assertIn("gaps=", text)
        self.assertGreater(text.count('": ('), 18)


class RealMatrixTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_sqlite_db_ingest_query(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            dbp = Path(td) / "qc.db"
            telemetry = Path(td) / "telemetry.jsonl"
            telemetry.write_text(
                json.dumps(
                    {"ts": "t1", "event": "turn_start", "data": {"input_chars": 8}}
                )
                + "\n",
                encoding="utf-8",
            )
            init = self._invoke("db", "init", "--path", str(dbp))
            self.assertEqual(init.returncode, 0, init.stderr)
            ingest = self._invoke(
                "db", "ingest", "--path", str(dbp), "--source", str(telemetry)
            )
            self.assertIn('"ingested": 1', ingest.stdout, ingest.stderr)
            rows = self._invoke(
                "db", "query", "--path", str(dbp), "--sql", "SELECT event FROM events"
            )
            self.assertIn("turn_start", rows.stdout, rows.stderr)

    def test_git_workflow_and_pr_end_to_end(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            proc = self._invoke("--cwd", td, "github", "workflow")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["branch"], "qc/workflow")
            origin = Path(td) / "origin2.git"
            work = Path(td) / "work2"
            work.mkdir()
            subprocess.run(["git", "init", "--bare", "-q", str(origin)], check=False)
            for args in (
                ["init", "-q"],
                ["config", "user.email", "qc@local"],
                ["config", "user.name", "QC"],
            ):
                subprocess.run(["git", *args], cwd=str(work), check=False)
            (work / "a.txt").write_text("pr\n", encoding="utf-8")
            for args in (
                ["add", "a.txt"],
                ["commit", "-q", "-m", "base"],
                ["remote", "add", "origin", str(origin)],
                ["push", "-q", "origin", "HEAD"],
            ):
                subprocess.run(["git", *args], cwd=str(work), check=False)
            subprocess.run(
                ["git", "update-ref", "refs/pull/123/head", "HEAD"],
                cwd=str(origin),
                check=False,
            )
            pr = self._invoke("--cwd", str(work), "github", "pr", "123")
            self.assertEqual(pr.returncode, 0, pr.stderr)
            self.assertEqual(json.loads(pr.stdout)["branch"], "quillancode-pr-123")

    def test_matrix_special_checks_are_real(self) -> None:
        import importlib.util

        path = PKG / "scripts" / "opencode_matrix.py"
        spec = importlib.util.spec_from_file_location("qc_matrix_test", path)
        self.assertIsNotNone(spec and spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        for name in (
            "check_export",
            "check_import",
            "check_git_workflow",
            "check_pr_checkout",
        ):
            ok, detail, evidence = getattr(module, name)()
            self.assertTrue(ok, f"{name}: {detail} {evidence}")


class LifecycleTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_debug_upgrade_uninstall_runtime_behavior(self) -> None:
        debug = self._invoke("debug")
        self.assertEqual(debug.returncode, 0, debug.stderr)
        info = json.loads(debug.stdout)
        self.assertIn("executable", info)
        self.assertTrue(info["tools"])
        upgrade = self._invoke("upgrade", "--check")
        self.assertEqual(upgrade.returncode, 0, upgrade.stderr)
        up = json.loads(upgrade.stdout)
        self.assertTrue(up["up_to_date"])
        uninstall = self._invoke("uninstall", "--dry-run")
        self.assertEqual(uninstall.returncode, 0, uninstall.stderr)
        plan = json.loads(uninstall.stdout)
        self.assertTrue(plan["dry_run"])
        self.assertTrue(plan["package"])


class ArtifactTests(unittest.TestCase):
    def _invoke(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "quillancode", *args],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
        )

    def test_safetensors_and_checkpoint_inspection(self) -> None:
        from quillancode.artifacts import inspect

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            header = json.dumps(
                {"w": {"dtype": "F16", "shape": [2, 3], "data_offsets": [0, 12]}}
            ).encode()
            sf = root / "m.safetensors"
            sf.write_bytes(len(header).to_bytes(8, "little") + header + b"\0" * 12)
            info = inspect(sf)
            self.assertEqual(info["kind"], "safetensors")
            self.assertEqual(info["tensors"][0]["shape"], [2, 3])
            proc = self._invoke("artifact", str(sf), "--json")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(json.loads(proc.stdout)["tensors"][0]["dtype"], "F16")
            gg = root / "m.gguf"
            gg.write_bytes(
                b"GGUF"
                + (3).to_bytes(4, "little")
                + (7).to_bytes(8, "little")
                + (2).to_bytes(8, "little")
            )
            self.assertIn("GGUF v3", inspect(gg)["notes"][0])


class ByoGuideTests(unittest.TestCase):
    def test_guides_do_not_claim_generation(self) -> None:
        proc = subprocess.run(
            [sys.executable, "-m", "quillancode", "guide", "deepseek"],
            cwd=str(PKG),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("DEEPSEEK_API_KEY", proc.stdout)
        self.assertIn("No live generation is claimed", proc.stdout)


class ConsoleEncodingTests(unittest.TestCase):
    def test_diff_with_unicode_does_not_crash(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            for args in (
                ["init", "-q"],
                ["config", "user.email", "qc@local"],
                ["config", "user.name", "QC"],
            ):
                subprocess.run(["git", *args], cwd=td, check=False)
            target = Path(td) / "unicode.txt"
            target.write_text("hello\n", encoding="utf-8")
            subprocess.run(["git", "add", "unicode.txt"], cwd=td, check=False)
            subprocess.run(["git", "commit", "-q", "-m", "base"], cwd=td, check=False)
            target.write_text("hello ◆ ★ café\n", encoding="utf-8")
            proc = subprocess.run(
                [sys.executable, "-m", "quillancode", "--cwd", td, "diff"],
                cwd=str(PKG),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("café", proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
