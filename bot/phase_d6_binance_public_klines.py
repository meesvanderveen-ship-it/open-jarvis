from __future__ import annotations

import json
import random
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional

from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import TIMEFRAME_SPECS, normalize_timeframes
from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE = "D6_binance_public_klines_reference_v1"
BINANCE_PUBLIC_MARKET_DATA_BASE_URL = "https://data-api.binance.vision"
KLINES_ENDPOINT = "/api/v3/klines"
BINANCE_KLINES_WEIGHT = 2
MAX_BINANCE_KLINES_LIMIT = 1000

SYMBOL_MAPPINGS: Dict[str, Dict[str, Dict[str, str]]] = {
    "BTC-USDC": {
        "primary_reference": {
            "binance_symbol": "BTCUSDC",
            "base_asset": "BTC",
            "quote_asset": "USDC",
            "quote_asset_warning": "",
        },
        "different_quote_reference": {
            "binance_symbol": "BTCUSDT",
            "base_asset": "BTC",
            "quote_asset": "USDT",
            "quote_asset_warning": "different_quote_asset_reference_only",
        },
    }
}

INTERVAL_MAPPING = {
    "1H": "1h",
    "4H": "4h",
    "1D": "1d",
}


@dataclass(frozen=True)
class BinanceRateLimitPolicy:
    max_requests_per_minute: int = 6
    max_requests_per_run: int = 2
    min_delay_seconds: float = 1.0
    max_retries_per_request: int = 1
    retry_budget_total: int = 1
    backoff_base_seconds: float = 1.0
    backoff_max_seconds: float = 6.0
    jitter_seconds: float = 0.25
    max_consecutive_errors: int = 1
    request_timeout_seconds: float = 10.0
    stop_on_zero_candle_response: bool = True
    stop_on_partial_candidate: bool = True

    def validate(self) -> None:
        if self.max_requests_per_minute <= 0:
            raise ValueError("binance_max_requests_per_minute_must_be_positive")
        if self.max_requests_per_run <= 0:
            raise ValueError("binance_max_requests_per_run_must_be_positive")
        if self.min_delay_seconds < 0:
            raise ValueError("binance_min_delay_seconds_must_not_be_negative")
        if self.max_retries_per_request < 0:
            raise ValueError("binance_max_retries_per_request_must_not_be_negative")
        if self.retry_budget_total < 0:
            raise ValueError("binance_retry_budget_total_must_not_be_negative")
        if self.backoff_base_seconds < 0 or self.backoff_max_seconds < 0 or self.jitter_seconds < 0:
            raise ValueError("binance_backoff_values_must_not_be_negative")
        if self.max_consecutive_errors <= 0:
            raise ValueError("binance_max_consecutive_errors_must_be_positive")
        if self.request_timeout_seconds <= 0:
            raise ValueError("binance_request_timeout_seconds_must_be_positive")


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
        "api_key_used": False,
        "state_write_performed": False,
        "synthetic_ohlcv_created": False,
        "external_candle_written_as_coinbase_candle": False,
    }


def _iso_from_ts(ts: int) -> str:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_decimal_str(value: Any) -> str:
    try:
        if value is None or str(value).strip() == "":
            return "0"
        return format(Decimal(str(value)), "f")
    except (InvalidOperation, TypeError, ValueError):
        return "0"


def _mapping_for(product_id: str, symbol: str | None = None) -> Dict[str, str]:
    product = str(product_id).upper()
    mappings = SYMBOL_MAPPINGS.get(product)
    if not mappings:
        raise ValueError("binance_symbol_mapping_not_defined")
    if symbol:
        symbol_n = str(symbol).upper()
        for mapping_type, mapping in mappings.items():
            if mapping["binance_symbol"] == symbol_n:
                return {**mapping, "mapping_type": mapping_type}
        raise ValueError("binance_symbol_not_allowed_for_coinbase_product")
    return {**mappings["primary_reference"], "mapping_type": "primary_reference"}


