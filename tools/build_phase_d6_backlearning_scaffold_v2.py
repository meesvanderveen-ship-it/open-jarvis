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

from bot.phase_d6_backlearning_scaffold_v2 import (  # noqa: E402
    build_backlearning_scaffold_v2,
    build_open_source_backlearning_architecture_v2,
    safety_flags,
)
from bot.phase_d6_candidate_coverage_validator import validate_candidate_coverage  # noqa: E402
from bot.phase_d6_coinbase_candle_ingest import assert_research_path  # noqa: E402
from bot.phase_d6_data_coverage import TIMEFRAME_SPECS  # noqa: E402
from bot.phase_d6_gap_aware_candle_planner import build_post_gap_fill_quality_summary, discover_candle_files  # noqa: E402
from bot.phase_d6_metrics import now_iso  # noqa: E402
from bot.phase_d6_rate_limited_public_fetch import (  # noqa: E402
    RateLimitPolicy,
    build_rate_limited_fetch_plan,
    execute_rate_limited_fetch,
)
from bot.phase_d6_report_bundle_writer import build_phase_d6_report_bundle, write_phase_d6_report_bundle  # noqa: E402
from bot.phase_d6_staged_gap_fill import build_staged_gap_fill_plan  # noqa: E402
from bot.phase_d6_tail_candle_refresh import merge_tail_refresh_result  # noqa: E402


BTC_4H_CANDLES = "research_data/coinbase/candles/product=BTC-USDC/timeframe=4H/study_window=3y.json"
PREVIOUS_4H_CANDIDATE = "/tmp/d6_staged_btc_1h_gap_fill_20260601_v15/product=BTC-USDC/timeframe=4H/BTCUSDC-4H-gap01.json"
MISSING_4H_START = 1761408000


