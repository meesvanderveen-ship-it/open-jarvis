from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_d6_baseline_backtest import REQUIRED_CANDLE_FIELDS
from bot.phase_d6_coinbase_candle_ingest import assert_research_path
from bot.phase_d6_data_coverage import TIMEFRAME_SPECS


D6_DATASET_QUALITY_PHASE = "D6_dataset_quality_report_v1"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_as_of(value: Any) -> Optional[datetime]:
    if value is None or str(value).strip() == "":
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _decimal(value: Any) -> Optional[Decimal]:
    try:
        if value is None or str(value).strip() == "":
            return None
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _days(seconds: int) -> str:
    return format(Decimal(seconds) / Decimal("86400"), "f").rstrip("0").rstrip(".") or "0"


def _validate_raw_candle(raw: Any) -> tuple[Optional[Dict[str, Any]], List[str]]:
    reasons: List[str] = []
    if not isinstance(raw, dict):
        return None, ["candle_not_object"]
    missing = sorted(REQUIRED_CANDLE_FIELDS - set(raw.keys()))
    if missing:
        reasons.append(f"missing_fields:{','.join(missing)}")
        return None, reasons
    try:
        start = int(raw["start"])
    except (TypeError, ValueError):
        reasons.append("invalid_start")
        return None, reasons

    open_ = _decimal(raw.get("open"))
    high = _decimal(raw.get("high"))
    low = _decimal(raw.get("low"))
    close = _decimal(raw.get("close"))
    volume = _decimal(raw.get("volume"))
    if any(value is None for value in [open_, high, low, close, volume]):
        reasons.append("invalid_decimal_ohlcv")
        return None, reasons
    if open_ <= ZERO or high <= ZERO or low <= ZERO or close <= ZERO:
        reasons.append("non_positive_price")
    if volume < ZERO:
        reasons.append("negative_volume")
    if high < max(open_, low, close):
        reasons.append("high_below_ohlc")
    if low > min(open_, high, close):
        reasons.append("low_above_ohlc")
    if reasons:
        return None, reasons

    return {
        "product_id": str(raw["product_id"]).strip().upper(),
        "timeframe": str(raw["timeframe"]).strip().upper(),
        "start": start,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    }, []


def _gap_count(sorted_starts: List[int], step_seconds: int) -> int:
    return sum(1 for prev, current in zip(sorted_starts, sorted_starts[1:]) if current - prev > step_seconds)


def _quality_class(*, warnings: List[str], fatal_errors: List[str], valid_count: int, expected_count: Optional[int], missing: Optional[int]) -> str:
    if fatal_errors or valid_count == 0:
        return "invalid"
    if expected_count and missing is not None and expected_count > 0:
        missing_ratio = Decimal(missing) / Decimal(expected_count)
        if missing_ratio > Decimal("0.20"):
            return "poor"
    if any(w in warnings for w in ["unsupported_timeframe", "mixed_product_ids", "mixed_timeframes"]):
        return "poor"
    if warnings:
        return "usable_with_warnings"
    return "good"


