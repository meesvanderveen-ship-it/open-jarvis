from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_binance_public_klines import (
    BinanceRateLimitPolicy,
    build_binance_klines_plan,
    execute_binance_klines_fetch,
)
from bot.phase_d6_candidate_coverage_validator import validate_candidate_coverage
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import D6_MAX_CANDLES_PER_REQUEST, TIMEFRAME_SPECS
from bot.phase_d6_gap_aware_candle_planner import DATA_FETCH_ACK, build_post_gap_fill_quality_summary, discover_candle_files
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_rate_limited_public_fetch import RateLimitPolicy, build_rate_limited_fetch_plan, execute_rate_limited_fetch
from bot.phase_d6_tail_candle_refresh import merge_tail_refresh_result


PHASE = "D6_btc_1h_staged_controller_v1"
BTC_1H_CANDLES = "research_data/coinbase/candles/product=BTC-USDC/timeframe=1H/study_window=3y.json"
DEFAULT_CANDLES_PER_CHUNK = 350
MAX_CHUNKS_PER_SPRINT = 3


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
        "binance_account_or_order_call_performed": False,
        "binance_trading_endpoint_call_performed": False,
        "external_candle_written_as_coinbase_candle": False,
        "normal_backtest_released_from_secondary_source": False,
        "state_write_performed": False,
    }


