from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, ROUND_CEILING
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import (
    D6_DEFAULT_TICKERS,
    D6_MAX_CANDLES_PER_REQUEST,
    D6_REQUIRED_TIMEFRAMES,
    TIMEFRAME_SPECS,
    normalize_timeframes,
    normalize_tickers,
    parse_as_of,
)
from bot.phase_d6_dataset_quality import build_phase_d6_dataset_quality_report
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_gap_aware_candle_planner_v1"
DATA_FETCH_ACK = "I_APPROVE_BOUNDED_MULTI_TICKER_COINBASE_CANDLE_FETCH_FOR_D6_RESEARCH_ONLY"
DEFAULT_CANDLE_ROOT = Path("research_data/coinbase/candles")


@dataclass(frozen=True)
class GapRange:
    ticker: str
    timeframe: str
    candles_path: str
    gap_start: int
    gap_end_exclusive: int
    missing_candle_count: int
    chunks_needed: int
    previous_start: int
    next_start: int


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


def _ceil_div(numerator: int, denominator: int) -> int:
    return int((Decimal(numerator) / Decimal(denominator)).to_integral_value(rounding=ROUND_CEILING))


def _candle_path(*, ticker: str, timeframe: str, root: str | Path = DEFAULT_CANDLE_ROOT) -> Path:
    return Path(root) / f"product={ticker}" / f"timeframe={timeframe}" / "study_window=3y.json"


def _load_candles(path: str | Path) -> List[Dict[str, Any]]:
    safe = assert_research_path(path)
    if not safe.exists():
        return []
    loaded = json.loads(safe.read_text(encoding="utf-8"))
    if not isinstance(loaded, list):
        return []
    rows: List[Dict[str, Any]] = []
    for row in loaded:
        if not isinstance(row, dict):
            continue
        try:
            int(row.get("start"))
        except (TypeError, ValueError):
            continue
        rows.append(dict(row))
    return rows


def _starts(rows: Iterable[Dict[str, Any]]) -> List[int]:
    out: set[int] = set()
    for row in rows:
        try:
            out.add(int(row.get("start")))
        except (TypeError, ValueError):
            continue
    return sorted(out)


