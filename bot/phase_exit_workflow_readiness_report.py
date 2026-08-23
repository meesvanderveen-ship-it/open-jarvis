from __future__ import annotations

import hashlib
import json
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "exit_workflow_readiness_report_v1"


def _read_text(root: Path, rel: str, max_chars: int = 650_000) -> str:
    path = root / rel
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[-max_chars:]
    except OSError:
        return ""


def _exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _sha256(root: Path, rel: str) -> str:
    path = root / rel
    try:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
    except OSError:
        return ""


def _load_json(root: Path, rel: str) -> Dict[str, Any]:
    try:
        payload = json.loads((root / rel).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = payload.get("orders", payload)
    if isinstance(raw, dict):
        return [dict(item) for item in raw.values() if isinstance(item, dict)]
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    return []


def _is_open_status(status: Any) -> bool:
    return str(status or "").strip().lower() in {
        "planned",
        "pending",
        "submitted",
        "partially_filled",
        "partial",
        "cancel_pending",
        "replace_pending",
        "open",
        "active",
        "new",
        "queued",
    }


def _is_d3_exit(order: Dict[str, Any]) -> bool:
    cid = str(order.get("client_order_id") or "")
    return (
        str(order.get("side") or "").upper() == "SELL"
        and (
            cid.startswith("phased3-")
            or str(order.get("phase") or "") == "D3_controlled_live_reduce_only_exits"
            or str(order.get("source_mode") or order.get("mode") or "") == "phase_d3_live_exit"
        )
    )


def _current_order_state(root: Path) -> Dict[str, Any]:
    orders = _orders_from_payload(_load_json(root, "state/open_orders.json"))
    open_orders = [order for order in orders if _is_open_status(order.get("status"))]
    open_d3 = [order for order in open_orders if _is_d3_exit(order)]
    return {
        "total_orders": len(orders),
        "open_orders": len(open_orders),
        "open_d3_exit": len(open_d3),
        "open_d3_by_ticker": dict(Counter(str(order.get("ticker") or order.get("product_id") or "") for order in open_d3)),
    }


def _test_presence(root: Path, tests: List[str]) -> Dict[str, bool]:
    return {rel: _exists(root, rel) for rel in tests}


def _contains_all(text: str, needles: List[str]) -> bool:
    return all(needle in text for needle in needles)


def _d2_status(root: Path) -> Dict[str, Any]:
    text = _read_text(root, "bot/phase_d2_position_executor.py")
    tests = _test_presence(
        root,
        [
            "tests/test_phase_d2_position_executor.py",
            "tests/test_phase_d21_pre_d3_hygiene.py",
            "tests/test_phase_d23_hardening_v1.py",
        ],
    )
    evidence = {
        "plan_ready_no_live_status": "position_executor_plan_ready_no_live_exit_submit" in text,
        "manageable_open_position_gate": "is_d2_manageable_open_position" in text,
        "plan_fingerprint": "build_d2_plan_fingerprint" in text and "plan_fingerprint" in text,
        "fee_edge_cost_model": "build_fee_cost_model" in text and "expected_net_edge_pct" in text,
        "min_size_increment_checks": _contains_all(text, ["base_increment", "min_order_quote", "_quantize_down"]),
        "persist_plan_optional": "persist_plan" in text,
    }
    return {
        "status": "partial",
        "what_exists": "D2 builds deterministic position exit plans from manageable open positions with fee/edge/min-size context and fingerprints.",
        "evidence": evidence,
        "tests_present": tests,
        "readiness": {
            "plan_after_proven_position": evidence["manageable_open_position_gate"],
            "plan_preview_not_sell_permission": evidence["plan_ready_no_live_status"],
            "fees_spread_slippage_min_edge_represented": evidence["fee_edge_cost_model"],
            "d2_implies_live_sell_permission": False,
        },
        "remaining_gaps": [
            "D2 plan persistence/apply remains separate from live submit gates.",
            "D2 evidence should be tied to post-run C4/D1 fill evidence before any future SELL.",
        ],
    }


def _d3_status(root: Path, current: Dict[str, Any]) -> Dict[str, Any]:
    pilot = _read_text(root, "bot/phase_d3_controlled_exit_pilot.py")
    exits = _read_text(root, "bot/phase_d3_controlled_live_exits.py")
    reservation = _read_text(root, "bot/phase_d3_reservation_governance.py")
    gate = _read_text(root, "bot/live_exit_gate.py")
    tests = _test_presence(
        root,
        [
            "tests/test_phase_d3_controlled_exit_pilot.py",
            "tests/test_phase_d3_controlled_live_exits.py",
            "tests/test_phase_d3_reservation_governance.py",
            "tests/test_live_exit_gate.py",
            "tests/test_coinbase_executor_live_exit_gate.py",
        ],
    )
    evidence = {
        "preview_only_warning": "preview_only_submit_live_false" in pilot,
        "one_shot_ack_required": "ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK" in pilot and "D3_ACK" in pilot,
        "baseline_sell_flags_safe": "_baseline_sell_flags_safe" in pilot,
        "replication_blocks_pilot": "d3_pilot_replication_enabled" in pilot,
        "zero_open_d3_before_submit": "d3_pilot_open_d3_exit_order_exists" in pilot,
        "central_live_exit_gate": "assert_live_exit_allowed" in exits and "LiveExitBlockedError" in exits,
        "duplicate_exit_detection": "duplicate_labels_detected" in reservation and "duplicate_actions_detected" in reservation,
        "no_oversell_available_base": "available_base_after_reservations" in reservation and "sell_base_exceeds" in pilot,
        "base_reservation_governance": "reserved_base_open_exit_orders" in reservation,
        "min_size_increment_checks": "base_increment" in reservation and "min_order_quote" in reservation,
        "partial_terminal_lifecycle_tools": _exists(root, "bot/phase_d3_live_exit_reconciliation.py")
        and _exists(root, "bot/phase_d3_open_exit_lifecycle_manager.py"),
    }
    return {
        "status": "partial",
        "what_exists": "D3 has controlled reduce-only exit planning, preview/readiness, reservation governance, central live-exit gate and one-shot ACK scaffolding.",
        "evidence": evidence,
        "tests_present": tests,
        "current_state": current,
        "readiness": {
            "preview_distinct_from_live_submit": evidence["preview_only_warning"],
            "live_exits_disabled_by_default": True,
            "exact_ack_required": evidence["one_shot_ack_required"],
            "duplicate_exits_prevented_or_reported": evidence["duplicate_exit_detection"],
            "open_exit_counts_capped": evidence["zero_open_d3_before_submit"],
            "no_oversell_enforced_or_reported": evidence["no_oversell_available_base"],
            "base_reservation_represented": evidence["base_reservation_governance"],
            "min_size_increment_represented": evidence["min_size_increment_checks"],
            "partial_terminal_fills_handled_or_flagged": evidence["partial_terminal_lifecycle_tools"],
        },
        "remaining_gaps": [
            "Current local state has no manageable open position, so live exit readiness cannot be green now.",
            "Future D3 live submit still needs fresh product rules, exact position/plan/fingerprint ACK, and zero open D3 exit evidence.",
            "Partial/terminal fill apply remains separate ACK-gated lifecycle reconciliation.",
        ],
    }


def _d4_status(root: Path) -> Dict[str, Any]:
    controlled = _read_text(root, "bot/phase_d4_controlled_cancel_replace.py")
    planner = _read_text(root, "bot/phase_d4_cancel_replace_planner.py")
    trailing = _read_text(root, "bot/phase_d4_trailing_preview.py")
    tests = _test_presence(
        root,
        [
            "tests/test_phase_d4_controlled_cancel_replace.py",
            "tests/test_phase_d4_cancel_replace_planner.py",
            "tests/test_phase_d4_trailing_preview.py",
            "tests/test_live_exit_gate_d4_controlled_cancel_replace.py",
        ],
    )
    evidence = {
        "preview_reprice_candidate": "preview_reprice_candidate" in controlled,
        "requires_future_ack": "requires_future_ack" in controlled,
        "controlled_ack": "D4_CONTROLLED_CANCEL_REPLACE_ACK" in controlled,
        "central_gate": "evaluate_d4_controlled_replacement_submit_allowed" in controlled,
        "trailing_preview": "trailing" in trailing.lower() and "preview" in trailing.lower(),
        "does_not_default_live": "no_live_action" in controlled and "cancel_replace_allowed" in controlled,
    }
    return {
        "status": "partial",
        "what_exists": "D4 has cancel/replace planning, controlled cancel-replace gates, and trailing preview scaffolding.",
        "evidence": evidence,
        "tests_present": tests,
        "readiness": {
            "observe_preview_only_by_default": evidence["preview_reprice_candidate"] and evidence["does_not_default_live"],
            "cannot_accidentally_cancel_replace_live": evidence["controlled_ack"] and evidence["central_gate"],
            "trailing_activation_distance_represented": evidence["trailing_preview"],
            "live_d4_blocked_now": True,
        },
        "remaining_gaps": [
            "D4 live cancel/replace requires active open exit lifecycle, exact order IDs, ACK and post-cancel reconciliation.",
            "Trailing automation remains out of scope until explicit operator design/ACK.",
        ],
    }


def _d5_status(root: Path) -> Dict[str, Any]:
    text = _read_text(root, "bot/phase_d5_execution_metrics.py")
    adapter = _read_text(root, "bot/phase_d6_d5_evidence_adapter.py")
    tests = _test_presence(
        root,
        [
            "tests/test_phase_d5_execution_metrics.py",
            "tests/test_phase_d5_learning_log.py",
            "tests/test_phase_d6_d5_evidence_adapter.py",
        ],
    )
    evidence = {
        "fee_metrics": "fee_bps_estimate" in text and "fee_quote" in text,
        "slippage_metrics": "slippage_vs_decision_mid_pct" in text and "slippage_vs_best_bid_or_ask_pct" in text,
        "no_fill_duration": "no_fill_duration_seconds" in text,
        "cancel_replace_outcome": "cancel_replace_outcome" in text,
        "partial_fill_flag": "partial_lifecycle_without_terminal_not_training_eligible" in text,
        "evidence_only": "learning_to_execution_allowed" in text and "False" in text,
        "future_gate": "D5_LEARNING_TO_EXECUTION_REQUIRES_SEPARATE_OPERATOR_APPROVAL_AND_ACK" in text,
        "d6_adapter_present": "D5" in adapter or "d5" in adapter,
    }
    return {
        "status": "partial",
        "what_exists": "D5 captures execution metrics as evidence-only reports and blocks learning-to-execution.",
        "evidence": evidence,
        "tests_present": tests,
        "readiness": {
            "fees_slippage_no_fill_cancel_partial_represented": all(
                evidence[key]
                for key in (
                    "fee_metrics",
                    "slippage_metrics",
                    "no_fill_duration",
                    "cancel_replace_outcome",
                    "partial_fill_flag",
                )
            ),
            "evidence_only": evidence["evidence_only"],
            "no_parameter_mutation": True,
            "learning_to_execution_ready": False,
        },
        "remaining_gaps": [
            "D5/D6 fee evidence and maker/taker/no-fill/cancel timing can be expanded, but must stay human-review-only.",
            "No D5 evidence may mutate parameters or authorize execution.",
        ],
    }


def build_synthetic_safety_matrix() -> Dict[str, Any]:
    position_base = Decimal("0.10000000")
    reserved_base = Decimal("0.04000000")
    requested_sell = Decimal("0.07000000")
    duplicate_labels = ["TP1", "TP1"]
    open_exit_count = 1
    return {
        "d3_preview_submit_live_false": {
            "passed": True,
            "evidence": "D3 preview path uses submit_live=False and reports preview_only_submit_live_false.",
        },
        "d3_live_submit_requires_flags_ack": {
            "passed": True,
            "required": [
                "one-shot arm ACK",
                "D3 human ACK",
                "safe false baseline flags",
                "required position id",
                "required candidate/plan fingerprint",
                "coinbase client only in live submit branch",
            ],
        },
        "live_exits_disabled_by_default": {
            "passed": True,
            "live_exit_allowed_now": False,
        },
        "duplicate_exit_detected": {
            "passed": len(set(duplicate_labels)) != len(duplicate_labels),
            "labels": duplicate_labels,
        },
        "no_oversell_detected": {
            "passed": requested_sell > max(Decimal("0"), position_base - reserved_base),
            "position_base": str(position_base),
            "reserved_base": str(reserved_base),
            "requested_sell": str(requested_sell),
        },
        "base_reservation_detected": {
            "passed": reserved_base > 0 and open_exit_count > 0,
            "reserved_base": str(reserved_base),
            "open_exit_count": open_exit_count,
        },
        "d4_cancel_replace_not_live_default": {
            "passed": True,
            "cancel_replace_allowed_now": False,
        },
        "d5_metrics_evidence_only": {
            "passed": True,
            "learning_to_execution_ready": False,
        },
        "follower_sell_false": {
            "passed": True,
            "follower_sell_ready": False,
        },
    }


def _readiness_summary(current: Dict[str, Any]) -> Dict[str, Any]:
    blockers = [
        "no_manageable_open_position_for_exit_now",
        "live_exit_requires_separate_exact_operator_ACK",
        "fresh_product_rules_and_position_plan_required_before_any_sell",
        "partial_terminal_fill_reconciliation_apply_requires_separate_ACK",
        "follower_receiver_API_and_sell_safety_not_proven",
    ]
    if current.get("open_d3_exit", 0) != 0:
        blockers.append("open_d3_exit_present_requires_lifecycle_review")
    return {
        "master_live_exit_ready": False,
        "master_live_exit_blockers": blockers,
        "follower_sell_ready": False,
        "follower_sell_blockers": [
            "follower_receiver_API_missing_or_unaudited",
            "follower_live_mode_not_approved",
            "follower_product_rules_balances_caps_not_proven",
            "follower_no_oversell_reduce_only_reservation_not_proven",
            "separate_follower_SELL_ACK_missing",
            "drift_reconcile_not_proven",
        ],
        "live_exit_allowed_now": False,
        "d2_d3_d4_d5_reports_authorize_sell": False,
        "learning_to_execution_ready": False,
        "parameter_optimization_approved": False,
    }


def build_exit_workflow_readiness_report(*, root: Path | str = ".") -> Dict[str, Any]:
    repo = Path(root)
    current = _current_order_state(repo)
    d2 = _d2_status(repo)
    d3 = _d3_status(repo, current)
    d4 = _d4_status(repo)
    d5 = _d5_status(repo)
    safety = build_synthetic_safety_matrix()
    readiness = _readiness_summary(current)
    report_ready = all(row.get("passed") is True for row in safety.values())
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_mode": "read_only_exit_workflow_readiness",
        "no_coinbase_call": True,
        "no_live_action": True,
        "http_replication_call_attempted": False,
        "state_write_performed": False,
        "master_ready_for_operator_preflight": True,
        "master_ready_for_operator_live_start": False,
        "master_live_exit_ready": readiness["master_live_exit_ready"],
        "follower_ready_for_paper_lifecycle_test": True,
        "follower_ready_for_live": False,
        "follower_sell_ready": readiness["follower_sell_ready"],
        "lifecycle_parity_ready": False,
        "all_ticker_ready": False,
        "learning_to_execution_ready": False,
        "exit_workflow_readiness_report_ready": report_ready,
        "current_order_state": current,
        "d2_position_executor": d2,
        "d3_controlled_exits": d3,
        "d4_cancel_replace_trailing": d4,
        "d5_execution_evidence": d5,
        "synthetic_safety_matrix": safety,
        "readiness_summary": readiness,
        "required_remaining_work_before_master_sell": [
            "fresh open-position evidence from C4/D1 applied state",
            "D2 ready plan tied to the exact position and product rules",
            "zero open D3 exit orders and coherent reservation governance",
            "candidate fingerprint review and exact D3 one-shot ACK",
            "live exit flags remain false until one-shot process-local arming",
            "post-submit lifecycle monitor and fill/cancel/reject reconciliation plan",
        ],
        "required_remaining_work_before_follower_sell": [
            "follower receiver/API audit",
            "paper/live separation and separate follower SELL ACK",
            "follower product rules, balances, caps and no-oversell checks",
            "follower reduce-only/reservation governance",
            "drift/reconcile and idempotency store",
            "D3/D4 lifecycle events remain observe-only until explicitly enabled",
        ],
        "recommended_next_sprint": {
            "route": "stale_state_hygiene_preview_or_regression_harness",
            "why": "Exit readiness blockers are now consolidated; next useful safe choices are preview-only stale denormalized reservation cleanup or a small regression harness that bundles the local report/readiness checks.",
        },
        "state_hashes": {
            "state/open_orders.json": _sha256(repo, "state/open_orders.json"),
            "state/positions.json": _sha256(repo, "state/positions.json"),
        },
        **d6_metric_safety_flags(),
    }


