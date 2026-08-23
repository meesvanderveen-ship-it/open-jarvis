from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path, normalize_candles
from bot.phase_d6_data_coverage import D6_MAX_CANDLES_PER_REQUEST, TIMEFRAME_SPECS, normalize_timeframes
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_rate_limited_public_fetch_v1"


@dataclass(frozen=True)
class RateLimitPolicy:
    max_requests_per_minute: int = 20
    max_requests_per_run: int = 25
    min_delay_seconds: float = 1.0
    max_retries_per_chunk: int = 2
    retry_budget_total: int = 4
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 8.0
    jitter_seconds: float = 0.25
    max_consecutive_errors: int = 2
    cooldown_after_error_seconds: float = 0.0
    stop_on_zero_candle_response: bool = True
    stop_on_partial_candidate: bool = True

    def validate(self) -> None:
        if self.max_requests_per_minute <= 0:
            raise ValueError("max_requests_per_minute_must_be_positive")
        if self.max_requests_per_run <= 0:
            raise ValueError("max_requests_per_run_must_be_positive")
        if self.min_delay_seconds < 0:
            raise ValueError("min_delay_seconds_must_not_be_negative")
        if self.max_retries_per_chunk < 0:
            raise ValueError("max_retries_per_chunk_must_not_be_negative")
        if self.retry_budget_total < 0:
            raise ValueError("retry_budget_total_must_not_be_negative")
        if self.backoff_base_seconds < 0 or self.backoff_max_seconds < 0 or self.jitter_seconds < 0:
            raise ValueError("backoff_values_must_not_be_negative")
        if self.max_consecutive_errors <= 0:
            raise ValueError("max_consecutive_errors_must_be_positive")
        if self.cooldown_after_error_seconds < 0:
            raise ValueError("cooldown_after_error_seconds_must_not_be_negative")


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


def _candidate_path(*, candidate_root: str | Path, ticker: str, timeframe: str, run_id: str) -> Path:
    return assert_research_path(candidate_root) / f"product={ticker}" / f"timeframe={timeframe}" / f"{run_id}.json"


def build_rate_limited_fetch_plan(
    *,
    ticker: str,
    timeframe: str,
    chunks: Iterable[Dict[str, Any]],
    candidate_root: str | Path,
    run_id: str,
    policy: RateLimitPolicy | None = None,
    boundary_shift_start_seconds: int | None = None,
    boundary_shift_end_seconds: int | None = None,
) -> Dict[str, Any]:
    policy = policy or RateLimitPolicy()
    policy.validate()
    timeframe_n = normalize_timeframes([timeframe])[0]
    step = TIMEFRAME_SPECS[timeframe_n].seconds
    request_rows: List[Dict[str, Any]] = []
    for idx, raw in enumerate(chunks):
        start = int(raw["start"])
        end_exclusive = int(raw["end_exclusive"])
        if end_exclusive <= start:
            raise ValueError("chunk_end_must_be_after_start")
        shift_start = step if boundary_shift_start_seconds is None else int(boundary_shift_start_seconds)
        shift_end = step if boundary_shift_end_seconds is None else int(boundary_shift_end_seconds)
        request_rows.append(
            {
                "chunk_index": int(raw.get("chunk_index", idx)),
                "expected_start": start,
                "expected_end_exclusive": end_exclusive,
                "expected_start_iso": _iso_from_ts(start),
                "expected_end_exclusive_iso": _iso_from_ts(end_exclusive),
                "request_start": start - shift_start,
                "request_end": end_exclusive - shift_end,
                "request_start_iso": _iso_from_ts(start - shift_start),
                "request_end_iso": _iso_from_ts(end_exclusive - shift_end),
                "coinbase_limit": int(raw.get("coinbase_limit") or D6_MAX_CANDLES_PER_REQUEST),
            }
        )
    planned = len(request_rows)
    blockers: List[str] = []
    if planned > policy.max_requests_per_minute:
        blockers.append("planned_requests_exceed_one_minute_policy")
    if planned > policy.max_requests_per_run:
        blockers.append("planned_requests_exceed_run_policy")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "rate_limited_public_fetch_plan_v1",
        "status": "rate_limited_public_fetch_plan_ready" if not blockers else "rate_limited_public_fetch_plan_blocked",
        "ticker": str(ticker).upper(),
        "timeframe": timeframe_n,
        "coinbase_granularity": TIMEFRAME_SPECS[timeframe_n].coinbase_granularity,
        "candidate_output_path": str(_candidate_path(candidate_root=candidate_root, ticker=str(ticker).upper(), timeframe=timeframe_n, run_id=run_id)),
        "request_count": planned,
        "requests": request_rows,
        "policy": policy.__dict__,
        "blockers": blockers,
        "dry_run": True,
        "fetch_executed": False,
        "partial_candidate_quarantined": False,
        **safety_flags(),
        "state_write_performed": False,
    }


