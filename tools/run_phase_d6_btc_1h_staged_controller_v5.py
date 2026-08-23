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

from bot.phase_d6_backlearning_multisource_v10 import (  # noqa: E402
    build_backlearning_multisource_scaffold_v10,
    build_open_source_backlearning_pattern_map_v8,
)
from bot.phase_d6_btc_1h_staged_controller import BTC_1H_CANDLES  # noqa: E402
from bot.phase_d6_btc_1h_staged_controller_v5 import (  # noqa: E402
    build_binance_btc_1h_reference_report_v6,
    build_btc_1h_staged_controller_plan_v5,
    build_cross_source_btc_1h_gap_diagnostic_v5,
    build_exploratory_backtest_decision_v30_v31,
    build_quality_summary_v30_v31,
    build_resume_status_v7,
    execute_btc_1h_staged_controller_v5,
)
from bot.phase_d6_metrics import now_iso  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


DEFAULT_RESUME = "reports/d6/btc-1h-staged-resume-status-v6-20260601.json"
DEFAULT_BINANCE_4H = "reports/d6/binance-btcusdc-4h-gap-reference-v1-20260601.json"
DEFAULT_POLICY = "reports/d6/multi-source-candle-policy-v1-20260601.json"
DEFAULT_MASTER = "reports/d6/24h-readiness-master-packet-v28-v29-20260601.json"
DEFAULT_KNOWN_GAP = "reports/d6/btc-4h-known-gap-preview-v1-20260601.json"


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


def _quality_counters(quality: Dict[str, Any]) -> Dict[str, int]:
    counters = dict(quality.get("global_counters") or {})
    keys = ["good_count", "warning_count", "poor_count", "invalid_count", "stale_last_candle", "candle_gaps_detected", "missing_candles_estimated"]
    return {key: int(counters.get(key) or 0) for key in keys}