def _candidate_path(*, candidate_root: str | Path, product_id: str, timeframe: str, symbol: str, run_id: str) -> Path:
    return (
        assert_research_path(candidate_root)
        / "source=binance"
        / f"venue=binance_spot"
        / f"mapped_coinbase_product={product_id.upper()}"
        / f"symbol={symbol.upper()}"
        / f"timeframe={timeframe}"
        / f"{run_id}.json"
    )


def build_multi_source_candle_policy_v1() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "multi_source_candle_policy_v1",
        "status": "multi_source_candle_policy_ready",
        "venue_roles": {
            "coinbase": "primary_execution_venue",
            "binance": "secondary_reference_venue",
        },
        "storage_policy": {
            "coinbase_raw_cache": "coinbase_candles_only",
            "external_candidate_root": "/tmp",
            "external_reference_allowed_paths": [
                "research_data/external_candles/source=binance",
                "research_data/cross_venue_candles",
            ],
            "external_as_coinbase_raw_cache_allowed": False,
            "synthetic_coinbase_ohlcv_allowed": False,
        },
        "required_provenance_fields": [
            "source",
            "venue",
            "symbol",
            "mapped_coinbase_product",
            "timeframe",
            "open_time",
            "quote_asset",
            "fetched_at",
            "endpoint",
            "request_cost",
            "transformation_applied",
        ],
        "allowed_uses": [
            "exploratory_cross_venue_analysis",
            "gap_diagnostic",
            "robustness_check",
            "cross_source_sanity_report",
        ],
        "disallowed_uses": [
            "normal_backtest_permission_from_secondary_source",
            "coinbase_raw_cache_repair_with_external_candle",
            "runtime_parameter_decision",
            "learning_to_runtime_bridge",
        ],
        "normal_backtest_gate": {
            "requires_primary_coinbase_quality": True,
            "secondary_reference_can_override_primary_gap": False,
            "normal_backtests_remain_deferred": True,
        },
        **safety_flags(),
    }


def build_binance_klines_plan(
    *,
    mapped_coinbase_product: str,
    timeframe: str,
    start: int,
    end_exclusive: int,
    candidate_root: str | Path,
    run_id: str,
    symbol: str | None = None,
    base_url: str = BINANCE_PUBLIC_MARKET_DATA_BASE_URL,
    limit: int = 1,
    policy: BinanceRateLimitPolicy | None = None,
) -> Dict[str, Any]:
    policy = policy or BinanceRateLimitPolicy()
    policy.validate()
    timeframe_n = normalize_timeframes([timeframe])[0]
    if timeframe_n not in INTERVAL_MAPPING:
        raise ValueError("binance_interval_mapping_not_defined")
    if end_exclusive <= start:
        raise ValueError("binance_kline_end_must_be_after_start")
    limit_n = int(limit)
    if limit_n <= 0 or limit_n > MAX_BINANCE_KLINES_LIMIT:
        raise ValueError("binance_kline_limit_out_of_bounds")
    mapping = _mapping_for(mapped_coinbase_product, symbol)
    query = {
        "symbol": mapping["binance_symbol"],
        "interval": INTERVAL_MAPPING[timeframe_n],
        "startTime": int(start) * 1000,
        "endTime": int(end_exclusive) * 1000,
        "limit": limit_n,
    }
    url = f"{base_url.rstrip('/')}{KLINES_ENDPOINT}?{urllib.parse.urlencode(query)}"
    blockers: List[str] = []
    request_count = 1
    if request_count > policy.max_requests_per_minute:
        blockers.append("binance_planned_requests_exceed_one_minute_policy")
    if request_count > policy.max_requests_per_run:
        blockers.append("binance_planned_requests_exceed_run_policy")
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "binance_public_klines_plan_v1",
        "status": "binance_public_klines_plan_ready" if not blockers else "binance_public_klines_plan_blocked",
        "source": "binance",
        "venue": "binance_spot",
        "endpoint": KLINES_ENDPOINT,
        "base_url": base_url.rstrip("/"),
        "mapped_coinbase_product": mapped_coinbase_product.upper(),
        "symbol": mapping["binance_symbol"],
        "mapping_type": mapping["mapping_type"],
        "quote_asset": mapping["quote_asset"],
        "quote_asset_warning": mapping["quote_asset_warning"],
        "timeframe": timeframe_n,
        "binance_interval": INTERVAL_MAPPING[timeframe_n],
        "expected_start": int(start),
        "expected_end_exclusive": int(end_exclusive),
        "expected_start_iso": _iso_from_ts(int(start)),
        "expected_end_exclusive_iso": _iso_from_ts(int(end_exclusive)),
        "limit": limit_n,
        "request_count": request_count,
        "request_weight_per_call": BINANCE_KLINES_WEIGHT,
        "request_cost": BINANCE_KLINES_WEIGHT * request_count,
        "request_url": url,
        "candidate_output_path": str(
            _candidate_path(
                candidate_root=candidate_root,
                product_id=mapped_coinbase_product,
                timeframe=timeframe_n,
                symbol=mapping["binance_symbol"],
                run_id=run_id,
            )
        ),
        "policy": policy.__dict__,
        "blockers": blockers,
        "dry_run": True,
        "fetch_executed": False,
        **safety_flags(),
    }


