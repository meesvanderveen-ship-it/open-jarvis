"""LLM/API cost & usage breakdown, and the multi-agent pipeline audit.

Shells out to tools/show_llm_cost_breakdown.py and
tools/build_multi_agent_prompt_audit.py (both read-only, no LLM/Coinbase
calls, no trading-state mutation -- see those files' docstrings). The
--since windows below are fixed, hardcoded values, never derived from
request input, per the shell_tool.run_json_tool contract.
"""

from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.shell_tool import run_json_tool


def get_llm_cost_24h() -> dict:
    return cache.get_or_compute(
        "llm_cost_24h",
        lambda: run_json_tool("show_llm_cost_breakdown.py", ["--since", "24h"]),
    )


def get_llm_cost_7d() -> dict:
    return cache.get_or_compute(
        "llm_cost_7d",
        lambda: run_json_tool("show_llm_cost_breakdown.py", ["--since", "7d"]),
    )


def get_multi_agent_prompt_audit() -> dict:
    return cache.get_or_compute(
        "multi_agent_prompt_audit",
        lambda: run_json_tool("build_multi_agent_prompt_audit.py"),
        ttl_seconds=300,
    )
