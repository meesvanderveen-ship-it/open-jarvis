"""Parameter Proposal Funnel data for the Learning Cockpit screen.

Shells out to tools/build_parameter_proposal_funnel.py (read-only, no
LLM/Coinbase calls, no trading-state mutation -- see that file's docstring).
"""

from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_parameter_proposal_funnel() -> dict:
    return cache.get_or_compute(
        "parameter_proposal_funnel", lambda: run_json_tool("build_parameter_proposal_funnel.py")
    )
