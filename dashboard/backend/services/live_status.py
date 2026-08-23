from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_live_status() -> dict:
    return cache.get_or_compute(
        "live_status", lambda: run_json_tool("show_autonomous_live_run_status.py")
    )
