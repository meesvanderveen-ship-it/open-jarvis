from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

from bot.phase_d6_candidate_coverage_validator import safety_flags, validate_candidate_coverage
from bot.phase_d6_coinbase_candle_ingest import assert_research_path, normalize_candles
from bot.phase_d6_data_coverage import D6_MAX_CANDLES_PER_REQUEST, TIMEFRAME_SPECS, normalize_timeframes, parse_as_of
from bot.phase_d6_gap_aware_candle_planner import DATA_FETCH_ACK, build_post_gap_fill_quality_summary, discover_candle_files
from bot.phase_d6_metrics import now_iso
from bot.phase_d6_tail_candle_refresh import merge_tail_refresh_result


PHASE = "D6_staged_gap_fill_v1"
DEFAULT_SUBRUN_MAX_CHUNKS = 10
DEFAULT_EXECUTION_MAX_CHUNKS = 25


def _iso_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ceil_div(numerator: int, denominator: int) -> int:
    return int((Decimal(numerator) / Decimal(denominator)).to_integral_value(rounding=ROUND_CEILING))


def _load_json_object(path: str | Path) -> Dict[str, Any]:
    safe = assert_research_path(path)
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(loaded, dict):
        raise ValueError("expected_json_object")
    content = loaded.get("content")
    return dict(content) if isinstance(content, dict) else dict(loaded)


def _expected_count(*, start: int, end_exclusive: int, step_seconds: int) -> int:
    if end_exclusive <= start:
        return 0
    return (int(end_exclusive) - int(start)) // int(step_seconds)


def _chunk_ranges(*, gap_start: int, gap_end_exclusive: int, timeframe: str) -> List[Dict[str, Any]]:
    timeframe_n = normalize_timeframes([timeframe])[0]
    step = TIMEFRAME_SPECS[timeframe_n].seconds
    ranges: List[Dict[str, Any]] = []
    cursor = int(gap_start)
    index = 0
    while cursor < int(gap_end_exclusive):
        end = min(cursor + (step * D6_MAX_CANDLES_PER_REQUEST), int(gap_end_exclusive))
        ranges.append(
            {
                "chunk_index": index,
                "start": cursor,
                "end_exclusive": end,
                "start_iso": _iso_from_ts(cursor),
                "end_exclusive_iso": _iso_from_ts(end),
                "expected_candle_count": _expected_count(start=cursor, end_exclusive=end, step_seconds=step),
                "coinbase_limit": D6_MAX_CANDLES_PER_REQUEST,
            }
        )
        cursor = end
        index += 1
    return ranges


def _candidate_path(*, candidate_root: str | Path, ticker: str, timeframe: str, subrun_id: str) -> Path:
    root = assert_research_path(candidate_root)
    return root / f"product={ticker}" / f"timeframe={timeframe}" / f"{subrun_id}.json"


def _select_gap_rows(command_plan: Dict[str, Any], *, tickers: Iterable[str], timeframes: Iterable[str]) -> List[Dict[str, Any]]:
    ticker_set = {str(t).upper() for t in tickers}
    timeframe_set = {normalize_timeframes([tf])[0] for tf in timeframes}
    rows = [dict(row) for row in command_plan.get("safe_rows") or []]
    rows.extend(dict(row) for row in command_plan.get("blocked_rows") or [])
    out: List[Dict[str, Any]] = []
    seen: Set[tuple[str, str, int, int]] = set()
    for row in rows:
        ticker = str(row.get("ticker") or "").upper()
        timeframe = str(row.get("timeframe") or "").upper()
        if ticker not in ticker_set or timeframe not in timeframe_set:
            continue
        key = (ticker, timeframe, int(row["gap_start"]), int(row["gap_end_exclusive"]))
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return sorted(out, key=lambda row: (str(row.get("ticker")), str(row.get("timeframe")), int(row.get("gap_start") or 0)))


