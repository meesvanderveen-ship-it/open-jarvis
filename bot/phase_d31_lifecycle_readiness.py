from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import build_phase_c43_status_report, count_local_phase_c_live_entry_orders
from bot.phase_d1_exit_orderbook_scaffold import build_phase_d1_status_report
from bot.phase_d2_position_executor import build_phase_d2_position_executor_report, is_d2_manageable_open_position
from bot.phase_d3_controlled_live_exits import build_phase_d3_controlled_live_exit_report, count_phase_d3_live_exit_orders
from bot.phase_d32_llm_pre_live_health import build_phase_d32_llm_pre_live_health_report
from bot.state_store import StateStore

D31_PHASE = "D3.1_end_to_end_lifecycle_readiness"
D31_READY_ENTRY_ARMING = "d31_ready_for_controlled_entry_only_arming"
D31_BLOCKED = "d31_lifecycle_readiness_blocked"
D31_WAITING_FOR_POSITION = "d31_waiting_for_filled_entry"
D31_REVIEW_OPEN_POSITION = "d31_open_position_requires_d2_d3_review"
D31_ENTRY_ARM_ACK = "I_UNDERSTAND_AND_APPROVE_D31_ENTRY_ONLY_ARMING_READINESS_REVIEW"

ZERO = Decimal("0")
D31_MAX_ENTRY_QUOTE = Decimal("25.00")
D31_MAX_OPEN_ENTRY_ORDERS = 4
D31_MAX_OPEN_EXIT_ORDERS = 4


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except Exception:
        return default


def _cfg_dec(cfg: Any, name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), str(default))


def _phase_c_allowed_tickers(cfg: Any) -> List[str]:
    return [_normalize_ticker(x) for x in _as_list(getattr(cfg, "phase_c_allowed_tickers", [])) if _normalize_ticker(x)]


def _bot_allowed_tickers(cfg: Any) -> List[str]:
    return [_normalize_ticker(x) for x in _as_list(getattr(cfg, "allowed_tickers", [])) if _normalize_ticker(x)]


def _manageable_positions(state_store: Optional[StateStore], ticker: Optional[str] = None) -> List[Dict[str, Any]]:
    store = state_store or StateStore()
    selected = _normalize_ticker(ticker)
    positions = []
    try:
        raw = store.get_positions()
    except Exception:
        return []
    for p in raw.values():
        if not isinstance(p, dict):
            continue
        pt = _normalize_ticker(p.get("ticker"))
        if selected and pt != selected:
            continue
        if is_d2_manageable_open_position(p, ticker=pt or selected):
            positions.append(p)
    return positions


def _open_order_summary(order_store: OrderStore) -> Dict[str, Any]:
    counts = order_store.open_order_counts()
    c43_counts = count_local_phase_c_live_entry_orders(order_store)
    d3_counts = count_phase_d3_live_exit_orders(order_store)
    return _json_safe({
        "all_open_orders": counts,
        "phase_c43_open_entry_orders": c43_counts,
        "phase_d3_open_exit_orders": d3_counts,
    })


