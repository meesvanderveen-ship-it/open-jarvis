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

from bot.phase_d6_backlearning_multisource_v6 import (  # noqa: E402
    build_backlearning_multisource_scaffold_v6,
    build_open_source_backlearning_pattern_map_v4,
)
from bot.phase_d6_btc_1h_staged_controller import (  # noqa: E402
    BTC_1H_CANDLES,
    build_binance_btc_1h_reference_report,
    build_btc_1h_staged_controller_plan,
    build_cross_source_btc_1h_gap_diagnostic,
    build_exploratory_backtest_decision_v22_v23,
    build_quality_summary_v22_v23,
    build_resume_status_v3,
    execute_btc_1h_staged_controller,
)
from bot.phase_d6_metrics import now_iso  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


DEFAULT_RESUME = "reports/d6/btc-1h-staged-resume-status-v1-20260601.json"
DEFAULT_KNOWN_GAP = "reports/d6/btc-4h-known-gap-preview-v1-20260601.json"
DEFAULT_BINANCE_4H = "reports/d6/binance-btcusdc-4h-gap-reference-v1-20260601.json"
DEFAULT_POLICY = "reports/d6/multi-source-candle-policy-v1-20260601.json"
DEFAULT_V21_MASTER = "reports/d6/24h-readiness-master-packet-v21-20260601.json"


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
    return {
        "good_count": int(counters.get("good_count") or 0),
        "warning_count": int(counters.get("warning_count") or 0),
        "poor_count": int(counters.get("poor_count") or 0),
        "invalid_count": int(counters.get("invalid_count") or 0),
        "stale_last_candle": int(counters.get("stale_last_candle") or 0),
        "candle_gaps_detected": int(counters.get("candle_gaps_detected") or 0),
        "missing_candles_estimated": int(counters.get("missing_candles_estimated") or 0),
    }