def build_staged_gap_fill_plan(
    *,
    command_plan: Dict[str, Any],
    candidate_root: str | Path,
    tickers: Iterable[str] = ("BTC-USDC",),
    timeframes: Iterable[str] = ("1D", "4H", "1H"),
    subrun_max_chunks: int = DEFAULT_SUBRUN_MAX_CHUNKS,
    execution_max_chunks: int = DEFAULT_EXECUTION_MAX_CHUNKS,
) -> Dict[str, Any]:
    if int(subrun_max_chunks) <= 0:
        raise ValueError("subrun_max_chunks_must_be_positive")
    if int(execution_max_chunks) <= 0:
        raise ValueError("execution_max_chunks_must_be_positive")
    rows = _select_gap_rows(command_plan, tickers=tickers, timeframes=timeframes)
    subruns: List[Dict[str, Any]] = []
    for row in rows:
        timeframe = normalize_timeframes([row["timeframe"]])[0]
        step = TIMEFRAME_SPECS[timeframe].seconds
        chunks = _chunk_ranges(gap_start=int(row["gap_start"]), gap_end_exclusive=int(row["gap_end_exclusive"]), timeframe=timeframe)
        for group_index in range(0, len(chunks), int(subrun_max_chunks)):
            group = chunks[group_index : group_index + int(subrun_max_chunks)]
            subrun_number = group_index // int(subrun_max_chunks) + 1
            subrun_id = f"{row['ticker'].replace('-', '')}-{timeframe}-gap{subrun_number:02d}"
            start = int(group[0]["start"])
            end_exclusive = int(group[-1]["end_exclusive"])
            expected = _expected_count(start=start, end_exclusive=end_exclusive, step_seconds=step)
            candidate = _candidate_path(
                candidate_root=candidate_root,
                ticker=str(row["ticker"]).upper(),
                timeframe=timeframe,
                subrun_id=subrun_id,
            )
            blockers: List[str] = []
            if len(group) > int(subrun_max_chunks):
                blockers.append("subrun_exceeds_chunk_budget")
            if expected <= 0:
                blockers.append("subrun_empty")
            subruns.append(
                {
                    "subrun_id": subrun_id,
                    "ticker": str(row["ticker"]).upper(),
                    "timeframe": timeframe,
                    "candles_path": row["candles_path"],
                    "gap_start": int(row["gap_start"]),
                    "gap_end_exclusive": int(row["gap_end_exclusive"]),
                    "subrange_start": start,
                    "subrange_end_exclusive": end_exclusive,
                    "subrange_start_iso": _iso_from_ts(start),
                    "subrange_end_exclusive_iso": _iso_from_ts(end_exclusive),
                    "expected_candle_count": expected,
                    "chunks_requested": len(group),
                    "subrun_max_chunks": int(subrun_max_chunks),
                    "candidate_output_path": str(candidate),
                    "chunks": group,
                    "ready_for_dry_run": not blockers,
                    "ready_for_fetch_under_existing_ack": not blockers,
                    "fetch_executed": False,
                    "validation_status": "not_fetched_yet",
                    "merge_executed": False,
                    "blockers": blockers,
                    "research_only": True,
                    "no_live_action": True,
                    "state_write_performed": False,
                    "parameter_change_allowed": False,
                    "learning_to_execution_allowed": False,
                }
            )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "staged_btc_1h_gap_fill_plan_v1",
        "status": "staged_gap_fill_plan_ready",
        "required_ack": DATA_FETCH_ACK,
        "candidate_root": str(assert_research_path(candidate_root)),
        "tickers": [str(t).upper() for t in tickers],
        "timeframes": normalize_timeframes(timeframes),
        "subrun_max_chunks": int(subrun_max_chunks),
        "execution_max_chunks": int(execution_max_chunks),
        "subrun_count": len(subruns),
        "total_planned_chunks": sum(int(row["chunks_requested"]) for row in subruns),
        "dry_run_required_first": True,
        "fetch_executed": False,
        "merge_executed": False,
        "subruns": subruns,
        "resumable_summary": build_resumable_summary(subruns=subruns),
        **safety_flags(),
        "coinbase_public_market_data_call_performed": False,
        "state_write_performed": False,
    }


