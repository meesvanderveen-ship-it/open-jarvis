from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, Optional


LIVE_EXIT_LOG_PATH = Path("logs/live_exit_orders.jsonl")
SELL_ALLOWED_SOURCES = {"phase_d3_controlled_live_exit"}
D4_CONTROLLED_CANCEL_REPLACE_SOURCE = "phase_d4_controlled_cancel_replace"
D4_CONTROLLED_CANCEL_REPLACE_ACK = "I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT"
FLAG_ATTRS = {
    "ENABLE_LIVE_EXIT_ORDERS": "enable_live_exit_orders",
    "AUTONOMOUS_ALLOW_EXITS": "autonomous_allow_exits",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "enable_phase_d3_actual_exit_submit",
    "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "phase_c_disable_exit_limit_orders",
}


class LiveExitBlockedError(RuntimeError):
    def __init__(self, message: str, *, evaluation: Dict[str, Any], event: Dict[str, Any]):
        super().__init__(message)
        self.evaluation = evaluation
        self.event = event


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _cfg_bool(cfg: Any, attr_name: str, default: bool) -> bool:
    try:
        return bool(getattr(cfg, attr_name, default))
    except Exception:
        return default


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_respects_increment(value: Decimal, increment: Decimal) -> bool:
    if increment <= 0:
        return True
    if value <= 0:
        return False
    units = value / increment
    return units == units.to_integral_value()


def get_live_exit_safety_flags(cfg: Any = None) -> Dict[str, Any]:
    flags: Dict[str, Any] = {}
    for env_name, attr_name in FLAG_ATTRS.items():
        default = True if env_name == "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS" else False
        flags[env_name] = _cfg_bool(cfg, attr_name, default)
    return flags