def build_preflight_v10(
    *,
    controller_plan: Dict[str, Any],
    controller_result: Dict[str, Any] | None,
    quality_summary: Dict[str, Any],
    binance_reference: Dict[str, Any],
) -> Dict[str, Any]:
    completed = int((controller_result or {}).get("completed_chunk_count") or 0)
    return {
        "generated_at": now_iso(),
        "phase": "D6_v22_v23_btc_1h_controller",
        "report_name": "24h_live_test_preflight_runner_v10",
        "status": "24h_live_test_preflight_v10_blocked",
        "scope": "btc_usdc_only_research_readiness_preview",
        "controller_status": (controller_result or controller_plan).get("status"),
        "btc_1h_chunks_completed_this_sprint": completed,
        "dataset_quality": _quality_counters(quality_summary),
        "binance_reference": {
            "btc_4h_reference_available": True,
            "btc_1h_reference_count": binance_reference.get("available_reference_count"),
            "reference_only": True,
        },
        "preflight_result": "blocked_until_primary_coinbase_dataset_quality_passes_and_live_ack_exists",
        "blockers": [
            "btc_usdc_1h_staged_gap_fill_incomplete",
            "primary_coinbase_dataset_quality_not_ready",
            "normal_backtests_deferred",
            "future_live_test_ack_missing",
        ],
        "state_write_performed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def build_master_packet_v22_v23(
    *,
    controller_plan: Dict[str, Any],
    controller_result: Dict[str, Any] | None,
    resume_status: Dict[str, Any],
    quality_summary: Dict[str, Any],
    binance_4h: Dict[str, Any],
    binance_1h: Dict[str, Any],
    backlearning_v6: Dict[str, Any],
    backtest_decision: Dict[str, Any],
) -> Dict[str, Any]:
    completed = list((controller_result or {}).get("completed_chunk_ids") or [])
    return {
        "generated_at": now_iso(),
        "phase": "D6_v22_v23_btc_1h_controller",
        "report_name": "24h_readiness_master_packet_v22_v23",
        "status": "24h_readiness_v22_v23_not_ready",
        "btc_usdc_only_24h_readiness": {
            "closer_than_v21": bool(completed),
            "ready_for_24h_live_run": False,
            "chunks_completed_this_sprint": completed,
            "next_btc_1h_scope": resume_status.get("next_pending_scope"),
            "remaining_blockers": [
                "btc_usdc_1h_gap_not_fully_closed",
                "btc_usdc_4h_coinbase_raw_gap_still_visible",
                "dataset_quality_warning_or_poor_rows_remain",
                "normal_backtests_deferred",
                "future_live_test_ack_missing",
            ],
        },
        "staged_non_btc_readiness": {
            "status": "blocked",
            "reason": "btc_usdc_only_path_not_ready_and_non_btc_lifecycle_evidence_not_in_scope",
        },
        "all_ticker_readiness": {
            "status": "blocked",
            "reason": "all_ticker_quality_and_live_lifecycle_evidence_not_ready",
        },
        "btc_1h_controller": {
            "plan_status": controller_plan.get("status"),
            "result_status": (controller_result or {}).get("status", "not_run"),
            "planned_chunk_count": controller_plan.get("planned_chunk_count"),
            "completed_chunk_count": len(completed),
            "stop_reason": (controller_result or {}).get("stop_reason", ""),
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
        },
        "dataset_quality": _quality_counters(quality_summary),
        "backlearning_status": backlearning_v6.get("status"),
        "backtest_decision": {
            "normal_backtests": backtest_decision.get("normal_backtests"),
            "parameter_evidence_created": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_changed": False,
            "learning_to_execution_enabled": False,
        },
        "required_future_acks": [
            "explicit_24h_live_test_start_ack_after_fresh_preflight_pass",
            "explicit_lifecycle_apply_ack_for_any_future_terminal_evidence_apply",
        ],
        "no_go_boundaries": [
            "no_live_submit",
            "no_cancel_replace_reprice",
            "no_state_write",
            "no_config_or_parameter_mutation",
            "no_coinbase_account_or_order_endpoint",
            "no_binance_account_or_order_endpoint",
            "no_external_candle_as_coinbase_candle",
            "no_auto_resume_after_failure",
        ],
        "next_largest_step": "continue_btc_usdc_1h_reviewed_staged_chunks_until_gap_closed_or_fail_closed",
        "state_write_performed": False,
        "human_review_required": True,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
    }


