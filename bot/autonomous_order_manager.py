from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List


PENDING_ENTRY_LIFECYCLE_STATES = [
    "pending_entry_created_preview",
    "live_submit_armed_by_operator_only",
    "open_entry_order_monitored",
    "cancel_if_stale_or_invalidated",
    "bounded_replace_same_thesis_only",
    "fill_detected",
    "position_opened",
    "d2_exit_plan_generated",
    "d3_exit_orders_guarded",
    "controlled_stop_route_separate",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_pending_entry_lifecycle_preview(entry_preview: Dict[str, Any]) -> Dict[str, Any]:
    preview = entry_preview if isinstance(entry_preview, dict) else {}
    eligible = bool(preview.get("eligible"))
    return {
        "generated_at": now_iso(),
        "phase": "autonomous_order_manager_pending_entry_preview_v1",
        "read_only": True,
        "coinbase_call_attempted": False,
        "live_submission_attempted": False,
        "state_mutation_performed": False,
        "entry_preview_eligible": eligible,
        "entry_preview_reason": preview.get("reason") or "",
        "entry_order_policy": preview.get("entry_order_policy") or "",
        "would_submit": False,
        "lifecycle_states": list(PENDING_ENTRY_LIFECYCLE_STATES),
        "cancel_if": preview.get("cancel_if") if isinstance(preview.get("cancel_if"), list) else [],
        "replace_policy": {
            "max_replaces_per_order": 1,
            "same_thesis_required": True,
            "bounded_price_improvement_only": True,
        },
        "fill_to_exit_handoff": {
            "fill_detected_by": "D1_or_phase_c43_reconciliation",
            "position_open_required_before_d2": True,
            "d3_requires_actual_base_and_no_duplicate_exit": True,
            "controlled_stop_route_separate": True,
        },
    }


__all__ = ["PENDING_ENTRY_LIFECYCLE_STATES", "build_pending_entry_lifecycle_preview"]
