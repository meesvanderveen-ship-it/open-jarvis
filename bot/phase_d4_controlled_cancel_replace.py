from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot
from bot.live_exit_gate import (
    D4_CONTROLLED_CANCEL_REPLACE_ACK,
    D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
    evaluate_d4_controlled_replacement_submit_allowed,
)
from bot.order_store import OrderStore
from bot.phase_c43_one_entry_smoke_test import extract_product_rules
from bot.phase_d4_cancel_replace_planner import build_phase_d4_cancel_replace_plan
from bot.state_store import StateStore


D4_CONTROLLED_CANCEL_REPLACE_PHASE = "D4_controlled_cancel_replace"
ZERO = Decimal("0")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _load_json(path: str | Path) -> Dict[str, Any]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw = payload.get("orders", payload)
    if isinstance(raw, dict):
        return [dict(item) for item in raw.values() if isinstance(item, dict)]
    if isinstance(raw, list):
        return [dict(item) for item in raw if isinstance(item, dict)]
    return []


def _position_from_payload(payload: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    raw = payload.get("positions", payload)
    if isinstance(raw, dict):
        direct = raw.get(selected) or raw.get(ticker)
        if isinstance(direct, dict):
            return dict(direct)
        for item in raw.values():
            if isinstance(item, dict) and _normalize_ticker(item.get("ticker")) == selected:
                return dict(item)
    return {}


def _find_order(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    for order in orders:
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if selected_client and str(order.get("client_order_id") or "").strip() == selected_client:
            return dict(order)
        order_exchange = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if selected_exchange and order_exchange == selected_exchange:
            return dict(order)
    return {}


def _normalize_status(value: Any, *, filled_base: Any = "0") -> str:
    status = str(value or "").strip().lower()
    if status in {"submitted", "pending", "open", "active", "accepted", "new", "created"}:
        return "partially_filled" if _to_decimal(filled_base) > ZERO else "open"
    if status in {"partial", "partially_filled"}:
        return "partially_filled"
    if status in {"filled", "done", "completed", "complete", "settled"}:
        return "filled"
    if status in {"cancelled", "canceled", "cancelled_order", "canceled_order"}:
        return "cancelled"
    if status in {"expired", "timed_out", "timeout"}:
        return "expired"
    if status in {"rejected", "failed", "failure"}:
        return "rejected"
    if status in {"pending_cancel", "cancel_pending"}:
        return "cancel_pending"
    if _to_decimal(filled_base) > ZERO:
        return "partially_filled"
    return status or "unknown"


def _open_d3_exit_orders(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    linked_position_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position = str(linked_position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in orders:
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if _normalize_status(order.get("status"), filled_base=order.get("filled_base")) not in {"open", "partially_filled", "cancel_pending"}:
            continue
        if selected_position and str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        out.append(dict(order))
    return out


def _candidate_preview(*, ticker: str, order: Dict[str, Any], linked_position_id: str, replacement_price: Decimal) -> Dict[str, Any]:
    return {
        "status": "d4_trailing_preview_reprice_candidate",
        "ticker": ticker,
        "linked_position_id": linked_position_id,
        "current_order_id": str(order.get("client_order_id") or ""),
        "current_exit_price": str(order.get("limit_price") or ""),
        "proposed_replacement_price": str(replacement_price),
        "proposed_action": "preview_reprice_candidate",
        "post_only_feasible": True,
        "blockers": [],
        "warnings": ["operator_selected_fixed_reprice_target"],
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "cancel_replace_allowed": False,
        "requires_future_ack": True,
    }


def _normalize_cancel_result(payload: Any, *, order_id: str) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    results = data.get("results") if isinstance(data.get("results"), list) else []
    for item in results:
        if not isinstance(item, dict):
            continue
        if order_id and str(item.get("order_id") or "").strip() != order_id:
            continue
        if bool(item.get("success")):
            return {"cancel_confirmed_by_response": True, "cancel_response_status": "cancelled", "cancel_error": ""}
    success_ids = [
        str(item).strip()
        for item in (data.get("success_results") or data.get("order_ids") or data.get("cancelled_order_ids") or [])
        if str(item).strip()
    ]
    if order_id and order_id in success_ids:
        return {"cancel_confirmed_by_response": True, "cancel_response_status": "cancelled", "cancel_error": ""}
    raw_status = str(data.get("status") or data.get("order_status") or data.get("result") or "").strip().lower()
    success = bool(data.get("success")) and raw_status in {"cancelled", "canceled", "cancel_pending", "pending_cancel"}
    return {
        "cancel_confirmed_by_response": success,
        "cancel_response_status": raw_status or ("success" if data.get("success") else "unknown"),
        "cancel_error": "" if success else "cancel_response_not_confirmed",
    }


def _normalize_submit_result(payload: Any) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    success_response = data.get("success_response") if isinstance(data.get("success_response"), dict) else {}
    error_response = data.get("error_response") if isinstance(data.get("error_response"), dict) else {}
    order_id = str(data.get("order_id") or data.get("id") or success_response.get("order_id") or "").strip()
    success = bool(data.get("success", True)) and bool(order_id)
    return {
        "replacement_submit_confirmed": success,
        "replacement_exchange_order_id": order_id,
        "replacement_submit_status": str(data.get("status") or success_response.get("status") or ("submitted" if success else "unknown")),
        "replacement_submit_error": "" if success else str(error_response.get("message") or error_response.get("error") or "replacement_submit_unconfirmed"),
    }


def _build_replacement_client_order_id(*, ticker: str, linked_position_id: str) -> str:
    clean_ticker = _normalize_ticker(ticker).replace("-", "")
    suffix = str(linked_position_id or "position")[-8:].replace("-", "")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"phased4-{clean_ticker}-TP1-repl-{suffix}-{stamp}"


def _state_invariants(
    *,
    ticker: str,
    linked_position_id: str,
    order: Dict[str, Any],
    position: Dict[str, Any],
    open_exits: List[Dict[str, Any]],
    replacement_size: Decimal,
) -> List[str]:
    blockers: List[str] = []
    if not order:
        blockers.append("active_order_not_found")
    if len(open_exits) != 1:
        blockers.append("open_d3_exit_count_not_one")
    if str(order.get("side") or "").strip().upper() != "SELL":
        blockers.append("active_order_not_sell")
    if str(order.get("linked_position_id") or "").strip() != str(linked_position_id or "").strip():
        blockers.append("linked_position_id_mismatch")
    status = _normalize_status(order.get("status"), filled_base=order.get("filled_base"))
    if status != "open":
        blockers.append(f"local_order_status_not_open:{status}")
    if _to_decimal(order.get("filled_base") or order.get("filled_size")) > ZERO or int(order.get("fill_count") or 0) != 0:
        blockers.append("local_order_has_fill_evidence")
    if _to_decimal(order.get("remaining_size") or order.get("size_base")) != replacement_size:
        blockers.append("local_remaining_size_mismatch")
    if str(position.get("status") or "").strip().lower() != "open":
        blockers.append("position_not_open")
    if _to_decimal(position.get("reserved_base_open_exit_orders")) < replacement_size:
        blockers.append("reserved_base_less_than_replacement_size")
    if _to_decimal(position.get("position_size_base")) + _to_decimal(position.get("reserved_base_open_exit_orders")) < replacement_size:
        blockers.append("position_base_less_than_replacement_size")
    if _normalize_ticker(order.get("ticker") or order.get("product_id")) != _normalize_ticker(ticker):
        blockers.append("ticker_mismatch")
    return blockers


def _resume_after_local_cancel_invariants(
    *,
    ticker: str,
    linked_position_id: str,
    order: Dict[str, Any],
    position: Dict[str, Any],
    open_exits: List[Dict[str, Any]],
    replacement_size: Decimal,
) -> List[str]:
    blockers: List[str] = []
    if not order:
        blockers.append("active_order_not_found")
    if len(open_exits) != 0:
        blockers.append("open_d3_exit_count_not_zero_after_confirmed_cancel")
    if str(order.get("side") or "").strip().upper() != "SELL":
        blockers.append("active_order_not_sell")
    if str(order.get("linked_position_id") or "").strip() != str(linked_position_id or "").strip():
        blockers.append("linked_position_id_mismatch")
    status = _normalize_status(order.get("status"), filled_base=order.get("filled_base"))
    if status != "cancelled":
        blockers.append(f"local_order_status_not_cancelled:{status}")
    if _to_decimal(order.get("filled_base") or order.get("filled_size")) > ZERO or int(order.get("fill_count") or 0) != 0:
        blockers.append("local_order_has_fill_evidence")
    if _to_decimal(order.get("remaining_size") or order.get("size_base")) != replacement_size:
        blockers.append("local_remaining_size_mismatch")
    if str(position.get("status") or "").strip().lower() != "open":
        blockers.append("position_not_open")
    if _to_decimal(position.get("reserved_base_open_exit_orders")) < replacement_size:
        blockers.append("reserved_base_less_than_replacement_size")
    if _normalize_ticker(order.get("ticker") or order.get("product_id")) != _normalize_ticker(ticker):
        blockers.append("ticker_mismatch")
    return blockers


_LIFECYCLE_TERMINAL_STATUSES = {"cancelled", "canceled", "filled", "expired", "rejected"}


def _resolve_lifecycle_snapshot(
    *,
    coinbase_client: Any,
    order: Dict[str, Any],
    exchange_order_id: str,
    snapshot: Optional[Dict[str, Any]],
    retry_past_non_terminal: bool = False,
    max_attempts: int = 4,
    retry_seconds: float = 0.75,
) -> Dict[str, Any]:
    if snapshot is not None:
        return _json_safe({"coinbase_call_attempted": False, "coinbase_call_succeeded": True, **dict(snapshot)})
    # A cancel resolves near-instantly on Coinbase's matching engine, but a
    # snapshot lookup taken immediately after can still race ahead of
    # settlement (confirmed live 2026-07-08 in the sibling controlled
    # stop-exit path: an order that had actually filled completely was read
    # back as "OPEN" moments after submit). retry_past_non_terminal is only
    # set by the post-cancel confirmation call site below -- the preflight
    # call site has no just-submitted action to race against, so it keeps its
    # original single-lookup behavior.
    fetched: Dict[str, Any] = {}
    attempts = max(1, int(max_attempts)) if retry_past_non_terminal else 1
    for attempt in range(attempts):
        fetched = fetch_coinbase_order_snapshot(
            coinbase_client=coinbase_client,
            order_id=exchange_order_id,
            local_order=order,
            include_fills=True,
        )
        status = str(fetched.get("normalized_status") or "").strip().lower()
        filled = _to_decimal(fetched.get("filled_base"))
        if not retry_past_non_terminal or status in _LIFECYCLE_TERMINAL_STATUSES or filled > ZERO:
            break
        if attempt < attempts - 1:
            time.sleep(max(0.0, float(retry_seconds)))
    fills_summary = fetched.get("fills_summary") if isinstance(fetched.get("fills_summary"), dict) else {}
    return _json_safe({
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": fetched.get("raw_status") or fetched.get("status") or "",
        "normalized_status": fetched.get("normalized_status") or "",
        "filled_base": fetched.get("filled_base") or "0",
        "filled_quote": fetched.get("filled_quote") or "0",
        "avg_fill_price": fetched.get("avg_fill_price") or "0",
        "fill_count": int(fills_summary.get("fill_count") or 0),
        "remaining_size": str(order.get("remaining_size") or order.get("size_base") or "0"),
        "snapshot": fetched,
    })


def _resolve_market_snapshot(*, coinbase_client: Any, ticker: str, snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if snapshot is not None:
        return _json_safe({"coinbase_call_attempted": False, "coinbase_call_succeeded": True, **dict(snapshot)})
    payload = coinbase_client.get_public_ticker(ticker)
    bid = _to_decimal(payload.get("best_bid"))
    ask = _to_decimal(payload.get("best_ask"))
    mid = _to_decimal(payload.get("price") or payload.get("mid_price"))
    if mid <= ZERO and bid > ZERO and ask > ZERO:
        mid = (bid + ask) / Decimal("2")
    return _json_safe({
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "best_bid": bid,
        "best_ask": ask,
        "mid_price": mid,
        "raw_ticker": payload,
    })


def _resolve_product_rules(*, coinbase_client: Any, ticker: str, rules: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if rules is not None:
        return _json_safe({"coinbase_call_attempted": False, "coinbase_call_succeeded": True, **dict(rules)})
    product = coinbase_client.get_product(ticker)
    extracted = extract_product_rules(product)
    return _json_safe({
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "base_increment": str(extracted.get("base_increment") or "0"),
        "price_increment": str(
            product.get("price_increment")
            or product.get("price_increment_size")
            or extracted.get("quote_increment")
            or "0"
        ),
        "quote_increment": str(extracted.get("quote_increment") or "0"),
        "min_order_quote": str(
            product.get("quote_min_size")
            or product.get("quote_min_order_size")
            or product.get("min_market_funds")
            or product.get("min_order_quote")
            or "0"
        ),
        "raw_product": product,
    })


def run_phase_d4_controlled_cancel_replace(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    replacement_price: Any,
    ack: str = "",
    allow_live_cancel: bool = False,
    allow_live_replace: bool = False,
    one_shot_armed_process_local: bool = False,
    coinbase_client: Any = None,
    orders_file: str | Path = "state/open_orders.json",
    positions_file: str | Path = "state/positions.json",
    order_events_file: str | Path = "logs/order_events.jsonl",
    lifecycle_snapshot: Optional[Dict[str, Any]] = None,
    market_snapshot: Optional[Dict[str, Any]] = None,
    product_rules: Optional[Dict[str, Any]] = None,
    post_cancel_snapshot: Optional[Dict[str, Any]] = None,
    resume_after_confirmed_cancel: bool = False,
    cancel_only_after_confirmed_cancel: bool = False,
    post_cancel_confirmation_max_attempts: int = 4,
    post_cancel_confirmation_retry_seconds: float = 0.75,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    replacement_price_dec = _to_decimal(replacement_price)
    orders_path = Path(orders_file)
    positions_path = Path(positions_file)
    orders_payload = _load_json(orders_path)
    positions_payload = _load_json(positions_path)
    orders = _orders_from_payload(orders_payload)
    position = _position_from_payload(positions_payload, selected_ticker)
    order = _find_order(
        orders,
        ticker=selected_ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    replacement_size = _to_decimal(order.get("remaining_size") or order.get("size_base")) if order else ZERO
    open_exits = _open_d3_exit_orders(orders, ticker=selected_ticker, linked_position_id=linked_position_id)
    estimated_quote = replacement_price_dec * replacement_size if replacement_price_dec > ZERO and replacement_size > ZERO else ZERO
    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": D4_CONTROLLED_CANCEL_REPLACE_PHASE,
        "status": "d4_controlled_cancel_replace_preflight_blocked",
        "ticker": selected_ticker,
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": str(linked_position_id or "").strip(),
        "replacement_price": str(replacement_price_dec),
        "replacement_size_base": str(replacement_size),
        "estimated_quote": str(estimated_quote),
        "required_ack": D4_CONTROLLED_CANCEL_REPLACE_ACK,
        "ack_valid": str(ack or "").strip() == D4_CONTROLLED_CANCEL_REPLACE_ACK,
        "one_shot_d4_replacement_submit_armed_process_local": bool(one_shot_armed_process_local),
        "cancel_attempted": False,
        "resume_after_confirmed_cancel": bool(resume_after_confirmed_cancel),
        "cancel_succeeded": False,
        "cancel_confirmed": False,
        "replacement_submit_attempted": False,
        "replacement_submit_succeeded": False,
        "replacement_client_order_id": "",
        "replacement_exchange_order_id": "",
        "state_write_performed": False,
        "live_action_performed": False,
        "coinbase_write_calls": 0,
        "blockers": [],
        "warnings": [],
        "old_order_status_after": str((order or {}).get("status") or ""),
        "new_order_status_after": "",
        "no_lifecycle_apply": True,
        "env_mutation": False,
        "service_restart": False,
        "learning_to_execution_allowed": False,
    }
    if resume_after_confirmed_cancel:
        blockers = _resume_after_local_cancel_invariants(
            ticker=selected_ticker,
            linked_position_id=linked_position_id,
            order=order,
            position=position,
            open_exits=open_exits,
            replacement_size=replacement_size,
        )
    else:
        blockers = _state_invariants(
            ticker=selected_ticker,
            linked_position_id=linked_position_id,
            order=order,
            position=position,
            open_exits=open_exits,
            replacement_size=replacement_size,
        )
    report["preflight_state"] = {
        "order_found": bool(order),
        "open_d3_exit_count_for_position": len(open_exits),
        "reserved_base_open_exit_orders": str(position.get("reserved_base_open_exit_orders") or "0"),
        "position_size_base": str(position.get("position_size_base") or "0"),
        "local_order_status": str((order or {}).get("status") or ""),
        "local_fill_count": int((order or {}).get("fill_count") or 0),
    }

    if coinbase_client is None and (lifecycle_snapshot is None or market_snapshot is None or product_rules is None or allow_live_cancel or allow_live_replace):
        blockers.append("coinbase_client_missing")
    if not report["ack_valid"]:
        blockers.append("d4_ack_missing_or_invalid")
    if replacement_price_dec <= ZERO:
        blockers.append("replacement_price_invalid")

    lifecycle = {}
    market = {}
    rules = {}
    if not blockers:
        try:
            lifecycle = _resolve_lifecycle_snapshot(
                coinbase_client=coinbase_client,
                order=order,
                exchange_order_id=exchange_order_id,
                snapshot=lifecycle_snapshot,
            )
        except Exception as exc:
            blockers.append("preflight_lifecycle_poll_failed")
            lifecycle = {"error": f"{type(exc).__name__}: {exc}", "coinbase_call_succeeded": False}
    lifecycle_status = _normalize_status(lifecycle.get("normalized_status") or lifecycle.get("raw_status"), filled_base=lifecycle.get("filled_base"))
    lifecycle_filled = _to_decimal(lifecycle.get("filled_base"))
    lifecycle_fill_count = int(lifecycle.get("fill_count") or 0)
    lifecycle_remaining = _to_decimal(lifecycle.get("remaining_size") or replacement_size)
    if lifecycle:
        if lifecycle_status in {"partially_filled", "filled"} or lifecycle_filled > ZERO or lifecycle_fill_count > 0:
            blockers.append("fill_evidence_route_to_d3_lifecycle_apply")
        elif lifecycle_status == "cancelled" and resume_after_confirmed_cancel:
            pass
        elif lifecycle_status in {"cancelled", "expired", "rejected"}:
            blockers.append("terminal_evidence_route_to_d3_terminal_closeout")
        elif lifecycle_status != "open":
            blockers.append(f"lifecycle_status_not_open:{lifecycle_status}")
        if lifecycle_status != "cancelled" and lifecycle_remaining != replacement_size:
            blockers.append("coinbase_remaining_size_mismatch")

    if not blockers:
        try:
            market = _resolve_market_snapshot(coinbase_client=coinbase_client, ticker=selected_ticker, snapshot=market_snapshot)
        except Exception as exc:
            blockers.append("market_snapshot_failed")
            market = {"error": f"{type(exc).__name__}: {exc}", "coinbase_call_succeeded": False}
    if not blockers:
        try:
            rules = _resolve_product_rules(coinbase_client=coinbase_client, ticker=selected_ticker, rules=product_rules)
        except Exception as exc:
            blockers.append("product_rules_failed")
            rules = {"error": f"{type(exc).__name__}: {exc}", "coinbase_call_succeeded": False}

    best_ask = _to_decimal(market.get("best_ask"))
    price_increment = _to_decimal(rules.get("price_increment"))
    base_increment = _to_decimal(rules.get("base_increment"))
    min_order_quote = _to_decimal(rules.get("min_order_quote"))
    if market and best_ask > ZERO and replacement_price_dec <= best_ask:
        blockers.append("replacement_price_not_post_only_safe_for_sell")
    if rules:
        if price_increment > ZERO and not _decimal_respects_increment(replacement_price_dec, price_increment):
            blockers.append("replacement_price_increment_violation")
        if base_increment > ZERO and not _decimal_respects_increment(replacement_size, base_increment):
            blockers.append("replacement_base_increment_violation")
        if min_order_quote > ZERO and estimated_quote < min_order_quote:
            blockers.append("replacement_below_min_order_quote")

    preview = _candidate_preview(
        ticker=selected_ticker,
        order=order,
        linked_position_id=linked_position_id,
        replacement_price=replacement_price_dec,
    ) if order else {}
    planner = build_phase_d4_cancel_replace_plan(
        preview_report=preview,
        current_order=order,
        linked_position_id=linked_position_id,
        position=position,
        product_rules={"min_order_quote": str(min_order_quote)},
        open_orders=open_exits,
        fake_order_status_snapshot={"status": "open", "filled_base": "0"} if lifecycle_status in {"open", "cancelled"} else {"status": lifecycle_status},
        operator_mode="future_ack_required",
    ) if preview and not resume_after_confirmed_cancel else {
        "status": "d4_cancel_replace_plan_ready",
        "proposed_action": "dry_run_cancel_replace_plan_ready",
        "replacement_price": str(replacement_price_dec),
        "replacement_size_base": str(replacement_size),
        "cancel_first_required": True,
        "replace_only_after_confirmed_cancel": True,
        "required_future_ack": D4_CONTROLLED_CANCEL_REPLACE_ACK,
        "blockers": [],
        "warnings": ["resume_after_confirmed_cancel_uses_prior_cancel_first_plan"],
    }
    if planner and planner.get("proposed_action") != "dry_run_cancel_replace_plan_ready":
        blockers.append("d4_planner_not_ready")

    gate_before_cancel = evaluate_d4_controlled_replacement_submit_allowed(
        source_tag=D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
        human_ack=ack,
        one_shot_armed_process_local=one_shot_armed_process_local,
        side="SELL",
        ticker=selected_ticker,
        linked_position_id=linked_position_id,
        old_order_confirmed_cancelled=False,
        cancel_first_required=True,
        replace_only_after_confirmed_cancel=True,
        post_only=True,
        reduce_only_local=True,
        replacement_size_base=replacement_size,
        reserved_base=position.get("reserved_base_open_exit_orders") or "0",
        available_base=position.get("available_base_after_reservations") or position.get("reserved_base_open_exit_orders") or "0",
        duplicate_open_exit_detected=len(open_exits) > 1,
        oversell_detected=False,
        candidate_count=1,
        target_price=replacement_price_dec,
        price_increment=price_increment,
        base_increment=base_increment,
        min_order_quote=min_order_quote,
        estimated_quote=estimated_quote,
        current_order_id=client_order_id,
        current_exchange_order_id=exchange_order_id,
    )
    gate_after_simulated_cancel = evaluate_d4_controlled_replacement_submit_allowed(
        **{
            **{
                "source_tag": D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
                "human_ack": ack,
                "one_shot_armed_process_local": one_shot_armed_process_local,
                "side": "SELL",
                "ticker": selected_ticker,
                "linked_position_id": linked_position_id,
                "old_order_confirmed_cancelled": True,
                "cancel_first_required": True,
                "replace_only_after_confirmed_cancel": True,
                "post_only": True,
                "reduce_only_local": True,
                "replacement_size_base": replacement_size,
                "reserved_base": position.get("reserved_base_open_exit_orders") or "0",
                "available_base": position.get("available_base_after_reservations") or position.get("reserved_base_open_exit_orders") or "0",
                "duplicate_open_exit_detected": False,
                "oversell_detected": False,
                "candidate_count": 1,
                "target_price": replacement_price_dec,
                "price_increment": price_increment,
                "base_increment": base_increment,
                "min_order_quote": min_order_quote,
                "estimated_quote": estimated_quote,
                "current_order_id": client_order_id,
                "current_exchange_order_id": exchange_order_id,
            }
        }
    )
    if "d4_replacement_confirmed_cancel_required" not in gate_before_cancel.get("blockers", []):
        blockers.append("replacement_gate_before_cancel_did_not_require_confirmed_cancel")
    if not gate_after_simulated_cancel.get("allowed"):
        blockers.append("replacement_gate_after_simulated_cancel_not_allowed")

    report.update({
        "lifecycle_evidence": lifecycle,
        "market_snapshot": market,
        "product_rules": rules,
        "d4_planner": planner,
        "replacement_submit_gate_before_cancel": gate_before_cancel,
        "replacement_submit_gate_after_simulated_cancel": gate_after_simulated_cancel,
        "blockers": sorted(set(blockers)),
    })
    if blockers:
        return _json_safe(report)

    live_requested = bool(
        (allow_live_cancel and allow_live_replace)
        or (allow_live_cancel and cancel_only_after_confirmed_cancel)
        or (resume_after_confirmed_cancel and allow_live_replace)
    )
    if not live_requested:
        report["status"] = "d4_controlled_cancel_replace_preflight_ready"
        report["warnings"].append("live_flags_not_requested_preview_only")
        return _json_safe(report)

    if resume_after_confirmed_cancel:
        report["live_action_performed"] = True
        report["cancel_response"] = {"resume_after_confirmed_cancel": True}
        report["cancel_confirmed_by_response"] = True
        confirmed = lifecycle
    else:
        report["cancel_attempted"] = True
        report["live_action_performed"] = True
        report["coinbase_write_calls"] = int(report["coinbase_write_calls"]) + 1
        try:
            cancel_payload = coinbase_client.cancel_order(exchange_order_id)
            cancel_result = _normalize_cancel_result(cancel_payload, order_id=exchange_order_id)
            report["cancel_response"] = cancel_payload
            report.update(cancel_result)
        except Exception as exc:
            report.update({
                "status": "d4_controlled_cancel_replace_cancel_failed_no_replace",
                "cancel_error": f"{type(exc).__name__}: {exc}",
                "blockers": ["cancel_failed_no_replace"],
            })
            return _json_safe(report)
        if not report.get("cancel_confirmed_by_response"):
            report.update({
                "status": "d4_controlled_cancel_replace_cancel_uncertain_no_replace",
                "blockers": ["cancel_response_not_confirmed_no_replace"],
            })
            return _json_safe(report)

        try:
            confirmed = _resolve_lifecycle_snapshot(
                coinbase_client=coinbase_client,
                order=order,
                exchange_order_id=exchange_order_id,
                snapshot=post_cancel_snapshot,
                retry_past_non_terminal=True,
                max_attempts=post_cancel_confirmation_max_attempts,
                retry_seconds=post_cancel_confirmation_retry_seconds,
            )
        except Exception as exc:
            report.update({
                "status": "d4_controlled_cancel_replace_cancel_uncertain_no_replace",
                "post_cancel_evidence": {"error": f"{type(exc).__name__}: {exc}"},
                "blockers": ["post_cancel_confirmation_failed_no_replace"],
            })
            return _json_safe(report)
    confirmed_status = _normalize_status(confirmed.get("normalized_status") or confirmed.get("raw_status"), filled_base=confirmed.get("filled_base"))
    report["post_cancel_evidence"] = confirmed
    if confirmed_status != "cancelled":
        report.update({
            "status": "d4_controlled_cancel_replace_cancel_uncertain_no_replace",
            "blockers": [f"post_cancel_status_not_cancelled:{confirmed_status}"],
        })
        return _json_safe(report)
    report["cancel_succeeded"] = True
    report["cancel_confirmed"] = True

    store = OrderStore(path=orders_path, log_path=order_events_file)
    states = StateStore()
    states.positions_file = positions_path
    now_iso = _now_iso()
    store.update_order(
        str(order.get("client_order_id") or client_order_id),
        {
            "status": "cancelled",
            "cancelled_at": now_iso,
            "closed_at": now_iso,
            "finalized_at": now_iso,
            "d4_cancel_replace_old_order_status": "confirmed_cancelled",
        },
        event_type="phase_d4_controlled_cancel_replace_old_order_cancelled",
    )
    report["state_write_performed"] = True
    report["old_order_status_after"] = "cancelled"

    if cancel_only_after_confirmed_cancel:
        report.update({
            "status": "d4_controlled_cancel_replace_cancel_confirmed_replacement_pending",
            "blockers": [],
            "warnings": list(report.get("warnings") or []) + ["cancel_confirmed_no_replacement_submitted_by_request"],
            "reserved_base_open_exit_orders_after": str(position.get("reserved_base_open_exit_orders") or "0"),
            "open_d3_exit_count_after": 0,
            "duplicate_open_exit_detected_after": False,
            "oversell_detected_after": False,
        })
        return _json_safe(report)

    gate_after_confirmed_cancel = evaluate_d4_controlled_replacement_submit_allowed(
        source_tag=D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
        human_ack=ack,
        one_shot_armed_process_local=one_shot_armed_process_local,
        side="SELL",
        ticker=selected_ticker,
        linked_position_id=linked_position_id,
        old_order_confirmed_cancelled=True,
        cancel_first_required=True,
        replace_only_after_confirmed_cancel=True,
        post_only=True,
        reduce_only_local=True,
        replacement_size_base=replacement_size,
        reserved_base=position.get("reserved_base_open_exit_orders") or "0",
        available_base=position.get("available_base_after_reservations") or position.get("reserved_base_open_exit_orders") or "0",
        duplicate_open_exit_detected=False,
        oversell_detected=False,
        candidate_count=1,
        target_price=replacement_price_dec,
        price_increment=price_increment,
        base_increment=base_increment,
        min_order_quote=min_order_quote,
        estimated_quote=estimated_quote,
        current_order_id=client_order_id,
        current_exchange_order_id=exchange_order_id,
    )
    report["replacement_submit_gate_after_confirmed_cancel"] = gate_after_confirmed_cancel
    if not gate_after_confirmed_cancel.get("allowed"):
        states.upsert_position(
            selected_ticker,
            {"reserved_base_open_exit_orders": "0"},
            caller_reason="d4_cancel_replace_replacement_gate_blocked_after_cancel",
            evidence_status="cancelled",
        )
        report.update({
            "status": "d4_controlled_cancel_replace_replacement_gate_blocked_after_cancel",
            "blockers": list(gate_after_confirmed_cancel.get("blockers") or ["replacement_gate_blocked_after_cancel"]),
            "reserved_base_open_exit_orders_after": "0",
        })
        return _json_safe(report)

    replacement_client_order_id = _build_replacement_client_order_id(
        ticker=selected_ticker,
        linked_position_id=linked_position_id,
    )
    report["replacement_client_order_id"] = replacement_client_order_id
    try:
        report["replacement_submit_attempted"] = True
        report["coinbase_write_calls"] = int(report["coinbase_write_calls"]) + 1
        submit_payload = coinbase_client.place_limit_order(
            ticker=selected_ticker,
            side="SELL",
            base_size=replacement_size,
            limit_price=replacement_price_dec,
            client_order_id=replacement_client_order_id,
            post_only=True,
        )
        submit_result = _normalize_submit_result(submit_payload)
        report["replacement_submit_response"] = submit_payload
        report.update(submit_result)
    except Exception as exc:
        states.upsert_position(
            selected_ticker,
            {"reserved_base_open_exit_orders": "0"},
            caller_reason="d4_cancel_replace_replacement_submit_failed_after_cancel",
            evidence_status="cancelled",
        )
        report.update({
            "status": "d4_controlled_cancel_replace_replacement_submit_failed",
            "replacement_submit_error": f"{type(exc).__name__}: {exc}",
            "blockers": ["replacement_submit_failed_after_confirmed_cancel"],
            "reserved_base_open_exit_orders_after": "0",
        })
        return _json_safe(report)
    if not report.get("replacement_submit_confirmed"):
        states.upsert_position(
            selected_ticker,
            {"reserved_base_open_exit_orders": "0"},
            caller_reason="d4_cancel_replace_replacement_submit_unconfirmed_after_cancel",
            evidence_status="cancelled",
        )
        report.update({
            "status": "d4_controlled_cancel_replace_replacement_submit_failed",
            "blockers": ["replacement_submit_unconfirmed_after_confirmed_cancel"],
            "reserved_base_open_exit_orders_after": "0",
        })
        return _json_safe(report)

    replacement_exchange_order_id = str(report.get("replacement_exchange_order_id") or "").strip()
    store.upsert_order(
        {
            "client_order_id": replacement_client_order_id,
            "exchange_order_id": replacement_exchange_order_id,
            "order_id": replacement_exchange_order_id,
            "ticker": selected_ticker,
            "product_id": selected_ticker,
            "side": "SELL",
            "status": "submitted",
            "mode": "live",
            "source_mode": D4_CONTROLLED_CANCEL_REPLACE_SOURCE,
            "phase": "D3_controlled_live_reduce_only_exits",
            "d4_phase": D4_CONTROLLED_CANCEL_REPLACE_PHASE,
            "d3_exit_label": str(order.get("d3_exit_label") or "TP1"),
            "created_at": now_iso,
            "submitted_at": now_iso,
            "size_base": str(replacement_size),
            "remaining_size": str(replacement_size),
            "filled_base": "0",
            "filled_quote": "0",
            "fill_count": 0,
            "limit_price": str(replacement_price_dec),
            "post_only": True,
            "execution_action": "place_limit_sell",
            "linked_position_id": linked_position_id,
            "reduce_only_local": True,
            "replacement_of_client_order_id": client_order_id,
            "replacement_of_exchange_order_id": exchange_order_id,
            "live_order_submitted": True,
        },
        event_type="phase_d4_controlled_cancel_replace_replacement_submitted",
    )
    final_position = states.upsert_position(
        selected_ticker,
        {
            "status": "open",
            "reserved_base_open_exit_orders": str(replacement_size),
            "last_d4_cancel_replace_replacement_client_order_id": replacement_client_order_id,
            "last_d4_cancel_replace_replacement_exchange_order_id": replacement_exchange_order_id,
            "last_d4_cancel_replace_replaced_client_order_id": client_order_id,
            "last_d4_cancel_replace_replaced_exchange_order_id": exchange_order_id,
        },
        caller_reason="d4_controlled_cancel_replace_replacement_submitted",
        evidence_status="open",
    )
    final_orders = OrderStore(path=orders_path, log_path=order_events_file)
    final_open_exits = _open_d3_exit_orders(
        final_orders.all_orders(),
        ticker=selected_ticker,
        linked_position_id=linked_position_id,
    )
    report.update({
        "status": "d4_controlled_cancel_replace_applied",
        "replacement_submit_succeeded": True,
        "new_order_status_after": "submitted",
        "reserved_base_open_exit_orders_after": str(final_position.get("reserved_base_open_exit_orders") or "0"),
        "open_d3_exit_count_after": len(final_open_exits),
        "duplicate_open_exit_detected_after": len(final_open_exits) > 1,
        "oversell_detected_after": False,
        "blockers": [],
    })
    return _json_safe(report)


def _decimal_respects_increment(value: Decimal, increment: Decimal) -> bool:
    if increment <= ZERO:
        return True
    if value <= ZERO:
        return False
    units = value / increment
    return units == units.to_integral_value()


__all__ = [
    "D4_CONTROLLED_CANCEL_REPLACE_PHASE",
    "run_phase_d4_controlled_cancel_replace",
]
