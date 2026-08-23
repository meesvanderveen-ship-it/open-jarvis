#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_backlearning_scaffold_v4 import (  # noqa: E402
    build_backlearning_scaffold_v4,
    build_open_source_backlearning_pattern_map_v3,
)
from bot.phase_d6_candidate_coverage_validator import validate_candidate_coverage  # noqa: E402
from bot.phase_d6_gap_aware_candle_planner import build_post_gap_fill_quality_summary, discover_candle_files  # noqa: E402
from bot.phase_d6_known_gap_quality_policy import (  # noqa: E402
    build_btc_4h_known_gap_preview_v1,
    build_known_gap_quality_policy_v1,
)
from bot.phase_d6_metrics import now_iso  # noqa: E402
from bot.phase_d6_rate_limited_public_fetch import RateLimitPolicy, build_rate_limited_fetch_plan, execute_rate_limited_fetch  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402
from bot.phase_d6_tail_candle_refresh import merge_tail_refresh_result  # noqa: E402


DEFAULT_1H_PLAN = "reports/d6/btc-1h-staged-rate-limited-plan-v2-20260601.json"
BTC_1H_CANDLES = "research_data/coinbase/candles/product=BTC-USDC/timeframe=1H/study_window=3y.json"


def _load_report_content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    content = loaded.get("content") if isinstance(loaded, dict) else None
    return dict(content) if isinstance(content, dict) else dict(loaded)


