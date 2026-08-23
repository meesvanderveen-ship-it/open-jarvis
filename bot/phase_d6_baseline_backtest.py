from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.phase_d6_data_coverage import TIMEFRAME_SPECS
from bot.phase_d6_coinbase_candle_ingest import assert_research_path


D6_BASELINE_BACKTEST_PHASE = "D6_baseline_backtest_scaffold_v1"
D6_BASELINES = {"buy_hold", "simple_ma"}
REQUIRED_CANDLE_FIELDS = {"product_id", "timeframe", "start", "open", "high", "low", "close", "volume"}
ZERO = Decimal("0")
ONE = Decimal("1")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_str(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
    if denominator == ZERO:
        return ZERO
    return numerator / denominator


def _validate_candle(raw: Dict[str, Any]) -> Dict[str, Any]:
    missing = sorted(REQUIRED_CANDLE_FIELDS - set(raw.keys()))
    if missing:
        raise ValueError(f"candle_missing_required_fields:{','.join(missing)}")
    start = int(raw["start"])
    candle = {
        "product_id": str(raw["product_id"]).strip().upper(),
        "timeframe": str(raw["timeframe"]).strip().upper(),
        "start": start,
        "open": _to_decimal(raw["open"]),
        "high": _to_decimal(raw["high"]),
        "low": _to_decimal(raw["low"]),
        "close": _to_decimal(raw["close"]),
        "volume": _to_decimal(raw["volume"]),
    }
    if candle["close"] <= ZERO:
        raise ValueError("candle_close_must_be_positive")
    return candle


def load_d6_candles(path: str | Path) -> Dict[str, Any]:
    candle_path = assert_research_path(path)
    payload = json.loads(candle_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("d6_candle_file_must_be_json_array")
    dedup: Dict[int, Dict[str, Any]] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            continue
        candle = _validate_candle(raw)
        dedup[candle["start"]] = candle
    candles = [dedup[start] for start in sorted(dedup)]
    if not candles:
        raise ValueError("d6_candle_file_empty_after_validation")
    product_ids = {c["product_id"] for c in candles}
    timeframes = {c["timeframe"] for c in candles}
    if len(product_ids) != 1:
        raise ValueError("d6_candle_file_multiple_products")
    if len(timeframes) != 1:
        raise ValueError("d6_candle_file_multiple_timeframes")
    timeframe = candles[0]["timeframe"]
    gap_count = _gap_count(candles, timeframe)
    return {
        "path": str(candle_path),
        "product_id": candles[0]["product_id"],
        "timeframe": timeframe,
        "candle_count": len(candles),
        "first_candle_start": candles[0]["start"],
        "last_candle_start": candles[-1]["start"],
        "gap_count": gap_count,
        "candles": candles,
    }


def _gap_count(candles: List[Dict[str, Any]], timeframe: str) -> int:
    spec = TIMEFRAME_SPECS.get(timeframe)
    if not spec or len(candles) < 2:
        return 0
    gaps = 0
    for previous, current in zip(candles, candles[1:]):
        if int(current["start"]) - int(previous["start"]) > spec.seconds:
            gaps += 1
    return gaps


def _max_drawdown(equity_curve: Iterable[Decimal]) -> Decimal:
    peak: Optional[Decimal] = None
    max_dd = ZERO
    for value in equity_curve:
        if peak is None or value > peak:
            peak = value
        if peak and peak > ZERO:
            drawdown = (peak - value) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd


def _buy_hold(candles: List[Dict[str, Any]], *, initial_quote: Decimal, fee_pct: Decimal) -> Dict[str, Any]:
    entry = candles[0]["close"]
    exit_price = candles[-1]["close"]
    quote_after_entry_fee = initial_quote * (ONE - fee_pct)
    base = quote_after_entry_fee / entry
    equity_curve = [base * c["close"] for c in candles]
    final_quote = base * exit_price * (ONE - fee_pct)
    fees_quote = initial_quote * fee_pct + (base * exit_price * fee_pct)
    return {
        "trades_count": 1,
        "round_trips": 1,
        "final_quote": final_quote,
        "fees_quote": fees_quote,
        "max_drawdown": _max_drawdown(equity_curve),
        "exposure_pct": ONE,
    }


def _ma(values: List[Decimal], index: int, window: int) -> Optional[Decimal]:
    if index + 1 < window:
        return None
    window_values = values[index + 1 - window:index + 1]
    return sum(window_values, ZERO) / Decimal(window)


def _simple_ma(
    candles: List[Dict[str, Any]],
    *,
    initial_quote: Decimal,
    fee_pct: Decimal,
    fast_window: int = 5,
    slow_window: int = 20,
) -> Dict[str, Any]:
    closes = [c["close"] for c in candles]
    quote = initial_quote
    base = ZERO
    in_position = False
    trades = 0
    exposed_bars = 0
    fees_quote = ZERO
    equity_curve: List[Decimal] = []

    for idx, candle in enumerate(candles):
        close = candle["close"]
        fast = _ma(closes, idx, fast_window)
        slow = _ma(closes, idx, slow_window)
        if fast is not None and slow is not None:
            if not in_position and fast > slow and quote > ZERO:
                fee = quote * fee_pct
                fees_quote += fee
                base = (quote - fee) / close
                quote = ZERO
                in_position = True
                trades += 1
            elif in_position and fast < slow and base > ZERO:
                gross = base * close
                fee = gross * fee_pct
                fees_quote += fee
                quote = gross - fee
                base = ZERO
                in_position = False
                trades += 1

        if in_position:
            exposed_bars += 1
        equity_curve.append(quote + base * close)

    if in_position and base > ZERO:
        gross = base * candles[-1]["close"]
        fee = gross * fee_pct
        fees_quote += fee
        quote = gross - fee
        base = ZERO
        trades += 1
        equity_curve[-1] = quote

    return {
        "trades_count": trades,
        "round_trips": trades // 2,
        "final_quote": quote,
        "fees_quote": fees_quote,
        "max_drawdown": _max_drawdown(equity_curve),
        "exposure_pct": Decimal(exposed_bars) / Decimal(len(candles)) if candles else ZERO,
        "fast_window": fast_window,
        "slow_window": slow_window,
    }


def build_phase_d6_baseline_backtest_report(
    *,
    candles_path: str | Path,
    baseline: str = "buy_hold",
    initial_quote: Any = "1000",
    fee_pct: Any = "0.0040",
) -> Dict[str, Any]:
    baseline_n = str(baseline or "").strip().lower()
    if baseline_n not in D6_BASELINES:
        raise ValueError(f"unsupported_d6_baseline:{baseline}")
    initial = _to_decimal(initial_quote)
    fee = _to_decimal(fee_pct)
    if initial <= ZERO:
        raise ValueError("initial_quote_must_be_positive")
    if fee < ZERO or fee >= ONE:
        raise ValueError("fee_pct_must_be_between_0_and_1")

    loaded = load_d6_candles(candles_path)
    candles = loaded["candles"]
    warnings = [
        "research_scaffold_only",
        "no_post_only_fill_model_yet",
        "no_slippage_model_yet",
        "no_parameter_optimization",
    ]
    if loaded["gap_count"]:
        warnings.append("candle_gaps_detected")

    result = (
        _buy_hold(candles, initial_quote=initial, fee_pct=fee)
        if baseline_n == "buy_hold"
        else _simple_ma(candles, initial_quote=initial, fee_pct=fee)
    )
    final_quote = result["final_quote"]
    net_return = _pct(final_quote - initial, initial)
    report = {
        "generated_at": _now_iso(),
        "phase": D6_BASELINE_BACKTEST_PHASE,
        "status": "d6_baseline_backtest_report_ready",
        "ticker": loaded["product_id"],
        "timeframe": loaded["timeframe"],
        "candles_path": str(assert_research_path(candles_path)),
        "candle_count": loaded["candle_count"],
        "first_candle_start": loaded["first_candle_start"],
        "last_candle_start": loaded["last_candle_start"],
        "gap_count": loaded["gap_count"],
        "baseline_type": baseline_n,
        "baseline_label": f"{baseline_n}_research_scaffold",
        "initial_quote": _decimal_str(initial),
        "final_quote": _decimal_str(final_quote),
        "net_return": _decimal_str(net_return),
        "net_return_pct": _decimal_str(net_return * Decimal("100")),
        "max_drawdown": _decimal_str(result["max_drawdown"]),
        "max_drawdown_pct": _decimal_str(result["max_drawdown"] * Decimal("100")),
        "trades_count": result["trades_count"],
        "round_trips": result["round_trips"],
        "exposure_pct": _decimal_str(result["exposure_pct"]),
        "fees_assumption_pct": _decimal_str(fee),
        "fees_paid_quote_estimate": _decimal_str(result["fees_quote"]),
        "post_only_fill_model": "not_modeled_v1",
        "warnings": warnings,
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }
    if baseline_n == "simple_ma":
        report["simple_ma"] = {
            "fast_window": result["fast_window"],
            "slow_window": result["slow_window"],
            "fixed_scaffold_parameters": True,
        }
    return report


def write_report(report: Dict[str, Any], output_path: str | Path) -> Path:
    path = assert_research_path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


__all__ = [
    "D6_BASELINE_BACKTEST_PHASE",
    "D6_BASELINES",
    "load_d6_candles",
    "build_phase_d6_baseline_backtest_report",
    "write_report",
]