def build_resumable_summary(*, subruns: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    complete = [row["subrun_id"] for row in subruns if row.get("validation_status") == "candidate_coverage_validation_pass" and row.get("merge_executed")]
    failed = [row["subrun_id"] for row in subruns if row.get("validation_status") == "candidate_coverage_validation_blocked"]
    pending = [row["subrun_id"] for row in subruns if row["subrun_id"] not in complete and row["subrun_id"] not in failed]
    zero = [row["subrun_id"] for row in subruns if int(row.get("candidate_count") or 0) == 0 and row.get("fetch_executed")]
    return {
        "completed_subruns": complete,
        "pending_subruns": pending,
        "failed_subruns": failed,
        "zero_candle_subruns": zero,
        "completed_count": len(complete),
        "pending_count": len(pending),
        "failed_count": len(failed),
        "zero_candle_count": len(zero),
    }


def select_subruns_for_execution(plan: Dict[str, Any], *, subrun_ids: Optional[Iterable[str]] = None) -> List[Dict[str, Any]]:
    wanted = {str(item) for item in subrun_ids or []}
    subruns = [dict(row) for row in plan.get("subruns") or [] if not wanted or str(row.get("subrun_id")) in wanted]
    total_chunks = sum(int(row.get("chunks_requested") or 0) for row in subruns)
    if total_chunks > int(plan.get("execution_max_chunks") or DEFAULT_EXECUTION_MAX_CHUNKS):
        raise ValueError("selected_subruns_exceed_execution_chunk_budget")
    blocked = [row.get("subrun_id") for row in subruns if row.get("blockers")]
    if blocked:
        raise ValueError(f"selected_subruns_not_ready:{','.join(str(item) for item in blocked)}")
    return subruns


def _call_public_candles(client: Any, *, subrun: Dict[str, Any], chunk: Dict[str, Any]) -> Dict[str, Any]:
    step = TIMEFRAME_SPECS[subrun["timeframe"]].seconds
    # Coinbase's candles endpoint behaves as start-exclusive/end-inclusive for
    # these historical windows. Shift the API boundary while validating against
    # the exact unshifted candidate range.
    return client.get_public_candles(
        product_id=subrun["ticker"],
        granularity=TIMEFRAME_SPECS[subrun["timeframe"]].coinbase_granularity,
        start=str(int(chunk["start"]) - step),
        end=str(int(chunk["end_exclusive"]) - step),
        limit=int(chunk.get("coinbase_limit") or D6_MAX_CANDLES_PER_REQUEST),
    )


def execute_staged_gap_fill(
    *,
    plan: Dict[str, Any],
    client: Any,
    subrun_ids: Optional[Iterable[str]] = None,
    merge: bool = True,
    fetched_at: datetime | None = None,
) -> Dict[str, Any]:
    if client is None:
        raise ValueError("staged_gap_fill_requires_read_only_coinbase_client")
    selected = select_subruns_for_execution(plan, subrun_ids=subrun_ids)
    fetched_at_dt = fetched_at or datetime.now(timezone.utc)
    result_rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    public_calls = 0
    updated_file_count = 0
    stop_reason = ""
    for subrun in selected:
        candles: List[Dict[str, Any]] = []
        subrun_errors: List[Dict[str, Any]] = []
        for chunk in subrun.get("chunks") or []:
            try:
                public_calls += 1
                raw = _call_public_candles(client, subrun=subrun, chunk=chunk)
                raw_candles = raw.get("candles", []) if isinstance(raw, dict) else []
                candles.extend(
                    normalize_candles(
                        raw_candles,
                        product_id=subrun["ticker"],
                        timeframe=subrun["timeframe"],
                        fetched_at=fetched_at_dt,
                        drop_open_candles=False,
                    )
                )
            except Exception as exc:  # pragma: no cover - HTTP/client exception type is external.
                err = {
                    "subrun_id": subrun["subrun_id"],
                    "chunk_index": chunk.get("chunk_index"),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                }
                errors.append(err)
                subrun_errors.append(err)
        candles = normalize_candles(
            candles,
            product_id=subrun["ticker"],
            timeframe=subrun["timeframe"],
            fetched_at=fetched_at_dt,
            drop_open_candles=False,
        )
        candidate_path = assert_research_path(subrun["candidate_output_path"])
        candidate_path.parent.mkdir(parents=True, exist_ok=True)
        candidate_path.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        validation = validate_candidate_coverage(
            candidate_path=candidate_path,
            existing_path=subrun["candles_path"],
            product_id=subrun["ticker"],
            timeframe=subrun["timeframe"],
            gap_start=int(subrun["subrange_start"]),
            gap_end_exclusive=int(subrun["subrange_end_exclusive"]),
        )
        merge_result: Dict[str, Any] | None = None
        if merge and validation.get("validator_pass"):
            merge_result = merge_tail_refresh_result(
                fetch_result={
                    "entries": [
                        {
                            "ticker": subrun["ticker"],
                            "timeframe": subrun["timeframe"],
                            "candidate_output_path": str(candidate_path),
                            "existing_cache_path": subrun["candles_path"],
                        }
                    ]
                }
            )
            updated_file_count += int(merge_result.get("updated_file_count") or 0)
        result_row = {
            **{key: value for key, value in subrun.items() if key != "chunks"},
            "candidate_count": len({int(row["start"]) for row in candles if "start" in row}),
            "first_candle_start": candles[0]["start"] if candles else None,
            "last_candle_start": candles[-1]["start"] if candles else None,
            "fetch_executed": True,
            "chunks_fetched": len(subrun.get("chunks") or []) - len(subrun_errors),
            "errors": subrun_errors,
            "validation": validation,
            "validation_status": validation.get("status"),
            "merge_result": merge_result,
            "merge_executed": bool(merge_result),
        }
        result_rows.append(result_row)
        if not validation.get("validator_pass"):
            stop_reason = f"stopped_after_validation_failure:{subrun['subrun_id']}"
            break
    status = "staged_gap_fill_result_ready"
    if errors or stop_reason:
        status = "staged_gap_fill_result_blocked"
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "staged_btc_1h_gap_fill_result_v1",
        "status": status,
        "candidate_root": plan.get("candidate_root"),
        "selected_subrun_ids": [row["subrun_id"] for row in selected],
        "executed_subrun_ids": [row["subrun_id"] for row in result_rows],
        "result_rows": result_rows,
        "resumable_summary": build_resumable_summary(subruns=result_rows + [row for row in plan.get("subruns") or [] if row.get("subrun_id") not in {r["subrun_id"] for r in result_rows}]),
        "errors": errors,
        "stop_reason": stop_reason,
        "coinbase_public_market_data_call_count": public_calls,
        "coinbase_public_market_data_call_performed": bool(public_calls),
        "fetch_executed": bool(result_rows),
        "merge_executed": bool(updated_file_count),
        "updated_file_count": updated_file_count,
        **safety_flags(),
        "state_write_performed": False,
    }


