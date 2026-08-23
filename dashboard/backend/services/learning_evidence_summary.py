"""Learning Evidence Summary data, merged into the Run Summary screen.

Shells out to tools/build_latest_learning_evidence_summary.py (read-only,
deterministic, no LLM/Coinbase calls -- see that file's docstring). This is
an evidence summary of logs and recorded decisions, not a model's chain of
thought.
"""

from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_learning_evidence_summary() -> dict:
    return cache.get_or_compute(
        "learning_evidence_summary", lambda: run_json_tool("build_latest_learning_evidence_summary.py")
    )
