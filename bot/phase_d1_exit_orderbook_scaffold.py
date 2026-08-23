from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.order_store import OrderStore

ZERO = Decimal("0")
D1_PHASE = "D1_exit_orderbook_scaffold_reduce_only_fill_bridge"
D1_MAX_EXIT_QUOTE = Decimal("25.00")
D1_MAX_OPEN_EXIT_ORDERS = 4
D1_MANAGED_PREFIXES = ("phasec-exit-", "phased1-")
D1_FINAL_ORDER_STATUSES = {"filled", "done", "completed", "cancelled", "canceled", "expired", "failed", "rejected"}
D1_OPEN_ORDER_STATUSES = {"open", "pending", "active", "submitted", "partially_filled", "new", "queued"}


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
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _to_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


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


def _cfg_bool(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _cfg_dec(cfg: Any, name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), str(default))


def _cfg_int(cfg: Any, name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except Exception:
        return int(default)


def _allowed_tickers(cfg: Any) -> List[str]:
    return [_normalize_ticker(x) for x in _as_list(getattr(cfg, "phase_c_allowed_tickers", [])) if _normalize_ticker(x)]


def _client_order_id(order: Dict[str, Any]) -> str:
    return str(order.get("client_order_id") or order.get("client_order_id_preview") or order.get("id") or "").strip()


def _exchange_order_id(order: Dict[str, Any]) -> str:
    return str(order.get("order_id") or order.get("id") or order.get("exchange_order_id") or "").strip()


def _order_ticker(order: Dict[str, Any]) -> str:
    return _normalize_ticker(order.get("ticker") or order.get("product_id") or order.get("product"))


def _order_side(order: Dict[str, Any]) -> str:
    return str(order.get("side") or "").strip().upper()


def _order_status(order: Dict[str, Any]) -> str:
    status = str(order.get("status") or order.get("order_status") or "").strip().lower()
    if not status and _to_decimal(order.get("filled_size") or order.get("filled_size_base"), "0") > ZERO:
        return "partially_filled"
    return status or "unknown"


def _extract_limit_gtc(order: Dict[str, Any]) -> Dict[str, Any]:
    cfg = _as_dict(order.get("order_configuration"))
    return _as_dict(cfg.get("limit_limit_gtc") or cfg.get("limit_limit_ioc") or cfg.get("limit_limit_fok"))


def _limit_price(order: Dict[str, Any]) -> Decimal:
    gtc = _extract_limit_gtc(order)
    return _to_decimal(order.get("limit_price") or gtc.get("limit_price"), "0")


def _base_size(order: Dict[str, Any]) -> Decimal:
    gtc = _extract_limit_gtc(order)
    return _to_decimal(order.get("base_size") or order.get("size_base") or order.get("remaining_size") or gtc.get("base_size"), "0")


def _filled_base(order: Dict[str, Any]) -> Decimal:
    return _to_decimal(order.get("filled_size_base") or order.get("filled_base") or order.get("filled_size"), "0")


def _avg_fill_price(order: Dict[str, Any]) -> Decimal:
    return _to_decimal(order.get("avg_fill_price") or order.get("average_filled_price") or order.get("average_price") or order.get("filled_price") or _limit_price(order), "0")


def _is_managed_live_exit_order(order: Dict[str, Any]) -> bool:
    cid = _client_order_id(order)
    mode = str(order.get("mode") or order.get("source_mode") or "").lower()
    side = _order_side(order)
    return side == "SELL" and (cid.startswith(D1_MANAGED_PREFIXES) or mode in {"phase_d1_exit", "autonomous_small_live_exit"})


def _open_positions(state_store: Any = None) -> List[Dict[str, Any]]:
    if state_store is None or not hasattr(state_store, "get_positions"):
        return []
    positions = state_store.get_positions()
    if not isinstance(positions, dict):
        return []
    out: List[Dict[str, Any]] = []
    for ticker, pos in positions.items():
        if not isinstance(pos, dict):
            continue
        if str(pos.get("status", "open")).lower() != "open":
            continue
        base = _to_decimal(pos.get("position_size_base") or pos.get("bot_managed_base"), "0")
        if base <= ZERO:
            continue
        payload = dict(pos)
        payload.setdefault("ticker", _normalize_ticker(ticker))
        out.append(payload)
    return out


def count_local_phase_d1_live_exit_orders(order_store: Optional[OrderStore] = None) -> Dict[str, Any]:
    store = order_store or OrderStore()
    open_orders = []
    for order in store.open_orders():
        if _is_managed_live_exit_order(order):
            open_orders.append(order)
    return {
        "total_open_live_exit_orders": len(open_orders),
        "tickers": sorted({_order_ticker(o) for o in open_orders if _order_ticker(o)}),
        "orders": [_json_safe(o) for o in open_orders],
    }


def build_phase_d1_exit_order_intent_from_position(
    *,
    cfg: Any,
    position: Dict[str, Any],
    action: str = "reduce_size",
    reduce_fraction: Any = "0.50",
    limit_price: Any = None,
    reason: str = "phase_d1_exit_scaffold_preview",
) -> Dict[str, Any]:
    """Build a deterministic SELL intent from an open position.

    This creates a preview intent only. It does not call Coinbase and does not
    authorize live exits. It clamps the sell size to the local position base and
    keeps the first D.1 phase under a small quote-value cap.
    """
    ticker = _normalize_ticker(position.get("ticker"))
    base_available = _to_decimal(position.get("bot_managed_base") or position.get("position_size_base"), "0")
    entry_price = _to_decimal(position.get("entry_price"), "0")
    px = _to_decimal(limit_price if limit_price is not None else position.get("current_price") or position.get("last_price") or entry_price, "0")
    fraction = _to_decimal(reduce_fraction, "0.50")
    if action == "close_position":
        requested_base = base_available
    else:
        if fraction <= ZERO or fraction > Decimal("1"):
            fraction = Decimal("0.50")
        requested_base = base_available * fraction

    max_quote = min(_cfg_dec(cfg, "phase_d1_max_exit_order_quote", D1_MAX_EXIT_QUOTE), D1_MAX_EXIT_QUOTE)
    if px > ZERO and requested_base * px > max_quote:
        requested_base = max_quote / px
    if requested_base > base_available:
        requested_base = base_available
    if requested_base < ZERO:
        requested_base = ZERO

    cid = f"phased1-{ticker.replace('-', '')}-{_now_iso().replace(':', '').replace('.', '')[-18:]}"
    return _json_safe({
        "intent_id": cid,
        "client_order_id": cid,
        "ticker": ticker,
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "decision": action,
        "size_base": str(requested_base),
        "estimated_quote_value": str(requested_base * px if px > ZERO else ZERO),
        "limit_price": str(px),
        "reduce_only_local": True,
        "source_position_order_id": str(position.get("order_id") or ""),
        "source_position_base": str(base_available),
        "reason": reason,
        "phase": D1_PHASE,
    })


def assess_phase_d1_exit_readiness(
    *,
    cfg: Any,
    position: Optional[Dict[str, Any]],
    exit_intent: Optional[Dict[str, Any]],
    order_store: Optional[OrderStore] = None,
    open_live_exit_orders_count: int = 0,
) -> Dict[str, Any]:
    position = _as_dict(position)
    intent = _as_dict(exit_intent)
    ticker = _normalize_ticker(intent.get("ticker") or position.get("ticker"))
    blockers: List[str] = []
    passed: List[str] = []
    warnings: List[str] = []

    allowed = set(_allowed_tickers(cfg))
    position_base = _to_decimal(position.get("bot_managed_base") or position.get("position_size_base"), "0")
    sell_base = _to_decimal(intent.get("size_base"), "0")
    limit_price = _to_decimal(intent.get("limit_price"), "0")
    estimated_quote = _to_decimal(intent.get("estimated_quote_value"), "0") or (sell_base * limit_price if limit_price > ZERO else ZERO)
    max_quote = min(_cfg_dec(cfg, "phase_d1_max_exit_order_quote", D1_MAX_EXIT_QUOTE), D1_MAX_EXIT_QUOTE)
    max_open = min(_cfg_int(cfg, "phase_d1_max_open_exit_orders", D1_MAX_OPEN_EXIT_ORDERS), D1_MAX_OPEN_EXIT_ORDERS)
    status = str(position.get("status", "open")).lower()

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(_cfg_bool(cfg, "enable_phase_d1_exit_orderbook_scaffold", True), "d1_scaffold_enabled", "d1_scaffold_disabled")
    require(not _cfg_bool(cfg, "enable_phase_d1_actual_exit_submit", False), "actual_exit_submit_disabled", "actual_exit_submit_enabled_forbidden_in_d1_scaffold")
    require(not _cfg_bool(cfg, "enable_live_exit_orders", False), "live_exit_orders_disabled", "live_exit_orders_enabled_not_allowed_until_later")
    require(not _cfg_bool(cfg, "autonomous_allow_exits", False), "autonomous_exits_disabled", "autonomous_allow_exits_true_not_allowed_until_later")
    require(_cfg_bool(cfg, "phase_c_disable_exit_limit_orders", True), "phase_c_exit_orders_disabled", "phase_c_exit_limit_orders_not_disabled")
    require(bool(ticker), "ticker_present", "ticker_missing")
    require(bool(allowed) and ticker in allowed, "ticker_allowed", "ticker_not_allowed")
    require(status == "open", "position_open", "position_not_open")
    require(position_base > ZERO, "position_base_positive", "position_base_missing_or_zero")
    require(str(intent.get("side") or "").upper() == "SELL", "side_sell", "side_not_sell")
    require(str(intent.get("execution_action") or "").lower() == "place_limit_sell", "execution_action_place_limit_sell", "execution_action_not_place_limit_sell")
    require(bool(intent.get("reduce_only_local")), "reduce_only_local_true", "reduce_only_local_missing")
    require(sell_base > ZERO, "sell_base_positive", "sell_base_missing_or_zero")
    require(sell_base <= position_base, "sell_base_lte_position_base", "sell_base_exceeds_position_base")
    require(limit_price > ZERO, "limit_price_present", "limit_price_missing")
    require(estimated_quote > ZERO and estimated_quote <= max_quote, "estimated_quote_within_d1_cap", "estimated_quote_missing_or_above_d1_cap")
    require(open_live_exit_orders_count < max_open, "open_exit_order_capacity_available", "max_open_exit_orders_reached")

    if sell_base == position_base:
        warnings.append("full_close_preview_only_no_live_exit_submit_in_d1")

    ready = not blockers
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D1_PHASE,
        "ticker": ticker,
        "status": "d1_exit_scaffold_ready_no_submit" if ready else "d1_exit_scaffold_blocked",
        "ready_no_submit": ready,
        "blockers": blockers,
        "passed_checks": passed,
        "warnings": warnings,
        "position_base": str(position_base),
        "sell_base": str(sell_base),
        "estimated_quote_value": str(estimated_quote),
        "max_exit_quote": str(max_quote),
        "open_live_exit_orders_count": int(open_live_exit_orders_count),
        "safety_policy": {
            "reduce_only_local": True,
            "no_live_exit_submit_in_d1": True,
            "sell_base_must_not_exceed_position": True,
            "max_exit_quote_25_usdc": True,
            "live_exits_forbidden_until_later": True,
        },
    })