def evaluate_live_exit_allowed(
    *,
    cfg: Any = None,
    side: str,
    source_module: str = "",
    source_function: str = "",
    source_tag: str = "",
    intended_exit_type: str = "",
    ticker: str = "",
    client_order_id: str = "",
    order_id: str = "",
    local_position_id: str = "",
    reason: str = "",
    close_reason: str = "",
    execution_status: str = "",
    human_ack: str = "",
    required_human_ack: str = "",
    allowed_sources: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    safe_side = str(side or "").upper().strip()
    flags = get_live_exit_safety_flags(cfg)
    allowed_source_set = {
        str(item).strip()
        for item in (allowed_sources if allowed_sources is not None else SELL_ALLOWED_SOURCES)
        if str(item).strip()
    }
    gate_applicable = safe_side == "SELL"
    blockers = []

    if gate_applicable:
        if not flags["ENABLE_LIVE_EXIT_ORDERS"]:
            blockers.append("enable_live_exit_orders_false")
        if not flags["AUTONOMOUS_ALLOW_EXITS"]:
            blockers.append("autonomous_allow_exits_false")
        if not flags["ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"]:
            blockers.append("enable_phase_d3_actual_exit_submit_false")
        if flags["PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"]:
            blockers.append("phase_c_disable_exit_limit_orders_true")
        if str(source_tag or "").strip() not in allowed_source_set:
            blockers.append("source_not_explicitly_allowed_for_live_sell")
        if required_human_ack and str(human_ack or "").strip() != str(required_human_ack).strip():
            blockers.append("required_human_ack_missing_or_invalid")

    allowed = (not gate_applicable) or (not blockers)
    return _json_safe({
        "generated_at": _now_iso(),
        "gate_applicable": gate_applicable,
        "allowed": allowed,
        "blocked": not allowed,
        "side": safe_side,
        "ticker": str(ticker or "").strip().upper(),
        "source_module": str(source_module or "").strip(),
        "source_function": str(source_function or "").strip(),
        "source_tag": str(source_tag or "").strip(),
        "intended_exit_type": str(intended_exit_type or "").strip(),
        "client_order_id": str(client_order_id or "").strip(),
        "order_id": str(order_id or "").strip(),
        "local_position_id": str(local_position_id or "").strip(),
        "reason": str(reason or "").strip(),
        "close_reason": str(close_reason or "").strip(),
        "execution_status": str(execution_status or "").strip(),
        "human_ack_present": bool(str(human_ack or "").strip()),
        "required_human_ack": bool(str(required_human_ack or "").strip()),
        "allowed_sources": sorted(allowed_source_set),
        "safety_flags_snapshot": flags,
        "block_reasons": blockers,
    })


def evaluate_d4_controlled_replacement_submit_allowed(
    *,
    cfg: Any = None,
    source_tag: str = "",
    human_ack: str = "",
    one_shot_armed_process_local: bool = False,
    side: str = "SELL",
    ticker: str = "",
    linked_position_id: str = "",
    old_order_confirmed_cancelled: bool = False,
    cancel_first_required: bool = True,
    replace_only_after_confirmed_cancel: bool = True,
    post_only: bool = True,
    reduce_only_local: bool = True,
    replacement_size_base: Any = "0",
    reserved_base: Any = "0",
    available_base: Any = "0",
    duplicate_open_exit_detected: bool = False,
    oversell_detected: bool = False,
    candidate_count: int = 1,
    target_price: Any = "0",
    price_increment: Any = "0",
    base_increment: Any = "0",
    min_order_quote: Any = "0",
    estimated_quote: Any = None,
    current_order_id: str = "",
    current_exchange_order_id: str = "",
    replacement_client_order_id: str = "",
) -> Dict[str, Any]:
    """Evaluate the narrow D.4 replacement-submit gate without live side effects."""
    safe_source = str(source_tag or "").strip()
    safe_side = str(side or "").strip().upper()
    selected_ticker = str(ticker or "").strip().upper()
    position_id = str(linked_position_id or "").strip()
    flags = get_live_exit_safety_flags(cfg)
    ack_valid = str(human_ack or "").strip() == D4_CONTROLLED_CANCEL_REPLACE_ACK
    size = _to_decimal(replacement_size_base)
    reserved = _to_decimal(reserved_base)
    available = _to_decimal(available_base)
    price = _to_decimal(target_price)
    price_inc = _to_decimal(price_increment)
    base_inc = _to_decimal(base_increment)
    min_quote = _to_decimal(min_order_quote)
    quote = _to_decimal(estimated_quote, "0") if estimated_quote is not None else price * size
    armed = bool(one_shot_armed_process_local)
    blockers = []

    if safe_source != D4_CONTROLLED_CANCEL_REPLACE_SOURCE:
        blockers.append("d4_replacement_source_not_allowed")
    if not ack_valid:
        blockers.append("d4_replacement_ack_missing_or_invalid")
    if not armed:
        blockers.append("d4_replacement_process_local_arming_missing")
    if safe_side != "SELL":
        blockers.append("d4_replacement_side_must_be_sell")
    if not cancel_first_required:
        blockers.append("d4_replacement_cancel_first_required")
    if not replace_only_after_confirmed_cancel:
        blockers.append("d4_replacement_replace_after_confirmed_cancel_required")
    if not old_order_confirmed_cancelled:
        blockers.append("d4_replacement_confirmed_cancel_required")
    if not post_only:
        blockers.append("d4_replacement_post_only_required")
    if not reduce_only_local:
        blockers.append("d4_replacement_reduce_only_local_required")
    if not position_id:
        blockers.append("d4_replacement_linked_position_id_missing")
    if size <= 0:
        blockers.append("d4_replacement_size_missing_or_zero")
    if price <= 0:
        blockers.append("d4_replacement_target_price_missing_or_zero")
    if candidate_count != 1:
        blockers.append("d4_replacement_candidate_count_not_one")
    if duplicate_open_exit_detected:
        blockers.append("d4_replacement_duplicate_open_exit_detected")
    if oversell_detected:
        blockers.append("d4_replacement_oversell_detected")
    if size > 0 and reserved < size:
        blockers.append("d4_replacement_reserved_base_insufficient")
    if size > 0 and available < size:
        blockers.append("d4_replacement_available_base_insufficient")
    if size > 0 and base_inc > 0 and not _decimal_respects_increment(size, base_inc):
        blockers.append("d4_replacement_base_increment_violation")
    if price > 0 and price_inc > 0 and not _decimal_respects_increment(price, price_inc):
        blockers.append("d4_replacement_price_increment_violation")
    if min_quote > 0 and quote < min_quote:
        blockers.append("d4_replacement_below_min_order_quote")

    if not armed:
        if not flags["ENABLE_LIVE_EXIT_ORDERS"]:
            blockers.append("enable_live_exit_orders_false")
        if not flags["AUTONOMOUS_ALLOW_EXITS"]:
            blockers.append("autonomous_allow_exits_false")
        if not flags["ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"]:
            blockers.append("enable_phase_d3_actual_exit_submit_false")
        if flags["PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"]:
            blockers.append("phase_c_disable_exit_limit_orders_true")

    allowed = not blockers
    return _json_safe({
        "generated_at": _now_iso(),
        "gate": "d4_controlled_replacement_submit",
        "allowed": allowed,
        "blocked": not allowed,
        "source_tag": safe_source,
        "required_source": D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
        "source_allowed": safe_source == D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
        "required_ack": D4_CONTROLLED_CANCEL_REPLACE_ACK,
        "human_ack_present": bool(str(human_ack or "").strip()),
        "ack_valid": ack_valid,
        "one_shot_d4_replacement_submit_armed_process_local": armed,
        "env_mutation": False,
        "scope": "single_runner_process_only",
        "side": safe_side,
        "ticker": selected_ticker,
        "linked_position_id": position_id,
        "current_order_id": str(current_order_id or "").strip(),
        "current_exchange_order_id": str(current_exchange_order_id or "").strip(),
        "replacement_client_order_id": str(replacement_client_order_id or "").strip(),
        "replacement_size_base": size,
        "reserved_base": reserved,
        "available_base": available,
        "target_price": price,
        "estimated_quote": quote,
        "price_increment": price_inc,
        "base_increment": base_inc,
        "min_order_quote": min_quote,
        "candidate_count": candidate_count,
        "cancel_first_required": bool(cancel_first_required),
        "replace_only_after_confirmed_cancel": bool(replace_only_after_confirmed_cancel),
        "old_order_confirmed_cancelled": bool(old_order_confirmed_cancelled),
        "post_only": bool(post_only),
        "reduce_only_local": bool(reduce_only_local),
        "duplicate_open_exit_detected": bool(duplicate_open_exit_detected),
        "oversell_detected": bool(oversell_detected),
        "autonomous_exits_allowed": False,
        "general_live_exits_released": False,
        "allowed_sources": [D4_CONTROLLED_CANCEL_REPLACE_SOURCE],
        "safety_flags_snapshot": flags,
        "blockers": blockers,
        "block_reasons": blockers,
        "no_coinbase_call": True,
        "no_live_action": True,
    })


def build_blocked_live_exit_event(evaluation: Dict[str, Any], **overrides: Any) -> Dict[str, Any]:
    event = {
        "generated_at": _now_iso(),
        "source_module": evaluation.get("source_module", ""),
        "source_function": evaluation.get("source_function", ""),
        "reason": evaluation.get("reason", ""),
        "ticker": evaluation.get("ticker", ""),
        "side": evaluation.get("side", ""),
        "intended_exit_type": evaluation.get("intended_exit_type", ""),
        "order_id": evaluation.get("order_id", ""),
        "client_order_id": evaluation.get("client_order_id", ""),
        "submit_time": None,
        "fill_time": None,
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "local_position_id": evaluation.get("local_position_id", ""),
        "close_reason": evaluation.get("close_reason") or evaluation.get("reason", ""),
        "execution_status": evaluation.get("execution_status", ""),
        "safety_flags_snapshot": evaluation.get("safety_flags_snapshot", {}),
        "blocked": True,
        "block_reasons": list(evaluation.get("block_reasons") or []),
    }
    event.update(_json_safe(overrides))
    return _json_safe(event)


def append_live_exit_event(event: Dict[str, Any], path: Path = LIVE_EXIT_LOG_PATH) -> Dict[str, Any]:
    safe_event = _json_safe(event)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(safe_event, ensure_ascii=False, sort_keys=True) + "\n")
    return safe_event


def assert_live_exit_allowed(**kwargs: Any) -> Dict[str, Any]:
    evaluation = evaluate_live_exit_allowed(**kwargs)
    if evaluation.get("allowed"):
        return evaluation
    event = build_blocked_live_exit_event(evaluation)
    raise LiveExitBlockedError(
        "live_exit_blocked_by_policy",
        evaluation=evaluation,
        event=event,
    )
