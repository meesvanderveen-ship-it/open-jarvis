from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_learning_status() -> dict:
    return cache.get_or_compute(
        "learning_status", lambda: run_json_tool("show_growbot_river_learning_status.py")
    )
