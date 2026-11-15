# MedAgent Workbench (医学智能体桌面工作台)

Brand name: **MedAgent Workbench** / **医学智能体桌面工作台** — "本地优先、模型无关的
医学科研 AI 智能体工作台". A medical fork of Open Science Desktop (MIT; see `NOTICE`
for the derivation and what this fork changes). Bundle identifier
`com.medagent.workbench` (renamed in 0.8.0 from `com.ai4s.workbench`, whose data
directory is migrated on first launch); internal `@ai4s/*` package names are
unchanged.

Project rules and working context for AI agents (Claude Code, Cursor, Codex, etc.).
`CLAUDE.md` is a symlink to this file — edit only `AGENTS.md`.

## Design principles

Keep it **simple, explicit, clear, complete**.

- **Simple** — no over-engineering; if not necessary, do not add entities.
- **Explicit** — no ambiguity; no bugs.
- **Clear** — understandable at a glance.
- **Complete** — cover the key points; prioritize safety.

## What this project is

An open-source, local-first, model-agnostic desktop workbench for **medical
research**: clinical evidence synthesis, diagnostic-accuracy statistics, case
reports, literature review, with provenance for every artifact. It is a fork of
[Open Science Desktop](https://github.com/ai4s-research/open-science) (MIT): the
desktop shell, the OpenCode runtime and the provenance ledger are shared with
upstream; the product identity, the connectors, the skill set and the example
project are medical. See `README.md` (what actually ships), `NOTICE` (derivation)
and the inherited design docs under `docs/`.

Recommended stack: **Tauri 2 + React + TypeScript + Vite**, Tailwind + Radix UI,
**OpenCode** as the agent runtime (bundled single-binary sidecar; HTTP + SSE API),
local workspace + SQLite + JSONL provenance.

## Repository map

- `apps/desktop/` — Tauri + React desktop shell (`src/` frontend, `src-tauri/` Rust).
- `packages/` — `ui`, `shared`, `sdk` (the `OpenCodeClient` wrapper).
- `runtime/` — `manager`, `opencode-profile`, `mcp`, `skills`, the OpenCode
  guard plugins and custom tools, and `computer/` (the computer-use host layer).
- `native/` — the per-platform computer-use providers (macOS Swift helper app,
  Linux AT-SPI script, Windows UI Automation script), ported from Orca (MIT).
  Staged into the bundle by `scripts/dev/build-computer-use.mjs`.
- `docs/` — product and technical specs.
- `examples/clinical-diagnostics/` — the built-in demo project (simulated
  diagnostic-accuracy study; its `analyze.py` reproduces every number in its
  report).
- `scripts/` — release and dev scripts.

## Architecture guardrails

- The UI never calls OpenCode directly — it goes through `packages/sdk` (`OpenCodeClient`).
  Pin the OpenCode version (see `OPENCODE_VERSION`) and bundle it as a sidecar.
- Keep the frontend, desktop shell, and agent runtime decoupled.
- Skills, MCP servers, and model providers must stay pluggable.
- Keep the artifact schema and workflow templates stable and versioned.
- Every feature must work on Windows, macOS, and Linux, AND in the gateway web
  client — including phone-width viewports (the web client is used from
  phones). If a feature fundamentally cannot work over the web (local kernels,
  native dialogs, host filesystem access), hide it in web mode (`isGatewayWeb`)
  instead of shipping a control that fails.

## Safety defaults (non-negotiable for the desktop)

- The agent may only access the current workspace.
- Command execution, file deletion, dependency install, and remote connections
  require approval (manual approval mode by default — never ship `off`).
- API keys go to the OS keychain / credential manager; never into provenance,
  logs, crash reports, git, or exported projects.
- **Medical boundary (non-negotiable):** nothing the app or its skills say may be
  presented as diagnosis or treatment advice for an individual patient, and no
  UI copy may imply clinical validation. The posture is stated in `README.md`,
  `NOTICE` and the medical skills; keep new copy consistent with it, and prefer
  research/teaching framing ("the evidence suggests…") over recommendation
  framing ("you should…").

## Working conventions

- Default working language for discussion is Chinese. **Code, comments and the
  inherited design docs stay English**; user-facing docs may be Chinese — the
  Chinese README is the primary one, and Chinese is the first UI language.
- One progress file: `PROGRESS.md`. Append one line per real milestone,
  `YYYY-MM-DD HH:MM` + a one-sentence conclusion, newest on top. Results and
  blockers only.
- Avoid adding new Markdown docs unless requested — too many docs become debt.
- Prefer minimal, verifiable changes; every step should produce a checkable result.
- Before pushing to master, run the checks for what you touched: `pnpm typecheck && pnpm lint && pnpm test`
  for the app, `cargo test -p osd-core` for the crates. CI on master runs only nightly.
- Do not write inferences as verified facts; tie conclusions to code or data.
- New session workspaces are local git repos: the app initializes them and makes
  best-effort local commits after workspace file changes. Never set a remote or push.