def build_phase_d1_exit_payload_preview(*, cfg: Any, exit_intent: Dict[str, Any], readiness: Dict[str, Any]) -> Dict[str, Any]:
    intent = _as_dict(exit_intent)
    ticker = _normalize_ticker(intent.get("ticker"))
    base = _to_decimal(intent.get("size_base"), "0")
    limit_price = _to_decimal(intent.get("limit_price"), "0")
    reject_reasons: List[str] = []
    if str(intent.get("side") or "").upper() != "SELL":
        reject_reasons.append("exit_payload_only_supports_sell")
    if str(intent.get("execution_action") or "").lower() != "place_limit_sell":
        reject_reasons.append("exit_payload_requires_place_limit_sell")
    if base <= ZERO:
        reject_reasons.append("missing_or_zero_base_size")
    if limit_price <= ZERO:
        reject_reasons.append("missing_or_zero_limit_price")
    if not bool(readiness.get("ready_no_submit")):
        reject_reasons.append("d1_readiness_not_green")

    client_order_id = str(intent.get("client_order_id") or "") or f"phased1-{ticker.replace('-', '')}"
    payload = {
        "client_order_id": client_order_id,
        "product_id": ticker,
        "side": "SELL",
        "order_configuration": {
            "limit_limit_gtc": {
                "base_size": format(base, "f"),
                "limit_price": format(limit_price, "f"),
                "post_only": bool(getattr(cfg, "phase_d1_exit_order_post_only", True)),
            }
        },
    }
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D1_PHASE,
        "ticker": ticker,
        "accepted": not reject_reasons,
        "reject_reasons": reject_reasons,
        "client_order_id": client_order_id,
        "side": "SELL",
        "order_type": "limit_limit_gtc",
        "size_base": str(base),
        "limit_price": str(limit_price),
        "estimated_quote_value": str(base * limit_price if limit_price > ZERO else ZERO),
        "post_only": bool(getattr(cfg, "phase_d1_exit_order_post_only", True)),
        "coinbase_payload_preview": payload,
        "safety_policy": {
            "preview_only": True,
            "no_coinbase_submit": True,
            "reduce_only_local": True,
        },
    })