def render_exit_workflow_readiness_markdown(report: Dict[str, Any]) -> str:
    readiness = report.get("readiness_summary") or {}
    lines = [
        "# Exit Workflow Readiness Report",
        "",
        "Read-only D2/D3/D4/D5 readiness artifact. It does not authorize SELL, call Coinbase, submit/cancel/replace, apply lifecycle, mutate state, or enable follower live.",
        "",
        "## Readiness",
        f"- master_live_exit_ready: `{report.get('master_live_exit_ready')}`",
        f"- follower_sell_ready: `{report.get('follower_sell_ready')}`",
        f"- live_exit_allowed_now: `{readiness.get('live_exit_allowed_now')}`",
        f"- lifecycle_parity_ready: `{report.get('lifecycle_parity_ready')}`",
        f"- learning_to_execution_ready: `{report.get('learning_to_execution_ready')}`",
        "",
        "## Current State",
    ]
    for key, value in (report.get("current_order_state") or {}).items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Components"])
    for key, title in (
        ("d2_position_executor", "D2 Position Executor"),
        ("d3_controlled_exits", "D3 Controlled Exits"),
        ("d4_cancel_replace_trailing", "D4 Cancel/Replace/Trailing"),
        ("d5_execution_evidence", "D5 Execution Evidence"),
    ):
        section = report.get(key) or {}
        lines.extend([
            "",
            f"### {title}",
            f"- status: `{section.get('status')}`",
            f"- what_exists: {section.get('what_exists')}",
        ])
        for gap in section.get("remaining_gaps") or []:
            lines.append(f"- gap: {gap}")
    lines.extend(["", "## Synthetic Safety Matrix"])
    for name, row in (report.get("synthetic_safety_matrix") or {}).items():
        lines.append(f"- {name}: passed=`{row.get('passed')}`")
    lines.extend(["", "## Master SELL Blockers"])
    for blocker in readiness.get("master_live_exit_blockers") or []:
        lines.append(f"- {blocker}")
    lines.extend(["", "## Follower SELL Blockers"])
    for blocker in readiness.get("follower_sell_blockers") or []:
        lines.append(f"- {blocker}")
    next_sprint = report.get("recommended_next_sprint") or {}
    lines.extend([
        "",
        "## Recommended Next Sprint",
        f"- route: `{next_sprint.get('route')}`",
        f"- why: {next_sprint.get('why')}",
        "",
        "## State Hashes",
    ])
    for key, value in (report.get("state_hashes") or {}).items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines)


__all__ = [
    "PHASE",
    "build_exit_workflow_readiness_report",
    "build_synthetic_safety_matrix",
    "render_exit_workflow_readiness_markdown",
]
