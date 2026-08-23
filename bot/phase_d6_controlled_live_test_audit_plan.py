from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


D6_CONTROLLED_LIVE_TEST_AUDIT_PLAN_PHASE = "D6_controlled_live_test_audit_plan_v1"


def _safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _content(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {}
    if isinstance(report.get("content"), dict):
        return dict(report["content"])
    return dict(report)


def extract_default_allowed_tickers(config_text: str) -> List[str]:
    match = re.search(r'"ALLOWED_TICKERS",\s*\((.*?)\)\s*,', config_text, flags=re.DOTALL)
    if not match:
        return []
    raw = "".join(re.findall(r'"([^"]+)"', match.group(1)))
    return [item.strip().upper() for item in raw.split(",") if item.strip()]


def _coverage_from_manifest_paths(paths: Iterable[str | Path]) -> Dict[str, Any]:
    tickers: Counter[str] = Counter()
    rows: List[Dict[str, Any]] = []
    for raw in paths:
        path = Path(raw)
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for entry in payload.get("entries") or []:
            ticker = str(entry.get("ticker") or "").upper()
            if ticker:
                tickers[ticker] += 1
            rows.append(
                {
                    "path": str(path),
                    "ticker": ticker,
                    "timeframe": entry.get("timeframe"),
                    "study_window": entry.get("study_window"),
                    "candle_count": entry.get("candle_count"),
                    "gap_count": entry.get("gap_count"),
                    "learning_to_execution_allowed": entry.get("learning_to_execution_allowed"),
                    "parameter_change_allowed": entry.get("parameter_change_allowed"),
                }
            )
    return {
        "covered_tickers": sorted(tickers),
        "coverage_entry_count": len(rows),
        "coverage_rows": rows,
    }


def _log_product_summary(log_path: str | Path) -> Dict[str, Any]:
    path = Path(log_path)
    event_types: Counter[str] = Counter()
    tickers: Counter[str] = Counter()
    live_tickers: Counter[str] = Counter()
    rows = 0
    if not path.exists():
        return {"row_count": 0, "event_types": {}, "tickers": {}, "live_tickers": {}}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except Exception:
            continue
        rows += 1
        event_type = str(payload.get("event_type") or "")
        event_types[event_type] += 1
        order = payload.get("order") if isinstance(payload.get("order"), dict) else {}
        ticker = str(
            payload.get("ticker") or payload.get("product_id") or order.get("ticker") or order.get("product_id") or ""
        ).upper()
        if ticker:
            tickers[ticker] += 1
        if ticker and (order.get("mode") == "live" or order.get("live_order_submitted") is True or "live" in event_type):
            live_tickers[ticker] += 1
    return {
        "row_count": rows,
        "event_types": dict(event_types.most_common()),
        "tickers": dict(tickers.most_common()),
        "live_tickers": dict(live_tickers.most_common()),
    }


def _route_scores() -> List[Dict[str, Any]]:
    return [
        {
            "route": "A_read_only_day_run",
            "workflow_proof_value": 4,
            "risk": 1,
            "evidence_value": 4,
            "backlearning_value": 4,
            "product_coverage_value": 5,
            "testability": 8,
            "required_acks": ["coinbase_read_only_if_exchange_state_needed"],
            "stop_conditions": ["unexpected_local_open_order", "audit_not_observe_only"],
            "decision": "defer_less_order_lifecycle_value",
        },
        {
            "route": "B_one_tiny_btc_usdc_post_only_lifecycle_test",
            "workflow_proof_value": 9,
            "risk": 4,
            "evidence_value": 8,
            "backlearning_value": 6,
            "product_coverage_value": 2,
            "testability": 7,
            "required_acks": ["coinbase_read_only", "live_submit", "lifecycle_apply_after_terminal_evidence"],
            "stop_conditions": ["one_order_limit", "no_cancel_replace_without_ack", "no_second_submit"],
            "decision": "good_if_operator_wants_direct_workflow_proof",
        },
        {
            "route": "C_observe_then_one_controlled_micro_order_if_preflight_passes",
            "workflow_proof_value": 10,
            "risk": 3,
            "evidence_value": 9,
            "backlearning_value": 7,
            "product_coverage_value": 3,
            "testability": 8,
            "required_acks": ["coinbase_read_only", "live_submit", "lifecycle_apply_after_terminal_evidence"],
            "stop_conditions": ["preflight_failure", "one_order_limit", "no_learning_to_execution"],
            "decision": "chosen_for_future_ack_prompt",
        },
        {
            "route": "D_multi_product_read_only_coverage_day",
            "workflow_proof_value": 3,
            "risk": 1,
            "evidence_value": 5,
            "backlearning_value": 7,
            "product_coverage_value": 9,
            "testability": 7,
            "required_acks": ["coinbase_read_only_if_live_exchange_data_needed"],
            "stop_conditions": ["no_orders", "no_parameter_changes"],
            "decision": "use_later_for_multi_crypto_research_gap",
        },
        {
            "route": "E_plan_only_until_exact_acks",
            "workflow_proof_value": 5,
            "risk": 1,
            "evidence_value": 5,
            "backlearning_value": 5,
            "product_coverage_value": 4,
            "testability": 9,
            "required_acks": [],
            "stop_conditions": ["missing_next_boundary_ack"],
            "decision": "executed_now_because_live_acks_absent",
        },
    ]


def build_controlled_live_test_audit_plan(
    *,
    config_text: str,
    order_events_path: str | Path,
    coverage_manifest_paths: Iterable[str | Path],
    final_readiness_packet: Optional[Dict[str, Any]] = None,
    live_readiness_report: Optional[Dict[str, Any]] = None,
    governance_evidence_report: Optional[Dict[str, Any]] = None,
    state_hashes_before: Optional[Dict[str, str]] = None,
    state_hashes_after: Optional[Dict[str, str]] = None,
    ack_status: Optional[Dict[str, bool]] = None,
) -> Dict[str, Any]:
    allowed_tickers = extract_default_allowed_tickers(config_text)
    coverage = _coverage_from_manifest_paths(coverage_manifest_paths)
    logs = _log_product_summary(order_events_path)
    final_packet = _content(final_readiness_packet)
    readiness = _content(live_readiness_report)
    governance = _content(governance_evidence_report)
    hashes_before = dict(state_hashes_before or {})
    hashes_after = dict(state_hashes_after or state_hashes_before or {})
    acks = {
        "ACK_COINBASE_READ_ONLY": False,
        "ACK_LIVE_SUBMIT": False,
        "ACK_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE": False,
        **dict(ack_status or {}),
    }
    covered = set(coverage["covered_tickers"])
    live = set(logs["live_tickers"])
    missing_coverage = sorted(set(allowed_tickers) - covered)
    return {
        "generated_at": now_iso(),
        "phase": D6_CONTROLLED_LIVE_TEST_AUDIT_PLAN_PHASE,
        "status": "controlled_live_test_audit_plan_ready",
        "scope": {
            "report_only": True,
            "local_checks_only": True,
            "coinbase_interaction": False,
            "openai_api_interaction": False,
            "live_submit": False,
            "trading_state_mutation": False,
            "system_mutation": False,
        },
        "current_readiness_state": {
            "final_packet_status": final_packet.get("final_status"),
            "final_packet_blockers": list(final_packet.get("blockers") or []),
            "readiness_report_overall_status": readiness.get("overall_status"),
            "governance_evidence_overall_status": governance.get("overall_status"),
            "governance_evidence_rows": (governance.get("historical_evidence_summary") or {}).get("evidence_row_count"),
            "state_hashes_match": hashes_before == hashes_after,
        },
        "backlearning_status": {
            "implemented_components": [
                "parameter_inventory",
                "d5_evidence_adapter",
                "regime_segmentation_scaffold",
                "fill_realism_assumptions_and_adapter",
                "parameter_review_pack",
                "human_review_export",
                "manifest_lineage_safety_index",
                "governance_evidence_bundle",
                "final_readiness_packet",
            ],
            "actual_parameter_search_performed": False,
            "parameter_review_approved": False,
            "learning_to_execution_enabled": False,
            "status_assessment": "scaffolded_and_governance_tested_report_only_not_executed_as_parameter_learning",
            "real_live_lifecycle_evidence_products": sorted(live),
            "fixture_or_report_only_evidence": {
                "d5_learning_log_fixture_rows_present": True,
                "governance_evidence_report_only": True,
                "dataset_coverage_report_only": True,
            },
        },
        "crypto_coverage_status": {
            "configured_allowed_tickers": allowed_tickers,
            "configured_allowed_ticker_count": len(allowed_tickers),
            "d6_coverage": coverage,
            "order_event_log_summary": logs,
            "missing_d6_coverage_tickers": missing_coverage,
            "products_with_live_lifecycle_evidence": sorted(live),
            "btc_usdc_only_live_lifecycle_evidence": sorted(live) == ["BTC-USDC"],
        },
        "blocker_classification": {
            "hard_blockers_before_live_test": [
                "missing_exact_live_boundary_acks",
                "coinbase_read_only_preflight_not_authorized",
                "live_submit_not_authorized",
                "lifecycle_apply_not_authorized",
            ],
            "non_blocking_warnings_for_small_btc_usdc_test": [
                "multi_crypto_backlearning_incomplete",
                "d6_cached_coverage_only_btc_usdc",
                "stale_denormalized_reserved_field_documented",
                "tp_close_fee_gap_documented",
                "bwrap_missing",
            ],
            "collect_during_one_day_run": [
                "fill_or_no_fill_duration",
                "post_only_maker_behavior",
                "fee_evidence",
                "order_lifecycle_snapshots",
                "d5_d6_live_run_evidence_rows",
                "logging_and_checkpoint_behavior",
            ],
            "defer_until_after_run": [
                "multi_crypto_backlearning_expansion",
                "full_dataset_quality_for_all_allowed_tickers",
                "parameter_review_or_approval",
                "stale_field_repair_apply",
                "bubblewrap_os_install",
            ],
        },
        "chosen_future_route": {
            "route": "C_observe_then_one_controlled_micro_order_if_preflight_passes",
            "why": "best balance for end_to_end workflow proof with one product, tiny notional, one-order limit, strict stops, and no learning-to-execution",
            "product_scope": "BTC-USDC only",
            "max_notional_usdc": "10",
            "order_count_limit": 1,
            "post_only_preferred": True,
            "no_cancel_replace_reprice_without_separate_ack": True,
        },
        "route_scores": _route_scores(),
        "ack_status": acks,
        "acks_missing_for_live_route": [key for key, present in acks.items() if not present],
        "future_ack_strings_required": {
            "ACK_COINBASE_READ_ONLY": "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "ACK_LIVE_SUBMIT": "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "ACK_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE": "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        },
        "preflight_commands_for_future_ack_prompt": [
            "python3 tools/show_open_orders.py --open-only --json --limit 20",
            "python3 tools/show_function_preservation_audit.py --fail-on-review",
            "python3 tools/show_phase_d3_controlled_live_exits.py --ticker BTC-USDC --json",
            "sha256sum state/open_orders.json state/positions.json",
            "bounded Coinbase product/rules and balance checks only if ACK_COINBASE_READ_ONLY is present",
        ],
        "day_run_evidence_plan": [
            "record local order status snapshots",
            "record bounded exchange snapshots only under read-only ACK",
            "build D5/D6 live-run evidence report after the day",
            "do not apply lifecycle unless terminal evidence and lifecycle ACK are present",
            "do not cancel_replace_reprice unless separately ACKed",
        ],
        "warnings": [
            "audit_plan_only_no_live_action",
            "no_coinbase_ack_present",
            "no_submit_ack_present",
            "no_lifecycle_apply_ack_present",
            "backlearning_not_used_for_live_behavior",
        ],
        "blockers": ["required_live_boundary_acks_missing"],
        **_safety_flags(),
    }


__all__ = [
    "D6_CONTROLLED_LIVE_TEST_AUDIT_PLAN_PHASE",
    "build_controlled_live_test_audit_plan",
    "extract_default_allowed_tickers",
]
