from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

from bot.order_store import OrderStore
from bot.state_store import StateStore

PHASE_D3_BASE_BALANCE_PREFLIGHT = "D3_base_balance_preflight"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


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


def _parse_required_decimal(value: Any, field_name: str, blockers: list[str]) -> Optional[Decimal]:
    try:
        if value is None:
            blockers.append(f"{field_name}_missing")
            return None
        text = str(value).strip()
        if not text:
            blockers.append(f"{field_name}_missing")
            return None
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        blockers.append(f"{field_name}_unparseable")
        return None


def _split_ticker(ticker: str) -> tuple[str, str]:
    normalized = _normalize_ticker(ticker)
    if "-" not in normalized:
        return normalized, ""
    return tuple(normalized.split("-", 1))  # type: ignore[return-value]


def build_phase_d3_base_balance_preflight_report(
    *,
    ticker: str,
    position_id: str,
    requested_sell_base: Any,
    coinbase_client: Any,
    state_store: Optional[StateStore] = None,
    order_store: Optional[OrderStore] = None,
) -> Dict[str, Any]:
    ticker = _normalize_ticker(ticker)
    requested_position_id = str(position_id or "").strip()
    requested_sell = _to_decimal(requested_sell_base, "0")
    state = state_store or StateStore()
    orders = order_store or OrderStore()
    base_asset, quote_asset = _split_ticker(ticker)

    blockers: list[str] = []
    warnings: list[str] = []

    position = state.get_position(ticker) if state is not None else None
    local_position_present = isinstance(position, dict)
    local_position_id = str((position or {}).get("order_id") or "").strip()
    local_position_size_base = _to_decimal((position or {}).get("position_size_base"), "0")
    local_bot_managed_base = _to_decimal((position or {}).get("bot_managed_base"), "0")

    if not local_position_present:
        blockers.append("local_position_missing")
    if requested_position_id and local_position_id != requested_position_id:
        blockers.append("position_id_mismatch")
    if requested_sell <= ZERO:
        blockers.append("requested_sell_base_nonpositive")
    if local_bot_managed_base < requested_sell:
        blockers.append("local_bot_managed_base_below_requested_sell_base")

    open_d3_exit_orders = []
    if orders is not None:
        open_d3_exit_orders = [
            o for o in orders.open_exit_orders(ticker=ticker)
            if str(o.get("linked_position_id") or "").strip() == requested_position_id
        ]
    if open_d3_exit_orders:
        blockers.append("open_d3_exit_order_exists")

    live_snapshot: Dict[str, Any] = {}
    live_base_available: Optional[Decimal] = None
    live_base_total: Optional[Decimal] = None
    live_quote_available: Optional[Decimal] = None
    live_quote_total: Optional[Decimal] = None
    coinbase_read_method = "get_spot_position"

    if coinbase_client is None:
        blockers.append("coinbase_client_missing")
    else:
        try:
            live_snapshot = coinbase_client.get_spot_position(ticker)
        except Exception as exc:
            error_text = str(exc or "").strip()
            if isinstance(exc, ValueError) and "COINBASE_API_KEY ontbreekt" in error_text:
                blockers.append("coinbase_auth_missing_for_read_only_balance_check")
                warnings.append("coinbase_auth_missing_for_read_only_balance_check")
            else:
                blockers.append("coinbase_client_error")
            warnings.append(f"coinbase_client_error_detail:{type(exc).__name__}")
            live_snapshot = {}

    if coinbase_client is not None and not live_snapshot and "coinbase_client_error" not in blockers:
        blockers.append("balance_api_response_unparseable")

    if live_snapshot:
        live_base_available = _parse_required_decimal(
            live_snapshot.get("available_base_balance"),
            "live_base_available",
            blockers,
        )
        hold_base = _parse_required_decimal(
            live_snapshot.get("hold_base_balance"),
            "live_base_hold",
            blockers,
        )
        live_quote_available = _parse_required_decimal(
            live_snapshot.get("available_quote_balance"),
            "live_quote_available",
            blockers,
        )
        hold_quote = _parse_required_decimal(
            live_snapshot.get("hold_quote_balance"),
            "live_quote_hold",
            blockers,
        )
        if live_base_available is not None and hold_base is not None:
            live_base_total = live_base_available + hold_base
        if live_quote_available is not None and hold_quote is not None:
            live_quote_total = live_quote_available + hold_quote

    if live_base_available is None:
        blockers.append("live_base_available_missing")
    elif live_base_available < requested_sell:
        blockers.append("live_base_available_below_requested_sell_base")

    safety_margin_base = None
    if live_base_available is not None:
        safety_margin_base = live_base_available - requested_sell

    local_vs_live_base_coherent = (
        live_base_total is not None
        and local_bot_managed_base > ZERO
        and live_base_total >= local_bot_managed_base
    )
    if live_base_total is not None and local_bot_managed_base > ZERO and live_base_total < local_bot_managed_base:
        warnings.append("live_base_total_below_local_bot_managed_base")

    sufficient_live_base = live_base_available is not None and live_base_available >= requested_sell > ZERO
    if not sufficient_live_base and "requested_sell_base_nonpositive" not in blockers and "live_base_available_below_requested_sell_base" not in blockers and "live_base_available_missing" not in blockers:
        blockers.append("live_base_available_below_requested_sell_base")

    status = "d3_base_balance_preflight_ready" if not blockers else "d3_base_balance_preflight_blocked"
    return {
        "phase": PHASE_D3_BASE_BALANCE_PREFLIGHT,
        "generated_at": _now_iso(),
        "status": status,
        "ticker": ticker,
        "base_asset": base_asset,
        "quote_asset": quote_asset,
        "requested_position_id": requested_position_id,
        "requested_sell_base": str(requested_sell),
        "local_position_present": local_position_present,
        "local_position_id": local_position_id,
        "local_position_size_base": str(local_position_size_base),
        "local_bot_managed_base": str(local_bot_managed_base),
        "live_base_available": str(live_base_available) if live_base_available is not None else None,
        "live_base_total": str(live_base_total) if live_base_total is not None else None,
        "live_quote_available": str(live_quote_available) if live_quote_available is not None else None,
        "live_quote_total": str(live_quote_total) if live_quote_total is not None else None,
        "sufficient_live_base_for_requested_sell": bool(sufficient_live_base),
        "local_vs_live_base_coherent": bool(local_vs_live_base_coherent),
        "safety_margin_base": str(safety_margin_base) if safety_margin_base is not None else None,
        "open_d3_exit_orders": {
            "count": len(open_d3_exit_orders),
            "client_order_ids": [str(o.get("client_order_id") or "") for o in open_d3_exit_orders],
        },
        "coinbase_read_method": coinbase_read_method,
        "coinbase_live_balance_snapshot": live_snapshot,
        "blockers": blockers,
        "warnings": warnings,
        "read_only": True,
        "no_submit": True,
        "safety_policy": {
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_mutate_state": True,
            "does_not_modify_env": True,
            "read_only_coinbase_balance_check_only": True,
        },
    }


__all__ = ["build_phase_d3_base_balance_preflight_report"]
