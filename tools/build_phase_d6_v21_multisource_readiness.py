#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_backlearning_multisource_v5 import build_backlearning_multisource_scaffold_v5  # noqa: E402
from bot.phase_d6_binance_public_klines import (  # noqa: E402
    BinanceRateLimitPolicy,
    build_binance_klines_plan,
    build_btc_1h_cross_source_gap_support_plan,
    build_btc_4h_gap_reference_report,
    build_multi_source_candle_policy_v1,
    execute_binance_klines_fetch,
)
from bot.phase_d6_metrics import now_iso  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402


DEFAULT_QUALITY = "reports/d6/post-staged-gap-fill-dataset-quality-summary-v15-20260601.json"
DEFAULT_MASTER = "reports/d6/24h-readiness-master-packet-v19-v20-20260601.json"
DEFAULT_KNOWN_GAP = "reports/d6/btc-4h-known-gap-preview-v1-20260601.json"
DEFAULT_1H_PILOT = "reports/d6/btc-1h-one-chunk-pilot-result-v1-20260601.json"
DEFAULT_RESUME = "reports/d6/btc-1h-staged-resume-status-v1-20260601.json"
DEFAULT_RATE_POLICY = "reports/d6/rate-limit-public-fetch-policy-v3-20260601.json"
DEFAULT_BACKLEARNING_V4 = "reports/d6/backlearning-scaffold-v4-20260601.json"


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


def _quality_counters(quality_summary: Dict[str, Any]) -> Dict[str, int]:
    summary = dict(quality_summary.get("summary") or quality_summary)
    return {
        "good_count": int(summary.get("good_count", 1)),
        "warning_count": int(summary.get("warning_count", 53)),
        "poor_count": int(summary.get("poor_count", 2)),
        "invalid_count": int(summary.get("invalid_count", 0)),
    }


