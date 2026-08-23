#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_bounded_coverage_expansion import build_coverage_refresh_v2, build_quality_summary_v2  # noqa: E402
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402
from bot.phase_d6_tail_candle_refresh import build_tail_refresh_plan, safety_flags  # noqa: E402


def _candle_paths() -> List[str]:
    root = PROJECT_ROOT / "research_data/coinbase/candles"
    return sorted(str(path.relative_to(PROJECT_ROOT)) for path in root.glob("product=*/timeframe=*/study_window=*.json"))


def _candidate_paths(candidate_root: str | Path) -> List[Path]:
    return sorted(Path(candidate_root).glob("product=*/timeframe=*/study_window=3y.json"))


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _tail_result(*, candidate_root: str, public_call_count: int, max_chunks: int) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for candidate in _candidate_paths(candidate_root):
        product = candidate.parent.parent.name.removeprefix("product=")
        timeframe = candidate.parent.name.removeprefix("timeframe=")
        existing = Path("research_data/coinbase/candles") / f"product={product}" / f"timeframe={timeframe}" / "study_window=3y.json"
        candidate_rows = _load_rows(candidate)
        existing_rows = _load_rows(existing)
        rows.append(
            {
                "ticker": product,
                "timeframe": timeframe,
                "candidate_output_path": str(candidate),
                "existing_cache_path": str(existing),
                "candidate_count": len(candidate_rows),
                "after_count": len(existing_rows),
                "first_candidate_start": candidate_rows[0].get("start") if candidate_rows else None,
                "last_candidate_start": candidate_rows[-1].get("start") if candidate_rows else None,
            }
        )
    return {
        "phase": "D6_tail_aware_candle_refresh_v1",
        "report_name": "tail_aware_refresh_result_v1",
        "status": "tail_aware_refresh_result_ready",
        "candidate_root": candidate_root,
        "max_chunks_used": max_chunks,
        "coinbase_public_market_data_call_count": public_call_count,
        "updated_file_count": len(rows),
        "rows": rows,
        **safety_flags(),
        "coinbase_public_market_data_call_performed": bool(public_call_count),
    }


