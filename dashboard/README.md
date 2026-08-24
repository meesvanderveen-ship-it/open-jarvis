# Tradingbot Control Center

A **read-only** web dashboard for the Coinbase trading bot: live status, GrowBot/River
learning readiness, parameter change proposals, opportunity radar, multi-agent decision
trace, positions/orders, risk guards, logs, and reports — in one place, without ever
touching `.env`, mutating state, calling Coinbase, or restarting anything.

## Why this exists

Visibility into the bot previously meant running one of ~94 `tools/show_*.py` CLI
scripts, or reading raw JSON/JSONL files by hand. This dashboard is a thin, read-only
window onto the exact same data — it reuses the existing vetted status tools and report
files rather than reimplementing any bot logic.

## Architecture

```
dashboard/
  backend/   FastAPI app — see backend/app.py. Binds 127.0.0.1 by default.
  frontend/  React + Vite SPA, based on satnaing/shadcn-admin (MIT license).
```

In production, **one process** (the FastAPI backend) serves both the JSON API
(`/api/*`) and the built static SPA (`/`) — no separate Node server needed.

### Why satnaing/shadcn-admin over Kiranism/next-shadcn-dashboard-starter

Both are MIT-licensed, shadcn/ui + Tailwind + TypeScript + TanStack Table starters.
satnaing/shadcn-admin is a Vite SPA (`npm run build` → static `dist/`), so the whole
app can be served by `StaticFiles` from the same FastAPI process that serves the API —
one process, one port, easy to bind to loopback and reach over a single SSH tunnel.
Kiranism is a Next.js App Router project; running it in production means either a
second long-lived Node process or losing App Router features under static export.
For a small, local, read-only operator tool, the simpler single-process story won.

The cloned template's demo pages (Clerk auth, fake sign-in, Tasks/Users/Chats/Apps
demo data) were removed; the sidebar, topbar, theme provider (dark by default), command
menu, and `data-table`/card/badge/sheet/tabs primitives were kept and reused.

## Backend design

- `app.py` — FastAPI app. `RedactJSONMiddleware` runs on **every** response and
  recursively redacts secret-shaped keys/values, even if a service forgets to.
- `security/safe_paths.py` — every file read goes through an allowlist check
  (explicit filename allowlist for `state/`, root-containment check for
  `reports/`/`logs/`). `.env`, `.env.*`, `.git`, `.ssh` are hard-denied regardless of
  any input.
- `security/redact.py` — key-pattern and value-pattern (API-key-shaped strings, JWTs,
  long hex tokens) redaction.
- `services/shell_tool.py` — the only place that shells out to `tools/show_*.py
  --json`. Fixed argv, `shell=False`, no request input ever reaches a subprocess
  argument.
- `cache.py` — tiny TTL cache so dashboard polling doesn't hammer the filesystem or
  spawn a subprocess per request.
- Nothing in this backend ever imports or calls
  `autonomous_parameter_governor.run_governor(apply=True)`, never writes
  `state/positions.json` / `state/open_orders.json` / `.env`, never calls Coinbase, and
  never restarts a service.

## Running it

### One-time setup

```bash
# Frontend needs Node 20.19+ or 22.12+ (this box's system Node was 18; a local
# Node 22 was installed at /opt/nodejs/node-v22.14.0-linux-x64 for this project).
cd dashboard/frontend
PATH=/opt/nodejs/node-v22.14.0-linux-x64/bin:$PATH npm install
PATH=/opt/nodejs/node-v22.14.0-linux-x64/bin:$PATH npm run build

# Backend has its own venv, separate from the bot's — but shells out to the
# bot's venv (.venv/bin/python3) to run tools/show_*.py, since those import bot.*.
cd ../backend
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Start (production-style: one process, API + SPA)

```bash
cd dashboard/backend
.venv/bin/python -m dashboard.backend.run
# Binds 127.0.0.1:8000 by default. Refuses any other host unless
# DASHBOARD_ALLOW_NON_LOOPBACK=true is explicitly set (it shouldn't be).
```

### Dev mode (separate Vite dev server with hot reload, proxies /api to the backend)

```bash
# terminal 1
cd dashboard/backend && .venv/bin/python -m dashboard.backend.run
# terminal 2
cd dashboard/frontend && PATH=/opt/nodejs/node-v22.14.0-linux-x64/bin:$PATH npm run dev
```

### Opening it via SSH tunnel

The dashboard only binds to `127.0.0.1` on the server, by design. From your local
machine:

```bash
ssh -L 8080:127.0.0.1:8000 <user>@<server-host>
```

Then open `http://127.0.0.1:8080` in your local browser.

### Config (dashboard-only, never the bot's `.env`)

| Env var | Default | Purpose |
|---|---|---|
| `DASHBOARD_HOST` | `127.0.0.1` | Bind address |
| `DASHBOARD_PORT` | `8000` | Bind port |
| `DASHBOARD_ALLOW_NON_LOOPBACK` | `false` | Must be `true` to bind off-loopback |
| `DASHBOARD_CACHE_TTL_SECONDS` | `8` | TTL cache for tool/file reads |
| `DASHBOARD_MAX_INLINE_BYTES` | `2097152` (2MB) | Report files larger than this return metadata only |
| `DASHBOARD_SUBPROCESS_TIMEOUT_SECONDS` | `20` | Timeout for `tools/show_*.py` calls |

## Testing