def _preflight_v14(*, plan: Dict[str, Any], result: Dict[str, Any] | None, quality: Dict[str, Any], binance_1h: Dict[str, Any]) -> Dict[str, Any]:
    completed = list((result or {}).get("completed_chunk_ids") or [])
    return {
        "generated_at": now_iso(),
        "phase": "D6_v30_v31_btc_1h_controller",
        "report_name": "24h_live_test_preflight_runner_v14",
        "status": "24h_live_test_preflight_v14_blocked",
        "scope": "btc_usdc_only_research_readiness_preview",
        "controller_status": (result or plan).get("status"),
        "btc_1h_chunks_completed_this_sprint": len(completed),
        "dataset_quality": _quality_counters(quality),
        "binance_reference": {"btc_1h_reference_count": binance_1h.get("available_reference_count"), "reference_only": True},
        "preflight_result": "blocked_until_primary_coinbase_dataset_quality_passes_and_live_ack_exists",
        "blockers": ["btc_usdc_1h_staged_gap_fill_incomplete", "btc_usdc_4h_coinbase_raw_gap_still_visible", "primary_coinbase_dataset_quality_not_ready", "normal_backtests_deferred", "future_live_test_ack_missing"],
        "state_write_performed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _master_v30_v31(
    *,
    plan: Dict[str, Any],
    result: Dict[str, Any] | None,
    resume: Dict[str, Any],
    quality: Dict[str, Any],
    binance_4h: Dict[str, Any],
    binance_1h: Dict[str, Any],
    backlearning: Dict[str, Any],
    backtest: Dict[str, Any],
) -> Dict[str, Any]:
    completed = list((result or {}).get("completed_chunk_ids") or [])
    all_completed = list(resume.get("previous_completed_chunks") or []) + list(resume.get("new_completed_chunks") or [])
    return {
        "generated_at": now_iso(),
        "phase": "D6_v30_v31_btc_1h_controller",
        "report_name": "24h_readiness_master_packet_v30_v31",
        "status": "24h_readiness_v30_v31_not_ready",
        "readiness_answers": {
            "btc_usdc_only_24h_closer": bool(completed),
            "btc_1h_chunks_ready_count": len(all_completed),
            "btc_1h_chunks_completed_this_sprint": completed,
            "btc_1h_open_scope": resume.get("next_pending_scope"),
            "btc_4h_coinbase_gap_status": "coinbase_raw_gap_still_visible_known_gap_reference_available",
            "binance_reference_policy": "secondary_reference_only_no_primary_cache_mutation_no_normal_backtest_release",
            "normal_backtest_blocker": "primary_coinbase_dataset_quality_has_warning_or_poor_rows",
            "live_24h_blocker": "fresh_preflight_and_explicit_live_ack_missing",
            "next_largest_step": "continue_btc_usdc_1h_reviewed_staged_chunks_from_next_resume_scope",
        },
        "btc_usdc_only_24h_readiness": {
            "closer_than_v28_v29": bool(completed),
            "ready_for_24h_live_run": False,
            "chunks_completed_this_sprint": completed,
            "next_btc_1h_scope": resume.get("next_pending_scope"),
            "remaining_blockers": ["btc_usdc_1h_gap_not_fully_closed", "btc_usdc_4h_coinbase_raw_gap_still_visible", "dataset_quality_warning_or_poor_rows_remain", "normal_backtests_deferred", "future_live_test_ack_missing"],
        },
        "staged_non_btc_readiness": {"status": "blocked", "reason": "btc_usdc_only_path_not_ready"},
        "all_ticker_readiness": {"status": "blocked", "reason": "all_ticker_quality_and_lifecycle_evidence_not_ready"},
        "btc_1h_controller": {
            "plan_status": plan.get("status"),
            "result_status": (result or {}).get("status", "not_run"),
            "planned_chunk_count": plan.get("planned_chunk_count"),
            "completed_chunk_count": len(completed),
            "stop_reason": (result or {}).get("stop_reason", ""),
            "fail_closed_reason": (result or {}).get("fail_closed_reason", ""),
            "auto_resume_allowed": False,
        },
        "btc_4h_coinbase_gap_and_binance_reference": {
            "coinbase_raw_gap_still_visible": True,
            "binance_reference_classification": binance_4h.get("binance_reference", {}).get("classification"),
            "binance_can_repair_coinbase_cache": False,
        },
        "binance_reference_policy": {
            "btc_1h_available_reference_count": binance_1h.get("available_reference_count"),
            "reference_only": True,
            "coinbase_cache_mutated_by_binance": False,
            "normal_backtest_permission_changed_by_binance": False,
        },
        "dataset_quality": _quality_counters(quality),
        "backlearning_status": backlearning.get("status"),
        "backtest_decision": {
            "normal_backtests": backtest.get("normal_backtests"),
            "exploratory_only": "deferred_or_plumbing_only",
            "parameter_evidence_created": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_changed": False,
            "learning_to_execution_enabled": False,
        },
        "required_future_acks": ["fresh_coinbase_read_preflight_ack", "explicit_24h_live_test_start_ack_after_fresh_preflight_pass", "separate_lifecycle_apply_ack_if_any_live_order_fills"],
        "no_go_boundaries": ["no_live_submit", "no_cancel_replace_reprice", "no_lifecycle_apply", "no_state_write", "no_config_or_parameter_mutation", "no_coinbase_account_or_order_endpoint", "no_binance_account_or_order_endpoint", "no_external_candle_as_coinbase_candle", "no_auto_resume_after_failure"],
        "next_largest_step": "continue_btc_usdc_1h_reviewed_staged_chunks_from_next_resume_scope",
        "state_write_performed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def _index_v30_v31(*, outputs: Iterable[str], master: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_v30_v31_btc_1h_controller",
        "report_name": "research_readiness_index_v30_v31",
        "status": "research_readiness_index_v30_v31_ready",
        "indexed_outputs": sorted(outputs),
        "readiness_status": master.get("status"),
        "btc_usdc_only_ready": master.get("btc_usdc_only_24h_readiness", {}).get("ready_for_24h_live_run"),
        "normal_backtests": master.get("backtest_decision", {}).get("normal_backtests"),
        "state_write_performed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="D.6 BTC-USDC 1H staged controller v30/v31.")
    parser.add_argument("--resume-status", default=DEFAULT_RESUME)
    parser.add_argument("--known-gap-preview", default=DEFAULT_KNOWN_GAP)
    parser.add_argument("--binance-4h-reference", default=DEFAULT_BINANCE_4H)
    parser.add_argument("--multi-source-policy", default=DEFAULT_POLICY)
    parser.add_argument("--previous-master", default=DEFAULT_MASTER)
    parser.add_argument("--candidate-root", default="/tmp/d6_btc_1h_staged_controller_v30_v31")
    parser.add_argument("--max-chunks", type=int, default=3)
    parser.add_argument("--execute-chunks", type=int, default=0)
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--binance-reference", action="store_true")
    args = parser.parse_args()

    source_paths = [args.resume_status, args.known_gap_preview, args.binance_4h_reference, args.multi_source_policy, args.previous_master, BTC_1H_CANDLES]
    binance_4h = _load_report_content(args.binance_4h_reference)
    plan = build_btc_1h_staged_controller_plan_v5(resume_status_path=args.resume_status, candidate_root=args.candidate_root, max_chunks=args.max_chunks)
    result = None
    if args.fetch:
        from bot.coinbase_client import CoinbaseClient  # noqa: E402

        result = execute_btc_1h_staged_controller_v5(
            plan=plan,
            coinbase_client=CoinbaseClient(),
            max_execute_chunks=args.execute_chunks or args.max_chunks,
            merge=not args.no_merge,
            binance_reference=args.binance_reference,
        )
    resume_v7 = build_resume_status_v7(plan=plan, result=result)
    binance_1h = build_binance_btc_1h_reference_report_v6(controller_result=result)
    cross_source = build_cross_source_btc_1h_gap_diagnostic_v5(controller_result=result)
    quality = build_quality_summary_v30_v31()
    pattern_map = build_open_source_backlearning_pattern_map_v8()
    backlearning = build_backlearning_multisource_scaffold_v10(
        quality_summary=quality,
        controller_result=result or {},
        binance_reference=binance_1h,
        source_paths=[BTC_1H_CANDLES, args.binance_4h_reference],
    )
    backtest = build_exploratory_backtest_decision_v30_v31(quality_summary=quality)
    preflight = _preflight_v14(plan=plan, result=result, quality=quality, binance_1h=binance_1h)
    master = _master_v30_v31(plan=plan, result=result, resume=resume_v7, quality=quality, binance_4h=binance_4h, binance_1h=binance_1h, backlearning=backlearning, backtest=backtest)
    specs = [
        ("btc_1h_staged_controller_plan_v5", plan, "btc-1h-staged-controller-plan-v5-20260601"),
        ("btc_1h_staged_resume_status_v7", resume_v7, "btc-1h-staged-resume-status-v7-20260601"),
        ("binance_btcusdc_1h_reference_v6", binance_1h, "binance-btcusdc-1h-reference-v6-20260601"),
        ("cross_source_btc_1h_gap_diagnostic_v5", cross_source, "cross-source-btc-1h-gap-diagnostic-v5-20260601"),
        ("post_btc_1h_staged_quality_summary_v30_v31", quality, "post-btc-1h-staged-quality-summary-v30-v31-20260601"),
        ("open_source_backlearning_pattern_map_v8", pattern_map, "open-source-backlearning-pattern-map-v8-20260601"),
        ("backlearning_multisource_scaffold_v10", backlearning, "backlearning-multisource-scaffold-v10-20260601"),
        ("exploratory_only_backtest_decision_v30_v31", backtest, "exploratory-only-backtest-decision-v30-v31-20260601"),
        ("24h_live_test_preflight_runner_v14", preflight, "24h-live-test-preflight-runner-v14-20260601"),
        ("24h_readiness_master_packet_v30_v31", master, "24h-readiness-master-packet-v30-v31-20260601"),
    ]
    if result is not None:
        specs.insert(1, ("btc_1h_staged_controller_result_v5", result, "btc-1h-staged-controller-result-v5-20260601"))
    outputs: List[str] = []
    for report_type, content, stem in specs:
        outputs.extend(_write_pair(report_type, content, stem, source_paths=source_paths))
    research_index = _index_v30_v31(outputs=outputs, master=master)
    outputs.extend(_write_pair("research_readiness_index_v30_v31", research_index, "research-readiness-index-v30-v31-20260601", source_paths=[*source_paths, *outputs]))
    print(json.dumps({"status": "v30_v31_reports_written", "fetch": args.fetch, "completed_chunks": (result or {}).get("completed_chunk_ids", []), "outputs": outputs}, indent=2, sort_keys=True))
    return 0 if not result or result.get("status") == "btc_1h_staged_controller_result_v5_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
