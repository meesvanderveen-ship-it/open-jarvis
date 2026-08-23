from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_rate_limited_public_fetch import RateLimitPolicy, build_rate_limited_fetch_plan


PHASE = "D6_v17_v18_readiness_v1"
MISSING_4H_START = 1761408000


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
        "live_order_action_performed": False,
        "coinbase_write_performed": False,
        "config_mutation_performed": False,
        "coinbase_account_or_order_call_performed": False,
    }


def _iso_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def build_btc_4h_gap_policy_v2(*, diagnostic: Dict[str, Any]) -> Dict[str, Any]:
    content = dict(diagnostic.get("content") or diagnostic)
    validation = dict(content.get("candidate_validation") or {})
    missing = list(validation.get("missing_expected_starts_sample") or content.get("missing_expected_start") and [content.get("missing_expected_start")] or [])
    recovered = bool(validation.get("validator_pass")) or bool(content.get("merge_executed"))
    single_missing = missing == [MISSING_4H_START] or missing == [str(MISSING_4H_START)]
    fetch_result = dict(content.get("rate_limited_fetch_result") or {})
    returned_start = fetch_result.get("first_candle_start")
    decision = "exact_validation_pass_merge_allowed" if recovered else "documented_single_candle_exchange_hole_pending_quality_exception"
    quality_exception_ready = False
    blockers: List[str] = []
    if not recovered:
        blockers.append("btc_4h_exact_candidate_validation_not_passed")
    if single_missing and int(returned_start or 0) != MISSING_4H_START:
        blockers.append("surgical_fetch_returned_adjacent_candle_not_missing_start")
    if not quality_exception_ready:
        blockers.append("dataset_quality_does_not_yet_support_documented_gap_exception")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_4h_gap_policy_v2",
        "status": "btc_4h_gap_policy_blocked_until_quality_exception" if blockers else "btc_4h_gap_policy_ready",
        "missing_expected_start": MISSING_4H_START,
        "missing_expected_start_iso": _iso_from_ts(MISSING_4H_START),
        "diagnostic_status": content.get("status"),
        "diagnostic_classification": content.get("classification"),
        "candidate_count": validation.get("candidate_count"),
        "expected_count": validation.get("expected_count"),
        "missing_expected_count": validation.get("missing_expected_count"),
        "surgical_fetch_first_candle_start": returned_start,
        "surgical_fetch_call_count": int(content.get("coinbase_public_market_data_call_count") or 0),
        "policy_decision": decision,
        "known_gap_policy": {
            "may_treat_as_documented_exchange_hole": bool(single_missing and not recovered),
            "may_merge_incomplete_candidate": False,
            "may_mark_4h_good_without_quality_exception_tooling": False,
            "requires_reported_gap_exception": True,
            "requires_human_review": True,
        },
        "recommended_next_step": "build_dataset_quality_known_gap_exception_preview_before_1h_fetch",
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


def build_rate_limit_policy_v2() -> Dict[str, Any]:
    conservative = RateLimitPolicy(
        max_requests_per_minute=6,
        min_delay_seconds=1.0,
        max_retries_per_chunk=2,
        retry_budget_total=4,
        backoff_base_seconds=1.0,
        backoff_max_seconds=16.0,
        jitter_seconds=0.5,
        max_consecutive_errors=2,
        cooldown_after_error_seconds=2.0,
        stop_on_zero_candle_response=True,
    )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "rate_limit_public_fetch_policy_v2",
        "status": "rate_limit_public_fetch_policy_v2_ready",
        "policy": conservative.__dict__,
        "execution_rules": [
            "single_threaded_public_candle_requests",
            "dry_run_before_fetch",
            "candidate_root_under_tmp",
            "fail_closed_on_plan_blockers",
            "fail_closed_on_zero_candle_response",
            "fail_closed_on_consecutive_errors",
            "quarantine_partial_candidate",
            "resume_from_next_resume_chunk_index_only_after_review",
            "no_account_or_order_endpoint",
        ],
        "chunk_budget": {
            "default_subrun_max_chunks": 10,
            "pilot_subrun_max_chunks": 1,
            "btc_1h_first_fetch_budget_recommendation": "one_chunk_only_after_4h_gap_policy_is_quality-gated",
        },
        **safety_flags(),
        "state_write_performed": False,
    }