def _summarize_fills(fills: Iterable[Dict[str, Any]], *, fallback_price: Any = None) -> Dict[str, Any]:
    total_base = ZERO
    total_quote = ZERO
    count = 0
    for fill in fills or []:
        if not isinstance(fill, dict):
            continue
        count += 1
        price = _to_decimal(fill.get("price") or fill.get("fill_price") or fallback_price, "0")
        base = _to_decimal(fill.get("size") or fill.get("filled_size") or fill.get("base_size"), "0")
        quote = _to_decimal(fill.get("quote_size") or fill.get("filled_value") or fill.get("commissionless_value") or fill.get("trade_value"), "0")
        if quote <= ZERO and price > ZERO and base > ZERO:
            quote = base * price
        total_base += max(ZERO, base)
        total_quote += max(ZERO, quote)
    avg_price = (total_quote / total_base) if total_base > ZERO and total_quote > ZERO else _to_decimal(fallback_price, "0")
    return {"fill_count": count, "filled_base": str(total_base), "filled_quote": str(total_quote), "avg_fill_price": str(avg_price)}


def _normalize_live_order_snapshot(order: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(order or {})
    return _json_safe({
        "client_order_id": _client_order_id(raw),
        "exchange_order_id": _exchange_order_id(raw),
        "ticker": _order_ticker(raw),
        "side": _order_side(raw),
        "status": _order_status(raw),
        "limit_price": str(_limit_price(raw)),
        "base_size": str(_base_size(raw)),
        "filled_base": str(_filled_base(raw)),
        "avg_fill_price": str(_avg_fill_price(raw)),
        "managed_by_phase_d1": _is_managed_live_exit_order(raw),
        "raw": raw,
    })


def reconcile_phase_d1_exit_fills_to_positions(
    *,
    cfg: Any,
    order_store: Optional[OrderStore] = None,
    state_store: Any = None,
    coinbase_client: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
    allow_coinbase_poll: bool = False,
    tickers: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Reconcile D.1 SELL fills into local OrderStore/StateStore.

    This function is safe to run as a preview. It never submits new orders and
    never buys. It only updates local state when explicit fill evidence is
    supplied via snapshot or Coinbase polling.
    """
    store = order_store or OrderStore()
    selected_tickers = {_normalize_ticker(t) for t in (tickers or []) if _normalize_ticker(t)}
    local_orders = [o for o in store.open_orders() if _is_managed_live_exit_order(o)]
    if selected_tickers:
        local_orders = [o for o in local_orders if _order_ticker(o) in selected_tickers]

    live_by_key: Dict[str, Dict[str, Any]] = {}
    coinbase_call_attempted = False
    coinbase_call_succeeded = False
    errors: List[Dict[str, str]] = []

    for snap in live_orders_snapshot or []:
        norm = _normalize_live_order_snapshot(snap)
        key = norm.get("client_order_id") or norm.get("exchange_order_id")
        if key:
            live_by_key[str(key)] = norm

    if allow_coinbase_poll and coinbase_client is not None:
        for local in local_orders:
            oid = str(local.get("exchange_order_id") or local.get("order_id") or "").strip()
            if not oid:
                continue
            coinbase_call_attempted = True
            try:
                payload = coinbase_client.get_order(oid)
                order_obj = _as_dict(payload.get("order") if isinstance(payload, dict) else payload)
                if not order_obj and isinstance(payload, dict):
                    order_obj = payload
                norm = _normalize_live_order_snapshot(order_obj)
                key = norm.get("client_order_id") or str(local.get("client_order_id") or oid)
                norm.setdefault("client_order_id", str(local.get("client_order_id") or ""))
                norm.setdefault("exchange_order_id", oid)
                live_by_key[str(key)] = norm
                coinbase_call_succeeded = True
            except Exception as exc:
                errors.append({"order_id": oid, "error_type": type(exc).__name__, "error": str(exc)})

    actions: List[Dict[str, Any]] = []
    for local in local_orders:
        cid = str(local.get("client_order_id") or "")
        oid = str(local.get("exchange_order_id") or local.get("order_id") or "")
        live = live_by_key.get(cid) or live_by_key.get(oid) or {}
        ticker = _order_ticker(local) or _normalize_ticker(live.get("ticker"))
        if not live:
            actions.append({"client_order_id": cid, "ticker": ticker, "action": "no_live_snapshot", "status": "skipped"})
            continue
        status = str(live.get("status") or "").lower()
        filled_base = _to_decimal(live.get("filled_base"), "0")
        avg_price = _to_decimal(live.get("avg_fill_price") or local.get("limit_price"), "0")
        fills_summary: Optional[Dict[str, Any]] = None
        if allow_coinbase_poll and coinbase_client is not None and oid:
            try:
                fills = coinbase_client.get_recent_fills_for_order(oid, limit=100)
                fills_summary = _summarize_fills(fills, fallback_price=avg_price)
                filled_base = max(filled_base, _to_decimal(fills_summary.get("filled_base"), "0"))
                avg_price = _to_decimal(fills_summary.get("avg_fill_price"), str(avg_price))
            except Exception as exc:
                errors.append({"order_id": oid, "error_type": type(exc).__name__, "error": str(exc)})
        is_final_fill = status in {"filled", "done", "completed"} or (filled_base > ZERO and status in D1_FINAL_ORDER_STATUSES)
        is_partial = filled_base > ZERO and not is_final_fill
        if is_partial:
            updated = store.update_order(cid, {
                "status": "partially_filled",
                "filled_size_base": str(filled_base),
                "avg_fill_price": str(avg_price),
                "last_live_order_snapshot": live,
                "last_fills_summary": fills_summary,
            }, event_type="phase_d1_live_exit_order_partially_filled")
            actions.append({"client_order_id": cid, "ticker": ticker, "action": "partial_exit_fill_recorded", "order": updated})
            continue
        if is_final_fill and filled_base > ZERO:
            updated = store.update_order(cid, {
                "status": "filled",
                "filled_at": _now_iso(),
                "filled_size_base": str(filled_base),
                "filled_quote_value": str(filled_base * avg_price if avg_price > ZERO else ZERO),
                "remaining_size": "0",
                "avg_fill_price": str(avg_price),
                "last_live_order_snapshot": live,
                "last_fills_summary": fills_summary,
            }, event_type="phase_d1_live_exit_order_filled")
            position_action = None
            if state_store is not None and hasattr(state_store, "get_position"):
                current = state_store.get_position(ticker) or {}
                current_base = _to_decimal(current.get("position_size_base") or current.get("bot_managed_base"), "0")
                remaining_base = max(ZERO, current_base - filled_base)
                if remaining_base <= ZERO:
                    if hasattr(state_store, "mark_position_closed"):
                        position_action = state_store.mark_position_closed(
                            ticker=ticker,
                            close_reason="phase_d1_live_limit_sell_filled",
                            close_price=str(avg_price),
                        )
                elif hasattr(state_store, "force_sync_position_base"):
                    position_action = state_store.force_sync_position_base(
                        ticker=ticker,
                        actual_base_size=str(remaining_base),
                        current_price=str(avg_price),
                    )
            actions.append({"client_order_id": cid, "ticker": ticker, "action": "exit_fill_to_position_update", "order": updated, "position": position_action})
            continue
        actions.append({"client_order_id": cid, "ticker": ticker, "action": "kept_open", "live_status": status or "unknown"})

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D1_PHASE,
        "status": "exit_fill_reconciliation_completed",
        "coinbase_call_attempted": coinbase_call_attempted,
        "coinbase_call_succeeded": coinbase_call_succeeded,
        "local_live_exit_orders_seen": len(local_orders),
        "actions": actions,
        "errors": errors,
        "safety_policy": {
            "does_not_submit": True,
            "does_not_create_entry_orders": True,
            "exit_fills_only": True,
            "positions_updated_only_after_fill_evidence": True,
        },
    })


def build_phase_d1_status_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    order_store: Optional[OrderStore] = None,
    state_store: Any = None,
    live_orders_snapshot: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    store = order_store or OrderStore()
    positions = _open_positions(state_store)
    counts = count_local_phase_d1_live_exit_orders(store)
    selected = _normalize_ticker(ticker)
    selected_position = next((p for p in positions if _normalize_ticker(p.get("ticker")) == selected), None)
    preview_intent = None
    readiness = None
    payload_preview = None
    if selected_position:
        preview_intent = build_phase_d1_exit_order_intent_from_position(cfg=cfg, position=selected_position, action="reduce_size")
        readiness = assess_phase_d1_exit_readiness(
            cfg=cfg,
            position=selected_position,
            exit_intent=preview_intent,
            order_store=store,
            open_live_exit_orders_count=int(counts.get("total_open_live_exit_orders") or 0),
        )
        payload_preview = build_phase_d1_exit_payload_preview(cfg=cfg, exit_intent=preview_intent, readiness=readiness)
    reconcile_preview = reconcile_phase_d1_exit_fills_to_positions(
        cfg=cfg,
        order_store=store,
        state_store=state_store,
        live_orders_snapshot=live_orders_snapshot or [],
        allow_coinbase_poll=False,
        tickers=None,
    )
    return _json_safe({
        "generated_at": _now_iso(),
        "phase": D1_PHASE,
        "ticker": selected,
        "config": {
            "enable_phase_d1_exit_orderbook_scaffold": bool(getattr(cfg, "enable_phase_d1_exit_orderbook_scaffold", True)),
            "enable_phase_d1_actual_exit_submit": bool(getattr(cfg, "enable_phase_d1_actual_exit_submit", False)),
            "enable_live_exit_orders": bool(getattr(cfg, "enable_live_exit_orders", False)),
            "autonomous_allow_exits": bool(getattr(cfg, "autonomous_allow_exits", False)),
            "phase_c_disable_exit_limit_orders": bool(getattr(cfg, "phase_c_disable_exit_limit_orders", True)),
            "phase_d1_max_exit_order_quote": str(getattr(cfg, "phase_d1_max_exit_order_quote", D1_MAX_EXIT_QUOTE)),
            "phase_d1_max_open_exit_orders": int(getattr(cfg, "phase_d1_max_open_exit_orders", D1_MAX_OPEN_EXIT_ORDERS)),
        },
        "open_position_count": len(positions),
        "selected_position_present": bool(selected_position),
        "selected_position": selected_position,
        "local_live_exit_order_counts": counts,
        "exit_intent_preview": preview_intent,
        "exit_readiness": readiness,
        "exit_payload_preview": payload_preview,
        "fill_reconciliation_preview": reconcile_preview,
        "next_step": "D.1 is reduce-only exit scaffold/fill bridge. Actual live exit submission remains disabled until a later explicit phase.",
        "safety_policy": {
            "reduce_only_local": True,
            "no_live_exit_submit_in_d1": True,
            "entry_orders_unchanged": True,
            "max_exit_quote_25_usdc": True,
            "max_open_exit_orders_4": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "D1_PHASE",
    "build_phase_d1_exit_order_intent_from_position",
    "assess_phase_d1_exit_readiness",
    "build_phase_d1_exit_payload_preview",
    "count_local_phase_d1_live_exit_orders",
    "reconcile_phase_d1_exit_fills_to_positions",
    "build_phase_d1_status_report",
]
