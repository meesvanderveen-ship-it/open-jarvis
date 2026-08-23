from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from bot.phase_d6_candidate_coverage_validator import filter_candidate_to_gap, safety_flags, validate_candidate_coverage
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_gap_aware_candle_planner import (
    DATA_FETCH_ACK,
    build_backtest_readiness_v13,
    build_post_gap_fill_quality_summary,
    build_preflight_v3,
    discover_candle_files,
)
from bot.phase_d6_metrics import now_iso
from bot.phase_d6_tail_candle_refresh import build_tail_refresh_plan, execute_tail_refresh, merge_tail_refresh_result


PHASE = "D6_btc_gap_fill_runner_v1"


def load_gap_fill_command_plan(path: str | Path) -> Dict[str, Any]:
    safe = assert_research_path(path)
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("gap_fill_command_plan_must_be_object")
    content = loaded.get("content")
    return content if isinstance(content, dict) else loaded


def select_btc_gap_rows(*, command_plan: Dict[str, Any], timeframes: Iterable[str] = ("1D", "4H")) -> List[Dict[str, Any]]:
    allowed = {str(tf).upper() for tf in timeframes}
    rows = []
    for row in command_plan.get("safe_rows") or []:
        if str(row.get("ticker") or "").upper() != "BTC-USDC":
            continue
        if str(row.get("timeframe") or "").upper() not in allowed:
            continue
        rows.append(dict(row))
    return sorted(rows, key=lambda row: int(row.get("missing_candle_count") or 0))


def build_btc_gap_fill_runner_plan(
    *,
    command_plan: Dict[str, Any],
    candidate_root: str | Path,
    timeframes: Iterable[str] = ("1D", "4H"),
) -> Dict[str, Any]:
    selected = select_btc_gap_rows(command_plan=command_plan, timeframes=timeframes)
    rows: List[Dict[str, Any]] = []
    for row in selected:
        plan = build_tail_refresh_plan(
            as_of=row["gap_end_exclusive_iso"],
            tickers=[row["ticker"]],
            timeframes=[row["timeframe"]],
            max_chunks=int(row["chunks_needed"]),
            output_root=candidate_root,
        )
        entry = dict(plan["entries"][0])
        filtered_path = (
            assert_research_path(candidate_root)
            / f"product={row['ticker']}"
            / f"timeframe={row['timeframe']}"
            / f"gap_start={row['gap_start']}_gap_end={row['gap_end_exclusive']}.json"
        )
        rows.append(
            {
                **row,
                "raw_candidate_output_path": entry["candidate_output_path"],
                "filtered_candidate_output_path": str(filtered_path),
                "tail_plan": plan,
                "dry_run_status": "planned_clean",
                "fetch_executed": False,
                "merge_executed": False,
            }
        )
    blocked_1h = [
        dict(row)
        for row in command_plan.get("blocked_rows") or []
        if str(row.get("ticker") or "").upper() == "BTC-USDC" and str(row.get("timeframe") or "").upper() == "1H"
    ]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_gap_fill_runner_v1",
        "status": "btc_gap_fill_runner_plan_ready",
        "required_ack": DATA_FETCH_ACK,
        "candidate_root": str(assert_research_path(candidate_root)),
        "selected_rows": rows,
        "selected_row_count": len(rows),
        "blocked_btc_1h_rows": blocked_1h,
        "fetch_executed": False,
        "merge_executed": False,
        "execution_order": [f"{row['ticker']}:{row['timeframe']}" for row in rows],
        **safety_flags(),
        "state_write_performed": False,
        "coinbase_public_market_data_call_performed": False,
    }