def _iso_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_report_content(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    content = loaded.get("content") if isinstance(loaded, dict) else None
    return dict(content) if isinstance(content, dict) else dict(loaded)


def _load_rows(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    return [dict(row) for row in loaded if isinstance(row, dict)] if isinstance(loaded, list) else []


def _detect_first_gap(*, candles_path: str | Path = BTC_1H_CANDLES) -> Dict[str, Any]:
    rows = _load_rows(candles_path)
    starts = sorted({int(row["start"]) for row in rows if "start" in row})
    step = TIMEFRAME_SPECS["1H"].seconds
    for previous, current in zip(starts, starts[1:]):
        if current - previous > step:
            missing = ((current - previous) // step) - 1
            return {
                "gap_start": previous + step,
                "gap_end_exclusive": current,
                "missing_candle_count": missing,
                "previous_start": previous,
                "next_start": current,
                "existing_count": len(starts),
            }
    return {
        "gap_start": None,
        "gap_end_exclusive": None,
        "missing_candle_count": 0,
        "previous_start": None,
        "next_start": None,
        "existing_count": len(starts),
    }


def build_btc_1h_staged_controller_plan(
    *,
    resume_status_path: str | Path,
    candidate_root: str | Path,
    max_chunks: int = MAX_CHUNKS_PER_SPRINT,
    candles_per_chunk: int = DEFAULT_CANDLES_PER_CHUNK,
    existing_path: str | Path = BTC_1H_CANDLES,
) -> Dict[str, Any]:
    if int(max_chunks) <= 0 or int(max_chunks) > MAX_CHUNKS_PER_SPRINT:
        raise ValueError("btc_1h_controller_max_chunks_out_of_bounds")
    if int(candles_per_chunk) <= 0 or int(candles_per_chunk) > D6_MAX_CANDLES_PER_REQUEST:
        raise ValueError("btc_1h_controller_candles_per_chunk_out_of_bounds")
    resume = _load_report_content(resume_status_path)
    prior_completed = list(resume.get("completed_pilot_chunks") or [])
    if not prior_completed:
        prior_completed = list(resume.get("previous_completed_chunks") or []) + list(resume.get("new_completed_chunks") or [])
    completed_numbers: List[int] = []
    for item in prior_completed:
        text = str(item)
        if "chunk" not in text:
            continue
        try:
            completed_numbers.append(int(text.rsplit("chunk", 1)[1].split("_", 1)[0].split(":", 1)[0]))
        except ValueError:
            continue
    next_chunk_number = max(completed_numbers, default=-1) + 1
    first_gap = _detect_first_gap(candles_path=existing_path)
    step = TIMEFRAME_SPECS["1H"].seconds
    blockers: List[str] = []
    if resume.get("auto_resume_allowed") is not False:
        blockers.append("resume_status_does_not_disable_auto_resume")
    if not first_gap.get("gap_start"):
        blockers.append("btc_1h_gap_not_detected")
    chunks: List[Dict[str, Any]] = []
    if not blockers:
        cursor = int(first_gap["gap_start"])
        gap_end = int(first_gap["gap_end_exclusive"])
        for idx in range(int(max_chunks)):
            start = cursor + idx * int(candles_per_chunk) * step
            end = min(start + int(candles_per_chunk) * step, gap_end)
            if end <= start:
                break
            expected = (end - start) // step
            chunk_number = next_chunk_number + idx
            chunk_id = f"BTCUSDC-1H-gap01:chunk{chunk_number}"
            run_id = f"BTCUSDC-1H-gap01-controller-chunk{chunk_number:02d}-v22-v23"
            fetch_plan = build_rate_limited_fetch_plan(
                ticker="BTC-USDC",
                timeframe="1H",
                chunks=[{"chunk_index": chunk_number, "start": start, "end_exclusive": end, "coinbase_limit": expected}],
                candidate_root=candidate_root,
                run_id=run_id,
                policy=RateLimitPolicy(
                    max_requests_per_minute=6,
                    max_requests_per_run=1,
                    min_delay_seconds=1.0,
                    max_retries_per_chunk=2,
                    retry_budget_total=2,
                    backoff_base_seconds=1.0,
                    backoff_max_seconds=12.0,
                    jitter_seconds=0.5,
                    max_consecutive_errors=2,
                    cooldown_after_error_seconds=2.0,
                    stop_on_zero_candle_response=True,
                    stop_on_partial_candidate=True,
                ),
            )
            chunks.append(
                {
                    "chunk_id": chunk_id,
                    "chunk_index": chunk_number,
                    "subrange_start": start,
                    "subrange_end_exclusive": end,
                    "subrange_start_iso": _iso_from_ts(start),
                    "subrange_end_exclusive_iso": _iso_from_ts(end),
                    "expected_candle_count": expected,
                    "request_budget": {"max_requests_per_run": 1, "max_requests_per_minute": 6},
                    "candidate_output_path": fetch_plan["candidate_output_path"],
                    "validation_rule": "exact_expected_starts_no_overlap_no_duplicates_matching_identity",
                    "allowed_merge_after_validation_pass": True,
                    "fetch_plan": fetch_plan,
                    "status": "planned",
                    "blockers": list(fetch_plan.get("blockers") or []),
                }
            )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_staged_controller_plan_v1",
        "status": "btc_1h_staged_controller_plan_ready" if not blockers else "btc_1h_staged_controller_plan_blocked",
        "required_ack": DATA_FETCH_ACK,
        "resume_status_path": str(assert_research_path(resume_status_path)),
        "resume_status": {
            "status": resume.get("status"),
            "completed_pilot_chunks": prior_completed,
            "next_pending_scope": resume.get("next_pending_scope"),
            "auto_resume_allowed": resume.get("auto_resume_allowed"),
        },
        "existing_path": str(assert_research_path(existing_path)),
        "first_gap": first_gap,
        "candidate_root": str(assert_research_path(candidate_root)),
        "max_chunks_this_sprint": int(max_chunks),
        "planned_chunk_count": len(chunks),
        "chunks": chunks,
        "fetch_executed": False,
        "merge_executed": False,
        "auto_resume_allowed": False,
        "blockers": blockers,
        **safety_flags(),
    }


def execute_btc_1h_staged_controller(
    *,
    plan: Dict[str, Any],
    coinbase_client: Any,
    max_execute_chunks: int = MAX_CHUNKS_PER_SPRINT,
    merge: bool = True,
    binance_reference: bool = False,
    binance_http_get: Any = None,
    fetched_at: datetime | None = None,
) -> Dict[str, Any]:
    if plan.get("blockers"):
        raise ValueError("btc_1h_controller_plan_has_blockers")
    if coinbase_client is None:
        raise ValueError("btc_1h_controller_requires_read_only_coinbase_client")
    if int(max_execute_chunks) <= 0 or int(max_execute_chunks) > MAX_CHUNKS_PER_SPRINT:
        raise ValueError("btc_1h_controller_execute_chunk_limit_out_of_bounds")
    fetched_at_dt = fetched_at or datetime.now(timezone.utc)
    result_rows: List[Dict[str, Any]] = []
    binance_rows: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    stop_reason = ""
    updated_file_count = 0
    coinbase_calls = 0
    for chunk in list(plan.get("chunks") or [])[: int(max_execute_chunks)]:
        fetch_plan = dict(chunk["fetch_plan"])
        try:
            fetch_result = execute_rate_limited_fetch(
                plan=fetch_plan,
                client=coinbase_client,
                fetched_at=fetched_at_dt,
            )
        except Exception as exc:
            errors.append({"chunk_id": chunk["chunk_id"], "error_type": type(exc).__name__, "error": str(exc)})
            stop_reason = f"stopped_after_coinbase_api_error:{chunk['chunk_id']}"
            break
        coinbase_calls += int(fetch_result.get("coinbase_public_market_data_call_count") or 0)
        if fetch_result.get("status") != "rate_limited_public_fetch_ready":
            stop_reason = fetch_result.get("stop_reason") or f"stopped_after_partial_candidate:{chunk['chunk_id']}"
            result_rows.append({**chunk, "fetch_result": fetch_result, "status": "blocked_after_fetch"})
            break
        validation = validate_candidate_coverage(
            candidate_path=fetch_result["candidate_output_path"],
            existing_path=plan["existing_path"],
            product_id="BTC-USDC",
            timeframe="1H",
            gap_start=int(chunk["subrange_start"]),
            gap_end_exclusive=int(chunk["subrange_end_exclusive"]),
        )
        if not validation.get("validator_pass"):
            stop_reason = f"stopped_after_validation_failure:{chunk['chunk_id']}"
            result_rows.append({**chunk, "fetch_result": fetch_result, "candidate_validation": validation, "status": "blocked_after_validation"})
            break
        merge_result = None
        if merge:
            merge_result = merge_tail_refresh_result(
                fetch_result={
                    "entries": [
                        {
                            "ticker": "BTC-USDC",
                            "timeframe": "1H",
                            "candidate_output_path": fetch_result["candidate_output_path"],
                            "existing_cache_path": plan["existing_path"],
                        }
                    ]
                }
            )
            updated_file_count += int(merge_result.get("updated_file_count") or 0)
        binance_result = None
        if binance_reference:
            b_plan = build_binance_klines_plan(
                mapped_coinbase_product="BTC-USDC",
                symbol="BTCUSDC",
                timeframe="1H",
                start=int(chunk["subrange_start"]),
                end_exclusive=int(chunk["subrange_end_exclusive"]),
                candidate_root="/tmp/d6_binance_btc_1h_reference_v22_v23",
                run_id=f"binance-btcusdc-1h-reference-chunk{chunk['chunk_index']:02d}-v22-v23",
                limit=int(chunk["expected_candle_count"]),
                policy=BinanceRateLimitPolicy(max_requests_per_run=1, max_requests_per_minute=6, max_retries_per_request=1, retry_budget_total=1),
            )
            try:
                binance_result = execute_binance_klines_fetch(plan=b_plan, http_get=binance_http_get, fetched_at=fetched_at_dt)
            except Exception as exc:
                binance_result = {
                    **b_plan,
                    "status": "binance_reference_diagnostic_error",
                    "errors": [{"error_type": type(exc).__name__, "error": str(exc)}],
                    "fail_closed": True,
                    **safety_flags(),
                }
            binance_rows.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "status": binance_result.get("status"),
                    "candidate_count": binance_result.get("candidate_count"),
                    "fail_closed": binance_result.get("fail_closed"),
                    "candidate_output_path": binance_result.get("candidate_output_path"),
                    "exact_expected_start_found": binance_result.get("exact_expected_start_found"),
                    "errors": binance_result.get("errors", []),
                    "reference_only": True,
                }
            )
        result_rows.append(
            {
                **chunk,
                "status": "completed",
                "fetch_result": fetch_result,
                "candidate_validation": validation,
                "merge_result": merge_result,
                "merge_executed": bool(merge_result),
                "binance_reference_result": binance_result,
            }
        )
    completed = [row["chunk_id"] for row in result_rows if row.get("status") == "completed"]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_staged_controller_result_v1",
        "status": "btc_1h_staged_controller_result_ready" if not stop_reason and not errors else "btc_1h_staged_controller_result_blocked",
        "selected_chunk_count": min(int(max_execute_chunks), len(plan.get("chunks") or [])),
        "completed_chunk_ids": completed,
        "completed_chunk_count": len(completed),
        "result_rows": result_rows,
        "binance_reference_rows": binance_rows,
        "errors": errors,
        "stop_reason": stop_reason,
        "coinbase_public_market_data_call_count": coinbase_calls,
        "coinbase_public_market_data_call_performed": bool(coinbase_calls),
        "fetch_executed": bool(result_rows),
        "merge_executed": bool(updated_file_count),
        "updated_file_count": updated_file_count,
        "auto_resume_allowed": False,
        **safety_flags(),
    }