def detect_candle_gaps(*, candles_path: str | Path, ticker: str, timeframe: str) -> List[GapRange]:
    timeframe_n = normalize_timeframes([timeframe])[0]
    ticker_n = normalize_tickers([ticker])[0]
    safe_path = assert_research_path(candles_path)
    starts = _starts(_load_candles(safe_path))
    if len(starts) < 2:
        return []
    step = TIMEFRAME_SPECS[timeframe_n].seconds
    gaps: List[GapRange] = []
    for previous, current in zip(starts, starts[1:]):
        delta = current - previous
        if delta <= step:
            continue
        missing = max((delta // step) - 1, 0)
        if missing <= 0:
            continue
        gaps.append(
            GapRange(
                ticker=ticker_n,
                timeframe=timeframe_n,
                candles_path=str(safe_path),
                gap_start=previous + step,
                gap_end_exclusive=current,
                missing_candle_count=missing,
                chunks_needed=_ceil_div(missing, D6_MAX_CANDLES_PER_REQUEST),
                previous_start=previous,
                next_start=current,
            )
        )
    return gaps


def _gap_to_row(gap: GapRange, *, candidate_root: str | Path, max_chunks_per_gap: int) -> Dict[str, Any]:
    candidate = (
        assert_research_path(candidate_root)
        / f"product={gap.ticker}"
        / f"timeframe={gap.timeframe}"
        / f"gap_start={gap.gap_start}_gap_end={gap.gap_end_exclusive}.json"
    )
    safe_to_fetch = gap.chunks_needed <= int(max_chunks_per_gap)
    command_base = (
        ".venv/bin/python tools/run_phase_d6_tail_candle_refresh.py "
        f"--as-of {_iso_from_ts(gap.gap_end_exclusive)} "
        f"--tickers {gap.ticker} --timeframes {gap.timeframe} "
        f"--max-chunks {gap.chunks_needed} "
        f"--candidate-root {candidate_root}"
    )
    blockers: List[str] = []
    if not safe_to_fetch:
        blockers.append("gap_exceeds_bounded_max_chunks")
    return {
        "ticker": gap.ticker,
        "timeframe": gap.timeframe,
        "candles_path": gap.candles_path,
        "previous_start": gap.previous_start,
        "next_start": gap.next_start,
        "gap_start": gap.gap_start,
        "gap_end_exclusive": gap.gap_end_exclusive,
        "gap_start_iso": _iso_from_ts(gap.gap_start),
        "gap_end_exclusive_iso": _iso_from_ts(gap.gap_end_exclusive),
        "missing_candle_count": gap.missing_candle_count,
        "chunks_needed": gap.chunks_needed,
        "max_chunks_per_gap": int(max_chunks_per_gap),
        "candidate_output_path": str(candidate),
        "dry_run_command": f"{command_base} --dry-run --json",
        "bounded_fetch_command": f"{command_base} --fetch --json",
        "merge_allowed_only_after_exact_gap_coverage": True,
        "safe_to_fetch_under_existing_ack": safe_to_fetch,
        "blockers": blockers,
        "research_only": True,
        "no_live_action": True,
        "state_write_performed": False,
        "parameter_change_allowed": False,
        "learning_to_execution_allowed": False,
    }


def discover_candle_files(
    *,
    tickers: Optional[Iterable[Any]] = None,
    timeframes: Optional[Iterable[Any]] = None,
    root: str | Path = DEFAULT_CANDLE_ROOT,
) -> List[Path]:
    tickers_n = normalize_tickers(tickers or D6_DEFAULT_TICKERS)
    timeframes_n = normalize_timeframes(timeframes or D6_REQUIRED_TIMEFRAMES)
    return [_candle_path(ticker=ticker, timeframe=timeframe, root=root) for ticker in tickers_n for timeframe in timeframes_n]


def build_open_source_inspiration_report() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "open_source_inspiration_gap_aware_refresh_v1",
        "status": "open_source_inspiration_gap_aware_refresh_ready",
        "sources": [
            {
                "project": "Freqtrade",
                "url": "https://docs.freqtrade.io/en/latest/data-download/",
                "license_or_compatibility_note": "Pattern-only reference; no code copied.",
                "safe_takeaway": "Incremental data refresh should calculate missing timeranges from existing local data and keep available data intact.",
            },
            {
                "project": "CCXT",
                "url": "https://github.com/ccxt/ccxt/wiki/manual",
                "license_or_compatibility_note": "Pattern-only reference; no dependency added.",
                "safe_takeaway": "OHLCV pagination must explicitly handle date windows, exchange-returned holes, redundancy and data aggregation gaps.",
            },
            {
                "project": "vectorbt",
                "url": "https://vectorbt.dev/",
                "license_or_compatibility_note": "Pattern-only reference; no vectorbt dependency added.",
                "safe_takeaway": "Backtest plumbing can remain local and array/pandas-oriented, separated from live execution and parameter decisions.",
            },
            {
                "project": "Hummingbot",
                "url": "https://hummingbot.org/connectors/connectors/architecture/order_lifecycle/",
                "license_or_compatibility_note": "Pattern-only reference; no code copied.",
                "safe_takeaway": "Order lifecycle, data ingestion and strategy orchestration should remain separate components with explicit state transitions.",
            },
        ],
        "adopted_patterns": [
            "gap_only_planning_before_fetch",
            "bounded_window_commands",
            "candidate_root_before_merge",
            "merge_only_after_exact_coverage_validation",
            "research_outputs_separate_from_trading_state",
            "backtest_plumbing_separate_from_parameter_review",
        ],
        "rejected_patterns": [
            "new_dependency_install",
            "framework_migration",
            "unbounded_bulk_download",
            "research_output_to_live_behavior_bridge",
        ],
        **safety_flags(),
        "state_write_performed": False,
        "coinbase_public_market_data_call_performed": False,
    }


def build_gap_aware_candle_planner(
    *,
    tickers: Optional[Iterable[Any]] = None,
    timeframes: Optional[Iterable[Any]] = None,
    candidate_root: str | Path = "/tmp/d6_gap_fill_candidate",
    max_chunks_per_gap: int = 25,
    as_of: Any = "2026-06-01T00:00:00Z",
) -> Dict[str, Any]:
    as_of_dt = parse_as_of(as_of)
    paths = discover_candle_files(tickers=tickers, timeframes=timeframes)
    rows: List[Dict[str, Any]] = []
    missing_files: List[str] = []
    for path in paths:
        ticker = path.parent.parent.name.removeprefix("product=")
        timeframe = path.parent.name.removeprefix("timeframe=")
        if not path.exists():
            missing_files.append(str(path))
            continue
        for gap in detect_candle_gaps(candles_path=path, ticker=ticker, timeframe=timeframe):
            rows.append(_gap_to_row(gap, candidate_root=candidate_root, max_chunks_per_gap=max_chunks_per_gap))
    safe_rows = [row for row in rows if row.get("safe_to_fetch_under_existing_ack")]
    blocked_rows = [row for row in rows if not row.get("safe_to_fetch_under_existing_ack")]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "gap_aware_candle_planner_v1",
        "status": "gap_aware_candle_planner_ready",
        "as_of": as_of_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "required_ack": DATA_FETCH_ACK,
        "candidate_root": str(assert_research_path(candidate_root)),
        "max_chunks_per_gap": int(max_chunks_per_gap),
        "file_count": len(paths),
        "missing_file_count": len(missing_files),
        "missing_files": missing_files,
        "gap_count": len(rows),
        "safe_gap_fetch_count": len(safe_rows),
        "blocked_gap_fetch_count": len(blocked_rows),
        "rows": rows,
        **safety_flags(),
        "fetch_executed": False,
        "merge_executed": False,
        "state_write_performed": False,
        "coinbase_public_market_data_call_performed": False,
    }