def build_research_index_v22_v23(*, outputs: Iterable[str], master: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_v22_v23_btc_1h_controller",
        "report_name": "research_readiness_index_v22_v23",
        "status": "research_readiness_index_v22_v23_ready",
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
    parser = argparse.ArgumentParser(description="D.6 BTC-USDC 1H staged controller v22/v23.")
    parser.add_argument("--resume-status", default=DEFAULT_RESUME)
    parser.add_argument("--known-gap-preview", default=DEFAULT_KNOWN_GAP)
    parser.add_argument("--binance-4h-reference", default=DEFAULT_BINANCE_4H)
    parser.add_argument("--multi-source-policy", default=DEFAULT_POLICY)
    parser.add_argument("--v21-master", default=DEFAULT_V21_MASTER)
    parser.add_argument("--candidate-root", default="/tmp/d6_btc_1h_staged_controller_v22_v23")
    parser.add_argument("--max-chunks", type=int, default=3)
    parser.add_argument("--execute-chunks", type=int, default=0)
    parser.add_argument("--reuse-plan-report", default="")
    parser.add_argument("--reuse-result-report", default="")
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--binance-reference", action="store_true")
    args = parser.parse_args()

    source_paths = [
        args.resume_status,
        args.known_gap_preview,
        args.binance_4h_reference,
        args.multi_source_policy,
        args.v21_master,
        BTC_1H_CANDLES,
    ]
    binance_4h = _load_report_content(args.binance_4h_reference)
    plan = (
        _load_report_content(args.reuse_plan_report)
        if args.reuse_plan_report
        else build_btc_1h_staged_controller_plan(
            resume_status_path=args.resume_status,
            candidate_root=args.candidate_root,
            max_chunks=args.max_chunks,
        )
    )
    result = _load_report_content(args.reuse_result_report) if args.reuse_result_report else None
    if args.fetch:
        from bot.coinbase_client import CoinbaseClient  # noqa: E402

        result = execute_btc_1h_staged_controller(
            plan=plan,
            coinbase_client=CoinbaseClient(),
            max_execute_chunks=args.execute_chunks or args.max_chunks,
            merge=not args.no_merge,
            binance_reference=args.binance_reference,
        )
    resume_v3 = build_resume_status_v3(plan=plan, result=result)
    binance_1h = build_binance_btc_1h_reference_report(controller_result=result)
    cross_source = build_cross_source_btc_1h_gap_diagnostic(controller_result=result)
    quality = build_quality_summary_v22_v23()
    pattern_map = build_open_source_backlearning_pattern_map_v4()
    backlearning = build_backlearning_multisource_scaffold_v6(
        quality_summary=quality,
        controller_result=result or {},
        binance_reference=binance_1h,
        source_paths=[BTC_1H_CANDLES, args.binance_4h_reference],
    )
    backtest_decision = build_exploratory_backtest_decision_v22_v23(quality_summary=quality)
    preflight = build_preflight_v10(
        controller_plan=plan,
        controller_result=result,
        quality_summary=quality,
        binance_reference=binance_1h,
    )
    master = build_master_packet_v22_v23(
        controller_plan=plan,
        controller_result=result,
        resume_status=resume_v3,
        quality_summary=quality,
        binance_4h=binance_4h,
        binance_1h=binance_1h,
        backlearning_v6=backlearning,
        backtest_decision=backtest_decision,
    )
    specs = [
        ("btc_1h_staged_controller_plan_v1", plan, "btc-1h-staged-controller-plan-v1-20260601"),
        ("btc_1h_staged_resume_status_v3", resume_v3, "btc-1h-staged-resume-status-v3-20260601"),
        ("binance_btcusdc_1h_reference_v2", binance_1h, "binance-btcusdc-1h-reference-v2-20260601"),
        ("cross_source_btc_1h_gap_diagnostic_v1", cross_source, "cross-source-btc-1h-gap-diagnostic-v1-20260601"),
        ("post_btc_1h_staged_quality_summary_v22_v23", quality, "post-btc-1h-staged-quality-summary-v22-v23-20260601"),
        ("open_source_backlearning_pattern_map_v4", pattern_map, "open-source-backlearning-pattern-map-v4-20260601"),
        ("backlearning_multisource_scaffold_v6", backlearning, "backlearning-multisource-scaffold-v6-20260601"),
        ("exploratory_only_backtest_decision_v22_v23", backtest_decision, "exploratory-only-backtest-decision-v22-v23-20260601"),
        ("24h_live_test_preflight_runner_v10", preflight, "24h-live-test-preflight-runner-v10-20260601"),
        ("24h_readiness_master_packet_v22_v23", master, "24h-readiness-master-packet-v22-v23-20260601"),
    ]
    if result is not None:
        specs.insert(1, ("btc_1h_staged_controller_result_v1", result, "btc-1h-staged-controller-result-v1-20260601"))
    outputs: List[str] = []
    for report_type, content, stem in specs:
        outputs.extend(_write_pair(report_type, content, stem, source_paths=source_paths))
    research_index = build_research_index_v22_v23(outputs=outputs, master=master)
    outputs.extend(
        _write_pair(
            "research_readiness_index_v22_v23",
            research_index,
            "research-readiness-index-v22-v23-20260601",
            source_paths=[*source_paths, *outputs],
        )
    )
    print(
        json.dumps(
            {
                "status": "v22_v23_reports_written",
                "fetch": args.fetch,
                "binance_reference": args.binance_reference,
                "controller_result_status": (result or {}).get("status", "not_run"),
                "completed_chunks": (result or {}).get("completed_chunk_ids", []),
                "outputs": outputs,
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0 if not result or result.get("status") == "btc_1h_staged_controller_result_ready" else 2


if __name__ == "__main__":
    raise SystemExit(main())