def build_resume_status_v3(*, plan: Dict[str, Any], result: Dict[str, Any] | None) -> Dict[str, Any]:
    completed = list((result or {}).get("completed_chunk_ids") or [])
    planned = [row["chunk_id"] for row in plan.get("chunks") or []]
    open_chunks = [row for row in planned if row not in completed]
    prior = list(plan.get("resume_status", {}).get("completed_pilot_chunks") or [])
    completed_numbers: List[int] = []
    for item in [*prior, *completed]:
        text = str(item)
        if "chunk" not in text:
            continue
        try:
            completed_numbers.append(int(text.rsplit("chunk", 1)[1].split("_", 1)[0].split(":", 1)[0]))
        except ValueError:
            continue
    next_after_batch = f"BTCUSDC-1H-gap01:chunk{max(completed_numbers, default=-1) + 1}_or_review"
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_staged_resume_status_v3",
        "status": "btc_1h_staged_resume_status_v3_ready",
        "previous_completed_chunks": prior,
        "new_completed_chunks": completed,
        "completed_chunk_count_this_sprint": len(completed),
        "next_pending_scope": open_chunks[0] if open_chunks else next_after_batch,
        "auto_resume_allowed": False,
        "requires_operator_review_before_next_chunk": True,
        "last_result_status": (result or {}).get("status", "not_run"),
        "stop_reason": (result or {}).get("stop_reason", ""),
        "blockers": [] if not (result or {}).get("stop_reason") else [(result or {}).get("stop_reason")],
        **safety_flags(),
    }