def _default_http_get(url: str, *, timeout: float) -> Dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "coinbase-bot-d6-research/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        body = response.read().decode("utf-8")
        return {"status_code": int(getattr(response, "status", 200)), "body": body}


def classify_binance_fetch_error(error: BaseException | str, *, zero_candle: bool = False, partial: bool = False) -> str:
    if zero_candle:
        return "zero_candle_response"
    if partial:
        return "candidate_incomplete"
    text = str(error).lower()
    if "429" in text or "418" in text or "rate" in text or "too many" in text:
        return "rate_limit_error"
    if any(token in text for token in ["timeout", "network", "connection", "dns", "temporarily unavailable"]):
        return "network_error"
    return "fetch_error"


def _backoff(policy: BinanceRateLimitPolicy, *, attempt: int, rng: random.Random) -> float:
    base = min(policy.backoff_max_seconds, policy.backoff_base_seconds * (2 ** max(attempt - 1, 0)))
    return base + rng.uniform(0, policy.jitter_seconds)


def normalize_binance_klines(
    rows: Iterable[Any],
    *,
    plan: Dict[str, Any],
    fetched_at: datetime,
) -> List[Dict[str, Any]]:
    dedup: Dict[int, Dict[str, Any]] = {}
    fetched_at_iso = fetched_at.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    for raw in rows or []:
        if not isinstance(raw, list) or len(raw) < 6:
            continue
        try:
            open_time_ms = int(raw[0])
        except (TypeError, ValueError):
            continue
        open_time = open_time_ms // 1000
        dedup[open_time] = {
            "source": "binance",
            "venue": "binance_spot",
            "symbol": plan["symbol"],
            "mapped_coinbase_product": plan["mapped_coinbase_product"],
            "timeframe": plan["timeframe"],
            "open_time": open_time,
            "open_time_ms": open_time_ms,
            "open_time_iso": _iso_from_ts(open_time),
            "open": _to_decimal_str(raw[1]),
            "high": _to_decimal_str(raw[2]),
            "low": _to_decimal_str(raw[3]),
            "close": _to_decimal_str(raw[4]),
            "volume": _to_decimal_str(raw[5]),
            "quote_asset": plan["quote_asset"],
            "quote_asset_warning": plan.get("quote_asset_warning", ""),
            "fetched_at": fetched_at_iso,
            "endpoint": plan["endpoint"],
            "request_cost": plan["request_weight_per_call"],
            "response_weight": plan["request_weight_per_call"],
            "transformation_applied": "normalized_binance_kline_array_to_external_reference_schema",
            "provenance": {
                "source": "binance",
                "venue": "binance_spot",
                "base_url": plan.get("base_url"),
                "endpoint": plan.get("endpoint"),
                "request_url": plan.get("request_url"),
                "mapping_type": plan.get("mapping_type"),
            },
        }
    return [dedup[start] for start in sorted(dedup)]


