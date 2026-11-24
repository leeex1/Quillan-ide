# quillancode

## 🧭 Canonical project context

| | |
| :--- | :--- |
| **This repo** | Provider-agnostic sovereign code-assistant CLI/TUI that absorbs the best surfaces of installed assistants. |
| **Canonical package** | Three deployed models: Quillan-Ronin Flagship (~1B), Quillan-Ronin-Mini (~0.8B) and Quillan-Dragon (~1B). The ONI Python sources are implementation/training only. |
| **Donor design** | Flagship and Mini: Qwen 0.6B + Llama ~1B + BitNet 2B-4T + Falcon3 ~1B **as a group** (cross-match fix in progress). Dragon: Falcon3 with an Ollama system message running Quillan's system prompt. |
| **Reading the scores** | The 95–100% table in the root README is **Track A** — the Quillan harness on a third-party frontier base, not a Quillan checkpoint. Hard-exam cells are pending re-test; ARC-AGI-3 public ~99s, private pending. |
| **Historical framing** | Edo period, rōnin and bushidō are real Japanese history and ethics — not roleplay, game mechanics, or fantasy lore. |
| **Canonical docs** | [Root README](https://github.com/leeex1/Quillan-Ronin#readme) · [Fleet model cards](https://github.com/leeex1/Quillan-Ronin/blob/main/docs/MODEL_CARDS.md) |

<!-- QUILLAN-DOCS-PROVENANCE:BEGIN -->
<details>
<summary><b>📌 Quillan documentation provenance</b> — expand for canonical sources</summary>

> **Documentation provenance.** This repo is part of the Quillan-Ronin ecosystem (CrashOverrideX / `leeex1`). Canonical sources live in the root repository: `README.md` (**READ FIRST** — Track A harness-on-frontier vs. Track B native WSP models vs. Track B′ custom Mini) and `docs/MODEL_CARDS.md` (fleet identity, verified facts, open gaps). The large 95–100% benchmark table in the root README is a **harness-on-frontier** result, not a score of any Quillan-owned checkpoint. Creator artifacts (books, music, game demo) have primary-source links in the root README's **Creator and verifiable artifacts** section.  Four-donor design: Flagship and Mini receive all four donors (Qwen ~0.6B + Llama ~1B + BitNet 2B-4T + Falcon3 ~1B) **as a group**; Dragon is Falcon3 with an Ollama system message running Quillan's system prompt. Cross-match fix in progress.  The canonical package is the three deployed models — Quillan-Ronin Flagship (~1B), Quillan-Ronin-Mini (~0.8B) and Quillan-Dragon (~1B); the ONI Python sources are the implementation/training package, not the shipped product. Canonical official links (site, social, repos, Ollama, HF, Grokipedia, NotebookLM, DeepWiki, Genius, YouTube/Suno) are in the root README's **Official links** directory. Historical framing is real Japanese history (Edo period, rōnin, bushidō) used as an ethical reference frame — not roleplay, game mechanics, or fantasy lore.

</details>

<!-- QUILLAN-DOCS-PROVENANCE:END -->

Sovereign, provider-agnostic code-assistant CLI/TUI. It does not replace the
assistants already installed on this machine — it **absorbs their best surfaces**
into one engine and bridges back to them when their native mode is needed.

Zero mandatory dependencies (Python 3.11+ standard library only). Optional
`rich` + `prompt_toolkit` enable an enhanced TUI.

## Why this exists

Surveyed on this host (evidence from `npm ls -g` and config directories):

| Tool | Version detected | Reused surface |
|---|---|---|
| opencode (`opencode-ai`) | 1.18.35 | provider config, 74–78 agent definitions, slash-command UX, `run` mode |
| Claude Code | 2.1.312 | permission tiers, step↔verify TODOs, subagents, skills |
| Gemini CLI | 0.55.1 | approval modes, context compression threshold idea |
| Qwen Code | 0.0.5 | model config, strict JSON tool schemas |
| GitHub Copilot CLI | 1.0.48 | diff/review posture, prompt-mode invocation |
| Kilo Code | 7.5.6 | multi-provider routing, per-task model override |
| Antigravity IDE | — | rules files, MCP registry |
| Windsurf | — | skills, plans, checkpoint/rewind |
| DeepSeek harness | — | OpenAI-compatible endpoint pattern, falsification loop |

`quillancode` implements these as native subsystems, not as wrappers:

- **Provider layer** — `mock`, `openai_compat` (OpenCode gateway, OpenAI, DeepSeek,
  Qwen, Ollama, OpenRouter, NVIDIA NIM) and `anthropic`. Keys come from environment
  variables, never from stored config.
- **Tool layer** — `read_file`, `write_file`, `edit_file`, `list_dir`, `glob`,
  `grep`, `bash`, `webfetch`, `todo_write`, `checkpoint`, `rewind`, `session_info`. Every path is
  resolved against the workspace root; traversal outside it is rejected.
- **Permission gate** — `low|medium|high|blocked` tiers, `allow|ask|deny` policy,
  session allowlists and regex blocked patterns.
- **Agent loop** — provider → tool schemas → gated execution → tool results →
  terminal answer, with automatic checkpoints on writes and deterministic
  context compaction.
- **Council** — all 34 seats encoded; `council` spawns seat-specific proposals
  and a judge synthesis (or an offline deterministic judge).
- **MCP client** — stdio JSON-RPC 2.0 (`initialize`, `tools/list`, `tools/call`)
  with a reader thread for Windows-safe timeouts; remote tools register as local tools.
- **Skills / agents** — discovers Markdown skills and agent definitions from
  opencode, Claude Code and Windsurf directories; `/agent <id>` activates one.
- **Config import** — reads opencode JSONC and Qwen YAML, imports endpoints and
  model names, **redacts literal secrets** and emits generated env-var names.
- **CLI bridge** — detects installed assistant binaries by absolute path and can
  delegate a prompt to them (`adapters run`).
- **TUI** — stdlib REPL with slash commands; automatically upgrades to
  `prompt_toolkit` + `rich` when installed.

## Install

```powershell
python -m pip install -e .
quillancode --version
```

## Use

```powershell
quillancode doctor                       # environment + readiness JSON
quillancode adapters list                # detected assistant CLIs
quillancode agents list --json           # inherited agent definitions
quillancode skills list                  # inherited skills
quillancode tools                        # builtin tool registry
quillancode seats                        # 34 council seats
quillancode commands list                # inherited Markdown slash commands
quillancode models --json                # list provider models
quillancode session list                 # list resumable sessions
quillancode session resume <id>          # resume a session (--fork available)
quillancode stats --json                 # local token/tool usage stats
quillancode auth list                    # stored credentials (masked)
quillancode plugin list                  # config-driven event hooks
quillancode serve --port 4096            # headless HTTP API
quillancode acp                          # ACP stdio loop
quillancode completion powershell        # shell completion script
quillancode lsp check file.py            # LSP diagnostics (config lsp.servers)
quillancode attach http://127.0.0.1:4096 "hello"
quillancode plugin search audit          # local plugin catalog
quillancode github issues --repo owner/repo
quillancode config import --from opencode
quillancode -p opencode chat             # interactive REPL with your OpenCode key
quillancode -p openai run "add a test for foo" --json
quillancode -p deepseek council "should we use SQLite or Postgres?" --agents 5
```

Native C++ hot-path core (speed):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\build_native.ps1
quillancode native info
quillancode native bench --rounds 3
```

`quillancode/bin/qc_core.exe` (clang++ `-O3`, ~416 KB) now implements the whole
filesystem hot path: `glob`, `grep`, `read`, `write`, `edit`, `list`, `hash`,
`append`, `validate`, and `bench`. The Python builtin tools call the compiled
binary first and fall back to stdlib if it is absent. Path confinement is
enforced in C++ (`validate` prints `BLOCKED` for escapes). Verify with
`quillancode native selftest` → `NATIVE_SELFTEST_OK`.

Measured on this project tree: Python scan 24.7 ms vs native 11 ms for one
round (~2.2x). LLM orchestration, MCP and providers remain in Python so the
verified 46-test surface stays intact; the native layer owns the hot I/O.

Local-first operation (Ollama):

```powershell
quillancode local status          # binary, server, model inventory
quillancode local pull qwen2.5-coder:0.5b
quillancode plug local-qwen --base-url http://localhost:11434/v1 --model qwen2.5-coder:0.5b --save
quillancode -p local-qwen chat
```

The agent also has native `git_status`, `git_diff`, `git_add`, `git_commit` and
`git_log` tools, gated by the same permission system (commit = high risk).

Extensions: drop a Python file with `register(registry, config, hooks)` into
`~/.quillancode/extensions/` or `.quillancode/extensions/`; discover with
`quillancode extensions list`. A bundled example registers an `echo` tool.

Desktop app and agentic IDE (required by user decision):

quillancode is BYO by design: it uses the OpenCode free tier when the desktop app
is running, and users connect any other provider/model/key via `quillancode plug`,
`quillancode auth login`, or the IDE's Provider·model·key panel. Keys are stored
locally and masked; nothing is embedded in the app.

The IDE is a free-floating SAO-style holo deck: translucent glass panels with
luminous hairline borders, corner brackets, deep shadows and a subtle hover
float. A slow WebGL matrix rain runs strictly behind the glass (30fps, 1× DPR).
Each foreground surface has its own shader layer: a data lattice in the explorer,
a neural pulse field in the agent panel, and chromatic ghost text with occasional
glitch in the editor. Panels include an explorer (↑ Up, filter, Ctrl+P quick open,
file-type icons), multi-file tabs with unsaved indicators, a line-numbered editor
with Ctrl+S save, provider/model/key controls, and an agent chat. It supports any file type: text is edited in place; images, audio,
video and PDFs are rendered inline; `.safetensors`, `.pt`, `.gguf`, `.npy/.npz`
and other binary artifacts are inspected into a tensor/entry table with a hex
preview (`quillancode artifact <path>` exposes the same inspector).
`quillancode ide selftest` and `quillancode desktop ui` verify these surfaces.
Branding assets (geometric Quillan logo, samurai/ronin badges, banner) are bundled
from the existing local media library under `quillancode/web/assets` and served at
`/assets/*`. The Electron shell has a full native menu: File (Open Folder, New
Window, Save, Quick Open, Exit), Edit, View, Agent (Focus Prompt, Clear,
Review), and Help. `desktop/icon.png` is the converted window icon.

```powershell
quillancode ide selftest          # IDE_SELFTEST_OK
quillancode desktop check         # DESKTOP_CHECK_OK (node --check)
powershell -ExecutionPolicy Bypass -File .\scripts\build_desktop.ps1
```

`desktop/` contains the Electron shell: it spawns `quillancode serve` for the
selected workspace and loads `/ide`, which exposes a workspace tree, file
open/save, agent chat and run-log in one window. The backend endpoints are
`/api/workspace`, `/api/files`, `/api/file` (GET/POST) and `/v1/chat`, all
workspace-confined. `scripts/build_desktop.ps1` installs Electron deps and runs
`electron-builder --win nsis`.

Middleman routing (OpenCode account):

If the OpenCode desktop app is running, quillancode can route `opencode/*` models
through that same local authenticated session — no API key needed, and usage stays
on the user's OpenCode account:

```powershell
quillancode free list                       # opencode-account: available
quillancode -p opencode-account run "hello"
quillancode --free run "hello"              # selects opencode-account first
```

The adapter reads the desktop app's own `~/.config/opencode/service.json` password
and calls its local API (`/api/session`, `/api/session/{id}/prompt`). API-key
providers remain separate: with `plug`, the user's own key covers billing outside
quillancode.

Free-tier-first operation:

```powershell
quillancode free list                    # discover usable free endpoints
quillancode --free run "hello"           # auto-select the best available free tier
quillancode free install --save          # persist the selection
```

Built-in presets: Google AI Studio (`GEMINI_API_KEY`, `gemini-flash-lite-latest`),
OpenRouter `:free` models (`OPENROUTER_API_KEY`), and local Ollama (no key).
On provider failure, quillancode automatically tries other ready providers.

Plug in any model without editing config:

```powershell
quillancode plug my-llm --base-url https://api.example.com/v1 --model vendor/model-x --api-key-env MY_KEY --save
quillancode -p my-llm chat
```

Set credentials in the environment, e.g.:

```powershell
$env:OPENCODE_API_KEY = "..."
$env:DEEPSEEK_API_KEY = "..."
$env:QUILLANCODE_KEY_NVIDIA = "..."
```

`/provider <name>` and `/agent <id>` switch model and persona mid-session.
`/rewind [id]` restores a checkpoint; `/trace` shows the tool trace.

## Configuration

`quillancode config init` writes `quillancode.toml` in the workspace. JSON is
also accepted. Example:

```toml
[provider]
default = "openai"

[providers.openai]
kind = "openai_compat"
base_url = "https://api.openai.com/v1"
model = "gpt-4o-mini"
api_key_env = "OPENAI_API_KEY"

[permissions]
default = "ask"

[settings]
compact_threshold = 0.8
checkpoint_on_write = true
max_tool_steps = 20
```

## Security posture

- Literal API keys found in upstream configs are counted and redacted, never copied.
- Telemetry JSONL redacts key/token/secret patterns before writing.
- Workspace path confinement is enforced at the tool boundary.
- `bash` is a high-risk tier and matches blocked patterns such as `rm -rf`.
- Tool output is data, never instructions.

A command-by-command comparison against the installed opencode 1.18.35, including
the qwenstudio/deepseek-harness findings and live-API evidence, is in
`docs/PARITY_AUDIT.md`.

## Verification

```powershell
python -m compileall -q quillancode tests
python -m unittest discover -s tests -v
```

The suite is fully offline: a mock provider with a monkeypatched `urlopen` proves
no network access, a stdlib JSON-RPC echo subprocess proves MCP, a temp directory
proves tool confinement, and subprocess tests prove the installed console script.

## Layout

```
quillancode/
  cli.py  config.py  models.py  agent.py  council.py
  adapters.py  agents.py  skills.py  importers.py
  mcp.py  hooks.py  telemetry.py  context.py
  providers/  (base, registry, mock, openai_compat, anthropic)
  tools/      (base, registry, permissions, builtin)
  tui/        (base, plain, rich_tui)
tests/test_core.py
```