def build_phase_d6_dataset_quality_report(
    *,
    candles_path: str | Path,
    as_of: Any = None,
) -> Dict[str, Any]:
    path = assert_research_path(candles_path)
    generated_at = _now_iso()
    fatal_errors: List[str] = []
    warnings: List[str] = []
    raw_rows: List[Any] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, list):
            fatal_errors.append("d6_candle_file_must_be_json_array")
        else:
            raw_rows = payload
    except json.JSONDecodeError:
        fatal_errors.append("d6_candle_file_invalid_json")

    valid_rows: List[Dict[str, Any]] = []
    invalid_ohlcv_count = 0
    invalid_reasons: Dict[str, int] = {}
    non_monotonic_count = 0
    previous_start: Optional[int] = None

    for raw in raw_rows:
        candle, reasons = _validate_raw_candle(raw)
        if reasons:
            invalid_ohlcv_count += 1
            for reason in reasons:
                invalid_reasons[reason] = invalid_reasons.get(reason, 0) + 1
            continue
        assert candle is not None
        if previous_start is not None and candle["start"] <= previous_start:
            non_monotonic_count += 1
        previous_start = candle["start"]
        valid_rows.append(candle)

    product_ids = sorted({row["product_id"] for row in valid_rows})
    timeframes = sorted({row["timeframe"] for row in valid_rows})
    product_id = product_ids[0] if len(product_ids) == 1 else None
    timeframe = timeframes[0] if len(timeframes) == 1 else None
    if len(product_ids) > 1:
        warnings.append("mixed_product_ids")
    if len(timeframes) > 1:
        warnings.append("mixed_timeframes")
    if invalid_ohlcv_count:
        warnings.append("invalid_ohlcv_rows_detected")
    if non_monotonic_count:
        warnings.append("non_monotonic_rows_detected")

    starts = [row["start"] for row in valid_rows]
    unique_starts = sorted(set(starts))
    duplicate_count = len(starts) - len(unique_starts)
    if duplicate_count:
        warnings.append("duplicate_start_rows_detected")

    first_start = unique_starts[0] if unique_starts else None
    last_start = unique_starts[-1] if unique_starts else None
    observed_span_seconds = (last_start - first_start) if first_start is not None and last_start is not None else 0
    expected_count: Optional[int] = None
    missing_estimate: Optional[int] = None
    gap_count = 0
    step_seconds: Optional[int] = None

    spec = TIMEFRAME_SPECS.get(timeframe or "")
    if timeframe and not spec:
        warnings.append("unsupported_timeframe")
    if spec and unique_starts:
        step_seconds = spec.seconds
        expected_count = int(observed_span_seconds // step_seconds) + 1
        missing_estimate = max(expected_count - len(unique_starts), 0)
        gap_count = _gap_count(unique_starts, step_seconds)
        if gap_count:
            warnings.append("candle_gaps_detected")
        if missing_estimate:
            warnings.append("missing_candles_estimated")
        if len(unique_starts) < 30:
            warnings.append("short_window_less_than_30_candles")
        as_of_dt = _parse_as_of(as_of)
        if as_of_dt and last_start is not None and last_start + (step_seconds * 2) < int(as_of_dt.timestamp()):
            warnings.append("stale_last_candle")
    elif valid_rows:
        warnings.append("expected_count_unavailable")

    quality_class = _quality_class(
        warnings=warnings,
        fatal_errors=fatal_errors,
        valid_count=len(unique_starts),
        expected_count=expected_count,
        missing=missing_estimate,
    )

    return {
        "generated_at": generated_at,
        "phase": D6_DATASET_QUALITY_PHASE,
        "status": "d6_dataset_quality_report_ready" if quality_class != "invalid" else "d6_dataset_quality_invalid",
        "candles_path": str(path),
        "product_id": product_id,
        "timeframe": timeframe,
        "raw_row_count": len(raw_rows),
        "candle_count": len(unique_starts),
        "valid_candle_row_count": len(valid_rows),
        "first_candle_start": first_start,
        "last_candle_start": last_start,
        "observed_span_seconds": observed_span_seconds,
        "observed_span_days": _days(observed_span_seconds),
        "timeframe_seconds": step_seconds,
        "expected_candle_count": expected_count,
        "missing_candle_estimate": missing_estimate,
        "gap_count": gap_count,
        "duplicate_count": duplicate_count,
        "non_monotonic_count": non_monotonic_count,
        "invalid_ohlcv_count": invalid_ohlcv_count,
        "invalid_reasons": invalid_reasons,
        "quality_class": quality_class,
        "warnings": warnings,
        "fatal_errors": fatal_errors,
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def write_dataset_quality_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_DATASET_QUALITY_PHASE",
    "build_phase_d6_dataset_quality_report",
    "write_dataset_quality_report",
]