def _load_report_content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(Path(path).read_text(encoding="utf-8"))
    content = loaded.get("content") if isinstance(loaded, dict) else None
    return dict(content) if isinstance(content, dict) else dict(loaded)


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _dedup_sort(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_start = {}
    for row in rows:
        try:
            by_start[int(row["start"])] = dict(row)
        except Exception:
            continue
    return [by_start[start] for start in sorted(by_start)]


def _write_candidate(path: str | Path, rows: List[Dict[str, Any]]) -> None:
    safe = assert_research_path(path)
    safe.parent.mkdir(parents=True, exist_ok=True)
    safe.write_text(json.dumps(_dedup_sort(rows), indent=2, sort_keys=True) + "\n", encoding="utf-8")


def build_btc_4h_surgical_diagnostic(*, fetch_result: Dict[str, Any] | None, merge: bool) -> Dict[str, Any]:
    previous_rows = _load_rows(PREVIOUS_4H_CANDIDATE)
    missing_start = MISSING_4H_START
    step = TIMEFRAME_SPECS["4H"].seconds
    candidate_root = "/tmp/d6_btc_4h_surgical_gap_20260601_v16"
    single_candidate = f"{candidate_root}/product=BTC-USDC/timeframe=4H/BTCUSDC-4H-missing-{missing_start}.json"
    combined_candidate = f"{candidate_root}/product=BTC-USDC/timeframe=4H/BTCUSDC-4H-gap01-combined.json"
    chunk = {"chunk_index": 0, "start": missing_start, "end_exclusive": missing_start + step, "coinbase_limit": 1}
    plan = build_rate_limited_fetch_plan(
        ticker="BTC-USDC",
        timeframe="4H",
        chunks=[chunk],
        candidate_root=candidate_root,
        run_id=f"BTCUSDC-4H-missing-{missing_start}",
        policy=RateLimitPolicy(max_requests_per_minute=6, min_delay_seconds=1.0, max_retries_per_chunk=2, retry_budget_total=2),
    )
    blockers: List[str] = []
    classification = "dry_run_only"
    validation: Dict[str, Any] | None = None
    merge_result: Dict[str, Any] | None = None
    if not previous_rows:
        blockers.append("previous_4h_candidate_unavailable")
    if fetch_result:
        single_rows = _load_rows(fetch_result.get("candidate_output_path") or single_candidate)
        _write_candidate(combined_candidate, [*previous_rows, *single_rows])
        validation = validate_candidate_coverage(
            candidate_path=combined_candidate,
            existing_path=BTC_4H_CANDLES,
            product_id="BTC-USDC",
            timeframe="4H",
            gap_start=1725912000,
            gap_end_exclusive=1775246400,
        )
        if validation.get("validator_pass"):
            classification = "chunk_window_hole_recovered_by_surgical_fetch"
            if merge:
                merge_result = merge_tail_refresh_result(
                    fetch_result={
                        "entries": [
                            {
                                "ticker": "BTC-USDC",
                                "timeframe": "4H",
                                "candidate_output_path": combined_candidate,
                                "existing_cache_path": BTC_4H_CANDLES,
                            }
                        ]
                    }
                )
        else:
            classification = "known_exchange_data_hole_or_unresolved_candidate_gap"
            blockers.extend(list(validation.get("blockers") or []))
    return {
        "generated_at": now_iso(),
        "phase": "D6_btc_4h_surgical_gap_diagnostic_v1",
        "report_name": "btc_4h_surgical_gap_diagnostic_v1",
        "status": "btc_4h_surgical_gap_diagnostic_ready" if not blockers else "btc_4h_surgical_gap_diagnostic_blocked",
        "missing_expected_start": missing_start,
        "missing_expected_start_iso": "2025-10-25T16:00:00Z",
        "previous_candidate_path": PREVIOUS_4H_CANDIDATE,
        "previous_candidate_count": len({int(row["start"]) for row in previous_rows if "start" in row}),
        "rate_limited_fetch_plan": plan,
        "rate_limited_fetch_result": fetch_result,
        "combined_candidate_path": combined_candidate,
        "candidate_validation": validation,
        "classification": classification,
        "merge_result": merge_result,
        "merge_executed": bool(merge_result),
        "updated_file_count": (merge_result or {}).get("updated_file_count", 0),
        "blockers": blockers,
        **safety_flags(),
        "coinbase_public_market_data_call_performed": bool((fetch_result or {}).get("coinbase_public_market_data_call_performed")),
        "coinbase_public_market_data_call_count": int((fetch_result or {}).get("coinbase_public_market_data_call_count") or 0),
        "state_write_performed": False,
    }


def build_btc_1h_staged_policy(*, staged_plan: Dict[str, Any], diagnostic: Dict[str, Any]) -> Dict[str, Any]:
    one_h = [row for row in staged_plan.get("subruns") or [] if row.get("timeframe") == "1H"]
    four_h_resolved = bool(diagnostic.get("merge_executed"))
    return {
        "generated_at": now_iso(),
        "phase": "D6_btc_1h_staged_gap_policy_v1",
        "report_name": "btc_1h_staged_gap_policy_v1",
        "status": "btc_1h_staged_gap_policy_ready",
        "subrun_count": len(one_h),
        "subruns": [
            {
                "subrun_id": row["subrun_id"],
                "start": row["subrange_start_iso"],
                "end_exclusive": row["subrange_end_exclusive_iso"],
                "expected_candle_count": row["expected_candle_count"],
                "chunks_requested": row["chunks_requested"],
            }
            for row in one_h
        ],
        "rate_limit_policy_per_subrun": {
            "max_requests_per_minute": 6,
            "min_delay_seconds": 1.0,
            "max_retries_per_chunk": 2,
            "retry_budget_total": 4,
            "partial_candidate_quarantine": True,
        },
        "resume_policy": "execute_next_pending_subrun_only_after_previous_subrun_exact_validation_pass_or_explicit_deferral",
        "merge_policy": "merge_only_after_exact_candidate_coverage_pass",
        "v16_execution_decision": "defer_1h_until_4h_resolved" if not four_h_resolved else "eligible_for_one_next_bounded_subrun_in_future_prompt",
        "four_h_resolved_in_v16": four_h_resolved,
        **safety_flags(),
        "state_write_performed": False,
    }


def build_preflight_v6(*, quality_summary: Dict[str, Any], diagnostic: Dict[str, Any], backlearning: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_24h_live_test_preflight_runner_v6",
        "report_name": "24h_live_test_preflight_runner_v6",
        "status": "24h_live_test_preflight_runner_v6_ready",
        "preflight_result": "blocked_for_remaining_dataset_quality_and_live_ack_review",
        "quality_summary": quality_summary.get("summary"),
        "btc_4h_diagnostic_status": diagnostic.get("status"),
        "backlearning_status": backlearning.get("status"),
        "required_future_acks": [
            "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        ],
        "no_go_boundaries": [
            "no_live_submit_without_exact_ack",
            "no_state_write_without_exact_ack",
            "no_parameter_mutation",
            "no_learning_to_execution",
            "no_account_or_order_endpoint_in_research_fetch",
        ],
        **safety_flags(),
        "state_write_performed": False,
    }


def build_master_v16(
    *,
    architecture: Dict[str, Any],
    diagnostic: Dict[str, Any],
    one_h_policy: Dict[str, Any],
    backlearning: Dict[str, Any],
    quality_summary: Dict[str, Any],
    preflight: Dict[str, Any],
) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    return {
        "generated_at": now_iso(),
        "phase": "D6_24h_readiness_master_packet_v16",
        "report_name": "24h_readiness_master_packet_v16",
        "status": "24h_readiness_master_packet_v16_ready",
        "v16_resolved": [
            "open_source_backlearning_architecture_v2",
            "rate_limited_public_fetch_wrapper",
            "btc_4h_surgical_diagnostic",
            "btc_1h_staged_policy_refresh",
            "backlearning_scaffold_v2",
        ],
        "quality_summary": summary,
        "btc_4h_diagnostic": {
            "status": diagnostic.get("status"),
            "classification": diagnostic.get("classification"),
            "merge_executed": diagnostic.get("merge_executed"),
            "updated_file_count": diagnostic.get("updated_file_count"),
        },
        "btc_1h_policy": {
            "subrun_count": one_h_policy.get("subrun_count"),
            "v16_execution_decision": one_h_policy.get("v16_execution_decision"),
        },
        "backlearning": {
            "status": backlearning.get("status"),
            "blockers": backlearning.get("blockers"),
            "learning_to_execution_enabled": False,
        },
        "btc_usdc_only_24h_status": "blocked_until_dataset_quality_and_exact_live_acks",
        "staged_non_btc_status": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
        "all_ticker_24h_status": "blocked",
        "remaining_data_quality_blockers": [
            "btc_usdc_1h_gap_pending",
            "stale_last_candle_warnings_for_non_btc_rows",
        ],
        "remaining_backlearning_blockers": backlearning.get("blockers"),
        "remaining_live_lifecycle_blockers": [
            "future_live_test_exact_acks_missing",
            "no_current_manageable_position",
            "non_btc_live_lifecycle_evidence_missing",
        ],
        "required_future_acks": preflight.get("required_future_acks"),
        "no_go_boundaries": preflight.get("no_go_boundaries"),
        "source_architecture_status": architecture.get("status"),
        **safety_flags(),
        "state_write_performed": False,
    }


def _write(report_type: str, content: Dict[str, Any], stem: str, date_stamp: str, source_paths: List[str]) -> Dict[str, Any]:
    report = build_phase_d6_report_bundle(report_type=report_type, content=content, source_paths=source_paths)
    json_path = f"reports/d6/{stem}-{date_stamp}.json"
    md_path = f"reports/d6/{stem}-{date_stamp}.md"
    result = write_phase_d6_report_bundle(report, json_path, metadata_sidecar=True)
    write_phase_d6_report_bundle(report, md_path, markdown=True)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build D.6 backlearning scaffold v2 and v16 readiness reports.")
    parser.add_argument("--date-stamp", default="20260601")
    parser.add_argument("--fetch-4h", action="store_true")
    parser.add_argument("--no-merge", action="store_true")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    quality_before = _load_report_content("reports/d6/post-staged-gap-fill-dataset-quality-summary-v15-20260601.json")
    architecture = build_open_source_backlearning_architecture_v2()
    fetch_result = None
    if args.fetch_4h:
        from coinbase_client import CoinbaseClient  # explicit bounded public fetch mode only

        diagnostic_plan = build_btc_4h_surgical_diagnostic(fetch_result=None, merge=False)["rate_limited_fetch_plan"]
        fetch_result = execute_rate_limited_fetch(plan=diagnostic_plan, client=CoinbaseClient())
    diagnostic = build_btc_4h_surgical_diagnostic(fetch_result=fetch_result, merge=not args.no_merge)
    quality_after = build_post_gap_fill_quality_summary(candle_paths=discover_candle_files(), as_of="2026-06-01T00:00:00Z") | {
        "report_name": "post_v16_dataset_quality_summary",
        "status": "post_v16_dataset_quality_summary_ready",
    }
    command_plan = _load_report_content("reports/d6/gap-fill-command-plan-v1-20260601.json")
    staged_plan = build_staged_gap_fill_plan(
        command_plan=command_plan,
        candidate_root="/tmp/d6_staged_btc_1h_gap_fill_20260601_v16",
    )
    one_h_policy = build_btc_1h_staged_policy(staged_plan=staged_plan, diagnostic=diagnostic)
    backlearning = build_backlearning_scaffold_v2(quality_summary=quality_after)
    preflight = build_preflight_v6(quality_summary=quality_after, diagnostic=diagnostic, backlearning=backlearning)
    master = build_master_v16(
        architecture=architecture,
        diagnostic=diagnostic,
        one_h_policy=one_h_policy,
        backlearning=backlearning,
        quality_summary=quality_after,
        preflight=preflight,
    )
    source_paths = [
        "bot/config.py",
        "reports/d6/staged-btc-1h-gap-fill-plan-v1-20260601.json",
        "reports/d6/staged-btc-1h-gap-fill-result-v1-20260601.json",
        "reports/d6/post-staged-gap-fill-dataset-quality-summary-v15-20260601.json",
        "reports/d6/open-source-inspiration-gap-aware-refresh-v1-20260601.json",
        BTC_4H_CANDLES,
    ]
    write_results = [
        _write("d6_open_source_backlearning_architecture_v2", architecture, "open-source-backlearning-architecture-v2", args.date_stamp, source_paths),
        _write("d6_btc_4h_surgical_gap_diagnostic_v1", diagnostic, "btc-4h-surgical-gap-diagnostic-v1", args.date_stamp, source_paths),
        _write("d6_btc_1h_staged_gap_policy_v1", one_h_policy, "btc-1h-staged-gap-policy-v1", args.date_stamp, source_paths),
        _write("d6_backlearning_scaffold_v2", backlearning, "backlearning-scaffold-v2", args.date_stamp, source_paths),
        _write("d6_24h_live_test_preflight_runner_v6", preflight, "24h-live-test-preflight-runner-v6", args.date_stamp, source_paths),
        _write("d6_24h_readiness_master_packet_v16", master, "24h-readiness-master-packet-v16", args.date_stamp, source_paths),
    ]
    out = {
        "quality_before": quality_before.get("summary"),
        "quality_after": quality_after.get("summary"),
        "architecture": architecture,
        "diagnostic": diagnostic,
        "one_h_policy": one_h_policy,
        "backlearning": backlearning,
        "preflight": preflight,
        "master": master,
        "write_results": write_results,
    }
    print(json.dumps(out, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not diagnostic.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