def build_binance_btc_1h_reference_report(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    rows = list((controller_result or {}).get("binance_reference_rows") or [])
    available = [row for row in rows if row.get("status") == "binance_public_klines_fetch_ready"]
    blocked = [row for row in rows if row.get("status") != "binance_public_klines_fetch_ready"]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "binance_btcusdc_1h_reference_v2",
        "status": "binance_btcusdc_1h_reference_v2_ready" if rows else "binance_btcusdc_1h_reference_v2_not_run",
        "reference_rows": rows,
        "available_reference_count": len(available),
        "blocked_reference_count": len(blocked),
        "reference_only": True,
        "coinbase_cache_mutated_by_binance": False,
        "normal_backtest_permission_changed": False,
        **safety_flags(),
    }


def build_cross_source_btc_1h_gap_diagnostic(*, controller_result: Dict[str, Any] | None) -> Dict[str, Any]:
    rows = []
    for row in (controller_result or {}).get("result_rows") or []:
        validation = row.get("candidate_validation") or {}
        b = row.get("binance_reference_result") or {}
        rows.append(
            {
                "chunk_id": row.get("chunk_id"),
                "coinbase_candidate_validation": validation.get("status"),
                "coinbase_candidate_count": validation.get("candidate_count"),
                "binance_reference_status": b.get("status"),
                "binance_reference_count": b.get("candidate_count"),
                "classification": "coinbase_gap_fill_with_secondary_reference_available"
                if b.get("status") == "binance_public_klines_fetch_ready"
                else "coinbase_gap_fill_secondary_reference_not_available_or_not_run",
            }
        )
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "cross_source_btc_1h_gap_diagnostic_v1",
        "status": "cross_source_btc_1h_gap_diagnostic_v1_ready",
        "diagnostic_rows": rows,
        "coinbase_primary_dataset": True,
        "binance_reference_only": True,
        "coinbase_cache_mutated_by_binance": False,
        "normal_backtest_permission_changed": False,
        **safety_flags(),
    }


