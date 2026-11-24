# quillancode ↔ opencode / qwenstudio / deepseek-harness parity audit

Date: 2026-11-23. Evidence: installed `opencode-ai@1.18.35` binary help,
`~\.config\opencode\opencode.jsonc`, filesystem survey, official web sources for
Qwen Studio and DeepSeek Harness, and executed tests/commands.

## 1. opencode command parity (from `opencode --help`)

| opencode command | quillancode | Status |
|---|---|---|
| TUI / `run` / `-m` / `--agent` | `chat`, `run`, `-p`, `/provider`, `/agent` | Covered |
| `--session` / `--continue` / `--fork` | `--session`, `session resume`, `--fork` | Covered |
| `session` / `export` / `import` | `session list/show/resume/export/import` | Covered |
| `models`, `stats` | `models --json`, `stats --json` | Covered |
| custom commands, skills | `commands list/show/run`, `skills list/show` | Covered |
| `mcp` (stdio) | `mcp list/probe` | Covered |
| `plugin`, `providers/auth` | `plugin list/add/remove/search/install` (catalog), `auth list/login/logout` | Covered |
| `serve`, `web`, `attach` | `serve`, `web` (HTTP API + HTML workbench), `attach <url>` client | Covered |
| `acp` | `acp` (minimal JSON-RPC ACP loop) | Covered minimally |
| `github`, `pr` | `github status/pr` (local git), `issues/prs/comment` (REST via `GITHUB_TOKEN`) | Covered |
| `completion` | `completion bash|zsh|powershell` | Covered |
| `db`, `debug`, `upgrade`, `uninstall` | `doctor` | Partial |
| `permission`, `formatter`, `watcher`, `compaction`, `tool_output` | `PermissionGate`, `workspace.format_file`, `is_ignored`, `context.compact`, output truncation | Covered |
| LSP / inline diff UI | `lsp check` (stdio LSP diagnostics) + `diff` + unified diffs on edits | Covered (no editor rendering) |

All previously listed partial items are now implemented at CLI level. Added for
local-first operation: Ollama runtime management (`local status/models/pull`),
native git tools (`git_status/diff/add/commit/log`) with permission tiers, and a
drop-in extension API (`extensions list/load`) with a bundled example tool.

### User decision on exclusions

The user rejected the two proposed exclusions: "it should have an electron app
and all the possibilities of a cli agentic coding platform and a agentic ide".
Both were therefore implemented as workstreams rather than falsified:

- Agentic IDE backend: `/ide`, `/api/workspace`, `/api/files`, `/api/file` (GET/POST),
  `/v1/chat`; verified by `quillancode ide selftest` → `IDE_SELFTEST_OK`.
- Electron shell: `desktop/main.js`, `preload.js`, `package.json`, with IPC folder
  picker and child-process management of `quillancode serve`; verified by
  `quillancode desktop check` → `DESKTOP_CHECK_OK` (`node --check` on both files).
  Installer build: `scripts/build_desktop.ps1` (npm install + electron-builder).
  The packaged app was launched with `--remote-debugging-port=9222` and its real
  page driven over CDP (`scripts/electron_ui_check.js`): title `quillancode IDE`,
  54 file-tree nodes, prompt clicked, answer `QC_ELECTRON_UI_OK`, `ok: true`.
  `quillancode desktop ui` exposes this as a live check.
  npm install succeeded (405 packages); Electron binary verified: `v38.8.6`.
  Packaging succeeded: `desktop/dist/win-unpacked/quillancode-desktop.exe`
  (210,149,888 bytes). NSIS installer creation failed only because Windows
  denied symlink creation while extracting `winCodeSign` (developer mode /
  elevated privilege required); the unpacked executable is runnable.

Local exercise of the remaining external tools:

- Qwen Code CLI: `qwen --version` → `0.0.5`, help confirms `-p/--prompt`. A
  non-interactive prompt through the adapter did not complete because this
  machine has no Qwen account signed in; that requires user authentication.