def build_preflight_v9(
    *,
    quality_summary: Dict[str, Any],
    btc_4h_reference: Dict[str, Any],
    one_h_support: Dict[str, Any],
) -> Dict[str, Any]:
    counters = _quality_counters(quality_summary)
    return {
        "generated_at": now_iso(),
        "phase": "D6_v21_multisource_readiness",
        "report_name": "24h_live_test_preflight_runner_v9",
        "status": "24h_live_test_preflight_v9_blocked",
        "scope": "btc_usdc_only_research_readiness_preview",
        "dataset_quality": counters,
        "coinbase_primary_gaps": {
            "btc_usdc_1d": "good",
            "btc_usdc_4h": "known_gap_preview_only_raw_cache_still_imperfect",
            "btc_usdc_1h": "staged_gap_fill_started_one_350_candle_chunk_merged",
        },
        "secondary_reference": {
            "binance_btcusdc_4h_status": btc_4h_reference.get("status"),
            "classification": btc_4h_reference.get("binance_reference", {}).get("classification"),
            "normal_backtest_permission_changed": False,
        },
        "btc_1h_support": {
            "support_plan_status": one_h_support.get("status"),
            "max_reference_requests_next_scope": one_h_support.get("next_safe_scope", {}).get("max_reference_requests"),
            "auto_resume_allowed": False,
        },
        "blockers": [
            "primary_coinbase_dataset_quality_not_ready",
            "btc_usdc_1h_staged_gap_fill_incomplete",
            "normal_backtests_deferred",
            "future_live_lifecycle_ack_required_before_any_live_run",
        ],
        "no_go_boundaries": [
            "no_live_submit",
            "no_cancel_replace_reprice",
            "no_state_write",
            "no_external_candle_as_coinbase_candle",
            "no_normal_backtest_release_from_secondary_reference",
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


def build_master_packet_v21(
    *,
    quality_summary: Dict[str, Any],
    known_gap_preview: Dict[str, Any],
    one_h_pilot: Dict[str, Any],
    resume_status: Dict[str, Any],
    multi_source_policy: Dict[str, Any],
    btc_4h_reference: Dict[str, Any],
    backlearning_v5: Dict[str, Any],
) -> Dict[str, Any]:
    counters = _quality_counters(quality_summary)
    reference_class = btc_4h_reference.get("binance_reference", {}).get("classification")
    return {
        "generated_at": now_iso(),
        "phase": "D6_v21_multisource_readiness",
        "report_name": "24h_readiness_master_packet_v21",
        "status": "24h_readiness_v21_not_ready",
        "btc_usdc_only_24h_readiness": {
            "closer_than_v19_v20": True,
            "reason": "secondary_reference_governance_and_btc_4h_cross_source_diagnostic_are_now_explicit",
            "ready_for_24h_live_run": False,
            "primary_blockers": [
                "btc_usdc_1h_staged_gap_fill_incomplete",
                "dataset_quality_warning_and_poor_counts_remain",
                "normal_backtests_deferred",
                "future_operator_ack_required_for_any_live_run",
            ],
        },
        "staged_non_btc_readiness": {
            "status": "blocked",
            "reason": "btc_usdc_only_path_not_ready_and_non_btc_quality_warnings_remain",
        },
        "all_ticker_readiness": {
            "status": "blocked",
            "reason": "multi_ticker_quality_and_lifecycle_evidence_not_ready",
        },
        "dataset_quality": counters,
        "coinbase_gap_state": {
            "btc_usdc_1d": "good",
            "btc_usdc_4h": {
                "known_gap_preview_status": known_gap_preview.get("status"),
                "gap_class": known_gap_preview.get("gap_class"),
                "raw_cache_mutated": False,
                "missing_expected_start": 1761408000,
            },
            "btc_usdc_1h": {
                "pilot_status": one_h_pilot.get("status"),
                "resume_next_scope": resume_status.get("next_pending_scope"),
                "auto_resume_allowed": False,
            },
        },
        "secondary_reference_state": {
            "policy_status": multi_source_policy.get("status"),
            "binance_btcusdc_4h_reference_classification": reference_class,
            "binance_reference_available": reference_class == "external_reference_available",
            "binance_reference_can_repair_coinbase_cache": False,
        },
        "backtest_decision": {
            "normal_backtests": "deferred",
            "exploratory_cross_venue_analysis_allowed": bool(
                backlearning_v5.get("quality_gates", {}).get("exploratory_cross_venue_gate", {}).get("allowed")
            ),
            "parameter_evidence_created": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "parameter_values_changed": False,
            "learning_to_execution_enabled": False,
        },
        "remaining_data_quality_blockers": [
            "btc_usdc_1h_staged_gap_fill_not_complete",
            "coinbase_btc_usdc_4h_known_gap_is_preview_annotation_only",
            "aggregate_dataset_quality_remains_warning_or_poor",
        ],
        "remaining_backlearning_blockers": [
            "normal_backtest_gate_requires_primary_coinbase_quality",
            "walk_forward_oos_trial_accounting_not_executed",
            "fill_realism_not_bound_to_live_comparison",
        ],
        "remaining_live_lifecycle_blockers": [
            "separate_operator_ack_required_before_24h_live_test",
            "preflight_telemetry_plan_still_research_only",
            "no_live_lifecycle_action_authorized",
        ],
        "required_future_acks": [
            "explicit_24h_live_test_start_ack_after_preflight_pass",
            "explicit_lifecycle_apply_ack_for_any_future_local_apply",
        ],
        "no_go_boundaries": [
            "no_live_submit",
            "no_cancel_replace_reprice",
            "no_state_write",
            "no_config_or_parameter_mutation",
            "no_coinbase_account_or_order_endpoint",
            "no_binance_account_or_order_endpoint",
            "no_external_candle_as_coinbase_candle",
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


def build_research_index_v21(*, outputs: Iterable[str], master: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_v21_multisource_readiness",
        "report_name": "research_readiness_index_v21",
        "status": "research_readiness_index_v21_ready",
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
    parser = argparse.ArgumentParser(description="Build D.6 v21 multi-source readiness reports.")
    parser.add_argument("--quality-summary", default=DEFAULT_QUALITY)
    parser.add_argument("--master-v19-v20", default=DEFAULT_MASTER)
    parser.add_argument("--known-gap-preview", default=DEFAULT_KNOWN_GAP)
    parser.add_argument("--one-h-pilot", default=DEFAULT_1H_PILOT)
    parser.add_argument("--resume-status", default=DEFAULT_RESUME)
    parser.add_argument("--rate-policy", default=DEFAULT_RATE_POLICY)
    parser.add_argument("--backlearning-v4", default=DEFAULT_BACKLEARNING_V4)
    parser.add_argument("--candidate-root", default="/tmp/d6_binance_public_klines_v21")
    parser.add_argument("--fetch-binance-4h", action="store_true")
    args = parser.parse_args()

    source_paths = [
        args.quality_summary,
        args.master_v19_v20,
        args.known_gap_preview,
        args.one_h_pilot,
        args.resume_status,
        args.rate_policy,
        args.backlearning_v4,
    ]
    quality = _load_report_content(args.quality_summary)
    known_gap = _load_report_content(args.known_gap_preview)
    one_h_pilot = _load_report_content(args.one_h_pilot)
    resume = _load_report_content(args.resume_status)

    multi_source_policy = build_multi_source_candle_policy_v1()
    plan = build_binance_klines_plan(
        mapped_coinbase_product="BTC-USDC",
        symbol="BTCUSDC",
        timeframe="4H",
        start=1761408000,
        end_exclusive=1761422400,
        candidate_root=args.candidate_root,
        run_id="binance-btcusdc-4h-gap-reference-v21",
        limit=1,
        policy=BinanceRateLimitPolicy(max_requests_per_run=1, max_requests_per_minute=6),
    )
    fetch_result = execute_binance_klines_fetch(plan=plan) if args.fetch_binance_4h else plan
    btc_4h_reference = build_btc_4h_gap_reference_report(fetch_result=fetch_result if args.fetch_binance_4h else None)
    one_h_support = build_btc_1h_cross_source_gap_support_plan()
    backlearning_v5 = build_backlearning_multisource_scaffold_v5(
        quality_summary=quality,
        multi_source_policy=multi_source_policy,
        btc_4h_reference=btc_4h_reference,
    )
    preflight = build_preflight_v9(
        quality_summary=quality,
        btc_4h_reference=btc_4h_reference,
        one_h_support=one_h_support,
    )
    master = build_master_packet_v21(
        quality_summary=quality,
        known_gap_preview=known_gap,
        one_h_pilot=one_h_pilot,
        resume_status=resume,
        multi_source_policy=multi_source_policy,
        btc_4h_reference=btc_4h_reference,
        backlearning_v5=backlearning_v5,
    )

    outputs = []
    for report_type, content, stem in [
        ("multi_source_candle_policy_v1", multi_source_policy, "multi-source-candle-policy-v1-20260601"),
        ("binance_btcusdc_4h_gap_reference_v1", btc_4h_reference, "binance-btcusdc-4h-gap-reference-v1-20260601"),
        ("btc_1h_cross_source_gap_support_plan_v1", one_h_support, "btc-1h-cross-source-gap-support-plan-v1-20260601"),
        ("backlearning_multisource_scaffold_v5", backlearning_v5, "backlearning-multisource-scaffold-v5-20260601"),
        ("24h_live_test_preflight_runner_v9", preflight, "24h-live-test-preflight-runner-v9-20260601"),
        ("24h_readiness_master_packet_v21", master, "24h-readiness-master-packet-v21-20260601"),
    ]:
        outputs.extend(_write_pair(report_type, content, stem, source_paths=source_paths))

    research_index = build_research_index_v21(outputs=outputs, master=master)
    outputs.extend(
        _write_pair(
            "research_readiness_index_v21",
            research_index,
            "research-readiness-index-v21-20260601",
            source_paths=[*source_paths, *outputs],
        )
    )
    print(json.dumps({"status": "v21_reports_written", "fetch_binance_4h": args.fetch_binance_4h, "outputs": outputs}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
