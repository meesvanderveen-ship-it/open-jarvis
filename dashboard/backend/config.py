"""Dashboard-only configuration.

This is deliberately separate from `bot/config.py` (the trading bot's own
config module). The dashboard never imports the bot's config, never reads
`.env`, and only knows about its own tiny set of settings below.
"""

from __future__ import annotations

import os
from pathlib import Path

# Repo root: dashboard/backend/config.py -> dashboard/backend -> dashboard -> repo root
PROJECT_ROOT = Path(__file__).resolve().parents[2]

REPORTS_ROOT = PROJECT_ROOT / "reports"
STATE_ROOT = PROJECT_ROOT / "state"
LOGS_ROOT = PROJECT_ROOT / "logs"
TOOLS_ROOT = PROJECT_ROOT / "tools"

# tools/show_*.py import `bot.*`, which requires the bot's own venv (not the
# dashboard's). We only ever invoke it with a fixed argv, never shell=True.
_BOT_VENV_PYTHON = PROJECT_ROOT / ".venv" / "bin" / "python3"
BOT_PYTHON_EXECUTABLE = str(_BOT_VENV_PYTHON) if _BOT_VENV_PYTHON.exists() else "python3"

HOST = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
PORT = int(os.environ.get("DASHBOARD_PORT", "8000"))

# Defense-in-depth: refuse to bind off-loopback unless explicitly overridden.
ALLOW_NON_LOOPBACK = os.environ.get("DASHBOARD_ALLOW_NON_LOOPBACK", "false").lower() in (
    "1",
    "true",
    "yes",
)

# TTL (seconds) for caching subprocess/file reads so the dashboard polling
# the UI doesn't hammer the filesystem or spawn a process per request.
CACHE_TTL_SECONDS = float(os.environ.get("DASHBOARD_CACHE_TTL_SECONDS", "8"))

# Any single report/state file body larger than this is summarized
# (size + parsed metadata only), never returned in full.
MAX_INLINE_BYTES = int(os.environ.get("DASHBOARD_MAX_INLINE_BYTES", str(2 * 1024 * 1024)))

# Subprocess timeout for shelling out to tools/show_*.py --json
SUBPROCESS_TIMEOUT_SECONDS = float(os.environ.get("DASHBOARD_SUBPROCESS_TIMEOUT_SECONDS", "20"))