def assess_phase_d31_entry_pilot_readiness(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    require_actual_entry_submit: bool = False,
    human_ack: str = "",
) -> Dict[str, Any]:
    """Assess whether the full C.4.3 -> D.2 -> D.3 lifecycle is ready for a controlled entry-only pilot.

    This function never submits an order and never changes config. It only answers:
    is the code/config/state safe enough to intentionally arm C.4.3 entry-only later?
    """
    ticker = _normalize_ticker(ticker)
    store = order_store or OrderStore()
    positions = _manageable_positions(state_store, ticker=ticker)
    all_positions = _manageable_positions(state_store, ticker=None)
    order_summary = _open_order_summary(store)
    c43_open_count = int(_as_dict(order_summary.get("phase_c43_open_entry_orders")).get("total_open_live_entry_orders") or 0)
    d3_open_count = int(_as_dict(order_summary.get("phase_d3_open_exit_orders")).get("total_open_d3_exit_orders") or 0)
    all_open_count = int(_as_dict(order_summary.get("all_open_orders")).get("total_open_orders") or 0)

    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    phase_c_allowed = set(_phase_c_allowed_tickers(cfg))
    bot_allowed = set(_bot_allowed_tickers(cfg))
    max_entry_quote = min(
        _cfg_dec(cfg, "phase_c_max_order_quote", D31_MAX_ENTRY_QUOTE),
        _cfg_dec(cfg, "autonomous_max_order_quote", D31_MAX_ENTRY_QUOTE),
        D31_MAX_ENTRY_QUOTE,
    )
    max_open_entry = min(
        _cfg_int(cfg, "phase_c_max_open_entry_orders", D31_MAX_OPEN_ENTRY_ORDERS),
        _cfg_int(cfg, "autonomous_max_open_orders", D31_MAX_OPEN_ENTRY_ORDERS),
        D31_MAX_OPEN_ENTRY_ORDERS,
    )
    max_new_entry = min(
        _cfg_int(cfg, "phase_c_max_new_orders_per_cycle", 1),
        _cfg_int(cfg, "autonomous_max_new_orders_per_cycle", 1),
        1,
    )

    require(_cfg_bool(cfg, "enable_phase_c43_autonomous_entry_submitter", True), "c43_entry_submitter_installed", "c43_entry_submitter_disabled")
    require(_cfg_bool(cfg, "enable_phase_c_live_small_limit_orders", False), "phase_c_small_live_limit_orders_enabled", "phase_c_small_live_limit_orders_disabled")
    require(_cfg_bool(cfg, "enable_autonomous_small_live_orderbook_mode", False), "autonomous_small_live_orderbook_mode_enabled", "autonomous_small_live_orderbook_mode_disabled")
    require(_cfg_bool(cfg, "enable_live_limit_orders", False), "live_limit_orders_flag_enabled", "live_limit_orders_flag_disabled")
    require(_cfg_bool(cfg, "enable_live_entry_orders", False), "live_entry_orders_flag_enabled", "live_entry_orders_flag_disabled")
    require(not _cfg_bool(cfg, "enable_live_exit_orders", False), "live_exit_orders_still_disabled", "live_exit_orders_enabled_before_position")
    require(not _cfg_bool(cfg, "autonomous_allow_exits", False), "autonomous_allow_exits_still_false", "autonomous_allow_exits_true_before_position")
    require(_cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True), "phase_c_exit_limit_orders_disabled", "phase_c_disable_exit_limit_orders_false_before_position")
    require(_cfg_bool(cfg, "autonomous_entry_only_first", True), "autonomous_entry_only_first_true", "autonomous_entry_only_first_false_before_position")
    require(_cfg_bool(cfg, "autonomous_require_post_only", True), "post_only_required", "post_only_not_required")
    require(_cfg_bool(cfg, "enable_phase_d2_position_executor", True), "d2_position_executor_enabled", "d2_position_executor_disabled")
    require(_cfg_bool(cfg, "enable_phase_d3_controlled_live_exits", True), "d3_controlled_exits_installed", "d3_controlled_exits_disabled")
    require(not _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False), "d3_actual_exit_submit_disabled_before_position", "d3_actual_exit_submit_enabled_before_position")
    require(max_entry_quote > ZERO and max_entry_quote <= D31_MAX_ENTRY_QUOTE, "entry_quote_cap_lte_25", "entry_quote_cap_above_25")
    require(max_open_entry <= D31_MAX_OPEN_ENTRY_ORDERS, "entry_open_order_cap_lte_4", "entry_open_order_cap_above_4")
    require(max_new_entry == 1, "one_new_entry_per_cycle", "max_new_entry_orders_not_1")
    require(bool(ticker), "ticker_present", "ticker_missing")
    require((not phase_c_allowed) or ticker in phase_c_allowed, "ticker_in_phase_c_allowlist", "ticker_not_in_phase_c_allowlist")
    require(c43_open_count < max_open_entry, "c43_entry_order_capacity_available", "c43_entry_open_order_capacity_full")
    require(d3_open_count == 0, "no_open_d3_exit_orders_before_entry", "open_d3_exit_orders_before_position")
    require(not positions, "no_manageable_position_for_selected_ticker", "selected_ticker_already_has_manageable_position")

    if all_positions:
        warnings.append("other_manageable_positions_exist_review_before_new_entry")
    if all_open_count and c43_open_count == 0 and d3_open_count == 0:
        warnings.append("non_phase_c43_d3_open_orders_exist_review_manually")
    if bot_allowed:
        missing = sorted(t for t in bot_allowed if t not in phase_c_allowed)
        if missing:
            warnings.append("phase_c_allowlist_subset_of_bot_allowed_tickers:" + ",".join(missing[:20]))
    if _cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False):
        warnings.append("entry_actual_submit_already_true_review_before_restart")
    else:
        passed.append("entry_actual_submit_currently_false_preview_safe")

    ack_ok = str(human_ack or "").strip() == D31_ENTRY_ARM_ACK
    if require_actual_entry_submit:
        require(_cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False), "entry_actual_submit_enabled", "entry_actual_submit_disabled")
        require(ack_ok, "human_ack_matches_d31", "human_ack_missing_or_invalid")
    else:
        passed.append("require_actual_entry_submit_false_readiness_only")

    ready = not blockers
    status = D31_READY_ENTRY_ARMING if ready else D31_BLOCKED
    if ready and not _cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False):
        status = D31_READY_ENTRY_ARMING
    if not positions and ready:
        lifecycle_state = D31_WAITING_FOR_POSITION
    elif positions:
        lifecycle_state = D31_REVIEW_OPEN_POSITION
    else:
        lifecycle_state = D31_BLOCKED

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D31_PHASE,
        "ticker": ticker,
        "status": status,
        "lifecycle_state": lifecycle_state,
        "ready_for_controlled_entry_only_arming": ready,
        "require_actual_entry_submit": require_actual_entry_submit,
        "human_ack_ok": ack_ok,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "passed_checks": passed,
        "limits": {
            "entry_max_quote": str(max_entry_quote),
            "entry_max_open_orders": max_open_entry,
            "entry_max_new_orders_per_cycle": max_new_entry,
            "d3_max_open_exit_orders": min(_cfg_int(cfg, "phase_d3_max_open_exit_orders", D31_MAX_OPEN_EXIT_ORDERS), D31_MAX_OPEN_EXIT_ORDERS),
        },
        "config_flags": {
            "enable_phase_c_actual_coinbase_submit": _cfg_bool(cfg, "enable_phase_c_actual_coinbase_submit", False),
            "enable_live_entry_orders": _cfg_bool(cfg, "enable_live_entry_orders", False),
            "enable_live_exit_orders": _cfg_bool(cfg, "enable_live_exit_orders", False),
            "enable_phase_d3_actual_exit_submit": _cfg_bool(cfg, "enable_phase_d3_actual_exit_submit", False),
            "autonomous_entry_only_first": _cfg_bool(cfg, "autonomous_entry_only_first", True),
            "autonomous_allow_exits": _cfg_bool(cfg, "autonomous_allow_exits", False),
            "phase_c_disable_exit_limit_orders": _cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True),
        },
        "open_order_summary": order_summary,
        "selected_manageable_position_count": len(positions),
        "all_manageable_position_count": len(all_positions),
        "phase_c_allowed_tickers": sorted(phase_c_allowed),
        "safety_policy": {
            "does_not_modify_env": True,
            "does_not_submit_orders": True,
            "entry_only_before_position": True,
            "live_exits_must_remain_disabled_until_position_and_d3_arming": True,
            "c43_then_d2_then_d3_lifecycle_required": True,
        },
    })