```bash
cd dashboard/backend
.venv/bin/python -m pytest tests -q     # 44 tests
python3 -m py_compile $(find . -name "*.py")

cd ../frontend
PATH=/opt/nodejs/node-v22.14.0-linux-x64/bin:$PATH npm run build   # tsc -b && vite build
PATH=/opt/nodejs/node-v22.14.0-linux-x64/bin:$PATH npm run lint
```

## What's read-only vs. not yet wired

**Read-only (all 11 screens):** Overview, Learning Cockpit, Parameter Proposal Board,
Opportunity Radar, Agent Trace, Positions & Orders, Risk & Safety, Logs & Evidence,
Reports & Audits, Simulation Lab, Manual Approval. No screen has a button that writes
anything, applies anything, or calls Coinbase.

**Deliberately not live-active (read-only preview only, by design — not a missing
feature):**
- Parameter apply (Parameter Proposal Board, Simulation Lab) — preview only.
- Manual approval actions (restart, clear stale lock, manual close, parameter apply,
  live flag changes) — status display only, no buttons execute anything.
- `.env` is never read, written, or exposed anywhere in this dashboard.

**Known simplifications (could be extended later, not started):**
- Agent Trace shows the hard-gate/synthesis/judge/risk/learning/reflection steps that
  are actually persisted to disk per cycle. The six individual analysis-archetype LLM
  outputs (regime/trend/breakout/meanrev/bull/bear) and the DeepSeek preprocessor step
  are not persisted per-ticker by the bot itself, so they are not fabricated in the
  trace — only what's genuinely on disk is shown.
- River walk-forward pass/fail detail (a separate report field) isn't surfaced yet;
  the three GrowBot/River readiness tiers and their blockers are.
- `reports/config/*.env` proposed-diff snippets are excluded from the Reports browser
  by extension filter (`.json`/`.md` only) as an extra-conservative choice, even though
  the redaction middleware would already scrub any secret-shaped value in them.

## Data sources

| Screen | Source |
|---|---|
| Overview | `tools/show_autonomous_live_run_status.py --json`, `tools/show_full_pipeline_health.py --json`, `state/runtime_ticker_universe.json` (tracked-ticker badges) |
| Learning Cockpit | `tools/show_growbot_river_learning_status.py --json`, plus the adaptive learning intelligence layer (`GET /api/learning/intelligence` -> `bot/adaptive_learning_intelligence.py`; see [`docs/ADAPTIVE_LEARNING.md`](../docs/ADAPTIVE_LEARNING.md)) |
| Parameter Proposals | same learning-status tool (`top_proposals`/`per_parameter_diagnostics`) + `approved_parameter_profile` (via the live-status tool); proposal-tier funnel via `GET /api/parameters/proposal-funnel` |
| Opportunity Radar | `state/decision_outcomes.json` (latest record per ticker) |
| Agent Trace | `state/decision_outcomes.json`, `state/positions.json`, `state/open_orders.json`, `state/trade_reflections.jsonl` |
| Positions & Orders | `state/positions.json`, `state/open_orders.json`, `tools/show_open_orders.py --json --summary` |
| Trade Thesis | `state/positions.json`, `logs/analysis.jsonl` (tailed), `state/open_orders.json` |
| Risk & Safety | derived checklist from the two status tools above |
| Logs & Evidence | `logs/*.jsonl` (tailed, never fully loaded) |
| Reports & Audits | `reports/**/*.{json,md}` (depth-capped, size-capped) |
| Simulation Lab | Parameter Proposals + `reports/adaptive_policy/adaptive-policy-lab-latest.json` + `reports/backtests/` |
| Manual Approval | live status + pipeline health + parameter proposals (status display only) |
| Prompt templates (in Agent Trace) | static AST-parsed inventory of `bot/prompts.py` |

Positions, Opportunity Radar and Trade Thesis filter out **closed/historical**
entries for tickers not in `state/runtime_ticker_universe.json` (written by
`run_trader_loop.py` at startup from its own `ALLOWED_TICKERS`/
`PHASE_C_ALLOWED_TICKERS`) — so narrowing the bot's ticker list doesn't leave
stale tickers cluttering these views. An **open** position is never hidden
this way, regardless of the current ticker list, since it still needs
monitoring/exit. If the state file is missing (bot never ran, or predates
this feature), filtering fails open and shows everything.

## Security notes

- **Secrets:** never read `.env`/`.env.*` anywhere in this codebase (grep for
  `\.env` in `dashboard/backend/` turns up only the *name* of a status field,
  `env_write_performed`, which is always `false`). Every JSON response passes through
  a redaction middleware that masks secret-shaped keys and secret-shaped values
  (API key prefixes, JWTs, long hex tokens) as defense-in-depth, even though none of
  the wired sources are expected to contain real credentials.
- **Path safety:** `state/` access is an explicit filename allowlist (not a glob);
  `reports/`/`logs/` access re-resolves and hard-checks containment on every read,
  independent of the request. `.git`, `.ssh`, and any `.env*` path component are
  denied unconditionally.
- **No writes, ever:** there is no endpoint, no code path, and no imported function in
  this dashboard that can write to `state/*.json`, `.env`, or call Coinbase. The one
  function capable of writing `approved_parameter_profile.json`
  (`autonomous_parameter_governor.run_governor(apply=True)`) is never imported.
- **Bind scope:** defaults to `127.0.0.1`; a startup guard refuses any other host
  unless explicitly overridden.
- **Large files:** `reports/reflection/` (2GB+, 432 snapshot files) and 6MB+ state
  files are never loaded in full — report bodies over 2MB return metadata only, and
  log tailing is bounded by both line count and bytes read.