def build_quality_summary_v22_v23(*, as_of: str = "2026-06-01T00:00:00Z") -> Dict[str, Any]:
    summary = build_post_gap_fill_quality_summary(candle_paths=discover_candle_files(), as_of=as_of)
    warning_counts = dict((summary.get("summary") or {}).get("warning_counts") or {})
    return {
        **summary,
        "report_name": "post_btc_1h_staged_quality_summary_v22_v23",
        "status": "post_btc_1h_staged_quality_summary_v22_v23_ready",
        "global_counters": {
            "good_count": (summary.get("summary") or {}).get("good_count"),
            "warning_count": (summary.get("summary") or {}).get("warning_count"),
            "poor_count": ((summary.get("summary") or {}).get("quality_class_counts") or {}).get("poor", 0),
            "invalid_count": (summary.get("summary") or {}).get("invalid_count"),
            "stale_last_candle": warning_counts.get("stale_last_candle", 0),
            "candle_gaps_detected": warning_counts.get("candle_gaps_detected", 0),
            "missing_candles_estimated": warning_counts.get("missing_candles_estimated", 0),
        },
        **safety_flags(),
    }


def build_exploratory_backtest_decision_v22_v23(*, quality_summary: Dict[str, Any]) -> Dict[str, Any]:
    counters = quality_summary.get("global_counters") or {}
    primary_clean = counters.get("poor_count") == 0 and counters.get("warning_count") == 0 and counters.get("invalid_count") == 0
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "exploratory_only_backtest_decision_v22_v23",
        "status": "exploratory_only_backtest_decision_v22_v23_ready",
        "normal_backtests": "deferred",
        "reason": "primary_coinbase_dataset_quality_still_warning_or_poor" if not primary_clean else "primary_quality_clean_but_live_gates_still_separate",
        "bounded_exploratory_plan_allowed": True,
        "tiny_plumbing_run_executed": False,
        "parameter_evidence_created": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "parameter_values_changed": False,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


__all__ = [
    "BTC_1H_CANDLES",
    "MAX_CHUNKS_PER_SPRINT",
    "PHASE",
    "build_binance_btc_1h_reference_report",
    "build_btc_1h_staged_controller_plan",
    "build_cross_source_btc_1h_gap_diagnostic",
    "build_exploratory_backtest_decision_v22_v23",
    "build_quality_summary_v22_v23",
    "build_resume_status_v3",
    "execute_btc_1h_staged_controller",
    "safety_flags",
]