def build_phase_d31_lifecycle_readiness_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    require_actual_entry_submit: bool = False,
    human_ack: str = "",
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    state = state_store or StateStore()
    ticker = _normalize_ticker(ticker)
    entry_readiness = assess_phase_d31_entry_pilot_readiness(
        cfg=cfg,
        ticker=ticker,
        order_store=store,
        state_store=state,
        require_actual_entry_submit=require_actual_entry_submit,
        human_ack=human_ack,
    )
    c43 = build_phase_c43_status_report(cfg=cfg, ticker=ticker, order_store=store, state_store=state)
    d1 = build_phase_d1_status_report(cfg=cfg, ticker=ticker, order_store=store, state_store=state)
    d2 = build_phase_d2_position_executor_report(cfg=cfg, ticker=ticker, state_store=state)
    d3 = build_phase_d3_controlled_live_exit_report(cfg=cfg, ticker=ticker, order_store=store, state_store=state)
    d32 = build_phase_d32_llm_pre_live_health_report(cfg=cfg, project_root=Path("."))

    blockers = list(entry_readiness.get("blockers") or [])
    warnings = list(entry_readiness.get("warnings") or [])
    if not bool(d32.get("ready", True)):
        blockers.extend(str(x) for x in (d32.get("blockers") or []))
    warnings.extend(str(x) for x in (d32.get("warnings") or []))
    ready = bool(entry_readiness.get("ready_for_controlled_entry_only_arming")) and not blockers
    status = str(entry_readiness.get("status") or D31_BLOCKED)
    if blockers:
        status = D31_BLOCKED

    if str(d2.get("status") or "") not in {"no_open_position_for_position_executor", "position_executor_plan_ready_no_live_exit_submit"}:
        warnings.append("d2_status_review:" + str(d2.get("status") or "unknown"))
    if str(d3.get("status") or "") not in {"d3_no_manageable_open_position", "d3_controlled_exit_ready_no_submit"}:
        warnings.append("d3_status_review:" + str(d3.get("status") or "unknown"))

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D31_PHASE,
        "ticker": ticker,
        "status": status,
        "ready_for_controlled_entry_only_arming": ready,
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "entry_readiness": entry_readiness,
        "stack": {
            "c43_status": c43.get("phase"),
            "c43_open_entry_orders": _as_dict(c43.get("local_live_entry_order_counts")).get("total_open_live_entry_orders", 0),
            "d1_status": d1.get("phase"),
            "d1_open_exit_orders": _as_dict(d1.get("local_live_exit_order_counts")).get("total_open_live_exit_orders", 0),
            "d2_status": d2.get("status"),
            "d2_plan_present": bool(d2.get("plan")),
            "d3_status": d3.get("status"),
            "d3_plan_present": bool(d3.get("plan_present")),
            "d3_position_present": bool(d3.get("position_present")),
            "d32_status": d32.get("status"),
            "d32_ready": bool(d32.get("ready")),
            "d32_recent_corrupt_rows": _as_dict(d32.get("counts")).get("recent_corrupt_rows", 0),
            "d32_recent_provider_error_rows": _as_dict(d32.get("counts")).get("recent_provider_error_rows", 0),
        },
        "llm_pre_live_health": d32,
        "next_step": (
            "Als dit rapport ready is: C.4.3 entry-only pilot arming kan bewust voorbereid worden; D.3 exits blijven uit tot er een echte gevulde entry en D.2-plan zijn."
            if ready else
            "Los blockers op voordat C.4.3 entry-only live arming wordt overwogen."
        ),
        "safety_policy": {
            "does_not_modify_env": True,
            "does_not_submit_orders": True,
            "actual_entry_submit_is_separate_manual_arming_step": True,
            "actual_exit_submit_remains_d3_only_after_real_position": True,
        },
    })


__all__ = [
    "D31_PHASE",
    "D31_ENTRY_ARM_ACK",
    "assess_phase_d31_entry_pilot_readiness",
    "build_phase_d31_lifecycle_readiness_report",
]