def build_btc_1h_staged_rate_limited_plan_v2(
    *,
    one_h_policy: Dict[str, Any],
    gap_policy: Dict[str, Any],
    candidate_root: str = "/tmp/d6_btc_1h_staged_v17_v18",
) -> Dict[str, Any]:
    content = dict(one_h_policy.get("content") or one_h_policy)
    subruns = [dict(row) for row in content.get("subruns") or []]
    first = subruns[0] if subruns else {}
    blocked = bool(gap_policy.get("blockers"))
    chunks: List[Dict[str, Any]] = []
    if first:
        # Report-only first-chunk pilot plan. It intentionally does not cover
        # the whole subrun, because v17/v18 must prove pacing/resume first.
        start_iso = str(first["start"]).replace("Z", "+00:00")
        start = int(datetime.fromisoformat(start_iso).timestamp())
        chunks = [{"chunk_index": 0, "start": start, "end_exclusive": start + 350 * 3600, "coinbase_limit": 350}]
    fetch_plan = (
        build_rate_limited_fetch_plan(
            ticker="BTC-USDC",
            timeframe="1H",
            chunks=chunks,
            candidate_root=candidate_root,
            run_id="BTCUSDC-1H-gap01-pilot-chunk01",
            policy=RateLimitPolicy(
                max_requests_per_minute=6,
                min_delay_seconds=1.0,
                max_retries_per_chunk=2,
                retry_budget_total=4,
                backoff_max_seconds=16.0,
                jitter_seconds=0.5,
                max_consecutive_errors=2,
                cooldown_after_error_seconds=2.0,
                stop_on_zero_candle_response=True,
            ),
        )
        if chunks
        else None
    )
    blockers: List[str] = []
    if blocked:
        blockers.append("btc_4h_gap_policy_not_quality_exception_ready")
    if not subruns:
        blockers.append("btc_1h_staged_subruns_unavailable")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_staged_rate_limited_plan_v2",
        "status": "btc_1h_staged_rate_limited_plan_blocked" if blockers else "btc_1h_staged_rate_limited_plan_ready",
        "subrun_count": len(subruns),
        "selected_pilot_subrun_id": first.get("subrun_id"),
        "selected_pilot_scope": {
            "mode": "one_chunk_policy_probe",
            "expected_candle_count": 350 if chunks else 0,
            "reason": "prove_rate_limit_resume_validation_before_full_subrun",
        },
        "rate_limited_fetch_plan": fetch_plan,
        "fetch_executed": False,
        "merge_executed": False,
        "execution_decision": "formal_block_until_4h_gap_policy_quality_exception" if blockers else "eligible_for_future_bounded_public_fetch_ack",
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


def build_backlearning_scaffold_v3(*, quality_summary: Dict[str, Any], gap_policy: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or quality_summary)
    blockers = ["dataset_quality_not_ready_for_normal_backtests"]
    if gap_policy.get("blockers"):
        blockers.append("known_gap_exception_policy_not_implemented")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "backlearning_scaffold_v3",
        "status": "backlearning_scaffold_v3_ready",
        "dataset_contracts": {
            "requires_candle_identity": ["product_id", "timeframe", "start"],
            "requires_gap_policy": True,
            "known_gap_exception_support": "preview_only_not_applied",
            "quality_summary": summary,
        },
        "trial_accounting": {
            "trial_id_required": True,
            "input_hashes_required": True,
            "dataset_quality_snapshot_required": True,
            "cost_model_snapshot_required": True,
            "human_review_required": True,
        },
        "walk_forward_oos": {
            "split_generation": "chronological_only",
            "holdout_lock": "no_metric_from_holdout_may_select_runtime_behavior",
            "degradation_report_required": True,
        },
        "metrics": {
            "allowed_descriptive_metrics": ["net_return", "drawdown", "turnover", "fees", "exposure", "trade_count"],
            "ranking_allowed": False,
            "parameter_search_allowed": False,
        },
        "fill_realism": {
            "fees_required": True,
            "slippage_hook_required": True,
            "latency_hook_required": True,
            "post_only_fill_model_required_before_live_comparison": True,
        },
        "execution_gate": {
            "runtime_mutation_allowed": False,
            "learning_to_execution_enabled": False,
            "separate_future_ack_required": True,
        },
        "blockers": blockers,
        **safety_flags(),
        "state_write_performed": False,
    }