def build_quality_summary_v15(*, as_of: str = "2026-06-01T00:00:00Z") -> Dict[str, Any]:
    return build_post_gap_fill_quality_summary(candle_paths=discover_candle_files(), as_of=as_of) | {
        "report_name": "post_staged_gap_fill_dataset_quality_summary_v15",
        "status": "post_staged_gap_fill_dataset_quality_summary_v15_ready",
    }


def build_backtest_readiness_v15(*, quality_summary: Dict[str, Any], staged_result: Dict[str, Any] | None) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    all_good = summary.get("good_count") == summary.get("quality_report_count") and summary.get("quality_report_count")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "exploratory_only_backtest_readiness_refresh_v15",
        "status": "exploratory_only_backtest_readiness_refresh_v15_ready",
        "normal_backtests_deferred": True,
        "exploratory_backtests_allowed_by_v15": bool(all_good),
        "exploratory_backtests_run_in_v15": False,
        "reason": "dataset_quality_warning_or_poor_rows_remain" if not all_good else "exploratory_only_btc_usdc_cached_baseline_may_be_considered_separately",
        "quality_summary": summary,
        "staged_gap_fill_status": (staged_result or {}).get("status", "not_run"),
        "parameter_evidence_created": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "parameter_values_changed": False,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


def build_preflight_v5(*, quality_summary: Dict[str, Any], staged_plan: Dict[str, Any], staged_result: Dict[str, Any] | None) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_live_test_preflight_runner_v5",
        "status": "24h_live_test_preflight_runner_v5_ready",
        "preflight_result": "blocked_for_remaining_dataset_quality_review",
        "route_matrix": {
            "btc_usdc_only": "ack_gated_after_remaining_gap_quality_review",
            "staged_non_btc_pilot": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
            "all_ticker_24h": "blocked",
        },
        "quality_summary": summary,
        "staged_gap_fill": {
            "plan_subrun_count": staged_plan.get("subrun_count"),
            "result_status": (staged_result or {}).get("status", "not_run"),
            "resumable_summary": (staged_result or staged_plan).get("resumable_summary"),
        },
        "telemetry_evidence_plan": [
            "pre_live_state_hashes",
            "open_order_snapshot",
            "controlled_order_intent_and_ack_record",
            "fill_or_terminal_evidence",
            "post_live_state_hashes",
            "no_second_sell_duplicate_oversell_check",
        ],
        "required_future_acks": [
            "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        ],
        **safety_flags(),
    }