def execute_btc_gap_fill_runner(
    *,
    runner_plan: Dict[str, Any],
    client: Any,
    fetched_at: Any = None,
    merge: bool = True,
) -> Dict[str, Any]:
    if client is None:
        raise ValueError("btc_gap_fill_requires_read_only_coinbase_client")
    result_rows: List[Dict[str, Any]] = []
    public_calls = 0
    merge_count = 0
    fetch_errors: List[Dict[str, Any]] = []
    for row in runner_plan.get("selected_rows") or []:
        fetch_result = execute_tail_refresh(plan=row["tail_plan"], client=client, fetched_at=fetched_at)
        public_calls += int(fetch_result.get("coinbase_public_market_data_call_count") or 0)
        raw_entry = dict((fetch_result.get("entries") or [{}])[0])
        filter_result = filter_candidate_to_gap(
            raw_candidate_path=raw_entry["candidate_output_path"],
            filtered_candidate_path=row["filtered_candidate_output_path"],
            gap_start=int(row["gap_start"]),
            gap_end_exclusive=int(row["gap_end_exclusive"]),
            product_id=row["ticker"],
            timeframe=row["timeframe"],
        )
        validation = validate_candidate_coverage(
            candidate_path=row["filtered_candidate_output_path"],
            existing_path=row["candles_path"],
            product_id=row["ticker"],
            timeframe=row["timeframe"],
            gap_start=int(row["gap_start"]),
            gap_end_exclusive=int(row["gap_end_exclusive"]),
        )
        merge_result: Dict[str, Any] | None = None
        if merge and validation.get("validator_pass"):
            merge_result = merge_tail_refresh_result(
                fetch_result={
                    "entries": [
                        {
                            "ticker": row["ticker"],
                            "timeframe": row["timeframe"],
                            "candidate_output_path": row["filtered_candidate_output_path"],
                            "existing_cache_path": row["candles_path"],
                        }
                    ]
                }
            )
            merge_count += int(merge_result.get("updated_file_count") or 0)
        elif not validation.get("validator_pass"):
            fetch_errors.append(
                {
                    "ticker": row["ticker"],
                    "timeframe": row["timeframe"],
                    "blockers": list(validation.get("blockers") or []),
                }
            )
        result_rows.append(
            {
                "ticker": row["ticker"],
                "timeframe": row["timeframe"],
                "gap_start": row["gap_start"],
                "gap_end_exclusive": row["gap_end_exclusive"],
                "chunks_needed": row["chunks_needed"],
                "raw_candidate_output_path": raw_entry.get("candidate_output_path"),
                "filtered_candidate_output_path": row["filtered_candidate_output_path"],
                "raw_candidate_count": raw_entry.get("candle_count"),
                "filtered_candidate_count": filter_result.get("filtered_count"),
                "outside_gap_count": filter_result.get("outside_gap_count"),
                "validation": validation,
                "merge_result": merge_result,
                "merge_executed": bool(merge_result),
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_gap_fill_result_v1",
        "status": "btc_gap_fill_result_ready" if not fetch_errors else "btc_gap_fill_result_blocked",
        "candidate_root": runner_plan.get("candidate_root"),
        "selected_row_count": len(runner_plan.get("selected_rows") or []),
        "result_rows": result_rows,
        "fetch_errors": fetch_errors,
        "coinbase_public_market_data_call_count": public_calls,
        "coinbase_public_market_data_call_performed": bool(public_calls),
        "fetch_executed": True,
        "merge_executed": bool(merge_count),
        "updated_file_count": merge_count,
        **safety_flags(),
        "state_write_performed": False,
    }


def build_candidate_validator_summary(*, runner_result: Dict[str, Any] | None, runner_plan: Dict[str, Any]) -> Dict[str, Any]:
    rows = []
    if runner_result:
        for row in runner_result.get("result_rows") or []:
            validation = dict(row.get("validation") or {})
            rows.append(
                {
                    "ticker": row.get("ticker"),
                    "timeframe": row.get("timeframe"),
                    "validator_pass": validation.get("validator_pass"),
                    "blockers": list(validation.get("blockers") or []),
                    "expected_count": validation.get("expected_count"),
                    "candidate_count": validation.get("candidate_count"),
                    "unexpected_count": validation.get("unexpected_count"),
                    "missing_expected_count": validation.get("missing_expected_count"),
                    "existing_overlap_count": validation.get("existing_overlap_count"),
                }
            )
    else:
        for row in runner_plan.get("selected_rows") or []:
            rows.append(
                {
                    "ticker": row.get("ticker"),
                    "timeframe": row.get("timeframe"),
                    "validator_pass": None,
                    "blockers": ["not_fetched_yet"],
                    "expected_count": row.get("missing_candle_count"),
                }
            )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "candidate_coverage_validator_v1",
        "status": "candidate_coverage_validator_v1_ready",
        "rows": rows,
        "pass_count": sum(1 for row in rows if row.get("validator_pass") is True),
        "block_count": sum(1 for row in rows if row.get("validator_pass") is False),
        "pending_count": sum(1 for row in rows if row.get("validator_pass") is None),
        **safety_flags(),
        "state_write_performed": False,
    }


