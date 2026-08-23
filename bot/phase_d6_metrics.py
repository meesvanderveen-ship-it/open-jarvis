from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List


D6_METRICS_PHASE = "D6_metrics_foundation_v1"
ZERO = Decimal("0")
ONE = Decimal("1")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or str(value).strip() == "":
            return Decimal(default)
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def decimal_str(value: Any) -> str:
    text = format(to_decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def ratio(numerator: Any, denominator: Any) -> Decimal:
    denom = to_decimal(denominator)
    if denom == ZERO:
        return ZERO
    return to_decimal(numerator) / denom


def pct_decimal(value: Any) -> Decimal:
    return to_decimal(value) * Decimal("100")


def net_return(initial_quote: Any, final_quote: Any) -> Decimal:
    initial = to_decimal(initial_quote)
    if initial == ZERO:
        return ZERO
    return (to_decimal(final_quote) - initial) / initial


def max_drawdown(equity_curve: Iterable[Any]) -> Decimal:
    peak = None
    max_dd = ZERO
    for raw in equity_curve:
        value = to_decimal(raw)
        if peak is None or value > peak:
            peak = value
        if peak and peak > ZERO:
            drawdown = (peak - value) / peak
            if drawdown > max_dd:
                max_dd = drawdown
    return max_dd


def exposure_ratio(exposed_bars: Any, total_bars: Any) -> Decimal:
    return ratio(exposed_bars, total_bars)


def build_return_metrics(*, initial_quote: Any, final_quote: Any) -> Dict[str, str]:
    value = net_return(initial_quote, final_quote)
    return {
        "initial_quote": decimal_str(initial_quote),
        "final_quote": decimal_str(final_quote),
        "net_return": decimal_str(value),
        "net_return_pct": decimal_str(pct_decimal(value)),
    }


def build_drawdown_metrics(equity_curve: Iterable[Any]) -> Dict[str, str]:
    value = max_drawdown(equity_curve)
    return {
        "max_drawdown": decimal_str(value),
        "max_drawdown_pct": decimal_str(pct_decimal(value)),
    }


def build_exposure_metrics(*, exposed_bars: Any, total_bars: Any) -> Dict[str, Any]:
    exposed = to_decimal(exposed_bars)
    total = to_decimal(total_bars)
    value = exposure_ratio(exposed, total)
    return {
        "exposed_bars": int(exposed) if exposed == exposed.to_integral_value() else decimal_str(exposed),
        "total_bars": int(total) if total == total.to_integral_value() else decimal_str(total),
        "exposure": decimal_str(value),
        "exposure_pct": decimal_str(pct_decimal(value)),
    }


def build_trade_metrics(*, trades_count: Any = 0, round_trips: Any = None, wins: Any = None, losses: Any = None) -> Dict[str, Any]:
    trades = int(to_decimal(trades_count))
    round_trip_count = int(to_decimal(round_trips if round_trips is not None else trades // 2))
    win_count = int(to_decimal(wins)) if wins is not None else None
    loss_count = int(to_decimal(losses)) if losses is not None else None
    out: Dict[str, Any] = {
        "trades_count": trades,
        "round_trips": round_trip_count,
    }
    if win_count is not None:
        out["wins"] = win_count
    if loss_count is not None:
        out["losses"] = loss_count
    if win_count is not None and loss_count is not None:
        out["winrate"] = decimal_str(ratio(win_count, win_count + loss_count))
        out["winrate_pct"] = decimal_str(pct_decimal(out["winrate"]))
    return out


def build_fee_metrics(*, fees_quote: Any = 0, initial_quote: Any = 0) -> Dict[str, str]:
    fees = to_decimal(fees_quote)
    initial = to_decimal(initial_quote)
    fee_ratio = ratio(fees, initial)
    return {
        "fees_paid_quote_estimate": decimal_str(fees),
        "fees_to_initial_quote": decimal_str(fee_ratio),
        "fees_to_initial_quote_pct": decimal_str(pct_decimal(fee_ratio)),
    }


def build_metric_warnings(
    *,
    trades_count: Any = 0,
    max_drawdown_value: Any = 0,
    exposure_value: Any = 0,
    data_quality_ready: bool = True,
    split_usable: bool = True,
    min_trades: int = 3,
    high_drawdown_threshold: Any = "0.30",
) -> List[str]:
    warnings: List[str] = []
    if int(to_decimal(trades_count)) < int(min_trades):
        warnings.append("too_few_trades")
    if to_decimal(max_drawdown_value) >= to_decimal(high_drawdown_threshold):
        warnings.append("high_drawdown")
    if to_decimal(exposure_value) == ZERO:
        warnings.append("zero_exposure")
    if not data_quality_ready:
        warnings.append("data_quality_blocked")
    if not split_usable:
        warnings.append("split_unusable")
    return warnings


def d6_metric_safety_flags() -> Dict[str, bool]:
    return {
        "research_only": True,
        "no_live_action": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
        "no_bulk_fetch": True,
        "no_optimization": True,
        "parameter_search_performed": False,
        "signal_generation_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_change_allowed": False,
    }


def build_phase_d6_metrics_report(
    *,
    initial_quote: Any,
    final_quote: Any,
    equity_curve: Iterable[Any],
    exposed_bars: Any,
    total_bars: Any,
    trades_count: Any = 0,
    round_trips: Any = None,
    fees_quote: Any = 0,
    data_quality_ready: bool = True,
    split_usable: bool = True,
) -> Dict[str, Any]:
    equity_values = list(equity_curve)
    return_metrics = build_return_metrics(initial_quote=initial_quote, final_quote=final_quote)
    drawdown_metrics = build_drawdown_metrics(equity_values)
    exposure_metrics = build_exposure_metrics(exposed_bars=exposed_bars, total_bars=total_bars)
    trade_metrics = build_trade_metrics(trades_count=trades_count, round_trips=round_trips)
    fee_metrics = build_fee_metrics(fees_quote=fees_quote, initial_quote=initial_quote)
    warnings = build_metric_warnings(
        trades_count=trade_metrics["trades_count"],
        max_drawdown_value=drawdown_metrics["max_drawdown"],
        exposure_value=exposure_metrics["exposure"],
        data_quality_ready=data_quality_ready,
        split_usable=split_usable,
    )
    return {
        "generated_at": now_iso(),
        "phase": D6_METRICS_PHASE,
        "status": "d6_metrics_report_ready",
        "metric_inputs_summary": {
            "equity_curve_points": len(equity_values),
            "data_quality_ready": bool(data_quality_ready),
            "split_usable": bool(split_usable),
        },
        "return_metrics": return_metrics,
        "drawdown_metrics": drawdown_metrics,
        "exposure_metrics": exposure_metrics,
        "trade_metrics": trade_metrics,
        "fee_metrics": fee_metrics,
        "warnings": warnings,
        **d6_metric_safety_flags(),
    }


__all__ = [
    "D6_METRICS_PHASE",
    "ZERO",
    "ONE",
    "to_decimal",
    "decimal_str",
    "ratio",
    "pct_decimal",
    "net_return",
    "max_drawdown",
    "exposure_ratio",
    "build_return_metrics",
    "build_drawdown_metrics",
    "build_exposure_metrics",
    "build_trade_metrics",
    "build_fee_metrics",
    "build_metric_warnings",
    "d6_metric_safety_flags",
    "build_phase_d6_metrics_report",
]
