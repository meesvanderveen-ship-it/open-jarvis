"""Adaptive Learning Intelligence data for the Learning Cockpit screen.

Shells out to tools/build_adaptive_learning_intelligence.py (read-only, no
LLM/Coinbase calls, no trading-state mutation -- see that file's docstring).
Cached like every other status endpoint.
"""

from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_learning_intelligence() -> dict:
    return cache.get_or_compute(
        "learning_intelligence", lambda: run_json_tool("build_adaptive_learning_intelligence.py")
    )