def build_master_packet_v15(
    *,
    staged_plan: Dict[str, Any],
    staged_result: Dict[str, Any] | None,
    quality_summary: Dict[str, Any],
    backtest_readiness: Dict[str, Any],
    preflight_v5: Dict[str, Any],
) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    result_summary = (staged_result or staged_plan).get("resumable_summary") or {}
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v15",
        "status": "24h_readiness_master_packet_v15_ready",
        "v15_resolved": [
            "staged_gap_fill_tooling_built",
            "explicit_start_end_subranges_planned",
            "chunk_budget_policy_fail_closed",
            "resumable_gap_fill_status_reported",
            "merge_policy_requires_exact_candidate_validation",
        ],
        "v14_verified": {
            "btc_1d_4h_merged": False,
            "v14_result": "candidate_validation_blocked_merge_because_candidates_were_empty",
        },
        "staged_gap_fill_status": (staged_result or {}).get("status", "not_run"),
        "staged_gap_fill_resumable_summary": result_summary,
        "quality_summary": summary,
        "backtest_status": backtest_readiness.get("status"),
        "btc_usdc_only_24h_status": "blocked_until_btc_gap_quality_is_resolved_then_ack_gated",
        "staged_non_btc_status": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
        "all_ticker_24h_status": "blocked",
        "remaining_blockers": [
            "btc_usdc_gap_subruns_not_all_completed",
            "dataset_quality_warning_or_poor_rows_present",
            "normal_backtests_deferred",
            "non_btc_live_lifecycle_evidence_missing",
            "future_live_test_exact_acks_missing",
        ],
        "preflight_v5_result": preflight_v5.get("preflight_result"),
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "DEFAULT_EXECUTION_MAX_CHUNKS",
    "DEFAULT_SUBRUN_MAX_CHUNKS",
    "PHASE",
    "build_backtest_readiness_v15",
    "build_master_packet_v15",
    "build_preflight_v5",
    "build_quality_summary_v15",
    "build_resumable_summary",
    "build_staged_gap_fill_plan",
    "execute_staged_gap_fill",
    "select_subruns_for_execution",
]