def _backoff(policy: RateLimitPolicy, *, attempt: int, rng: random.Random) -> float:
    base = min(policy.backoff_max_seconds, policy.backoff_base_seconds * (2 ** max(attempt - 1, 0)))
    return base + rng.uniform(0, policy.jitter_seconds)


def classify_fetch_error(error: BaseException | str, *, zero_candle: bool = False, validation_failed: bool = False) -> str:
    if zero_candle:
        return "zero_candle_response"
    if validation_failed:
        return "validation_failed"
    text = str(error).lower()
    if "429" in text or "rate" in text or "too many" in text:
        return "rate_limit_error"
    if any(token in text for token in ["timeout", "network", "connection", "dns", "temporarily unavailable"]):
        return "network_error"
    return "fetch_error"


def execute_rate_limited_fetch(
    *,
    plan: Dict[str, Any],
    client: Any,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.monotonic,
    fetched_at: datetime | None = None,
    rng_seed: int = 60601,
) -> Dict[str, Any]:
    if client is None:
        raise ValueError("rate_limited_fetch_requires_read_only_coinbase_client")
    if plan.get("blockers"):
        raise ValueError("rate_limited_fetch_plan_has_blockers")
    policy = RateLimitPolicy(**dict(plan.get("policy") or {}))
    policy.validate()
    fetched_at_dt = fetched_at or datetime.now(timezone.utc)
    rng = random.Random(rng_seed)
    candles: List[Dict[str, Any]] = []
    errors: List[Dict[str, Any]] = []
    request_results: List[Dict[str, Any]] = []
    call_count = 0
    retry_count = 0
    consecutive_errors = 0
    last_call_at: Optional[float] = None
    fail_closed = False
    stop_reason = ""
    for request in plan.get("requests") or []:
        if last_call_at is not None:
            elapsed = now_fn() - last_call_at
            if elapsed < policy.min_delay_seconds:
                sleep_fn(policy.min_delay_seconds - elapsed)
        attempts = 0
        success = False
        raw_candles: List[Dict[str, Any]] = []
        while attempts <= policy.max_retries_per_chunk:
            attempts += 1
            try:
                call_count += 1
                last_call_at = now_fn()
                raw = client.get_public_candles(
                    product_id=plan["ticker"],
                    granularity=plan["coinbase_granularity"],
                    start=str(int(request["request_start"])),
                    end=str(int(request["request_end"])),
                    limit=int(request.get("coinbase_limit") or D6_MAX_CANDLES_PER_REQUEST),
                )
                raw_candles = raw.get("candles", []) if isinstance(raw, dict) else []
                success = True
                consecutive_errors = 0
                break
            except Exception as exc:  # pragma: no cover - client exception type is external.
                consecutive_errors += 1
                err = {
                    "chunk_index": request.get("chunk_index"),
                    "attempt": attempts,
                    "error_type": type(exc).__name__,
                    "error_classification": classify_fetch_error(exc),
                    "error": str(exc),
                    "consecutive_errors": consecutive_errors,
                }
                errors.append(err)
                if (
                    attempts > policy.max_retries_per_chunk
                    or retry_count >= policy.retry_budget_total
                    or consecutive_errors >= policy.max_consecutive_errors
                ):
                    fail_closed = True
                    stop_reason = "retry_budget_or_consecutive_error_limit_reached"
                    break
                retry_count += 1
                sleep_fn(_backoff(policy, attempt=attempts, rng=rng))
                if policy.cooldown_after_error_seconds:
                    sleep_fn(policy.cooldown_after_error_seconds)
        normalized = normalize_candles(
            raw_candles,
            product_id=plan["ticker"],
            timeframe=plan["timeframe"],
            fetched_at=fetched_at_dt,
            drop_open_candles=False,
        )
        candles.extend(normalized)
        request_results.append(
            {
                "chunk_index": request.get("chunk_index"),
                "success": success,
                "attempts": attempts,
                "raw_candle_count": len(raw_candles),
                "normalized_candle_count": len(normalized),
                "zero_candle_response": success and not raw_candles,
                "error_classification": "zero_candle_response" if success and not raw_candles else "",
            }
        )
        if success and not raw_candles and policy.stop_on_zero_candle_response:
            fail_closed = True
            stop_reason = "zero_candle_response_fail_closed"
        if fail_closed:
            break
    candles = normalize_candles(
        candles,
        product_id=plan["ticker"],
        timeframe=plan["timeframe"],
        fetched_at=fetched_at_dt,
        drop_open_candles=False,
    )
    candidate_path = assert_research_path(plan["candidate_output_path"])
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    zero_count = sum(1 for row in request_results if row.get("zero_candle_response"))
    unsuccessful_count = sum(1 for row in request_results if not row.get("success"))
    partial = fail_closed or zero_count > 0 or unsuccessful_count > 0
    quarantine_path = ""
    if partial:
        quarantine = candidate_path.with_suffix(".quarantine.json")
        quarantine.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        quarantine_path = str(quarantine)
    return {
        **dict(plan),
        "generated_at": now_iso(),
        "status": "rate_limited_public_fetch_blocked" if partial else "rate_limited_public_fetch_ready",
        "dry_run": False,
        "fetch_executed": True,
        "coinbase_public_market_data_call_count": call_count,
        "coinbase_public_market_data_call_performed": bool(call_count),
        "retry_count": retry_count,
        "errors": errors,
        "request_results": request_results,
        "candidate_count": len({int(row["start"]) for row in candles if "start" in row}),
        "first_candle_start": candles[0]["start"] if candles else None,
        "last_candle_start": candles[-1]["start"] if candles else None,
        "zero_candle_response_count": zero_count,
        "unsuccessful_request_count": unsuccessful_count,
        "partial_candidate_quarantined": partial,
        "quarantine_path": quarantine_path,
        "fail_closed": partial,
        "stop_reason": stop_reason,
        "next_resume_chunk_index": int(request_results[-1]["chunk_index"]) + 1 if partial and request_results else None,
        "resume_token": {
            "ticker": plan.get("ticker"),
            "timeframe": plan.get("timeframe"),
            "candidate_output_path": str(candidate_path),
            "next_chunk_index": int(request_results[-1]["chunk_index"]) + 1 if partial and request_results else None,
            "requires_operator_review": bool(partial),
        },
        "next_safe_command": "review_quarantine_and_resume_token_before_any_manual_resume" if partial else "validate_candidate_coverage_before_merge",
        **safety_flags(),
        "state_write_performed": False,
    }


__all__ = [
    "PHASE",
    "RateLimitPolicy",
    "build_rate_limited_fetch_plan",
    "classify_fetch_error",
    "execute_rate_limited_fetch",
    "safety_flags",
]
