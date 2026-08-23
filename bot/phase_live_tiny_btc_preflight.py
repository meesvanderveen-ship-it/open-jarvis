from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List

from bot.phase_d6_metrics import d6_metric_safety_flags, now_iso


PHASE_LIVE_TINY_BTC_PREFLIGHT = "btc_usdc_tiny_live_preflight_v1"
PROVEN_PRODUCT = "BTC-USDC"
MAX_TINY_QUOTE_USDC = Decimal("10")
ACTUAL_SUBMIT_ACK = "I_APPROVE_BTC_USDC_TINY_24H_ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_MAX_10_USDC"


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer value: {value!r}") from exc


def _bool(value: Any) -> bool:
    return bool(value)


def _tickers(values: Iterable[Any] | None) -> List[str]:
    result: List[str] = []
    for value in values or []:
        ticker = str(value).strip().upper()
        if ticker:
            result.append(ticker)
    return result


def _pass_or_block(condition: bool, passed: List[str], blockers: List[str], pass_name: str, block_name: str) -> None:
    if condition:
        passed.append(pass_name)
    else:
        blockers.append(block_name)


def _snapshot(cfg: Any) -> Dict[str, Any]:
    fields = {
        "execution_mode": getattr(cfg, "execution_mode", None),
        "allowed_tickers": _tickers(getattr(cfg, "allowed_tickers", [])),
        "phase_c_allowed_tickers": _tickers(getattr(cfg, "phase_c_allowed_tickers", [])),
        "default_quote_size_usdc": str(getattr(cfg, "default_quote_size_usdc", "")),
        "max_notional_usd": str(getattr(cfg, "max_notional_usd", "")),
        "phase_c_max_order_quote": str(getattr(cfg, "phase_c_max_order_quote", "")),
        "autonomous_max_order_quote": str(getattr(cfg, "autonomous_max_order_quote", "")),
        "max_new_orders_per_cycle": getattr(cfg, "max_new_orders_per_cycle", None),
        "phase_c_max_new_orders_per_cycle": getattr(cfg, "phase_c_max_new_orders_per_cycle", None),
        "autonomous_max_new_orders_per_cycle": getattr(cfg, "autonomous_max_new_orders_per_cycle", None),
        "max_open_positions": getattr(cfg, "max_open_positions", None),
        "phase_c_max_open_entry_orders": getattr(cfg, "phase_c_max_open_entry_orders", None),
        "autonomous_max_open_orders": getattr(cfg, "autonomous_max_open_orders", None),
        "enable_live_exit_orders": _bool(getattr(cfg, "enable_live_exit_orders", False)),
        "enable_phase_d3_actual_exit_submit": _bool(getattr(cfg, "enable_phase_d3_actual_exit_submit", False)),
        "autonomous_allow_exits": _bool(getattr(cfg, "autonomous_allow_exits", False)),
        "phase_c_disable_exit_limit_orders": _bool(getattr(cfg, "phase_c_disable_exit_limit_orders", True)),
        "enable_phase_c_actual_coinbase_submit": _bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "enable_phase_c_live_small_limit_orders": _bool(getattr(cfg, "enable_phase_c_live_small_limit_orders", False)),
        "enable_live_limit_orders": _bool(getattr(cfg, "enable_live_limit_orders", False)),
        "enable_live_entry_orders": _bool(getattr(cfg, "enable_live_entry_orders", False)),
        "enable_autonomous_small_live_orderbook_mode": _bool(getattr(cfg, "enable_autonomous_small_live_orderbook_mode", False)),
    }
    return fields