def build_preflight_v7(
    *,
    quality_summary: Dict[str, Any],
    gap_policy: Dict[str, Any],
    one_h_plan: Dict[str, Any],
    backlearning: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_live_test_preflight_runner_v7",
        "status": "24h_live_test_preflight_runner_v7_ready",
        "preflight_result": "blocked_research_only",
        "quality_summary": dict(quality_summary.get("summary") or quality_summary),
        "btc_4h_gap_policy_status": gap_policy.get("status"),
        "btc_1h_execution_decision": one_h_plan.get("execution_decision"),
        "backlearning_status": backlearning.get("status"),
        "no_go_boundaries": [
            "no_live_submit",
            "no_cancel_replace_reprice",
            "no_state_write",
            "no_config_or_parameter_mutation",
            "no_account_or_order_endpoint",
            "no_unbounded_fetch_loop",
        ],
        "future_ack_matrix": {
            "read_only_preflight": "required_later",
            "controlled_test_order": "required_later",
            "lifecycle_apply_after_terminal_evidence": "required_later",
        },
        "evidence_plan_for_later_24h_test": [
            "pre_state_hashes",
            "dataset_quality_snapshot",
            "open_order_snapshot",
            "decision_trace",
            "order_intent_ack_record",
            "terminal_evidence",
            "post_state_hashes",
            "duplicate_or_oversell_audit",
        ],
        **safety_flags(),
        "state_write_performed": False,
    }


def build_master_packet_v17_v18(
    *,
    quality_summary: Dict[str, Any],
    gap_policy: Dict[str, Any],
    rate_limit_policy: Dict[str, Any],
    one_h_plan: Dict[str, Any],
    backlearning: Dict[str, Any],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or quality_summary)
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v17_v18",
        "status": "24h_readiness_master_packet_v17_v18_ready",
        "v17_v18_resolved": [
            "btc_4h_gap_policy_formalized",
            "btc_1h_staged_rate_limited_plan_created",
            "rate_limit_policy_hardened",
            "backlearning_scaffold_v3_created",
            "24h_preflight_v7_refreshed",
        ],
        "quality_summary": summary,
        "btc_usdc_only_24h_status": "blocked_until_btc_4h_known_gap_policy_and_1h_gap_fill_complete_then_exact_acks",
        "staged_non_btc_status": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
        "all_ticker_24h_status": "blocked",
        "btc_4h_gap_policy": {
            "status": gap_policy.get("status"),
            "decision": gap_policy.get("policy_decision"),
            "blockers": gap_policy.get("blockers"),
        },
        "btc_1h_staged": {
            "status": one_h_plan.get("status"),
            "decision": one_h_plan.get("execution_decision"),
            "selected_pilot_subrun_id": one_h_plan.get("selected_pilot_subrun_id"),
        },
        "rate_limit_policy": rate_limit_policy.get("policy"),
        "backlearning": {
            "status": backlearning.get("status"),
            "blockers": backlearning.get("blockers"),
        },
        "preflight": {
            "status": preflight.get("status"),
            "result": preflight.get("preflight_result"),
        },
        "remaining_blockers": [
            "dataset_quality_known_gap_exception_tooling_missing",
            "btc_usdc_1h_staged_gap_fill_not_started",
            "normal_backtests_deferred",
            "future_live_test_exact_acks_missing",
        ],
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "MISSING_4H_START",
    "PHASE",
    "build_backlearning_scaffold_v3",
    "build_btc_1h_staged_rate_limited_plan_v2",
    "build_btc_4h_gap_policy_v2",
    "build_master_packet_v17_v18",
    "build_preflight_v7",
    "build_rate_limit_policy_v2",
    "safety_flags",
]