def execute_binance_klines_fetch(
    *,
    plan: Dict[str, Any],
    http_get: Callable[[str], Dict[str, Any]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    now_fn: Callable[[], float] = time.monotonic,
    fetched_at: datetime | None = None,
    rng_seed: int = 60601,
) -> Dict[str, Any]:
    if plan.get("blockers"):
        raise ValueError("binance_klines_plan_has_blockers")
    policy = BinanceRateLimitPolicy(**dict(plan.get("policy") or {}))
    policy.validate()
    fetched_at_dt = fetched_at or datetime.now(timezone.utc)
    getter = http_get or (lambda url: _default_http_get(url, timeout=policy.request_timeout_seconds))
    rng = random.Random(rng_seed)
    attempts = 0
    retries = 0
    errors: List[Dict[str, Any]] = []
    response_status: Optional[int] = None
    raw_rows: List[Any] = []
    last_call_at: Optional[float] = None
    consecutive_errors = 0
    while attempts <= policy.max_retries_per_request:
        if last_call_at is not None:
            elapsed = now_fn() - last_call_at
            if elapsed < policy.min_delay_seconds:
                sleep_fn(policy.min_delay_seconds - elapsed)
        attempts += 1
        try:
            last_call_at = now_fn()
            response = getter(plan["request_url"])
            response_status = int(response.get("status_code", 200))
            if response_status >= 400:
                raise RuntimeError(f"binance_http_{response_status}")
            loaded = json.loads(str(response.get("body", "[]")))
            if not isinstance(loaded, list):
                raise RuntimeError("binance_klines_response_not_list")
            raw_rows = loaded
            consecutive_errors = 0
            break
        except Exception as exc:  # pragma: no cover - network failures depend on environment.
            consecutive_errors += 1
            errors.append(
                {
                    "attempt": attempts,
                    "error_type": type(exc).__name__,
                    "error_classification": classify_binance_fetch_error(exc),
                    "error": str(exc),
                    "consecutive_errors": consecutive_errors,
                }
            )
            if (
                attempts > policy.max_retries_per_request
                or retries >= policy.retry_budget_total
                or consecutive_errors >= policy.max_consecutive_errors
            ):
                break
            retries += 1
            sleep_fn(_backoff(policy, attempt=attempts, rng=rng))
    candles = normalize_binance_klines(raw_rows, plan=plan, fetched_at=fetched_at_dt)
    zero = not raw_rows and not errors
    expected_start = int(plan["expected_start"])
    expected_end = int(plan["expected_end_exclusive"])
    in_window = [row for row in candles if expected_start <= int(row["open_time"]) < expected_end]
    exact_expected_start_found = any(int(row["open_time"]) == expected_start for row in in_window)
    partial = bool(errors) or (zero and policy.stop_on_zero_candle_response)
    if policy.stop_on_partial_candidate and candles and not exact_expected_start_found:
        partial = True
    candidate_path = assert_research_path(plan["candidate_output_path"])
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    candidate_path.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    quarantine_path = ""
    if partial:
        quarantine = candidate_path.with_suffix(".quarantine.json")
        quarantine.write_text(json.dumps(candles, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        quarantine_path = str(quarantine)
    stop_reason = ""
    if errors:
        stop_reason = "binance_retry_budget_or_error_limit_reached"
    elif zero:
        stop_reason = "binance_zero_candle_response_fail_closed"
    elif candles and not exact_expected_start_found:
        stop_reason = "binance_candidate_missing_expected_start"
    return {
        **dict(plan),
        "generated_at": now_iso(),
        "status": "binance_public_klines_fetch_blocked" if partial else "binance_public_klines_fetch_ready",
        "dry_run": False,
        "fetch_executed": True,
        "binance_public_market_data_call_count": attempts,
        "binance_public_market_data_call_performed": attempts > 0,
        "retry_count": retries,
        "response_status": response_status,
        "raw_kline_count": len(raw_rows),
        "candidate_count": len(candles),
        "first_open_time": candles[0]["open_time"] if candles else None,
        "last_open_time": candles[-1]["open_time"] if candles else None,
        "exact_expected_start_found": exact_expected_start_found,
        "zero_candle_response_count": 1 if zero else 0,
        "partial_candidate_quarantined": partial,
        "quarantine_path": quarantine_path,
        "fail_closed": partial,
        "stop_reason": stop_reason,
        "errors": errors,
        "candidate_output_path": str(candidate_path),
        "resume_token": {
            "source": "binance",
            "symbol": plan.get("symbol"),
            "mapped_coinbase_product": plan.get("mapped_coinbase_product"),
            "requires_operator_review": bool(partial),
        },
        "next_safe_command": "review_binance_reference_candidate_before_any_followup" if partial else "build_cross_source_diagnostic_report",
        **safety_flags(),
    }


def build_btc_4h_gap_reference_report(*, fetch_result: Dict[str, Any] | None) -> Dict[str, Any]:
    result = dict(fetch_result or {})
    available = bool(result.get("exact_expected_start_found")) and not bool(result.get("fail_closed"))
    if not result:
        status = "binance_reference_fetch_not_run"
        classification = "external_reference_not_checked"
    elif available:
        status = "binance_reference_available"
        classification = "external_reference_available"
    elif result.get("zero_candle_response_count"):
        status = "binance_reference_missing"
        classification = "external_reference_missing"
    else:
        status = "binance_reference_inconclusive_fail_closed"
        classification = "external_reference_inconclusive"
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "binance_btcusdc_4h_gap_reference_v1",
        "status": status,
        "coinbase_gap": {
            "mapped_coinbase_product": "BTC-USDC",
            "timeframe": "4H",
            "missing_expected_start": 1761408000,
            "missing_expected_start_iso": _iso_from_ts(1761408000),
            "coinbase_raw_gap_preserved": True,
            "coinbase_raw_cache_mutated": False,
        },
        "binance_reference": {
            "classification": classification,
            "source": result.get("source", "binance"),
            "venue": result.get("venue", "binance_spot"),
            "symbol": result.get("symbol", "BTCUSDC"),
            "quote_asset": result.get("quote_asset", "USDC"),
            "candidate_output_path": result.get("candidate_output_path", ""),
            "candidate_count": result.get("candidate_count", 0),
            "exact_expected_start_found": result.get("exact_expected_start_found", False),
            "request_cost": result.get("request_cost", 0),
            "errors": result.get("errors", []),
            "fail_closed": result.get("fail_closed", False),
        },
        "normal_backtest_permission_changed": False,
        "exploratory_cross_venue_analysis_allowed": bool(available),
        "notes": [
            "external_reference_does_not_repair_coinbase_execution_market_data",
            "coinbase_known_gap_policy_remains_visible",
        ],
        **safety_flags(),
    }


def build_btc_1h_cross_source_gap_support_plan() -> Dict[str, Any]:
    return {
        "generated_at": now_iso(),
        "phase": PHASE,
        "report_name": "btc_1h_cross_source_gap_support_plan_v1",
        "status": "btc_1h_cross_source_gap_support_plan_ready",
        "objective": "support_coinbase_btc_1h_staged_gap_diagnostics_with_secondary_reference_only",
        "rules": [
            "coinbase_remains_primary_execution_market_dataset",
            "binance_reference_may_classify_market_wide_or_coinbase_specific_missing_intervals",
            "binance_reference_must_not_replace_coinbase_raw_cache",
            "one_reference_window_per_operator_review_cycle_by_default",
            "auto_resume_disabled_after_partial_or_validation_failure",
        ],
        "candidate_validation_support": {
            "compare_expected_open_times": True,
            "compare_directional_ohlcv_sanity": True,
            "permit_merge_to_coinbase_cache_based_on_binance": False,
            "permit_normal_backtest_release_based_on_binance": False,
        },
        "next_safe_scope": {
            "mapped_coinbase_product": "BTC-USDC",
            "timeframe": "1H",
            "max_reference_requests": 1,
            "max_candles": 24,
            "requires_clean_btcusdc_4h_reference_diagnostic_or_operator_review": True,
        },
        **safety_flags(),
    }


__all__ = [
    "BINANCE_PUBLIC_MARKET_DATA_BASE_URL",
    "BinanceRateLimitPolicy",
    "KLINES_ENDPOINT",
    "PHASE",
    "build_binance_klines_plan",
    "build_btc_1h_cross_source_gap_support_plan",
    "build_btc_4h_gap_reference_report",
    "build_multi_source_candle_policy_v1",
    "classify_binance_fetch_error",
    "execute_binance_klines_fetch",
    "normalize_binance_klines",
    "safety_flags",
]