def build_btc_usdc_tiny_live_preflight_report(
    cfg: Any,
    *,
    generated_at: str | None = None,
    actual_submit_ack: str = "",
    require_actual_submit_enabled: bool = False,
) -> Dict[str, Any]:
    passed: List[str] = []
    blockers: List[str] = []
    snapshot = _snapshot(cfg)
    exact_ack = actual_submit_ack == ACTUAL_SUBMIT_ACK

    allowed = snapshot["allowed_tickers"]
    phase_c_allowed = snapshot["phase_c_allowed_tickers"]

    _pass_or_block(allowed == [PROVEN_PRODUCT], passed, blockers, "allowed_tickers_btc_usdc_only", "allowed_tickers_not_btc_usdc_only")
    _pass_or_block(
        phase_c_allowed == [PROVEN_PRODUCT],
        passed,
        blockers,
        "phase_c_allowed_tickers_btc_usdc_only",
        "phase_c_allowed_tickers_not_btc_usdc_only",
    )

    for key in ("default_quote_size_usdc", "max_notional_usd", "phase_c_max_order_quote", "autonomous_max_order_quote"):
        try:
            value = _dec(snapshot[key])
        except ValueError:
            blockers.append(f"{key}_invalid")
            continue
        _pass_or_block(value > Decimal("0") and value <= MAX_TINY_QUOTE_USDC, passed, blockers, f"{key}_lte_10_usdc", f"{key}_above_10_usdc")

    for key in ("max_new_orders_per_cycle", "phase_c_max_new_orders_per_cycle", "autonomous_max_new_orders_per_cycle"):
        try:
            value = _int(snapshot[key])
        except ValueError:
            blockers.append(f"{key}_invalid")
            continue
        _pass_or_block(value == 1, passed, blockers, f"{key}_is_1", f"{key}_not_1")

    for key in ("max_open_positions", "phase_c_max_open_entry_orders", "autonomous_max_open_orders"):
        try:
            value = _int(snapshot[key])
        except ValueError:
            blockers.append(f"{key}_invalid")
            continue
        _pass_or_block(value == 1, passed, blockers, f"{key}_is_1", f"{key}_not_1")

    _pass_or_block(not snapshot["enable_live_exit_orders"], passed, blockers, "enable_live_exit_orders_false", "enable_live_exit_orders_true")
    _pass_or_block(
        not snapshot["enable_phase_d3_actual_exit_submit"],
        passed,
        blockers,
        "enable_phase_d3_actual_exit_submit_false",
        "enable_phase_d3_actual_exit_submit_true",
    )
    _pass_or_block(not snapshot["autonomous_allow_exits"], passed, blockers, "autonomous_allow_exits_false", "autonomous_allow_exits_true")
    _pass_or_block(snapshot["phase_c_disable_exit_limit_orders"], passed, blockers, "phase_c_disable_exit_limit_orders_true", "phase_c_disable_exit_limit_orders_false")

    actual_submit = snapshot["enable_phase_c_actual_coinbase_submit"]
    if require_actual_submit_enabled:
        _pass_or_block(exact_ack, passed, blockers, "actual_submit_ack_exact", "actual_submit_ack_missing_or_invalid")
        _pass_or_block(actual_submit, passed, blockers, "enable_phase_c_actual_coinbase_submit_true_after_ack", "enable_phase_c_actual_coinbase_submit_false_for_armed_start")
    elif actual_submit:
        _pass_or_block(exact_ack, passed, blockers, "actual_submit_enabled_with_exact_ack", "enable_phase_c_actual_coinbase_submit_true_without_exact_ack")
    else:
        passed.append("enable_phase_c_actual_coinbase_submit_false_pre_ack")

    safety_flags = d6_metric_safety_flags()
    _pass_or_block(
        safety_flags.get("learning_to_execution_allowed") is False,
        passed,
        blockers,
        "learning_to_execution_allowed_false",
        "learning_to_execution_allowed_true",
    )
    _pass_or_block(
        safety_flags.get("parameter_change_allowed") is False,
        passed,
        blockers,
        "parameter_change_allowed_false",
        "parameter_change_allowed_true",
    )

    status = "pass_btc_usdc_tiny_preflight" if not blockers else "blocked_btc_usdc_tiny_preflight"
    return {
        "generated_at": generated_at or now_iso(),
        "phase": PHASE_LIVE_TINY_BTC_PREFLIGHT,
        "status": status,
        "passed_checks": passed,
        "blockers": blockers,
        "effective_config": snapshot,
        "required_scope": {
            "allowed_tickers": [PROVEN_PRODUCT],
            "phase_c_allowed_tickers": [PROVEN_PRODUCT],
            "max_quote_or_notional_usdc": str(MAX_TINY_QUOTE_USDC),
            "max_new_orders_per_cycle": 1,
            "max_open_orders": 1,
            "live_exits_enabled": False,
            "learning_to_execution_allowed": False,
            "all_ticker_scope_allowed": False,
            "actual_submit_ack": ACTUAL_SUBMIT_ACK,
        },
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "env_mutation_performed": False,
        "learning_to_execution_allowed": False,
        "parameter_review_allowed": False,
        "parameter_review_approved": False,
        **safety_flags,
    }


__all__ = [
    "ACTUAL_SUBMIT_ACK",
    "MAX_TINY_QUOTE_USDC",
    "PHASE_LIVE_TINY_BTC_PREFLIGHT",
    "PROVEN_PRODUCT",
    "build_btc_usdc_tiny_live_preflight_report",
]
