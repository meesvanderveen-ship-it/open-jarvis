from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_non_live_readiness_continuation_v1"
DATA_FETCH_ACK = "I_APPROVE_BOUNDED_MULTI_TICKER_COINBASE_CANDLE_FETCH_FOR_D6_RESEARCH_ONLY"
BTC_READ_ACK = "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST"
BTC_SUBMIT_ACK = "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC"
BTC_APPLY_ACK = "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER"


def safety_flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "parameter_values_changed": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "learning_to_execution_enabled": False,
        "coinbase_fetch_performed": False,
        "config_mutation_performed": False,
    }


def content(report: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not report:
        return {}
    if isinstance(report.get("content"), dict):
        return dict(report["content"])
    return dict(report)


def rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(content(report).get("rows") or [])


def _missing_dataset_rows(dataset_plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [row for row in rows(dataset_plan) if row.get("missing_data_blocker") or not row.get("cached_data_present")]


def _missing_timeframe_map(readiness_matrix: Dict[str, Any]) -> Dict[str, List[str]]:
    return {
        row["ticker"]: list(row.get("required_timeframes_missing") or [])
        for row in rows(readiness_matrix)
    }


def validate_prefetch_plan(*, fetch_plan: Dict[str, Any], dataset_plan: Dict[str, Any]) -> Dict[str, Any]:
    plan = content(fetch_plan)
    dry_run = str(plan.get("dry_run_command") or "")
    fetch = str(plan.get("fetch_command_after_ack") or "")
    required_timeframes = set(plan.get("required_timeframes") or [])
    missing_rows = _missing_dataset_rows(dataset_plan)
    missing_pairs = {(row.get("ticker"), row.get("timeframe")) for row in missing_rows}
    blockers: List[str] = []
    if not dry_run or "--dry-run" not in dry_run:
        blockers.append("dry_run_command_missing_or_not_dry_run")
    if not fetch or "--fetch" not in fetch:
        blockers.append("fetch_command_missing")
    if DATA_FETCH_ACK != plan.get("required_ack"):
        blockers.append("required_ack_missing_or_unexpected")
    if "state/" in dry_run or "state/" in fetch:
        blockers.append("command_references_state_path")
    if int(plan.get("constraints", {}).get("max_chunks_per_run") or plan.get("max_chunks_per_run") or 0) <= 0:
        blockers.append("max_chunks_not_bounded")
    if required_timeframes != {"1H", "4H", "1D"}:
        blockers.append("required_timeframes_incomplete")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "prefetch_validation_report_v1",
        "status": "prefetch_validation_pass" if not blockers else "prefetch_validation_blocked",
        "required_ack": DATA_FETCH_ACK,
        "dry_run_command_present": bool(dry_run),
        "fetch_command_ack_gated": DATA_FETCH_ACK == plan.get("required_ack") and "--fetch" in fetch,
        "max_chunks_bounded": "max-chunks" in dry_run and "max-chunks" in fetch,
        "output_paths_outside_state": "state/" not in dry_run and "state/" not in fetch,
        "coinbase_call_performed": False,
        "fetch_executed": False,
        "missing_pair_count": len(missing_pairs),
        "required_timeframes": sorted(required_timeframes),
        "blockers": blockers,
        **safety_flags(),
    }


def build_backlearning_evidence_aggregator(
    *,
    dataset_plan: Dict[str, Any],
    readiness_matrix: Dict[str, Any],
    backlearning_review: Dict[str, Any],
    guardrails: Dict[str, Any],
    workflow_equivalence: Dict[str, Any],
) -> Dict[str, Any]:
    matrix_rows = rows(readiness_matrix)
    missing_map = _missing_timeframe_map(readiness_matrix)
    eq_rows = {row["ticker"]: row for row in rows(workflow_equivalence)}
    evidence_rows = []
    for row in matrix_rows:
        ticker = row["ticker"]
        eq = eq_rows.get(ticker, {})
        blockers = []
        if missing_map.get(ticker):
            blockers.append("missing_required_timeframes")
        if not row.get("dataset_quality_present"):
            blockers.append("missing_dataset_quality")
        if not row.get("baseline_backtest_possible"):
            blockers.append("missing_cached_backtest_input")
        if not row.get("cost_scenario_support_present"):
            blockers.append("missing_cost_scenario_support")
        if not row.get("fill_realism_evidence_present"):
            blockers.append("missing_fill_realism_evidence")
        if not eq.get("lifecycle_evidence"):
            blockers.append("missing_live_lifecycle_evidence")
        evidence_rows.append(
            {
                "ticker": ticker,
                "dataset_quality_ready": bool(row.get("dataset_quality_present")),
                "cached_backtest_ready": bool(row.get("baseline_backtest_possible")),
                "cost_evidence_ready": bool(row.get("cost_scenario_support_present")),
                "fill_realism_ready": bool(row.get("fill_realism_evidence_present")),
                "trial_accounting_ready": not missing_map.get(ticker) and bool(row.get("baseline_backtest_possible")),
                "parameter_review_status": "blocked",
                "blockers": blockers or ["human_review_not_approved"],
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "backlearning_evidence_aggregator_v1",
        "status": "backlearning_evidence_aggregation_ready_blocked",
        "summary": {
            "ticker_count": len(evidence_rows),
            "parameter_review_ready_count": 0,
            "blocked_count": len(evidence_rows),
            "missing_dataset_rows": len(_missing_dataset_rows(dataset_plan)),
            "review_package_status": content(backlearning_review).get("status"),
            "guardrail_status": content(guardrails).get("status"),
        },
        "rows": evidence_rows,
        "parameter_review_blocked": True,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


def build_gap_closure_tracker(
    *,
    checklist: Dict[str, Any],
    readiness_matrix: Dict[str, Any],
    workflow_equivalence: Dict[str, Any],
) -> Dict[str, Any]:
    matrix = {row["ticker"]: row for row in rows(readiness_matrix)}
    equivalence = {row["ticker"]: row for row in rows(workflow_equivalence)}
    tracked = []
    for row in rows(checklist):
        ticker = row["ticker"]
        matrix_row = matrix.get(ticker, {})
        eq = equivalence.get(ticker, {})
        status = "blocked"
        if ticker == "BTC-USDC":
            status = "data_coverage_partial"
        if row.get("dataset_quality") and row.get("cached_baseline"):
            status = "cached_backtest_ready"
        if row.get("lifecycle_evidence") and status == "cached_backtest_ready":
            status = "controlled_live_pilot_candidate"
        if not row.get("candles_1h") and not row.get("candles_4h") and not row.get("candles_1d"):
            status = "configured_only"
        tracked.append(
            {
                "ticker": ticker,
                "closure_status": status,
                "configured": bool(row.get("configured")),
                "missing_timeframes": list(matrix_row.get("required_timeframes_missing") or []),
                "blockers": list(row.get("blockers") or eq.get("blockers_before_ticker_can_join_24h_live_test") or []),
                "next_non_live_step": "fetch_missing_candles_after_ack" if matrix_row.get("required_timeframes_missing") else "run_dataset_quality",
                "ack_required_for_next_step": bool(matrix_row.get("required_timeframes_missing")),
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "multi_ticker_gap_closure_tracker_v1",
        "status": "multi_ticker_gap_closure_tracker_ready",
        "summary": {
            "ticker_count": len(tracked),
            "workflow_equivalent_to_btc_usdc_count": sum(1 for row in tracked if row["closure_status"] == "workflow_equivalent_to_btc_usdc"),
            "configured_only_count": sum(1 for row in tracked if row["closure_status"] == "configured_only"),
            "data_coverage_partial_count": sum(1 for row in tracked if row["closure_status"] == "data_coverage_partial"),
            "blocked_count": sum(1 for row in tracked if row["closure_status"] in {"blocked", "configured_only"}),
        },
        "rows": tracked,
        **safety_flags(),
    }


def build_next_ack_decision_packet() -> Dict[str, Any]:
    decisions = [
        {
            "route": "data_fetch_ack_route",
            "ack": DATA_FETCH_ACK,
            "does": "allows bounded D6 research candle fetch for missing ticker/timeframe rows",
            "does_not": ["does_not_trade", "does_not_change_parameters", "does_not_enable_learning_to_execution"],
            "expected_outputs": ["cached candle files outside state", "dataset quality can run after fetch"],
            "stop_conditions": ["fetch command differs from validated plan", "output path enters state", "max chunks unbounded"],
            "recommended_order": 1,
        },
        {
            "route": "btc_usdc_only_live_test_ack_route",
            "ack": BTC_READ_ACK,
            "does": "allows bounded read-only preflight only when separately approved",
            "does_not": ["does_not_submit_without_submit_ack", "does_not_include_other_tickers"],
            "expected_outputs": ["fresh preflight evidence", "state hash checkpoint"],
            "stop_conditions": ["open orders exist", "D3 active exit exists", "audit not observe-only"],
            "recommended_order": 2,
        },
        {
            "route": "btc_usdc_one_order_submit_ack_route",
            "ack": BTC_SUBMIT_ACK,
            "does": "allows exactly one controlled BTC-USDC test order within stated notional limit after preflight passes",
            "does_not": ["does_not_allow_second_order", "does_not_allow_cancel_replace", "does_not_allow_all_ticker_live"],
            "expected_outputs": ["one order lifecycle evidence row"],
            "stop_conditions": ["preflight fails", "product/rules unclear", "missing lifecycle apply ACK for terminal apply"],
            "recommended_order": 3,
        },
        {
            "route": "parameter_review_route_later",
            "ack": "future_exact_parameter_review_governance_ack_required",
            "does": "starts human-review discussion only after evidence blockers clear",
            "does_not": ["does_not_optimize_now", "does_not_change_config", "does_not_enable_learning_to_execution"],
            "expected_outputs": ["human-review packet"],
            "stop_conditions": ["missing OOS evidence", "missing cost/fill realism", "trial accounting incomplete"],
            "recommended_order": 4,
        },
    ]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "next_ack_decision_packet_v1",
        "status": "next_ack_decision_packet_ready",
        "recommended_sequence": [row["route"] for row in sorted(decisions, key=lambda row: row["recommended_order"])],
        "decisions": decisions,
        **safety_flags(),
    }


def build_master_readiness_refresh_v2(
    *,
    prefetch_validation: Dict[str, Any],
    evidence_aggregator: Dict[str, Any],
    gap_tracker: Dict[str, Any],
    ack_packet: Dict[str, Any],
    remaining_overview: Dict[str, Any],
    state_hashes: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    overview = content(remaining_overview)
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "master_readiness_refresh_v2",
        "status": "master_readiness_refresh_v2_ready",
        "current_safety": {
            "open_orders_expected": 0,
            "open_d3_exit_expected": 0,
            "state_hashes": dict(state_hashes or {}),
            "live_action_authorized": False,
        },
        "p0_p8_status": overview.get("todo_items") or [],
        "completed_sprint_tasks": [
            "prefetch_validation_harness",
            "backlearning_evidence_aggregator",
            "multi_ticker_gap_closure_tracker",
            "next_ack_decision_packet",
            "master_readiness_refresh_v2",
        ],
        "newest_blockers": {
            "data_fetch_ack_required": True,
            "dataset_quality_blocked_until_data": True,
            "backtests_blocked_until_data_quality": True,
            "parameter_review_blocked": True,
            "btc_usdc_live_test_ack_required": True,
            "all_ticker_live_blocked": True,
        },
        "fastest_safe_route": "choose_data_fetch_ack_or_btc_usdc_only_live_test_ack_as_separate_task",
        "all_ticker_route": "fetch_data_then_dataset_quality_then_cached_backtests_then_workflow_equivalence_refresh",
        "data_fetch_route": {"validation_status": prefetch_validation.get("status"), "required_ack": DATA_FETCH_ACK},
        "backtest_route": "blocked_until_cached_data_and_dataset_quality_exist",
        "backlearning_route": {"status": evidence_aggregator.get("status"), "parameter_review_blocked": True},
        "live_route": {"btc_usdc_only": "ack_gated", "all_ticker": "blocked"},
        "ack_packet_status": ack_packet.get("status"),
        "gap_tracker_summary": gap_tracker.get("summary"),
        "no_go_boundaries": [
            "no_coinbase_without_ack",
            "no_fetch_without_ack",
            "no_live_order_without_ack",
            "no_lifecycle_apply_without_ack",
            "no_config_or_parameter_mutation",
            "no_learning_to_execution",
        ],
        **safety_flags(),
    }


__all__ = [
    "build_backlearning_evidence_aggregator",
    "build_gap_closure_tracker",
    "build_master_readiness_refresh_v2",
    "build_next_ack_decision_packet",
    "safety_flags",
    "validate_prefetch_plan",
]
