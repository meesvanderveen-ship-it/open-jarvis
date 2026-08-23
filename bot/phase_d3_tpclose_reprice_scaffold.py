from __future__ import annotations

import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Dict, Optional

from bot.coinbase_client import CoinbaseClient
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot
from bot.live_exit_gate import assert_live_exit_allowed
from bot.order_store import OrderStore
from bot.state_store import StateStore


TPCLOSE_REPRICE_ACK = "I_UNDERSTAND_AND_APPROVE_D3_D4_CANCEL_REPLACE_REPRICE_FOR_BTC_USDC"
TPCLOSE_REPRICE_PHASE = "D3_D4_tpclose_cancel_replace_reprice_scaffold"
TPCLOSE_REPRICE_SOURCE = "phase_d3_d4_tpclose_reprice_scaffold"
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


def _clone_cfg_for_process_local_submit(cfg: Any) -> Any:
    cloned = copy.copy(cfg)
    for key, value in {
        "enable_phase_d3_actual_exit_submit": True,
        "enable_live_exit_orders": True,
        "autonomous_allow_exits": True,
        "phase_c_disable_exit_limit_orders": False,
    }.items():
        try:
            setattr(cloned, key, value)
        except Exception:
            pass
    return cloned


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if value <= ZERO:
        return ZERO
    if increment <= ZERO:
        return value
    return (value / increment).to_integral_value(rounding=ROUND_DOWN) * increment


def _find_order(store: OrderStore, client_order_id: str, exchange_order_id: str) -> Dict[str, Any]:
    order = store.get_order(client_order_id)
    if isinstance(order, dict):
        local_exchange = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if local_exchange == str(exchange_order_id or "").strip():
            return dict(order)
    return {}


def _open_exit_orders(store: OrderStore, ticker: str) -> list[Dict[str, Any]]:
    return [dict(o) for o in store.open_exit_orders(ticker=ticker)]


def _snapshot_status(snapshot: Dict[str, Any]) -> str:
    return str(snapshot.get("normalized_status") or "").strip().lower()


def _snapshot_zero_fill(snapshot: Dict[str, Any]) -> bool:
    return (
        _to_decimal(snapshot.get("filled_base"), "0") == ZERO
        and _to_decimal(snapshot.get("filled_quote"), "0") == ZERO
        and int(snapshot.get("fill_count") or 0) == 0
    )


def _normalize_cancel_response(payload: Any, order_id: str) -> Dict[str, Any]:
    data = payload if isinstance(payload, dict) else {}
    order_id = str(order_id or "").strip()
    raw_results = data.get("results") if isinstance(data.get("results"), list) else []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        item_order = str(item.get("order_id") or item.get("id") or "").strip()
        if item_order == order_id and bool(item.get("success", False)):
            return {"cancel_succeeded": True, "cancel_response_shape": "results_success"}
    for key in ("success_results", "order_ids", "cancelled_order_ids"):
        values = [str(x).strip() for x in (data.get(key) or []) if str(x).strip()]
        if order_id in values:
            return {"cancel_succeeded": True, "cancel_response_shape": key}
    if bool(data.get("success", False)):
        return {"cancel_succeeded": True, "cancel_response_shape": "success_bool"}
    return {"cancel_succeeded": False, "cancel_response_shape": "unconfirmed"}


def _extract_rules(product: Dict[str, Any], *, base_increment: Any, base_min_size: Any, quote_min_size: Any, price_increment: Any) -> Dict[str, Decimal]:
    return {
        "base_increment": _to_decimal(product.get("base_increment") or product.get("base_increment_size") or base_increment, "0"),
        "base_min_size": _to_decimal(product.get("base_min_size") or product.get("base_min_size_size") or base_min_size, "0"),
        "quote_min_size": _to_decimal(product.get("quote_min_size") or product.get("min_market_funds") or quote_min_size, "1"),
        "price_increment": _to_decimal(product.get("price_increment") or product.get("quote_increment") or price_increment, "0.01"),
    }


