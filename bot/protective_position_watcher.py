from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ZERO = Decimal("0")
D3_PHASE = "D3_controlled_live_reduce_only_exits"
OPEN_STATUSES = {"planned", "pending", "submitted", "open", "active", "partially_filled", "cancel_pending", "replace_pending", "new", "queued"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _load_json(path: str | Path) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _positions_list(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("positions"), dict):
        raw = raw["positions"]
    if isinstance(raw, dict):
        return [dict(v) for v in raw.values() if isinstance(v, dict)]
    if isinstance(raw, list):
        return [dict(v) for v in raw if isinstance(v, dict)]
    return []


def _orders_list(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, dict) and isinstance(raw.get("orders"), dict):
        raw = raw["orders"]
    if isinstance(raw, dict):
        return [dict(v) for v in raw.values() if isinstance(v, dict)]
    if isinstance(raw, list):
        return [dict(v) for v in raw if isinstance(v, dict)]
    return []


def _position_id(position: Dict[str, Any]) -> str:
    for key in ("position_id", "logical_position_id", "recovery_linked_position_id", "phase_c43_exchange_order_id", "order_id"):
        text = str(position.get(key) or "").strip()
        if text:
            return text
    return _normalize_ticker(position.get("ticker"))


def _position_base(position: Dict[str, Any]) -> Decimal:
    for key in ("bot_managed_base", "position_size_base", "base_size", "filled_size_base", "filled_base"):
        value = _to_decimal(position.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def is_open_position(position: Dict[str, Any]) -> bool:
    return str(position.get("status") or "open").strip().lower() in {"open", "active"} and _position_base(position) > ZERO


def is_pending_buy_entry(order: Dict[str, Any]) -> bool:
    return (
        str(order.get("side") or "").strip().upper() == "BUY"
        and str(order.get("status") or "").strip().lower() in OPEN_STATUSES
        and str(order.get("phase") or "").strip() != D3_PHASE
    )


def is_open_d3_exit(order: Dict[str, Any], *, ticker: str, position_id: str = "") -> bool:
    if _normalize_ticker(order.get("ticker") or order.get("product_id")) != _normalize_ticker(ticker):
        return False
    if str(order.get("side") or "").strip().upper() != "SELL":
        return False
    if str(order.get("phase") or "").strip() != D3_PHASE:
        return False
    if str(order.get("status") or "").strip().lower() not in OPEN_STATUSES:
        return False
    linked = str(position_id or "").strip()
    return not linked or str(order.get("linked_position_id") or "").strip() in {"", linked}


def _reserved_base(orders: Iterable[Dict[str, Any]]) -> Decimal:
    total = ZERO
    for order in orders:
        total += max(ZERO, _to_decimal(order.get("remaining_size") or order.get("size_base") or order.get("base_size"), "0"))
    return total


def _market_for_ticker(market_by_ticker: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    market = market_by_ticker.get(ticker) or market_by_ticker.get(_normalize_ticker(ticker)) or {}
    return market if isinstance(market, dict) else {}


def _current_mid(position: Dict[str, Any], market: Dict[str, Any]) -> Decimal:
    for value in (
        market.get("mid_price"),
        market.get("current_mid"),
        market.get("current_price"),
        position.get("last_mid_price"),
        position.get("current_price"),
    ):
        dec = _to_decimal(value, "0")
        if dec > ZERO:
            return dec
    return ZERO


def _risk_state(position: Dict[str, Any]) -> Dict[str, Any]:
    stop = _to_decimal(position.get("stop_price"), "0")
    invalidation = _to_decimal(position.get("invalidation_price") or position.get("stop_price"), "0")
    incomplete = bool(
        stop <= ZERO
        or invalidation <= ZERO
        or str(position.get("protective_stop_status") or "").strip().lower() == "position_risk_incomplete"
        or bool(position.get("position_risk_incomplete"))
    )
    blockers: List[str] = []
    if stop <= ZERO:
        blockers.append("stop_price_missing")
    if invalidation <= ZERO:
        blockers.append("invalidation_price_missing")
    if str(position.get("protective_stop_status") or "").strip().lower() == "position_risk_incomplete":
        blockers.append("protective_stop_status_incomplete")
    return {"complete": not incomplete, "stop_price": stop, "invalidation_price": invalidation, "blockers": blockers}


def _trailing_state(position: Dict[str, Any], market: Dict[str, Any], current_mid: Decimal) -> str:
    if str(position.get("trailing_stop_exchange_live") or "").strip().lower() == "true":
        return "active"
    activation = _to_decimal(position.get("trailing_activation_price") or market.get("trailing_activation_price"), "0")
    if activation > ZERO and current_mid > ZERO and current_mid >= activation:
        return "active"
    if bool(position.get("trailing_active")):
        return "active"
    if _to_decimal(position.get("trailing_trigger_pct"), "0") > ZERO or _to_decimal(position.get("trailing_distance_pct"), "0") > ZERO:
        return "preview_only"
    return "inactive"


def build_protective_position_watcher_report(
    *,
    positions: Any = None,
    open_orders: Any = None,
    market_by_ticker: Optional[Dict[str, Any]] = None,
    d2_plans: Optional[Dict[str, Any]] = None,
    allow_coinbase_read_only: bool = False,
    coinbase_client: Any = None,
) -> Dict[str, Any]:
    market_by_ticker = market_by_ticker or {}
    all_positions = _positions_list(positions or {})
    all_orders = _orders_list(open_orders or {})
    open_positions = [p for p in all_positions if is_open_position(p)]
    pending_buys = [o for o in all_orders if is_pending_buy_entry(o)]
    coinbase_call_attempted = bool(allow_coinbase_read_only and coinbase_client is not None)

    reports: List[Dict[str, Any]] = []
    for position in open_positions:
        ticker = _normalize_ticker(position.get("ticker") or position.get("product_id"))
        position_id = _position_id(position)
        market = _market_for_ticker(market_by_ticker, ticker)
        mid = _current_mid(position, market)
        risk = _risk_state(position)
        stop_candidates = [risk["stop_price"], risk["invalidation_price"]]
        stop_floor = max([x for x in stop_candidates if x > ZERO], default=ZERO)
        stop_breached = bool(risk["complete"] and mid > ZERO and stop_floor > ZERO and mid <= stop_floor)
        exits = [o for o in all_orders if is_open_d3_exit(o, ticker=ticker, position_id=position_id)]
        reserved = _reserved_base(exits)
        base = _position_base(position)
        available = max(ZERO, base - reserved)
        blockers: List[str] = []
        warnings: List[str] = []
        if not risk["complete"]:
            blockers.extend(risk["blockers"])
        if any(_to_decimal(o.get("filled_base") or o.get("filled_size"), "0") > ZERO for o in exits):
            blockers.append("reconcile_fill_first")
        if reserved > base and base > ZERO:
            blockers.append("reserved_base_exceeds_position_base")
        if len(exits) > 1:
            warnings.append("multiple_open_d3_exit_orders_review_duplicate_risk")

        if not risk["complete"]:
            action = "risk_state_incomplete"
        elif "reconcile_fill_first" in blockers:
            action = "reconcile_fill_first"
        elif stop_breached and exits and reserved > ZERO:
            action = "cancel_tp_then_stop_exit_preview"
        elif stop_breached:
            action = "controlled_stop_sell_preview"
        elif not exits:
            action = "d3_missing_create_preview"
        else:
            action = "keep_open"

        reports.append({
            "ticker": ticker,
            "position_id": position_id,
            "position_status": str(position.get("status") or "open"),
            "entry_price": str(position.get("entry_price") or position.get("avg_fill_price") or ""),
            "current_mid": str(mid),
            "stop_price": str(risk["stop_price"]),
            "invalidation_price": str(risk["invalidation_price"]),
            "stop_breached": stop_breached,
            "trailing_state": _trailing_state(position, market, mid),
            "trailing_stop_exchange_live": False,
            "trailing_stop_software_preview": _trailing_state(position, market, mid) in {"active", "triggered", "preview_only"},
            "trailing_stop_live_replace_enabled": False,
            "open_d3_exit_orders": len(exits),
            "reserved_base": str(reserved),
            "available_base": str(available),
            "recommended_action": action,
            "blockers": sorted(set(blockers)),
            "warnings": warnings,
            "coinbase_call_attempted": coinbase_call_attempted,
            "live_action_attempted": False,
            "state_write_attempted": False,
        })

    pending_reviews = [
        {
            "ticker": _normalize_ticker(o.get("ticker") or o.get("product_id")),
            "client_order_id": str(o.get("client_order_id") or ""),
            "side": "BUY",
            "status": str(o.get("status") or ""),
            "recommended_action": "use_pending_entry_cancel_lifecycle",
            "stop_sell_action_allowed": False,
            "reason": "pending_buy_has_no_base_position_no_naked_sell",
        }
        for o in pending_buys
    ]
    unprotected = [r["ticker"] for r in reports if r["recommended_action"] == "risk_state_incomplete"]
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "protective_position_watcher_preview_v1",
        "status": "risk_attention_required" if unprotected or any(r["stop_breached"] for r in reports) else "ok",
        "preview_only": True,
        "requires_llm": False,
        "position_count": len(reports),
        "pending_buy_entry_count": len(pending_reviews),
        "positions": reports,
        "pending_buy_entries": pending_reviews,
        "blocked_new_entry_tickers": sorted(set(unprotected)),
        "coinbase_call_attempted": coinbase_call_attempted,
        "live_action_attempted": False,
        "state_write_attempted": False,
        "policy": {
            "pending_buy_never_gets_stop_sell": True,
            "spot_no_reduce_only_requires_base_reservation_checks": True,
            "stop_breach_requires_cancel_tp_first_when_base_reserved": True,
            "cancel_verify_required_before_stop_sell": True,
            "fill_reconcile_required_before_d3": True,
            "trailing_preview_only": True,
        },
    })


def build_protective_position_watcher_report_from_files(
    *,
    positions_path: str | Path = "state/positions.json",
    open_orders_path: str | Path = "state/open_orders.json",
    market_path: str | Path | None = None,
    d2_plans_path: str | Path | None = "state/phase_d2_position_executor_plans.json",
    allow_coinbase_read_only: bool = False,
) -> Dict[str, Any]:
    market = _load_json(market_path) if market_path else {}
    return build_protective_position_watcher_report(
        positions=_load_json(positions_path),
        open_orders=_load_json(open_orders_path),
        market_by_ticker=market,
        d2_plans=_load_json(d2_plans_path) if d2_plans_path else {},
        allow_coinbase_read_only=allow_coinbase_read_only,
        coinbase_client=None,
    )


__all__ = [
    "build_protective_position_watcher_report",
    "build_protective_position_watcher_report_from_files",
    "is_open_position",
    "is_pending_buy_entry",
]