def build_gap_fill_command_plan(*, planner: Dict[str, Any]) -> Dict[str, Any]:
    rows = [dict(row) for row in planner.get("rows") or []]
    safe_rows = [row for row in rows if row.get("safe_to_fetch_under_existing_ack")]
    blocked_rows = [row for row in rows if not row.get("safe_to_fetch_under_existing_ack")]
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "gap_fill_command_plan_v1",
        "status": "gap_fill_command_plan_ready",
        "required_ack": DATA_FETCH_ACK,
        "candidate_root": planner.get("candidate_root"),
        "planned_gap_count": len(rows),
        "safe_gap_fetch_count": len(safe_rows),
        "blocked_gap_fetch_count": len(blocked_rows),
        "dry_run_required_first": True,
        "fetch_executed": False,
        "merge_executed": False,
        "safe_rows": safe_rows,
        "blocked_rows": blocked_rows,
        "execution_decision": "plan_only_because_at_least_one_btc_gap_exceeds_bounded_limit"
        if any(row.get("ticker") == "BTC-USDC" for row in blocked_rows)
        else "candidate_dry_run_possible_for_safe_rows_only",
        "merge_policy": "merge_only_after_candidate_rows_cover_exact_gap_ranges",
        **safety_flags(),
        "coinbase_public_market_data_call_performed": False,
        "state_write_performed": False,
    }


def build_post_gap_fill_quality_summary(*, candle_paths: Iterable[str | Path], as_of: Any) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for path in candle_paths:
        if not Path(path).exists():
            continue
        quality = build_phase_d6_dataset_quality_report(candles_path=path, as_of=as_of)
        rows.append(
            {
                "product_id": quality.get("product_id"),
                "timeframe": quality.get("timeframe"),
                "candles_path": quality.get("candles_path"),
                "candle_count": quality.get("candle_count"),
                "quality_class": quality.get("quality_class"),
                "gap_count": quality.get("gap_count"),
                "warnings": list(quality.get("warnings") or []),
                "fatal_errors": list(quality.get("fatal_errors") or []),
                "status": quality.get("status"),
            }
        )
    warning_counts: Dict[str, int] = {}
    class_counts: Dict[str, int] = {}
    for row in rows:
        klass = str(row.get("quality_class") or "unknown")
        class_counts[klass] = class_counts.get(klass, 0) + 1
        for warning in row.get("warnings") or []:
            key = str(warning)
            warning_counts[key] = warning_counts.get(key, 0) + 1
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "post_gap_fill_dataset_quality_summary_v13",
        "status": "post_gap_fill_dataset_quality_summary_v13_ready",
        "summary": {
            "quality_report_count": len(rows),
            "good_count": sum(1 for row in rows if row.get("quality_class") == "good"),
            "warning_count": sum(1 for row in rows if row.get("quality_class") != "good" and row.get("quality_class") != "invalid"),
            "invalid_count": sum(1 for row in rows if row.get("quality_class") == "invalid"),
            "quality_class_counts": dict(sorted(class_counts.items())),
            "warning_counts": dict(sorted(warning_counts.items())),
        },
        "rows": rows,
        **safety_flags(),
        "fetch_executed": False,
        "merge_executed": False,
        "state_write_performed": False,
        "coinbase_public_market_data_call_performed": False,
    }


