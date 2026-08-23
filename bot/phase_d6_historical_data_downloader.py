from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import TIMEFRAME_SPECS, normalize_timeframe
from bot.phase_d6_historical_data_sources import binance_source_contract, coinbase_source_contract
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso
from bot.phase_d6_rate_limited_public_fetch import RateLimitPolicy, build_rate_limited_fetch_plan, execute_rate_limited_fetch


def _flags() -> Dict[str, bool]:
    return {
        **d6_metric_safety_flags(),
        "human_review_required": True,
        "state_write_performed": False,
        "live_order_action_performed": False,
        "coinbase_account_or_order_call_performed": False,
        "binance_account_or_order_call_performed": False,
        "binance_trading_endpoint_call_performed": False,
        "config_mutation_performed": False,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
        "live_recommendation": False,
        "learning_to_execution_enabled": False,
    }


def _existing_path(product: str, timeframe: str) -> str:
    return f"research_data/coinbase/candles/product={product.upper()}/timeframe={normalize_timeframe(timeframe)}/study_window=3y.json"


def plan_historical_download(
    *,
    source: str,
    product: str,
    symbol: str,
    timeframe: str,
    start: int,
    end: int,
    max_chunks: int,
    max_requests: int,
    candidate_root: str | Path,
    run_id: str,
    no_binance_repair: bool = True,
    primary_only_normal_gate: bool = True,
) -> Dict[str, Any]:
    timeframe_n = normalize_timeframe(timeframe)
    step = TIMEFRAME_SPECS[timeframe_n].seconds
    if end <= start:
        raise ValueError("historical_download_end_must_be_after_start")
    if max_chunks <= 0 or max_requests <= 0:
        raise ValueError("historical_download_limits_must_be_positive")
    source_n = source.lower()
    if source_n not in {"coinbase", "binance"}:
        raise ValueError("historical_download_unknown_source")
    cursor = int(start)
    chunks: List[Dict[str, Any]] = []
    for idx in range(int(max_chunks)):
        if cursor >= int(end):
            break
        chunk_end = min(cursor + 350 * step, int(end))
        chunks.append({"chunk_index": idx, "start": cursor, "end_exclusive": chunk_end, "coinbase_limit": (chunk_end - cursor) // step})
        cursor = chunk_end
    contract = (
        coinbase_source_contract(product=product, timeframe=timeframe_n, run_id=run_id)
        if source_n == "coinbase"
        else binance_source_contract(symbol=symbol, mapped_coinbase_product=product, timeframe=timeframe_n, run_id=run_id)
    )
    fetch_plan = None
    if source_n == "coinbase":
        fetch_plan = build_rate_limited_fetch_plan(
            ticker=product,
            timeframe=timeframe_n,
            chunks=chunks,
            candidate_root=candidate_root,
            run_id=run_id,
            policy=RateLimitPolicy(max_requests_per_minute=6, max_requests_per_run=min(max_requests, len(chunks) or 1), min_delay_seconds=1.0, max_retries_per_chunk=2, retry_budget_total=4, backoff_base_seconds=1.0, backoff_max_seconds=12.0, jitter_seconds=0.5, max_consecutive_errors=2, cooldown_after_error_seconds=2.0, stop_on_zero_candle_response=True, stop_on_partial_candidate=True),
        )
    return {
        "generated_at": now_iso(),
        "phase": "D6_historical_data_downloader_v1",
        "report_name": "historical_data_download_plan_v1",
        "status": "historical_data_download_plan_v1_ready",
        "source_contract": contract,
        "source": source_n,
        "product": product.upper(),
        "symbol": symbol.upper(),
        "timeframe": timeframe_n,
        "start": int(start),
        "end": int(end),
        "chunk_count": len(chunks),
        "chunks": chunks,
        "max_requests": int(max_requests),
        "candidate_root": str(assert_research_path(candidate_root)),
        "existing_cache_path": _existing_path(product, timeframe_n),
        "fetch_plan": fetch_plan,
        "dry_run": True,
        "allow_merge_default": False,
        "no_binance_repair": bool(no_binance_repair),
        "primary_only_normal_gate": bool(primary_only_normal_gate),
        "resume_manifest_required_for_continuation": True,
        **_flags(),
    }


def execute_coinbase_historical_download(*, plan: Dict[str, Any], client: Any) -> Dict[str, Any]:
    if plan.get("source") != "coinbase":
        raise ValueError("only_coinbase_execution_supported_without_reference_tool")
    result = execute_rate_limited_fetch(plan=plan["fetch_plan"], client=client)
    return {
        "generated_at": now_iso(),
        "phase": "D6_historical_data_downloader_v1",
        "report_name": "historical_data_download_result_v1",
        "status": "historical_data_download_result_v1_ready" if result.get("status") == "rate_limited_public_fetch_ready" else "historical_data_download_result_v1_blocked",
        "download_plan": {key: plan.get(key) for key in ["source", "product", "symbol", "timeframe", "start", "end", "chunk_count"]},
        "fetch_result": result,
        "candidate_output_path": result.get("candidate_output_path"),
        "candidate_count": result.get("candidate_count"),
        "merge_executed": False,
        "next_safe_step": "validate_candidate_exactly_before_any_merge",
        **_flags(),
    }


def build_gap_report(*, validation: Dict[str, Any], known_gap_decision: Dict[str, Any] | None = None) -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": "D6_historical_data_downloader_v1",
        "report_name": "historical_data_gap_report_v1",
        "status": "historical_data_gap_report_v1_ready",
        "validation": validation,
        "known_gap_decision": known_gap_decision or {},
        "normal_backtest_allowed": False if validation.get("blocks_normal_backtest", True) else True,
        "secondary_source_repair_allowed": False,
        **_flags(),
    }


def load_resume_manifest(path: str | Path) -> Dict[str, Any]:
    loaded = json.loads(assert_research_path(path).read_text(encoding="utf-8"))
    return dict(loaded.get("content") or loaded)


__all__ = ["build_gap_report", "execute_coinbase_historical_download", "load_resume_manifest", "plan_historical_download"]