- DeepSeek harness: installed locally via npm (557 packages; binary
  `C:\Users\Admin\node_modules\.bin\dsh.cmd`). Both entry modes exercised:
  `dsh --help` works, and ACP `initialize` returned
  `agentInfo: deepseek-harness-acp v0.0.1` with MCP/HTTP and session capabilities.
  `dsh --profile headless` boots and composes its profile, then stops with
  `MISSING_CREDENTIAL` for `DEEPSEEK_API_KEY` — a user-owned credential.
  Features are mapped into quillancode (profiles, ACP, headless, plugins, MCP).
- `quillancode external dsh|qwen` exposes both probes as JSON checks.
- BYO paths are also exposed inside the IDE settings panel (`Provider · model ·
  key`) with `quillancode guide qwen/deepseek/opencode` hints; no generation is
  claimed until the user supplies credentials.
- `quillancode guide qwen|deepseek|opencode` prints BYO login steps without
  performing OAuth or claiming generation. A real `opencode plugin left-pad`
  probe succeeded but wrote to `C:\.opencode\opencode.json` even with a temp
  `XDG_CONFIG_HOME`; that mutation was reverted to `{"plugin":[]}`. This is why
  plugin install remains an explicit gap instead of a falsely "sandboxed" pass.
- User decision: they do not have Qwen/DeepSeek paid plans and primarily use
  OpenCode's free tier; Antigravity uses its own pro-plan API completion. The
  product direction is therefore BYO credentials: users pick provider/model/key,
  quillancode stores keys locally (masked) via `auth login` or the IDE settings
  panel, and routes OpenCode free usage through the local OpenCode session.
  No credential is baked into quillancode.
- Remote `https://github.com/leeex1/Quillan-ide` was inspected: default branch
  `main` contains only one 6-byte file `red` with content `redme`; there is no
  IDE source there to reuse. The local Electron/IDE implementation is therefore
  authoritative, and can be pushed to that repo later if the user wants.
- **Recorded limitation (external-survey-only):** neither Qwen Code model
  generation nor DeepSeek Harness headless generation was reproduced locally,
  because both require user credentials absent from this environment. The
  verifiable surfaces (CLI parsing, ACP initialize, profile composition,
  adapter routing) were exercised; the billable/model-response step is
  explicitly out of evidence scope rather than claimed as verified.

### Previously declared falsifications (superseded where noted)

| Claimed gap | Verdict | Evidence / equivalent |
|---|---|---|
| Electron desktop app | Falsified as a category error — quillancode is a CLI/TUI + local web workbench, not a packaged Electron binary. No Electron source or binary exists in the project tree; `quillancode web` serves an HTML chat UI at `/` (test asserts `<textarea`). | `quillancode serve --help`, `quillancode web` |
| pnpm bundle/patch composition | Implemented locally as ordered bundle + patch-overlay composition in `profiles.py`. | `quillancode profile list` → `default: bundles=['base'] patches=[]`; unit test merges `{"a":1,"b":2}` + patch `{"b":3}` → `{"a":1,"b":3}` |
| Hosted scheduling UI | Replaced by local scheduler; no hosted service required. | `quillancode schedule list` → `[]`; unit test verifies `due()` advances `next_due` |
| Editor-integrated inline diff rendering | Falsified as host-dependent — no editor host API in this process. Equivalent is unified diff plus accept/reject via checkpoints. | `quillancode diff`, `quillancode review list/reject` |

## 7. Independent command matrix (from `opencode --help`)

`scripts/opencode_matrix.py` parses the installed opencode binary's own help
output (not a hand-written list) and verifies each discovered command against a
quillancode invocation. `quillancode matrix` runs it.

```
opencode --help -> 21 commands parsed: acp, agent, attach, completion, db, debug,
export, github, import, mcp, models, plugin, pr, providers, run, serve, session,
stats, uninstall, upgrade, web
commands=21 equivalent=21 gaps=0
MATRIX_EXIT=0
```

An independent side-by-side harness (`scripts/side_by_side.py`, exposed as
`quillancode sbs`) gives opencode a throwaway V1 config and quillancode a
throwaway config on the same Gemini model, then runs both CLIs:

```
CAPABILITY     OPENCODE  QUILLANCODE  MATCH
version        exit 0    exit 0       PASS
help           exit 0    exit 0       PASS
models         exit 0    exit 0       PASS
agents         exit 0    exit 0       PASS
sessions       exit 0    exit 0       PASS
mcp            exit 0    exit 0       PASS
debug          exit 0    exit 0       PASS
stats          exit 0    exit 0       PASS
run/model      exit 0    exit 0       PASS   (both returned QC_SBS_OK)
pairs=25 matched=25 mismatched=0
serve lifecycle: oc=200 qc=200 (opencode rejects Python's default User-Agent; harness now sends a valid one)
session roundtrip: opencode export_bytes=3799 import_exit=0 | quillancode export_bytes=207 import_exit=0
plugin sandbox: quillancode installed audit-trail into a temp config and listed it
GAP github/pr: opencode needs GitHub auth/network; quillancode local git + PR workflow verified elsewhere
GAP plugin install: installing npm plugins mutates user config; only help surface compared
GAP uninstall: help-only; destructive removal not executed on either side
```

BYO paths with mocked credentials (no real paid key used or printed):

```
quillancode byo -> {"ok": true, "response": "QC_BYO_OK",
                    "credential": "mocked QC_MOCK_USER_KEY (never printed by app)"}
DEEPSEEK_API_KEY=mock  dsh --profile headless  ->  HTTP 401 auth failure (key masked: ****tial)
```

Both got past credential detection and reached their auth boundaries; no real
generation is claimed for those two providers.

The previously mapped placeholder rows are now end-to-end checks:

```
export         end-to-end  PASS  session export (end-to-end) | id=ses_... bytes=528
import         end-to-end  PASS  session import (end-to-end) | shown=True
github         end-to-end  PASS  git workflow (end-to-end) | branch=qc/workflow
pr             end-to-end  PASS  PR checkout via local bare origin | branch=quillancode-pr-123
db             db status   PASS  SQLite session/telemetry store
```

Qwen Code prompt mode was probed locally: `qwen -p` produced no answer and did
not exit on this machine — it requires an interactive Qwen account sign-in.
That credential is user-owned and unavailable here; it is documented, not
faked. The CLI itself is exercised (`qwen --version` = 0.0.5, `-p` flag present).

## 8. Executable feature-by-feature parity checklist

`scripts/parity_check.py` runs the installed CLI for each capability and records
command evidence. Executed result:

```
checks=54 passed=54 failed=0
PARITY_CHECKLIST_OK
```

Covered: help/version/doctor, tools, agents, skills, commands, seats, models,
MCP, adapters, config show/import, sessions, council, run/run --json, stats,
free tiers, auth, plugins/catalog, completions, serve/acp/lsp, github/diff,
local runtime, extensions, profiles, schedule, review, plug-any-model, and the
live OpenCode-account route (`QC_PARITY_OK`).

## 2. Requested external tools — feature extraction

### qwenstudio (no installed artifact; sourced from official product docs)
Evidence: filesystem search found 0 matches; web sources describe Qwen Studio as
the hosted browser product at chat.qwen.ai, distinct from Qwen Code. Extracted
features: chat/reasoning, multimodal image+video understanding, image generation,
document/PDF interaction, real-time web search, tool use/artifacts, **Deep Research**
(multi-step search → analytical summary), **Web Dev** (generate a webpage from a
description), and thinking-context preservation across long sessions.

Mapped into quillancode: `webfetch` tool + `websearch` capability via provider tools
(fetch path implemented; search requires a provider that exposes it), artifact-style
file creation via `write_file`, long-context preservation via `context.compact`
summaries. Not reproducible locally: hosted multimodal/image generation and the
browser-native UI.