def _write_pair(report_type: str, content: Dict[str, Any], stem: str, *, source_paths: Iterable[str]) -> Tuple[str, str]:
    bundle = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}.json"
    md_path = f"reports/d6/{stem}.md"
    write_phase_d6_report_bundle(bundle, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(bundle, md_path, markdown=True)
    return json_path, md_path


def _one_h_policy_ready(known_gap_preview: Dict[str, Any]) -> bool:
    return (
        known_gap_preview.get("status") == "btc_4h_known_gap_preview_ready"
        and known_gap_preview.get("gap_class") == "acceptable_known_gap_for_exploratory_research"
        and known_gap_preview.get("preview_semantics", {}).get("normal_backtest_allowed") is False
    )


def _build_policy_v3() -> Dict[str, Any]:
    policy = RateLimitPolicy(
        max_requests_per_minute=6,
        max_requests_per_run=1,
        min_delay_seconds=1.0,
        max_retries_per_chunk=2,
        retry_budget_total=4,
        backoff_base_seconds=1.0,
        backoff_max_seconds=16.0,
        jitter_seconds=0.5,
        max_consecutive_errors=2,
        cooldown_after_error_seconds=2.0,
        stop_on_zero_candle_response=True,
        stop_on_partial_candidate=True,
    )
    return {
        "generated_at": now_iso(),
        "phase": "D6_v19_v20_readiness_v1",
        "report_name": "rate_limit_public_fetch_policy_v3",
        "status": "rate_limit_public_fetch_policy_v3_ready",
        "policy": policy.__dict__,
        "error_classifications": [
            "rate_limit_error",
            "network_error",
            "zero_candle_response",
            "candidate_incomplete",
            "validation_failed",
        ],
        "resume_policy": {
            "resume_token_required": True,
            "auto_resume_after_partial": False,
            "operator_review_required_after_partial_or_validation_failure": True,
            "next_safe_command_reported": True,
        },
        "execution_rules": [
            "single_threaded_public_candle_requests",
            "per_run_request_budget",
            "per_subrun_cooldown",
            "quarantine_partial_candidate",
            "stop_on_partial_candidate",
            "no_account_or_order_endpoint",
        ],
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _build_pilot_plan(*, candidate_root: str, one_h_plan: Dict[str, Any]) -> Dict[str, Any]:
    v17_fetch_plan = dict(one_h_plan.get("rate_limited_fetch_plan") or {})
    requests = list(v17_fetch_plan.get("requests") or [])
    if not requests:
        raise ValueError("btc_1h_pilot_plan_missing_v17_request")
    request = dict(requests[0])
    chunk = {
        "chunk_index": 0,
        "start": int(request["expected_start"]),
        "end_exclusive": int(request["expected_end_exclusive"]),
        "coinbase_limit": int(request.get("coinbase_limit") or 350),
    }
    return build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="1H",
        chunks=[chunk],
        candidate_root=candidate_root,
        run_id="BTCUSDC-1H-gap01-pilot-chunk01-v19-v20",
        policy=RateLimitPolicy(
            max_requests_per_minute=6,
            max_requests_per_run=1,
            min_delay_seconds=1.0,
            max_retries_per_chunk=2,
            retry_budget_total=4,
            backoff_max_seconds=16.0,
            jitter_seconds=0.5,
            max_consecutive_errors=2,
            cooldown_after_error_seconds=2.0,
            stop_on_zero_candle_response=True,
            stop_on_partial_candidate=True,
        ),
    )


def build_btc_1h_pilot_result(
    *,
    one_h_plan: Dict[str, Any],
    known_gap_preview: Dict[str, Any],
    candidate_root: str,
    execute: bool,
    merge: bool,
) -> Dict[str, Any]:
    pilot_plan = _build_pilot_plan(candidate_root=candidate_root, one_h_plan=one_h_plan)
    gates: List[str] = []
    if not _one_h_policy_ready(known_gap_preview):
        gates.append("known_gap_preview_not_ready_for_exploratory_1h_pilot")
    if pilot_plan.get("blockers"):
        gates.extend(list(pilot_plan.get("blockers") or []))
    fetch_result: Dict[str, Any] | None = None
    validation: Dict[str, Any] | None = None
    merge_result: Dict[str, Any] | None = None
    if execute and not gates:
        from bot.coinbase_client import CoinbaseClient  # Imported only for explicit bounded public data fetch mode.

        fetch_result = execute_rate_limited_fetch(plan=pilot_plan, client=CoinbaseClient())
        if fetch_result.get("status") != "rate_limited_public_fetch_ready":
            gates.append(fetch_result.get("stop_reason") or "rate_limited_fetch_not_ready")
        else:
            request = pilot_plan["requests"][0]
            validation = validate_candidate_coverage(
                candidate_path=fetch_result["candidate_output_path"],
                existing_path=BTC_1H_CANDLES,
                product_id="BTC-USDC",
                timeframe="1H",
                gap_start=int(request["expected_start"]),
                gap_end_exclusive=int(request["expected_end_exclusive"]),
            )
            if not validation.get("validator_pass"):
                gates.append("validation_failed")
            elif merge:
                merge_result = merge_tail_refresh_result(
                    fetch_result={
                        "entries": [
                            {
                                "ticker": "BTC-USDC",
                                "timeframe": "1H",
                                "candidate_output_path": fetch_result["candidate_output_path"],
                                "existing_cache_path": BTC_1H_CANDLES,
                            }
                        ]
                    }
                )
    status = "btc_1h_one_chunk_pilot_ready" if execute and not gates else "btc_1h_one_chunk_pilot_blocked"
    return {
        "generated_at": now_iso(),
        "phase": "D6_v19_v20_readiness_v1",
        "report_name": "btc_1h_one_chunk_pilot_result_v1",
        "status": status,
        "execute_requested": bool(execute),
        "fetch_executed": bool(fetch_result and fetch_result.get("fetch_executed")),
        "merge_requested": bool(merge),
        "merge_executed": bool(merge_result),
        "pilot_plan": pilot_plan,
        "fetch_result": fetch_result,
        "candidate_validation": validation,
        "merge_result": merge_result,
        "blockers": gates,
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": not bool(fetch_result and fetch_result.get("coinbase_public_market_data_call_performed")),
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "coinbase_account_or_order_call_performed": False,
        "coinbase_write_performed": False,
        "config_mutation_performed": False,
    }


def build_resume_status(*, pilot_result: Dict[str, Any]) -> Dict[str, Any]:
    validation = pilot_result.get("candidate_validation") or {}
    completed = bool(pilot_result.get("merge_executed") and validation.get("validator_pass"))
    return {
        "generated_at": now_iso(),
        "phase": "D6_v19_v20_readiness_v1",
        "report_name": "btc_1h_staged_resume_status_v1",
        "status": "btc_1h_staged_resume_status_ready",
        "completed_pilot_chunks": ["BTCUSDC-1H-gap01:chunk0"] if completed else [],
        "blocked_pilot_chunks": [] if completed else ["BTCUSDC-1H-gap01:chunk0"],
        "next_pending_scope": "BTCUSDC-1H-gap01:chunk1_or_review" if completed else "BTCUSDC-1H-gap01:chunk0",
        "auto_resume_allowed": False,
        "requires_operator_review_before_next_chunk": True,
        "pilot_status": pilot_result.get("status"),
        "pilot_blockers": pilot_result.get("blockers"),
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def build_preflight_v8(
    *,
    quality_summary: Dict[str, Any],
    known_gap_preview: Dict[str, Any],
    pilot_result: Dict[str, Any],
    backlearning: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_v19_v20_readiness_v1",
        "report_name": "24h_live_test_preflight_runner_v8",
        "status": "24h_live_test_preflight_runner_v8_ready",
        "preflight_result": "blocked_research_only",
        "quality_summary": dict(quality_summary.get("summary") or quality_summary),
        "btc_4h_known_gap_modelled": known_gap_preview.get("status") == "btc_4h_known_gap_preview_ready",
        "btc_1h_pilot_status": pilot_result.get("status"),
        "backlearning_status": backlearning.get("status"),
        "later_required_acks": [
            "bounded_read_only_preflight_ack",
            "exact_one_order_live_test_ack",
            "terminal_evidence_lifecycle_apply_ack",
        ],
        "no_go_boundaries": [
            "no_live_submit",
            "no_cancel_replace_reprice",
            "no_state_write",
            "no_config_or_parameter_mutation",
            "no_account_or_order_endpoint",
            "no_unbounded_fetch_loop",
            "no_synthetic_ohlcv",
            "no_auto_resume_after_partial",
        ],
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def build_master_v19_v20(
    *,
    quality_before: Dict[str, Any],
    quality_after: Dict[str, Any],
    known_gap_preview: Dict[str, Any],
    pilot_result: Dict[str, Any],
    backlearning: Dict[str, Any],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_v19_v20_readiness_v1",
        "report_name": "24h_readiness_master_packet_v19_v20",
        "status": "24h_readiness_master_packet_v19_v20_ready",
        "btc_usdc_only_24h_status": "closer_but_blocked_until_1h_gap_fill_quality_backtests_and_exact_live_acks",
        "staged_non_btc_status": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
        "all_ticker_status": "blocked",
        "known_gap_result": {
            "btc_4h_modelled": known_gap_preview.get("status") == "btc_4h_known_gap_preview_ready",
            "gap_class": known_gap_preview.get("gap_class"),
            "normal_backtest_allowed": known_gap_preview.get("preview_semantics", {}).get("normal_backtest_allowed"),
            "raw_cache_mutated": known_gap_preview.get("preview_semantics", {}).get("raw_cache_mutated"),
        },
        "btc_1h_pilot": {
            "status": pilot_result.get("status"),
            "fetch_executed": pilot_result.get("fetch_executed"),
            "merge_executed": pilot_result.get("merge_executed"),
            "blockers": pilot_result.get("blockers"),
        },
        "quality_before": dict(quality_before.get("summary") or quality_before),
        "quality_after": dict(quality_after.get("summary") or quality_after),
        "backlearning": {
            "status": backlearning.get("status"),
            "blockers": backlearning.get("blockers"),
        },
        "preflight": {
            "status": preflight.get("status"),
            "result": preflight.get("preflight_result"),
        },
        "remaining_blockers": [
            "btc_usdc_1h_staged_gap_fill_incomplete",
            "normal_backtests_deferred",
            "stale_last_candle_warnings_for_non_btc_rows",
            "future_live_test_exact_acks_missing",
        ],
        "next_step": "continue_btc_1h_staged_gap_fill_one_reviewed_chunk_at_a_time_after_safety_refresh",
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def build_reports(args: argparse.Namespace) -> Dict[str, Any]:
    source_paths = [
        "bot/phase_d6_known_gap_quality_policy.py",
        "bot/phase_d6_backlearning_scaffold_v4.py",
        "bot/phase_d6_rate_limited_public_fetch.py",
        args.one_h_plan,
        "reports/d6/btc-4h-gap-policy-v2-20260601.json",
        "reports/d6/24h-readiness-master-packet-v17-v18-20260601.json",
    ]
    quality_before = build_post_gap_fill_quality_summary(candle_paths=discover_candle_files(), as_of=args.as_of)
    known_policy = build_known_gap_quality_policy_v1()
    known_preview = build_btc_4h_known_gap_preview_v1(as_of=args.as_of)
    one_h_plan = _load_report_content(args.one_h_plan)
    rate_policy = _build_policy_v3()
    pilot = build_btc_1h_pilot_result(
        one_h_plan=one_h_plan,
        known_gap_preview=known_preview,
        candidate_root=args.candidate_root,
        execute=args.execute_1h_pilot,
        merge=not args.no_merge,
    )
    resume = build_resume_status(pilot_result=pilot)
    quality_after = build_post_gap_fill_quality_summary(candle_paths=discover_candle_files(), as_of=args.as_of)
    pattern_map = build_open_source_backlearning_pattern_map_v3()
    backlearning = build_backlearning_scaffold_v4(quality_summary=quality_after, known_gap_preview=known_preview)
    preflight = build_preflight_v8(
        quality_summary=quality_after,
        known_gap_preview=known_preview,
        pilot_result=pilot,
        backlearning=backlearning,
    )
    master = build_master_v19_v20(
        quality_before=quality_before,
        quality_after=quality_after,
        known_gap_preview=known_preview,
        pilot_result=pilot,
        backlearning=backlearning,
        preflight=preflight,
    )
    specs = [
        ("d6_known_gap_quality_policy_v1", known_policy, "known-gap-quality-policy-v1-20260601"),
        ("d6_btc_4h_known_gap_preview_v1", known_preview, "btc-4h-known-gap-preview-v1-20260601"),
        ("d6_rate_limit_public_fetch_policy_v3", rate_policy, "rate-limit-public-fetch-policy-v3-20260601"),
        ("d6_btc_1h_one_chunk_pilot_result_v1", pilot, "btc-1h-one-chunk-pilot-result-v1-20260601"),
        ("d6_btc_1h_staged_resume_status_v1", resume, "btc-1h-staged-resume-status-v1-20260601"),
        ("d6_open_source_backlearning_pattern_map_v3", pattern_map, "open-source-backlearning-pattern-map-v3-20260601"),
        ("d6_backlearning_scaffold_v4", backlearning, "backlearning-scaffold-v4-20260601"),
        ("d6_24h_live_test_preflight_runner_v8", preflight, "24h-live-test-preflight-runner-v8-20260601"),
        ("d6_24h_readiness_master_packet_v19_v20", master, "24h-readiness-master-packet-v19-v20-20260601"),
    ]
    outputs = []
    for report_type, content, stem in specs:
        json_path, md_path = _write_pair(report_type, content, stem, source_paths=source_paths)
        outputs.append({"report_type": report_type, "json": json_path, "markdown": md_path, "status": content.get("status")})
    return {
        "status": "phase_d6_v19_v20_readiness_reports_written",
        "outputs": outputs,
        "known_gap_preview_status": known_preview.get("status"),
        "known_gap_class": known_preview.get("gap_class"),
        "btc_1h_pilot_status": pilot.get("status"),
        "fetch_executed": pilot.get("fetch_executed"),
        "merge_executed": pilot.get("merge_executed"),
        "quality_before": quality_before.get("summary"),
        "quality_after": quality_after.get("summary"),
        "state_write_performed": False,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 v19/v20 research-only readiness reports.")
    parser.add_argument("--one-h-plan", default=DEFAULT_1H_PLAN)
    parser.add_argument("--candidate-root", default="/tmp/d6_btc_1h_staged_v19_v20")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--execute-1h-pilot", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = build_reports(args)
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(result["status"])
        print("known_gap_preview_status:", result["known_gap_preview_status"])
        print("btc_1h_pilot_status:", result["btc_1h_pilot_status"])
    return 0 if result.get("btc_1h_pilot_status") in {"btc_1h_one_chunk_pilot_ready", "btc_1h_one_chunk_pilot_blocked"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