def build_quality_summary_v14(*, as_of: str = "2026-06-01T00:00:00Z") -> Dict[str, Any]:
    return build_post_gap_fill_quality_summary(candle_paths=discover_candle_files(), as_of=as_of) | {
        "report_name": "post_btc_gap_fill_dataset_quality_summary_v14",
        "status": "post_btc_gap_fill_dataset_quality_summary_v14_ready",
    }


def build_backtest_readiness_v14(*, quality_summary: Dict[str, Any], runner_result: Dict[str, Any] | None) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "exploratory_only_backtest_readiness_refresh_v14",
        "status": "exploratory_only_backtest_readiness_refresh_v14_ready",
        "normal_backtests_deferred": True,
        "exploratory_backtests_deferred_in_v14": True,
        "reason": "dataset_quality_still_not_good_after_btc_gap_fill" if summary.get("good_count") != summary.get("quality_report_count") else "normal_backtest_review_still_separate",
        "quality_summary": summary,
        "btc_gap_fill_updated_file_count": (runner_result or {}).get("updated_file_count", 0),
        "parameter_evidence_created": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "parameter_values_changed": False,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


def build_preflight_v4(*, quality_summary: Dict[str, Any], runner_result: Dict[str, Any] | None) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_live_test_preflight_runner_v4",
        "status": "24h_live_test_preflight_runner_v4_ready",
        "preflight_result": "blocked_for_remaining_dataset_quality_review",
        "route_matrix": {
            "btc_usdc_only": "ack_gated_after_remaining_gap_quality_review",
            "staged_non_btc_pilot": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
            "all_ticker_24h": "blocked",
        },
        "quality_summary": summary,
        "btc_gap_fill_status": (runner_result or {}).get("status", "not_run"),
        "required_future_acks": [
            "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        ],
        **safety_flags(),
    }


def build_master_packet_v14(
    *,
    validator_summary: Dict[str, Any],
    runner_plan: Dict[str, Any],
    runner_result: Dict[str, Any] | None,
    quality_summary: Dict[str, Any],
    backtest_readiness: Dict[str, Any],
    preflight_v4: Dict[str, Any],
) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    blocked_1h = list(runner_plan.get("blocked_btc_1h_rows") or [])
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v14",
        "status": "24h_readiness_master_packet_v14_ready",
        "v14_resolved": [
            "candidate_coverage_validator_built",
            "btc_1d_4h_smallest_first_gap_fill_runner_built",
            "btc_1d_4h_candidates_validated_before_merge" if validator_summary.get("pass_count") else "btc_1d_4h_candidate_validation_pending",
        ],
        "btc_gap_fill_updated_file_count": (runner_result or {}).get("updated_file_count", 0),
        "btc_gap_fill_status": (runner_result or {}).get("status", "not_run"),
        "btc_1h_staged_plan": {
            "status": "still_blocked_by_large_gap",
            "rows": blocked_1h,
            "next_step": "split_1h_gap_into_multiple_bounded_subruns_or_raise_explicit_chunk_bound_in_a_separate_research_task",
        },
        "quality_summary": summary,
        "backtest_status": backtest_readiness.get("status"),
        "btc_usdc_only_24h_status": "ack_gated_after_remaining_gap_quality_review",
        "staged_non_btc_status": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
        "all_ticker_24h_status": "blocked",
        "remaining_blockers": [
            "btc_usdc_1h_gap_still_unfilled",
            "dataset_quality_warning_or_poor_rows_present",
            "normal_backtests_not_run",
            "non_btc_live_lifecycle_evidence_missing",
            "future_live_test_exact_acks_missing",
        ],
        "preflight_v4_result": preflight_v4.get("preflight_result"),
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "PHASE",
    "build_backtest_readiness_v14",
    "build_btc_gap_fill_runner_plan",
    "build_candidate_validator_summary",
    "build_master_packet_v14",
    "build_preflight_v4",
    "build_quality_summary_v14",
    "execute_btc_gap_fill_runner",
    "load_gap_fill_command_plan",
    "select_btc_gap_rows",
]