def _quality_counts(quality: Dict[str, Any]) -> Dict[str, Any]:
    rows = [dict(row) for row in quality.get("rows") or [] if isinstance(row, dict)]
    warning_counts: Dict[str, int] = {}
    quality_class_counts: Dict[str, int] = {}
    for row in rows:
        q = str(row.get("quality_class") or "unknown")
        quality_class_counts[q] = quality_class_counts.get(q, 0) + 1
        for warning in row.get("warnings") or []:
            key = str(warning)
            warning_counts[key] = warning_counts.get(key, 0) + 1
    return {
        "quality_class_counts": dict(sorted(quality_class_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
        "row_count": len(rows),
    }


def _btc_rows(quality: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [dict(row) for row in quality.get("rows") or [] if row.get("product_id") == "BTC-USDC"]


def _exploratory_refresh_v12(quality: Dict[str, Any]) -> Dict[str, Any]:
    counts = _quality_counts(quality)
    return {
        "phase": "D6_tail_aware_candle_refresh_v1",
        "report_name": "exploratory_only_backtest_readiness_refresh_v12",
        "status": "exploratory_only_backtest_readiness_refresh_v12_ready",
        "normal_backtests_deferred": True,
        "exploratory_backtests_deferred_after_tail_pilot": True,
        "reason": "tail_refresh_pilot_introduced_gap_warnings_for_btc_rows",
        "quality_counts": counts,
        "btc_usdc_quality_rows": _btc_rows(quality),
        "parameter_evidence_created": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "parameter_values_changed": False,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


def _preflight_v2(quality: Dict[str, Any]) -> Dict[str, Any]:
    counts = _quality_counts(quality)
    return {
        "phase": "D6_tail_aware_candle_refresh_v1",
        "report_name": "24h_live_test_preflight_runner_v2",
        "status": "24h_live_test_preflight_runner_v2_ready",
        "preflight_result": "blocked_for_research_quality_review",
        "reason": "btc_tail_refresh_pilot_created_gap_quality_warnings",
        "route_matrix": {
            "btc_usdc_only": "ack_gated_but_research_quality_warning_after_tail_pilot",
            "staged_non_btc_pilot": "blocked_until_separate_design",
            "all_ticker_24h": "blocked",
        },
        "quality_counts": counts,
        "required_future_acks": [
            "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        ],
        **safety_flags(),
    }


def _master_v12(tail_result: Dict[str, Any], quality: Dict[str, Any]) -> Dict[str, Any]:
    counts = _quality_counts(quality)
    return {
        "phase": "D6_tail_aware_candle_refresh_v1",
        "report_name": "24h_readiness_master_packet_v12",
        "status": "24h_readiness_master_packet_v12_ready",
        "tail_refresh_status": "btc_pilot_completed_do_not_expand_yet",
        "tail_refresh_updated_file_count": tail_result.get("updated_file_count"),
        "dataset_quality_status": "warning_only_with_btc_gap_warnings_after_tail_pilot",
        "quality_counts": counts,
        "btc_usdc_quality_rows": _btc_rows(quality),
        "btc_usdc_only_24h_status": "ack_gated_but_research_quality_warning_after_tail_pilot",
        "staged_non_btc_status": "blocked_until_separate_design",
        "all_ticker_24h_status": "blocked",
        "remaining_blockers": [
            "tail_refresh_gap_fill_design_needed",
            "dataset_quality_warning_or_poor_rows_present",
            "normal_backtests_not_run",
            "non_btc_live_lifecycle_evidence_missing",
            "future_live_test_exact_acks_missing",
        ],
        "next_safe_sprint": "build_gap_aware_tail_refresh_or_gap_fill_planner_before_more_fetch",
        "parameter_evidence_created": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "parameter_values_changed": False,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


def _write(*, report_type: str, content: Dict[str, Any], stem: str, date_stamp: str, source_paths: List[str]) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 tail refresh postprocess reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--as-of", default="2026-06-01T00:00:00Z")
    parser.add_argument("--candidate-root", required=True)
    parser.add_argument("--public-call-count", type=int, required=True)
    parser.add_argument("--max-chunks", type=int, required=True)
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    candle_paths = _candle_paths()
    config_text = Path("bot/config.py").read_text(encoding="utf-8")
    tool_plan = build_tail_refresh_plan(
        as_of=args.as_of,
        tickers=["BTC-USDC"],
        timeframes=["1D", "1H", "4H"],
        max_chunks=args.max_chunks,
        output_root=args.candidate_root,
    )
    tool_plan["status"] = "tail_aware_candle_refresh_tool_v1_ready"
    tail_result = _tail_result(
        candidate_root=args.candidate_root,
        public_call_count=args.public_call_count,
        max_chunks=args.max_chunks,
    )
    coverage = build_coverage_refresh_v2(config_text=config_text, candle_paths=candle_paths, as_of=args.as_of)
    coverage["report_name"] = "multi_ticker_dataset_coverage_plan_refresh_v12"
    coverage["status"] = "multi_ticker_dataset_coverage_plan_refresh_v12_ready"
    quality = build_quality_summary_v2(candle_paths=candle_paths, as_of=args.as_of)
    quality["report_name"] = "post_tail_refresh_dataset_quality_summary_v12"
    quality["status"] = "post_tail_refresh_dataset_quality_summary_v12_ready"
    exploratory = _exploratory_refresh_v12(quality)
    preflight = _preflight_v2(quality)
    master = _master_v12(tail_result, quality)
    source_paths = ["bot/config.py", *candle_paths]
    specs = [
        ("d6_tail_aware_candle_refresh_tool_v1", tool_plan, "tail-aware-candle-refresh-tool-v1"),
        ("d6_tail_aware_refresh_result_v1", tail_result, "tail-aware-refresh-result-v1"),
        ("d6_multi_ticker_dataset_coverage_plan_refresh_v12", coverage, "multi-ticker-dataset-coverage-plan-refresh-v12"),
        ("d6_post_tail_refresh_dataset_quality_summary_v12", quality, "post-tail-refresh-dataset-quality-summary-v12"),
        ("d6_exploratory_only_backtest_readiness_refresh_v12", exploratory, "exploratory-only-backtest-readiness-refresh-v12"),
        ("d6_24h_live_test_preflight_runner_v2", preflight, "24h-live-test-preflight-runner-v2"),
        ("d6_24h_readiness_master_packet_v12", master, "24h-readiness-master-packet-v12"),
    ]
    results = [
        _write(report_type=report_type, content=content, stem=stem, date_stamp=args.date_stamp, source_paths=source_paths)
        for report_type, content, stem in specs
    ]
    if args.json:
        print(json.dumps({"status": "tail_refresh_postprocess_reports_written", "results": results}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