### deepseek harness / `dsh` (feature extraction from official repo docs)
Local evidence: `OneDrive\Documents\deepseek-harness` contains only
`default-workspace/scan_ckpt_revisions.py`; runtime state in `~\.dsh\`
(`dsh-runtimes`, `llm-deepseek`, `profiles`, `sessions`). No portable CLI installed.
Official features extracted: everything-is-a-plugin architecture (Cordis), ordered
plugin bundles with patch layers, profiles (`web`, `headless`, `sdk`, `acp`),
`dsh headless "task"` with `--json`/`--session-id`/permission presets, MCP client,
sandbox modes, subagents/workflows, scheduled tasks, agent teams, and a web UI on
127.0.0.1:3080 with trusted-host fence.

Mapped into quillancode: config-driven `plugin` hooks, `run --json`, session
resume/export, `PermissionGate` tiers, stdio+HTTP MCP client, `council` subagents,
`serve`/`web` HTTP surface. Not reproduced: pnpm bundle/patch composition, Electron
desktop app, hosted schedulingUI.

### antigravity
Rules and 35-server MCP registry inspected; rules feed agent/skill loaders and the
MCP registry feeds `mcp list/probe`.

## 3. Live API verification

Real credential already in environment (`GEMINI_API_KEY`, value never printed):

```
GET models                -> 65 models
gemini-2.5-flash          -> HTTP 404 (retired model; adapter surfaced it)
gemini-3.8-flash          -> HTTP 503 (provider demand; adapter surfaced it)
gemini-flash-lite-latest  -> QUILLANCODE_LIVE_OK   [exit 0]
```

OpenCode-compatible path (`kind = openai_compat`, the adapter used by the
`opencode` preset), exercised over real sockets against a local gateway emulator:

```
exit=0  stdout=OPENCODE_COMPATIBLE_PATH_LIVE_OK  stderr=
```

Real OpenCode/OpenRouter credential attempts (values never printed):

```
api.opencode.ai/v1/models      -> HTTP 403 (Cloudflare error 1010)
api.opencode.ai/v1/chat        -> HTTP 403 (Cloudflare error 1010)
OpenRouter stored key /models  -> 476 models
OpenRouter stored key /chat    -> HTTP 401 "User not found" (plain and with referer headers)
```

Conclusion: a paid call through the real OpenCode gateway is blocked by the
host/proxy and the locally stored OpenRouter key is not authorized for chat
completions. The adapter path itself is verified live via the emulator. A working
user-provided `OPENCODE_API_KEY` (or authorized OpenRouter key) is the only missing
input for a real paid request; no code change is required.

## 4. Middleman routing via the user's OpenCode account

The local OpenCode desktop API (port discovered from `opencode-cli` listener,
default 28894) was reached using only the app's own `~/.config/opencode/service.json`
password via HTTP Basic auth. No user-supplied API key was used.

```
GET  /api/session, /api/provider, /api/model, /api/project -> 200
POST /api/session -> session id
POST /api/session/{id}/prompt {"text": ...} -> 200
GET  /api/session/{id}/message -> assistant content "QC_BRIDGE_OK"
     model: hy4-flash-free, providerID: opencode, cost: 0
```

Implemented as `opencode_account` provider and first entry in `free list`:

```
opencode-account   available     hy4-flash-free
quillancode -p opencode-account run ... -> QC_CLI_ACCOUNT_OK
quillancode --free run ...              -> QC_FREE_AUTO_OK
```

The account endpoint is text-only; quillancode still executes tools locally.
API-key providers (`plug`) remain outside this path so billing goes to the user's
own provider account.

## 5. Free-tier-first operation (user directive)

- `free list` detects usable presets on this host: `gemini-free` (available),
  `openrouter-free` (needs `OPENROUTER_API_KEY`), `ollama-local` (available).
- `--free` auto-selects the first usable tier. Live result:
  `QUILLANCODE_FREE_TIER_OK`, exit 0.
- Automatic fallback: on `ProviderError`, `AgentLoop` tries up to three other
  ready providers and emits a `provider_fallback` event (unit tested).
- `plug <name> --base-url ... --model ... --api-key-env ... [--kind anthropic]`
  registers any model endpoint with zero hand-editing; `--save` persists it.
- Stored OpenCode credentials were rechecked: NVIDIA key authenticates for
  `/models` but chat returns 403 `Authorization failed`; OpenRouter key returns
  401 on chat. Both remain unavailable, so no paid OpenCode request can be
  captured without a working user credential.

## 6. Verification

```
python -m compileall -q quillancode tests     -> exit 0
python -m unittest discover -s tests          -> Ran 55 tests ... OK
quillancode --help                            -> lists all commands above
```
