"""Latest Run Summary / decision-evidence summary for the Overview screen.

Shells out to tools/build_latest_run_summary.py (deterministic, read-only,
no LLM call -- see that file's docstring) for the cycle narrative, then
merges in learning_notes from the existing learning-status service. No new
data sources, no bot-state mutation, no Coinbase calls.
"""

from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.services.learning_evidence_summary import get_learning_evidence_summary
from dashboard.backend.services.learning_status import get_learning_status
from dashboard.backend.services.shell_tool import run_json_tool, ToolExecutionError


def _learning_notes(learning: dict) -> list[str]:
    notes = []
    episode_count = learning.get("episode_count")
    new_episodes = learning.get("new_memory_episodes")
    if episode_count is not None:
        notes.append(
            f"GrowBot/River has observed {episode_count} learning episode(s) total"
            + (f", {new_episodes} new this run." if new_episodes else ".")
        )
    proposal_count = learning.get("proposal_count")
    blocked = learning.get("blocked_proposal_count")
    if proposal_count is not None:
        notes.append(
            f"{proposal_count} active parameter proposal(s), {blocked or 0} currently blocked "
            "-- preview only, never auto-applied."
        )
    product_readiness = learning.get("product_readiness") or {}
    if product_readiness:
        ready_tiers = [k for k, v in product_readiness.items() if v]
        notes.append(
            f"Readiness tiers currently met: {', '.join(ready_tiers) if ready_tiers else 'none yet'}."
        )
    if not notes:
        notes.append("No learning status available this run.")
    return notes


def _learning_evidence_notes() -> dict:
    """Decision/run/learning evidence summary lines for this cycle.

    Best-effort: if the evidence-summary tool fails for any reason, the run
    summary still renders -- this is additive context, never a hard
    dependency of the Overview screen.
    """
    try:
        evidence = get_learning_evidence_summary()
    except ToolExecutionError:
        return {
            "decision_evidence_summary": [],
            "run_evidence_summary": [],
            "learning_evidence_summary": ["Learning evidence summary unavailable this cycle."],
        }
    return {
        "decision_evidence_summary": evidence.get("decision_evidence_summary", []),
        "run_evidence_summary": evidence.get("run_evidence_summary", []),
        "learning_evidence_summary": evidence.get("learning_evidence_summary", []),
    }


def get_run_summary() -> dict:
    summary = cache.get_or_compute("run_summary", lambda: run_json_tool("build_latest_run_summary.py"))
    learning = get_learning_status()
    return {
        **summary,
        "learning_notes": _learning_notes(learning),
        **_learning_evidence_notes(),
    }
