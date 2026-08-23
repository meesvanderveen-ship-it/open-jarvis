from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_pipeline_health() -> dict:
    return cache.get_or_compute(
        "pipeline_health", lambda: run_json_tool("show_full_pipeline_health.py")
    )