def build_backtest_readiness_v13(*, quality_summary: Dict[str, Any], planner: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "exploratory_only_backtest_readiness_refresh_v13",
        "status": "exploratory_only_backtest_readiness_refresh_v13_ready",
        "normal_backtests_deferred": True,
        "exploratory_backtests_deferred_in_v13": True,
        "reason": "dataset_quality_still_has_warning_or_poor_rows_and_gap_plan_is_not_filled_yet",
        "quality_summary": summary,
        "gap_count": planner.get("gap_count"),
        "blocked_gap_fetch_count": planner.get("blocked_gap_fetch_count"),
        "parameter_evidence_created": False,
        "optimization_performed": False,
        "ranking_performed": False,
        "parameter_values_changed": False,
        "learning_to_execution_enabled": False,
        **safety_flags(),
    }


def build_preflight_v3(*, quality_summary: Dict[str, Any], planner: Dict[str, Any]) -> Dict[str, Any]:
    summary = dict(quality_summary.get("summary") or {})
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_live_test_preflight_runner_v3",
        "status": "24h_live_test_preflight_runner_v3_ready",
        "preflight_result": "blocked_for_research_quality_gap_review",
        "route_matrix": {
            "btc_usdc_only": "ack_gated_after_gap_quality_review",
            "staged_non_btc_pilot": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
            "all_ticker_24h": "blocked",
        },
        "quality_summary": summary,
        "gap_summary": {
            "gap_count": planner.get("gap_count"),
            "safe_gap_fetch_count": planner.get("safe_gap_fetch_count"),
            "blocked_gap_fetch_count": planner.get("blocked_gap_fetch_count"),
        },
        "required_future_acks": [
            "I_APPROVE_BOUNDED_COINBASE_READ_ONLY_PREFLIGHT_FOR_ONE_DAY_LIVE_TEST",
            "I_APPROVE_EXACTLY_ONE_CONTROLLED_LIVE_TEST_ORDER_MAX_10_USDC_BTC_USDC",
            "I_APPROVE_LIFECYCLE_APPLY_AFTER_TERMINAL_EVIDENCE_FOR_THIS_ONE_TEST_ORDER",
        ],
        **safety_flags(),
    }


def build_master_packet_v13(
    *,
    open_source_report: Dict[str, Any],
    planner: Dict[str, Any],
    command_plan: Dict[str, Any],
    quality_summary: Dict[str, Any],
    backtest_readiness: Dict[str, Any],
    preflight_v3: Dict[str, Any],
) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "24h_readiness_master_packet_v13",
        "status": "24h_readiness_master_packet_v13_ready",
        "v13_resolved": [
            "open_source_patterns_reviewed",
            "gap_aware_candle_planner_built",
            "btc_gap_ranges_detected",
            "bounded_gap_fill_command_plan_created",
        ],
        "v13_not_run": [
            "gap_fill_fetch",
            "gap_fill_merge",
            "normal_backtests",
            "new_exploratory_backtests",
        ],
        "reason_not_run": command_plan.get("execution_decision"),
        "open_source_pattern_count": len(open_source_report.get("sources") or []),
        "gap_summary": {
            "gap_count": planner.get("gap_count"),
            "safe_gap_fetch_count": planner.get("safe_gap_fetch_count"),
            "blocked_gap_fetch_count": planner.get("blocked_gap_fetch_count"),
        },
        "quality_summary": quality_summary.get("summary"),
        "backtest_status": backtest_readiness.get("status"),
        "btc_usdc_only_24h_status": "ack_gated_after_gap_quality_review",
        "staged_non_btc_status": "blocked_until_separate_design_and_non_btc_lifecycle_evidence",
        "all_ticker_24h_status": "blocked",
        "remaining_blockers": [
            "btc_usdc_1h_gap_exceeds_current_bounded_gap_limit",
            "dataset_quality_warning_or_poor_rows_present",
            "normal_backtests_not_run",
            "non_btc_live_lifecycle_evidence_missing",
            "future_live_test_exact_acks_missing",
        ],
        "next_safe_sprint": "implement_gap_exact_candidate_fetch_validation_and_fill_btc_gap_rows_in_order_of_smallest_gap_first",
        "preflight_v3_result": preflight_v3.get("preflight_result"),
        **safety_flags(),
        "fetch_executed": False,
        "merge_executed": False,
        "state_write_performed": False,
        "coinbase_public_market_data_call_performed": False,
    }


__all__ = [
    "DATA_FETCH_ACK",
    "PHASE",
    "build_backtest_readiness_v13",
    "build_gap_aware_candle_planner",
    "build_gap_fill_command_plan",
    "build_master_packet_v13",
    "build_open_source_inspiration_report",
    "build_post_gap_fill_quality_summary",
    "build_preflight_v3",
    "detect_candle_gaps",
    "discover_candle_files",
    "safety_flags",
]