def build_phase_d3_tpclose_reprice_scaffold_report(
    *,
    cfg: Any,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    new_limit_price: Any,
    state_store: Optional[StateStore] = None,
    order_store: Optional[OrderStore] = None,
    coinbase_client: Any = None,
    old_snapshot: Optional[Dict[str, Any]] = None,
    base_increment: Any = "0.00000001",
    base_min_size: Any = "0.00000001",
    quote_min_size: Any = "1",
    price_increment: Any = "0.01",
    submit_live: bool = False,
    reprice_ack: str = "",
    confirm_label: str = "",
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    store = order_store or OrderStore()
    states = state_store or StateStore()
    client = coinbase_client
    order = _find_order(store, client_order_id, exchange_order_id)
    position = states.get_position(selected_ticker) or {}
    open_exits = _open_exit_orders(store, selected_ticker)
    blockers: list[str] = []
    warnings: list[str] = []

    if not order:
        blockers.append("target_order_not_found_locally")
    if order and str(order.get("d3_exit_label") or "").strip().upper() != "TP_CLOSE":
        blockers.append("target_order_not_tp_close")
    if order and str(order.get("status") or "").strip().lower() not in {"submitted", "open"}:
        blockers.append("target_order_not_open_local")
    if order and str(order.get("linked_position_id") or "").strip() != str(linked_position_id or "").strip():
        blockers.append("linked_position_id_mismatch")
    matching_open = [
        o for o in open_exits
        if str(o.get("client_order_id") or "").strip() == str(client_order_id or "").strip()
        and str(o.get("exchange_order_id") or o.get("order_id") or "").strip() == str(exchange_order_id or "").strip()
    ]
    if len(open_exits) != 1 or len(matching_open) != 1:
        blockers.append("expected_exactly_one_matching_open_exit")
    if str(confirm_label or "").strip().upper() != "TP_CLOSE":
        blockers.append("confirm_label_tp_close_required")

    snapshot = dict(old_snapshot or {})
    if submit_live and not snapshot and client is not None:
        try:
            snapshot = fetch_coinbase_order_snapshot(
                coinbase_client=client,
                order_id=exchange_order_id,
                local_order=order,
                include_fills=True,
            )
        except Exception as exc:
            blockers.append("fresh_old_order_snapshot_failed")
            warnings.append(f"old_snapshot_error:{type(exc).__name__}:{exc}")
    status = _snapshot_status(snapshot)
    if not snapshot:
        blockers.append("fresh_old_order_snapshot_required")
    elif status != "open":
        blockers.append(f"old_order_not_open:{status or 'unknown'}")
    if snapshot and not _snapshot_zero_fill(snapshot):
        blockers.append("old_order_has_fill_evidence")

    raw_size = _to_decimal((order or {}).get("remaining_size") or (order or {}).get("size_base"), "0")
    price = _to_decimal(new_limit_price, "0")
    product_rules = _extract_rules({}, base_increment=base_increment, base_min_size=base_min_size, quote_min_size=quote_min_size, price_increment=price_increment)
    live_base_available = ZERO
    if submit_live and client is not None:
        try:
            product_rules = _extract_rules(
                client.get_product(selected_ticker),
                base_increment=base_increment,
                base_min_size=base_min_size,
                quote_min_size=quote_min_size,
                price_increment=price_increment,
            )
        except Exception as exc:
            blockers.append("product_rules_read_failed")
            warnings.append(f"product_rules_error:{type(exc).__name__}:{exc}")
    rounded_size = _quantize_down(raw_size, product_rules["base_increment"])
    estimated_quote = rounded_size * price
    if rounded_size <= ZERO:
        blockers.append("replacement_size_zero")
    if product_rules["base_min_size"] > ZERO and rounded_size < product_rules["base_min_size"]:
        blockers.append("replacement_below_base_min")
    if product_rules["quote_min_size"] > ZERO and estimated_quote < product_rules["quote_min_size"]:
        blockers.append("replacement_below_quote_min")
    if product_rules["price_increment"] > ZERO and price != _quantize_down(price, product_rules["price_increment"]):
        blockers.append("replacement_price_increment_violation")
    position_base = _to_decimal(position.get("bot_managed_base") or position.get("position_size_base"), "0")
    if rounded_size > position_base:
        blockers.append("replacement_size_exceeds_local_position_base")

    report: Dict[str, Any] = {
        "phase": TPCLOSE_REPRICE_PHASE,
        "generated_at": _now_iso(),
        "ticker": selected_ticker,
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "linked_position_id": linked_position_id,
        "new_limit_price": str(price),
        "status": "tpclose_reprice_scaffold_blocked",
        "submit_live_requested": bool(submit_live),
        "ack_valid": str(reprice_ack or "").strip() == TPCLOSE_REPRICE_ACK,
        "required_ack": TPCLOSE_REPRICE_ACK,
        "old_snapshot_status": status,
        "old_snapshot_filled_base": str(snapshot.get("filled_base") or "0"),
        "old_snapshot_fill_count": int(snapshot.get("fill_count") or 0),
        "old_order_local_status_before": str((order or {}).get("status") or ""),
        "old_order_remaining_size_before": str(raw_size),
        "open_exit_count_before": len(open_exits),
        "replacement_size_base": str(rounded_size),
        "replacement_estimated_quote": str(estimated_quote),
        "product_rules": {k: str(v) for k, v in product_rules.items()},
        "state_write_performed": False,
        "coinbase_call_performed": bool(submit_live),
        "coinbase_write_performed": False,
        "live_order_action_performed": False,
        "cancel_attempted": False,
        "cancel_succeeded": False,
        "cancel_confirmed_terminal": False,
        "replace_attempted": False,
        "replace_succeeded": False,
        "replacement_client_order_id": "",
        "replacement_exchange_order_id": "",
        "blockers": sorted(set(blockers)),
        "warnings": warnings,
        "safety_policy": {
            "dry_run_default": True,
            "exact_old_exchange_order_id_required": exchange_order_id,
            "cancel_first_required": True,
            "replace_only_after_confirmed_cancel": True,
            "one_replacement_only": True,
            "market_orders_forbidden": True,
            "tp_close_only": True,
        },
    }
    if report["blockers"]:
        return _json_safe(report)
    if not submit_live:
        report["status"] = "tpclose_reprice_scaffold_ready_for_ack"
        return _json_safe(report)
    if not report["ack_valid"]:
        report["status"] = "tpclose_reprice_scaffold_ack_required"
        report["blockers"] = ["reprice_ack_missing_or_invalid"]
        return _json_safe(report)
    if client is None:
        report["status"] = "tpclose_reprice_scaffold_blocked"
        report["blockers"] = ["coinbase_client_missing"]
        return _json_safe(report)

    report["cancel_attempted"] = True
    report["live_order_action_performed"] = True
    report["coinbase_write_performed"] = True
    try:
        cancel_response = client.cancel_order(exchange_order_id)
        cancel_result = _normalize_cancel_response(cancel_response, exchange_order_id)
        report.update(cancel_result)
    except Exception as exc:
        report["status"] = "tpclose_reprice_cancel_failed_no_replace"
        report["blockers"] = [f"cancel_failed:{type(exc).__name__}:{exc}"]
        return _json_safe(report)
    if not report["cancel_succeeded"]:
        report["status"] = "tpclose_reprice_cancel_unconfirmed_no_replace"
        report["blockers"] = ["cancel_response_not_confirmed"]
        return _json_safe(report)

    try:
        cancel_snapshot = fetch_coinbase_order_snapshot(
            coinbase_client=client,
            order_id=exchange_order_id,
            local_order=order,
            include_fills=True,
        )
        cancel_status = _snapshot_status(cancel_snapshot)
        report["cancel_confirmation_status"] = cancel_status
        report["cancel_confirmed_terminal"] = cancel_status in {"cancelled", "canceled", "expired", "rejected"}
        if not _snapshot_zero_fill(cancel_snapshot):
            report["blockers"] = ["cancel_confirmation_has_fill_evidence"]
            report["status"] = "tpclose_reprice_cancel_confirmed_fill_evidence_no_replace"
            return _json_safe(report)
    except Exception as exc:
        report["status"] = "tpclose_reprice_cancel_confirmation_failed_no_replace"
        report["blockers"] = [f"cancel_confirmation_failed:{type(exc).__name__}:{exc}"]
        return _json_safe(report)
    if not report["cancel_confirmed_terminal"]:
        report["status"] = "tpclose_reprice_cancel_not_terminal_no_replace"
        report["blockers"] = ["cancel_not_terminal_confirmed"]
        return _json_safe(report)

    try:
        live_position = client.get_spot_position(selected_ticker)
        live_base_available = _to_decimal(live_position.get("available_base_balance"), "0")
        report["live_base_available_after_cancel"] = str(live_base_available)
    except Exception as exc:
        report["status"] = "tpclose_reprice_live_balance_failed_no_replace"
        report["blockers"] = [f"live_balance_failed:{type(exc).__name__}:{exc}"]
        return _json_safe(report)
    if live_base_available < rounded_size:
        report["status"] = "tpclose_reprice_live_base_insufficient_no_replace"
        report["blockers"] = ["live_base_available_below_replacement_size"]
        return _json_safe(report)

    now_iso = _now_iso()
    store.update_order(
        client_order_id,
        {
            "status": "cancelled",
            "cancelled_at": now_iso,
            "closed_at": now_iso,
            "finalized_at": now_iso,
            "cancel_replace_reprice_status": "cancelled_before_replacement",
        },
        event_type="phase_d3_tpclose_reprice_old_order_cancelled",
    )

    replacement_client_id = f"phased3-{selected_ticker.replace('-', '')}-TPCLOSE-repl-pos1-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    gate = assert_live_exit_allowed(
        cfg=_clone_cfg_for_process_local_submit(cfg),
        side="SELL",
        source_module="bot.phase_d3_tpclose_reprice_scaffold",
        source_function="build_phase_d3_tpclose_reprice_scaffold_report",
        source_tag="phase_d3_controlled_live_exit",
        intended_exit_type="limit_sell_replacement",
        ticker=selected_ticker,
        client_order_id=replacement_client_id,
        order_id="",
        local_position_id=linked_position_id,
        reason="TP_CLOSE_REPRICE",
        close_reason="TP_CLOSE",
        execution_status="replacement_submit_attempted",
        human_ack=reprice_ack,
        required_human_ack=TPCLOSE_REPRICE_ACK,
        allowed_sources={"phase_d3_controlled_live_exit"},
    )
    try:
        replace_response = client.place_limit_order(
            ticker=selected_ticker,
            side="SELL",
            base_size=rounded_size,
            limit_price=price,
            client_order_id=replacement_client_id,
            post_only=True,
        )
    except Exception as exc:
        report["status"] = "tpclose_reprice_replacement_failed_manual_review_required"
        report["blockers"] = [f"replacement_failed:{type(exc).__name__}:{exc}"]
        report["live_exit_gate_evaluation"] = gate
        report["state_write_performed"] = True
        return _json_safe(report)

    success_response = replace_response.get("success_response") if isinstance(replace_response, dict) else {}
    replacement_exchange_id = str((success_response or {}).get("order_id") or replace_response.get("order_id") or "").strip()
    if not replacement_exchange_id:
        report["status"] = "tpclose_reprice_replacement_unconfirmed_manual_review_required"
        report["blockers"] = ["replacement_exchange_order_id_missing"]
        report["live_exit_gate_evaluation"] = gate
        report["state_write_performed"] = True
        return _json_safe(report)

    new_order = store.upsert_order(
        {
            "client_order_id": replacement_client_id,
            "exchange_order_id": replacement_exchange_id,
            "order_id": replacement_exchange_id,
            "ticker": selected_ticker,
            "product_id": selected_ticker,
            "side": "SELL",
            "status": "submitted",
            "mode": "live",
            "source_mode": TPCLOSE_REPRICE_SOURCE,
            "phase": "D3_controlled_live_reduce_only_exits",
            "created_at": now_iso,
            "submitted_at": now_iso,
            "size_base": str(rounded_size),
            "remaining_size": str(rounded_size),
            "filled_base": "0",
            "filled_quote": "0",
            "fill_count": 0,
            "size_quote": str(estimated_quote),
            "limit_price": str(price),
            "post_only": True,
            "execution_action": "place_limit_sell",
            "linked_position_id": linked_position_id,
            "reduce_only_local": True,
            "d3_exit_label": "TP_CLOSE",
            "replacement_of_client_order_id": client_order_id,
            "replacement_of_exchange_order_id": exchange_order_id,
            "coinbase_response": replace_response,
        },
        event_type="phase_d3_tpclose_reprice_replacement_submitted",
    )
    states.upsert_position(
        selected_ticker,
        {
            "status": "open",
            "reserved_base_open_exit_orders": str(rounded_size),
            "bot_managed_base": str(position.get("bot_managed_base") or position.get("position_size_base") or "0"),
            "position_size_base": str(position.get("position_size_base") or "0"),
            "last_tpclose_reprice_replacement_client_order_id": replacement_client_id,
            "last_tpclose_reprice_replacement_exchange_order_id": replacement_exchange_id,
        },
    )

    report.update(
        {
            "status": "tpclose_reprice_replacement_submitted",
            "state_write_performed": True,
            "replace_attempted": True,
            "replace_succeeded": True,
            "replacement_client_order_id": replacement_client_id,
            "replacement_exchange_order_id": replacement_exchange_id,
            "new_order": new_order,
            "live_exit_gate_evaluation": gate,
            "blockers": [],
        }
    )
    return _json_safe(report)


__all__ = [
    "TPCLOSE_REPRICE_ACK",
    "TPCLOSE_REPRICE_PHASE",
    "build_phase_d3_tpclose_reprice_scaffold_report",
]
