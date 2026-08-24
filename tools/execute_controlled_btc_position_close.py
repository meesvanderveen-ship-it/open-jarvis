#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.atomic_io import atomic_write_json
from bot.coinbase_client import CoinbaseClient
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot_with_diagnostics, normalize_order_status
from bot.order_store import FINAL_ORDER_STATUSES, OPEN_ORDER_STATUSES, OrderStore
from bot.phase_c43_one_entry_smoke_test import extract_product_rules
from bot.state_store import StateStore


PHASE = "controlled_btc_position_close_v1"
REQUIRED_ACK_PREFIX = "CLOSE_BTC_POSITION_AND_CANCEL_STALE_TP_"
CONTROLLED_CLOSE_PREFIX = "controlled-close-"
ZERO = Decimal("0")
COINBASE_CREDENTIAL_ENV_KEYS = ("COINBASE_API_KEY", "COINBASE_API_SECRET")


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
    except (InvalidOperation, ValueError, TypeError):
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


def _coinbase_credential_presence() -> Dict[str, str]:
    return {
        key: "set" if os.getenv(key, "").strip() else "missing"
        for key in COINBASE_CREDENTIAL_ENV_KEYS
    }


def _credential_report_metadata(*, project_dotenv_loaded: bool, config_loaded: bool = False) -> Dict[str, Any]:
    presence = _coinbase_credential_presence()
    return {
        "project_dotenv_loaded": bool(project_dotenv_loaded),
        "coinbase_credential_presence": presence,
        "credential_scheme": "coinbase_cdp_jwt_env",
        "coinbase_credentials_ready": all(value == "set" for value in presence.values()),
        "bot_config_loaded": bool(config_loaded),
    }


def _load_bot_config_for_coinbase_auth() -> Dict[str, Any]:
    project_dotenv_expected = (PROJECT_ROOT / ".env").exists()
    project_dotenv_loaded = (
        project_dotenv_expected
        and os.getenv("BOT_CONFIG_SKIP_DOTENV", "").strip().lower() not in {"1", "true", "yes", "on"}
    )
    metadata: Dict[str, Any] = _credential_report_metadata(
        project_dotenv_loaded=project_dotenv_loaded,
        config_loaded=False,
    )
    cfg = None
    try:
        from bot.config import BotConfig

        cfg = BotConfig()
        cfg.validate()
        metadata["bot_config_loaded"] = True
    except Exception as exc:
        metadata["bot_config_loaded"] = False
        metadata["bot_config_error_type"] = type(exc).__name__
        metadata["bot_config_error"] = str(exc)

    metadata.update(
        _credential_report_metadata(
            project_dotenv_loaded=project_dotenv_loaded,
            config_loaded=bool(metadata.get("bot_config_loaded")),
        )
    )
    return {"cfg": cfg, "metadata": metadata}


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _quantize_down(value: Decimal, increment: Decimal) -> Decimal:
    if increment <= ZERO:
        return value
    try:
        units = (value / increment).to_integral_value(rounding=ROUND_DOWN)
        return units * increment
    except Exception:
        return value


def _product_rule_decimal(rules: Dict[str, Any], *keys: str) -> Decimal:
    for key in keys:
        value = _to_decimal(rules.get(key), "0")
        if value > ZERO:
            return value
    return ZERO


def _position_base(position: Dict[str, Any]) -> Decimal:
    values = [
        _to_decimal(position.get(key), "0")
        for key in ("bot_managed_base", "position_size_base", "base_size", "filled_size_base")
        if _to_decimal(position.get(key), "0") > ZERO
    ]
    return min(values) if values else ZERO


def _expected_ack(linked_position_id: str) -> str:
    return f"{REQUIRED_ACK_PREFIX}{str(linked_position_id or '').strip()[:8]}"


def _controlled_client_order_id(*, ticker: str, linked_position_id: str) -> str:
    clean_ticker = _normalize_ticker(ticker).replace("-", "")
    suffix = _now_iso().replace(":", "").replace(".", "").replace("+", "")[-18:]
    pos_part = str(linked_position_id or "position")[-8:].replace("-", "")
    return f"{CONTROLLED_CLOSE_PREFIX}{clean_ticker}-{pos_part}-{suffix}"


def _evidence_hash(snapshot: Dict[str, Any]) -> str:
    payload = {
        "normalized_status": str(snapshot.get("normalized_status") or ""),
        "filled_base": str(snapshot.get("filled_base") or "0"),
        "filled_quote": str(snapshot.get("filled_quote") or "0"),
        "avg_fill_price": str(snapshot.get("avg_fill_price") or "0"),
        "fill_count": int(snapshot.get("fill_count") or 0),
        "remaining_size": str(snapshot.get("remaining_size") or "0"),
    }
    return hashlib.sha256(repr(sorted(payload.items())).encode("utf-8")).hexdigest()


def _find_stale_tp(
    store: OrderStore,
    *,
    ticker: str,
    linked_position_id: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Optional[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    order = store.get_order(client_order_id) if client_order_id else None
    if isinstance(order, dict):
        return dict(order)
    for candidate in store.all_orders():
        if _normalize_ticker(candidate.get("ticker") or candidate.get("product_id")) != selected_ticker:
            continue
        if str(candidate.get("linked_position_id") or "").strip() != str(linked_position_id or "").strip():
            continue
        if str(candidate.get("side") or "").strip().upper() != "SELL":
            continue
        if str(candidate.get("exchange_order_id") or candidate.get("order_id") or "").strip() == str(exchange_order_id or "").strip():
            return dict(candidate)
    return None


def _find_controlled_close_orders(
    store: OrderStore,
    *,
    ticker: str,
    linked_position_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    linked = str(linked_position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in store.all_orders():
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if str(order.get("linked_position_id") or "").strip() != linked:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() == PHASE or str(order.get("client_order_id") or "").startswith(CONTROLLED_CLOSE_PREFIX):
            out.append(dict(order))
    out.sort(key=lambda item: str(item.get("created_at") or item.get("updated_at") or ""))
    return out


def _nested_success_order_id(order: Dict[str, Any]) -> str:
    response = _as_dict(order.get("coinbase_response"))
    success = _as_dict(response.get("success_response"))
    return str(success.get("order_id") or "").strip()


def _controlled_close_lookup_order_id(order: Dict[str, Any]) -> str:
    return str(
        order.get("exchange_order_id")
        or order.get("order_id")
        or _nested_success_order_id(order)
        or order.get("client_order_id")
        or ""
    ).strip()


def _open_sell_orders_except_stale_tp(
    store: OrderStore,
    *,
    ticker: str,
    linked_position_id: str,
    stale_tp_client_order_id: str,
) -> List[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    linked = str(linked_position_id or "").strip()
    out: List[Dict[str, Any]] = []
    for order in store.open_exit_orders(ticker=selected_ticker):
        if str(order.get("client_order_id") or "").strip() == str(stale_tp_client_order_id or "").strip():
            continue
        if linked and str(order.get("linked_position_id") or "").strip() != linked:
            continue
        out.append(dict(order))
    return out


def _snapshot_order(
    *,
    coinbase_client: Any,
    exchange_order_id: str,
    local_order: Optional[Dict[str, Any]],
    include_fills: bool,
) -> Dict[str, Any]:
    if coinbase_client is None:
        return {
            "coinbase_call_attempted": False,
            "coinbase_call_succeeded": False,
            "coinbase_snapshot_unavailable": True,
            "normalized_status": "",
            "blockers": ["coinbase_client_missing"],
        }
    try:
        snapshot = fetch_coinbase_order_snapshot_with_diagnostics(
            coinbase_client=coinbase_client,
            order_id=exchange_order_id,
            local_order=local_order or {},
            include_fills=include_fills,
        )
        return _as_dict(snapshot)
    except Exception as exc:
        return {
            "coinbase_call_attempted": True,
            "coinbase_call_succeeded": False,
            "coinbase_snapshot_unavailable": True,
            "coinbase_error_type": type(exc).__name__,
            "coinbase_error_message": str(exc),
            "normalized_status": "",
            "blockers": ["coinbase_snapshot_unavailable"],
        }


def _normal_status_from_local_or_snapshot(order: Dict[str, Any], snapshot: Optional[Dict[str, Any]] = None) -> str:
    snap = snapshot or {}
    normalized = str(snap.get("normalized_status") or "").strip().lower()
    if normalized:
        return normalized
    return normalize_order_status(order.get("status"), filled_base=order.get("filled_base") or order.get("filled_size") or "0")


def _available_base_from_coinbase(coinbase_client: Any, ticker: str) -> Dict[str, Any]:
    if coinbase_client is None:
        return {"lookup_attempted": False, "lookup_succeeded": False, "available_base": None}
    try:
        spot = coinbase_client.get_spot_position(ticker)
        return {
            "lookup_attempted": True,
            "lookup_succeeded": True,
            "available_base": str(spot.get("available_base_balance") or "0"),
            "spot_position": spot,
        }
    except Exception as exc:
        return {
            "lookup_attempted": True,
            "lookup_succeeded": False,
            "available_base": None,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _load_exchange_rules(coinbase_client: Any, ticker: str) -> Dict[str, Any]:
    if coinbase_client is None:
        return {"lookup_attempted": False, "lookup_succeeded": False, "rules": {}}
    try:
        rules = extract_product_rules(coinbase_client.get_product(ticker))
        return {"lookup_attempted": True, "lookup_succeeded": True, "rules": rules}
    except Exception as exc:
        return {
            "lookup_attempted": True,
            "lookup_succeeded": False,
            "rules": {},
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _best_bid(coinbase_client: Any, ticker: str) -> Dict[str, Any]:
    if coinbase_client is None:
        return {"lookup_attempted": False, "lookup_succeeded": False, "best_bid": "0", "best_ask": "0"}
    try:
        book = coinbase_client.get_product_book(ticker, limit=1)
        bids = book.get("bids") if isinstance(book, dict) else []
        asks = book.get("asks") if isinstance(book, dict) else []
        best_bid = str((bids[0] or {}).get("price") or "0") if bids else "0"
        best_ask = str((asks[0] or {}).get("price") or "0") if asks else "0"
        return {
            "lookup_attempted": True,
            "lookup_succeeded": _to_decimal(best_bid, "0") > ZERO,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "book": book,
        }
    except Exception as exc:
        return {
            "lookup_attempted": True,
            "lookup_succeeded": False,
            "best_bid": "0",
            "best_ask": "0",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def _place_near_market_limit_ioc(
    *,
    coinbase_client: Any,
    ticker: str,
    client_order_id: str,
    base_size: Decimal,
    limit_price: Decimal,
) -> Dict[str, Any]:
    # Delegate to the shared CoinbaseClient.place_limit_order_ioc rather than
    # re-building the sor_limit_ioc order_configuration payload here. This file
    # used to hand-roll its own copy of that payload (and call the private
    # coinbase_client._request directly, since place_near_market_limit_ioc_sell
    # was never actually a real CoinbaseClient method -- the hasattr check
    # always fell through). Two independent implementations of the same order
    # shape is exactly how bot/coinbase_client.py's own copy carried an invalid
    # field name (limit_limit_ioc instead of sor_limit_ioc) for months without
    # this file's already-correct copy ever revealing the mismatch: confirmed
    # live 2026-07-08, when that bug left a stop-breached position unprotected
    # for 6+ hours. A single shared implementation can't drift from itself.
    return _as_dict(coinbase_client.place_limit_order_ioc(
        ticker=ticker,
        side="SELL",
        base_size=base_size,
        limit_price=limit_price,
        client_order_id=client_order_id,
    ))


def _extract_submitted_order_id(response: Dict[str, Any]) -> str:
    success = _as_dict(response.get("success_response"))
    return str(response.get("order_id") or response.get("id") or success.get("order_id") or "").strip()


def _terminal_fill_evidence(snapshot: Dict[str, Any]) -> bool:
    return (
        str(snapshot.get("normalized_status") or "").strip().lower() == "filled"
        and (_to_decimal(snapshot.get("filled_base"), "0") > ZERO or int(snapshot.get("fill_count") or 0) > 0)
    )


def _snapshot_value(snapshot: Dict[str, Any], *keys: str, default: Any = "") -> Any:
    raw = _as_dict(snapshot.get("raw_order"))
    fills_summary = _as_dict(snapshot.get("fills_summary"))
    for key in keys:
        for source in (snapshot, raw, fills_summary):
            value = source.get(key)
            if value is None:
                continue
            if isinstance(value, str) and not value.strip():
                continue
            return value
    return default


def _apply_filled_close(
    *,
    state_store: StateStore,
    order_store: OrderStore,
    ticker: str,
    close_order: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> Dict[str, Any]:
    client_order_id = str(close_order.get("client_order_id") or "").strip()
    evidence_hash = _evidence_hash(snapshot)
    if str(close_order.get("controlled_close_applied_evidence_hash") or "").strip() == evidence_hash:
        return {
            "status": "controlled_close_apply_idempotent_noop",
            "state_write_performed": False,
            "applied_actions": [],
            "evidence_hash": evidence_hash,
        }

    now = _now_iso()
    filled_base = str(snapshot.get("filled_base") or close_order.get("size_base") or "0")
    filled_quote = str(snapshot.get("filled_quote") or "0")
    avg_price = str(snapshot.get("avg_fill_price") or "0")
    total_fees = str(_snapshot_value(snapshot, "total_fees", "commission", default=close_order.get("total_fees") or "0"))
    settled_raw = _snapshot_value(snapshot, "settled", default=close_order.get("settled"))
    settled = bool(settled_raw) if not isinstance(settled_raw, str) else settled_raw.strip().lower() in {"1", "true", "yes"}
    order_updates = {
        "status": "filled",
        "remaining_size": "0",
        "remaining_base": "0",
        "filled_base": filled_base,
        "filled_quote": filled_quote,
        "filled_size": filled_base,
        "avg_fill_price": avg_price,
        "total_fees": total_fees,
        "settled": settled,
        "local_reconcile_reason": "coinbase_filled_controlled_btc_position_close",
        "fill_count": int(snapshot.get("fill_count") or 0),
        "finalized_at": now,
        "closed_at": now,
        "controlled_close_applied_evidence_hash": evidence_hash,
        "controlled_close_applied_at": now,
    }
    order_store.update_order(client_order_id, order_updates, event_type="controlled_position_close_order_filled_applied")
    position_updates = {
        "status": "closed",
        "position_size_base": "0",
        "position_size_quote": "0",
        "bot_managed_base": "0",
        "reserved_base_open_exit_orders": "0",
        "monitoring_enabled": False,
        "close_time": now,
        "closed_at": now,
        "close_reason": "controlled_btc_position_close_filled",
        "last_controlled_position_close_evidence_hash": evidence_hash,
        "last_controlled_position_close_at": now,
    }
    state_store.upsert_position(
        ticker,
        position_updates,
        caller_reason="controlled_btc_position_close_filled",
        evidence_status="filled",
    )
    return {
        "status": "controlled_close_local_apply_performed",
        "state_write_performed": True,
        "applied_actions": ["mark_close_sell_filled", "close_local_position"],
        "evidence_hash": evidence_hash,
        "order_updates": order_updates,
        "position_updates": position_updates,
    }


def _reconcile_controlled_close_orders(
    *,
    state_store: StateStore,
    order_store: OrderStore,
    ticker: str,
    controlled_orders: List[Dict[str, Any]],
    coinbase_client: Any,
) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "attempted": bool(controlled_orders),
        "checked_order_count": 0,
        "snapshots": [],
        "status": "no_controlled_close_order_found" if not controlled_orders else "no_terminal_fill_evidence",
        "state_write_performed": False,
        "applied_actions": [],
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
    }
    for order in controlled_orders:
        result["checked_order_count"] += 1
        local_status = str(order.get("status") or "").strip().lower()
        if local_status == "filled":
            snapshot = {
                "normalized_status": "filled",
                "filled_base": str(order.get("filled_base") or order.get("filled_size") or order.get("size_base") or "0"),
                "filled_quote": str(order.get("filled_quote") or "0"),
                "avg_fill_price": str(order.get("avg_fill_price") or "0"),
                "total_fees": str(order.get("total_fees") or "0"),
                "settled": bool(order.get("settled")),
                "fill_count": int(order.get("fill_count") or 0),
                "remaining_size": "0",
                "evidence_source": "local_filled_controlled_close_order",
            }
        else:
            lookup_order_id = _controlled_close_lookup_order_id(order)
            snapshot = _snapshot_order(
                coinbase_client=coinbase_client,
                exchange_order_id=lookup_order_id,
                local_order=order,
                include_fills=True,
            )
            snapshot["lookup_order_id"] = lookup_order_id
            snapshot["local_client_order_id"] = str(order.get("client_order_id") or "")
        result["snapshots"].append(snapshot)
        if not _terminal_fill_evidence(snapshot):
            continue
        apply_result = _apply_filled_close(
            state_store=state_store,
            order_store=order_store,
            ticker=ticker,
            close_order=order,
            snapshot=snapshot,
        )
        result.update(
            {
                "status": "controlled_close_filled_reconciled",
                "fill_evidence": snapshot,
                "local_apply_result": apply_result,
                "state_write_performed": bool(apply_result.get("state_write_performed")),
                "applied_actions": apply_result.get("applied_actions") or [],
            }
        )
        return _json_safe(result)
    return _json_safe(result)


def build_controlled_position_close_report(
    *,
    ticker: str,
    linked_position_id: str,
    stale_tp_client_order_id: str,
    stale_tp_exchange_order_id: str,
    order_type: str,
    ack: str,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
    coinbase_client: Any = None,
    credential_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    linked = str(linked_position_id or "").strip()
    required_ack = _expected_ack(linked)
    ack_valid = str(ack or "").strip() == required_ack
    store = order_store or OrderStore()
    states = state_store or StateStore()
    position = states.get_position(selected_ticker) or {}
    position_status = str(position.get("status") or "").strip().lower()
    position_base = _position_base(position)
    stale_tp = _find_stale_tp(
        store,
        ticker=selected_ticker,
        linked_position_id=linked,
        client_order_id=stale_tp_client_order_id,
        exchange_order_id=stale_tp_exchange_order_id,
    )
    credentials = credential_context or _credential_report_metadata(project_dotenv_loaded=False, config_loaded=False)

    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "phase": PHASE,
        "ticker": selected_ticker,
        "linked_position_id": linked,
        "status": "blocked_review_required",
        "required_ack": required_ack,
        "ack_valid": ack_valid,
        "order_type": str(order_type or "").strip().lower(),
        "project_dotenv_loaded": bool(credentials.get("project_dotenv_loaded")),
        "coinbase_credential_presence": _as_dict(credentials.get("coinbase_credential_presence")),
        "credential_scheme": "coinbase_cdp_jwt_env",
        "coinbase_credentials_ready": bool(credentials.get("coinbase_credentials_ready")),
        "bot_config_loaded": bool(credentials.get("bot_config_loaded")),
        "live_cancel_attempted": False,
        "live_sell_submit_attempted": False,
        "live_order_submitted": False,
        "state_write_performed": False,
        "no_coinbase_cancel": True,
        "no_coinbase_submit": True,
        "no_coinbase_replace": True,
        "blockers": [],
        "warnings": [],
        "position": {
            "present": bool(position),
            "status": position_status,
            "position_base": str(position_base),
        },
        "stale_tp": {
            "client_order_id": stale_tp_client_order_id,
            "exchange_order_id": stale_tp_exchange_order_id,
            "local_order_found": bool(stale_tp),
            "local_status": str((stale_tp or {}).get("status") or ""),
        },
        "cancel_result": {},
        "cancel_verification": {},
        "sell_sizing": {},
        "sell_submit_result": {},
        "fill_evidence": {},
        "local_apply_result": {},
        "applied_actions": [],
    }
    if "bot_config_error_type" in credentials:
        report["bot_config_error_type"] = credentials.get("bot_config_error_type")
        report["bot_config_error"] = credentials.get("bot_config_error")

    if not ack_valid:
        report["status"] = "ack_required_noop"
        report["blockers"].append("exact_ack_required")
        return _json_safe(report)
    if credential_context is not None and not credentials.get("coinbase_credentials_ready"):
        report["status"] = "credential_load_failed"
        report["blocker"] = "coinbase_credentials_missing_after_config_load"
        report["blockers"].append("coinbase_credentials_missing_after_config_load")
        return _json_safe(report)
    if not position:
        report["status"] = "noop_position_missing"
        report["blockers"].append("position_not_found")
        return _json_safe(report)
    if report["order_type"] not in {"near_market_limit_ioc", "market_sell"}:
        report["blockers"].append("unsupported_order_type")
        return _json_safe(report)

    controlled_orders = _find_controlled_close_orders(store, ticker=selected_ticker, linked_position_id=linked)
    reconcile_result = _reconcile_controlled_close_orders(
        state_store=states,
        order_store=store,
        ticker=selected_ticker,
        controlled_orders=controlled_orders,
        coinbase_client=coinbase_client,
    )
    report["controlled_close_reconcile"] = reconcile_result
    if reconcile_result.get("status") == "controlled_close_filled_reconciled":
        report.update({
            "status": "controlled_close_filled_reconciled",
            "fill_evidence": reconcile_result.get("fill_evidence") or {},
            "local_apply_result": reconcile_result.get("local_apply_result") or {},
            "state_write_performed": bool(reconcile_result.get("state_write_performed")),
            "applied_actions": reconcile_result.get("applied_actions") or [],
        })
        return _json_safe(report)
    if position_status == "closed" or position_base <= ZERO:
        report["status"] = "noop_position_already_closed"
        return _json_safe(report)
    if not stale_tp:
        report["blockers"].append("stale_tp_local_order_not_found")
        return _json_safe(report)

    stale_local_client = str(stale_tp.get("client_order_id") or "").strip()
    stale_local_exchange = str(stale_tp.get("exchange_order_id") or stale_tp.get("order_id") or "").strip()
    if stale_local_client != str(stale_tp_client_order_id or "").strip():
        report["blockers"].append("stale_tp_client_order_id_mismatch")
    if stale_local_exchange != str(stale_tp_exchange_order_id or "").strip():
        report["blockers"].append("stale_tp_exchange_order_id_mismatch")
    if str(stale_tp.get("side") or "").strip().upper() != "SELL":
        report["blockers"].append("stale_tp_not_sell")
    if report["blockers"]:
        return _json_safe(report)

    open_duplicate_sells = _open_sell_orders_except_stale_tp(
        store,
        ticker=selected_ticker,
        linked_position_id=linked,
        stale_tp_client_order_id=stale_tp_client_order_id,
    )
    if open_duplicate_sells:
        report["status"] = "duplicate_sell_blocked"
        report["blockers"].append("duplicate_open_sell_blocks_controlled_close")
        report["duplicate_open_sells"] = open_duplicate_sells
        return _json_safe(report)

    stale_status = _normal_status_from_local_or_snapshot(stale_tp)
    cancel_verified = stale_status == "cancelled"
    if not cancel_verified and stale_status in OPEN_ORDER_STATUSES | {"open"}:
        report["live_cancel_attempted"] = True
        report["no_coinbase_cancel"] = False
        try:
            cancel_response = coinbase_client.cancel_order(stale_tp_exchange_order_id)
            report["cancel_result"] = {"attempted": True, "response": _json_safe(cancel_response)}
        except Exception as exc:
            report["status"] = "cancel_failed"
            report["cancel_result"] = {"attempted": True, "error_type": type(exc).__name__, "error": str(exc)}
            report["blockers"].append("stale_tp_cancel_failed")
            return _json_safe(report)

    if not cancel_verified:
        verification = _snapshot_order(
            coinbase_client=coinbase_client,
            exchange_order_id=stale_tp_exchange_order_id,
            local_order=stale_tp,
            include_fills=False,
        )
        report["cancel_verification"] = verification
        verified_status = str(verification.get("normalized_status") or "").strip().lower()
        cancel_verified = verified_status == "cancelled"
        if cancel_verified and stale_status != "cancelled":
            store.update_order(
                stale_tp_client_order_id,
                {
                    "status": "cancelled",
                    "remaining_size": "0",
                    "cancelled_at": _now_iso(),
                    "finalized_at": _now_iso(),
                    "controlled_close_cancel_verified": True,
                },
                event_type="controlled_position_close_stale_tp_cancel_verified",
            )
            report["state_write_performed"] = True
            report["applied_actions"].append("mark_stale_tp_cancelled")
    if not cancel_verified:
        report["status"] = "awaiting_cancel_verification"
        report["blockers"].append("stale_tp_cancel_not_verified")
        return _json_safe(report)

    report["status"] = "stop_sell_ready"
    report["pre_sell_status"] = "stop_sell_ready"
    report["cancel_verification"]["cancel_verified"] = True

    cb_available = _available_base_from_coinbase(coinbase_client, selected_ticker)
    rules_lookup = _load_exchange_rules(coinbase_client, selected_ticker)
    book = _best_bid(coinbase_client, selected_ticker)
    report["coinbase_available_base_lookup"] = cb_available
    report["exchange_rules_lookup"] = rules_lookup
    report["market_lookup"] = {k: v for k, v in book.items() if k != "book"}

    candidate_base = position_base
    if cb_available.get("available_base") is not None:
        candidate_base = min(candidate_base, _to_decimal(cb_available.get("available_base"), "0"))
    rules = _as_dict(rules_lookup.get("rules"))
    base_increment = _product_rule_decimal(rules, "base_increment", "base_increment_size")
    base_min_size = _product_rule_decimal(rules, "base_min_size", "base_min_order_size")
    quote_min_size = _product_rule_decimal(rules, "quote_min_size", "quote_min_order_size")
    price_increment = _product_rule_decimal(rules, "quote_increment", "price_increment", "price_increment_size")
    sell_base = _quantize_down(candidate_base, base_increment)
    best_bid = _to_decimal(book.get("best_bid"), "0")
    max_slippage = Decimal("0.0100")
    raw_limit_price = best_bid * (Decimal("1") - max_slippage) if best_bid > ZERO else ZERO
    limit_price = _quantize_down(raw_limit_price, price_increment)
    estimated_quote = sell_base * (limit_price if limit_price > ZERO else best_bid)
    report["sell_sizing"] = {
        "position_base": str(position_base),
        "coinbase_available_base": cb_available.get("available_base"),
        "candidate_base_before_increment": str(candidate_base),
        "sell_base": str(sell_base),
        "base_increment": str(base_increment),
        "base_min_size": str(base_min_size),
        "quote_min_size": str(quote_min_size),
        "best_bid": str(best_bid),
        "limit_price": str(limit_price),
        "estimated_quote": str(estimated_quote),
    }
    if cb_available.get("lookup_attempted") and not cb_available.get("lookup_succeeded"):
        report["blockers"].append("coinbase_available_base_lookup_failed")
    if sell_base <= ZERO:
        report["blockers"].append("sell_base_missing_or_zero_after_clamp")
    if base_min_size > ZERO and sell_base < base_min_size:
        report["blockers"].append("sell_base_below_coinbase_base_min_size")
    if quote_min_size > ZERO and estimated_quote > ZERO and estimated_quote < quote_min_size:
        report["blockers"].append("sell_quote_below_coinbase_quote_min_size")
    if report["order_type"] == "near_market_limit_ioc" and limit_price <= ZERO:
        report["blockers"].append("near_market_limit_ioc_requires_best_bid_and_price_increment")
    if report["blockers"]:
        return _json_safe(report)

    client_order_id = _controlled_client_order_id(ticker=selected_ticker, linked_position_id=linked)
    report["live_sell_submit_attempted"] = True
    report["no_coinbase_submit"] = False
    try:
        if report["order_type"] == "market_sell":
            response = coinbase_client.place_market_order(
                ticker=selected_ticker,
                side="SELL",
                size=sell_base,
                client_order_id=client_order_id,
            )
        else:
            response = _place_near_market_limit_ioc(
                coinbase_client=coinbase_client,
                ticker=selected_ticker,
                client_order_id=client_order_id,
                base_size=sell_base,
                limit_price=limit_price,
            )
    except Exception as exc:
        report["status"] = "controlled_close_sell_submit_failed"
        report["sell_submit_result"] = {"error_type": type(exc).__name__, "error": str(exc)}
        report["blockers"].append("controlled_close_sell_submit_failed")
        return _json_safe(report)

    response_dict = _as_dict(_json_safe(response))
    exchange_order_id = _extract_submitted_order_id(response_dict)
    if not exchange_order_id:
        report["status"] = "controlled_close_sell_submit_rejected"
        report["sell_submit_result"] = {"response": response_dict, "exchange_order_id": ""}
        report["blockers"].append("controlled_close_sell_missing_exchange_order_id")
        return _json_safe(report)

    close_record = store.upsert_order(
        {
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "order_id": exchange_order_id,
            "ticker": selected_ticker,
            "product_id": selected_ticker,
            "side": "SELL",
            "status": "submitted",
            "mode": "live",
            "source_mode": "controlled_btc_position_close",
            "phase": PHASE,
            "created_at": _now_iso(),
            "size_base": str(sell_base),
            "remaining_size": str(sell_base),
            "limit_price": str(limit_price),
            "execution_action": "controlled_position_close_sell",
            "linked_position_id": linked,
            "reduce_only_local": True,
            "stale_tp_client_order_id": stale_tp_client_order_id,
            "stale_tp_exchange_order_id": stale_tp_exchange_order_id,
            "coinbase_response": response_dict,
        },
        event_type="controlled_position_close_sell_submitted",
    )
    report["live_order_submitted"] = True
    report["state_write_performed"] = True
    report["applied_actions"].append("record_controlled_close_sell")
    report["sell_submit_result"] = {
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "response": response_dict,
    }

    fill_snapshot = _snapshot_order(
        coinbase_client=coinbase_client,
        exchange_order_id=exchange_order_id,
        local_order=close_record,
        include_fills=True,
    )
    report["fill_evidence"] = fill_snapshot
    if _terminal_fill_evidence(fill_snapshot):
        apply_result = _apply_filled_close(
            state_store=states,
            order_store=store,
            ticker=selected_ticker,
            close_order=close_record,
            snapshot=fill_snapshot,
        )
        report["status"] = "controlled_close_filled_reconciled"
        report["local_apply_result"] = apply_result
        report["state_write_performed"] = True
        report["applied_actions"].extend(apply_result.get("applied_actions") or [])
        return _json_safe(report)

    report["status"] = "controlled_close_sell_submitted_awaiting_fill_evidence"
    report["blockers"].append("terminal_fill_evidence_required_before_local_apply")
    return _json_safe(report)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ACK-gated controlled BTC position close after stale D.3 TP cancel.")
    parser.add_argument("--ticker", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--stale-tp-client-order-id", required=True)
    parser.add_argument("--stale-tp-exchange-order-id", required=True)
    parser.add_argument("--order-type", default="near_market_limit_ioc")
    parser.add_argument("--ack", default="")
    parser.add_argument("--json-out", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    ack_valid = str(args.ack or "").strip() == _expected_ack(args.linked_position_id)
    credential_context: Optional[Dict[str, Any]] = None
    coinbase_client = None
    if ack_valid:
        loaded = _load_bot_config_for_coinbase_auth()
        credential_context = _as_dict(loaded.get("metadata"))
        cfg = loaded.get("cfg")
        if credential_context.get("coinbase_credentials_ready"):
            if cfg is not None:
                coinbase_client = CoinbaseClient(
                    host=getattr(cfg, "coinbase_api_host", None),
                    timeout=getattr(cfg, "coinbase_timeout_seconds", None),
                )
            else:
                coinbase_client = CoinbaseClient()
    report = build_controlled_position_close_report(
        ticker=args.ticker,
        linked_position_id=args.linked_position_id,
        stale_tp_client_order_id=args.stale_tp_client_order_id,
        stale_tp_exchange_order_id=args.stale_tp_exchange_order_id,
        order_type=args.order_type,
        ack=args.ack,
        order_store=OrderStore(),
        state_store=StateStore(),
        coinbase_client=coinbase_client,
        credential_context=credential_context,
    )
    out = Path(args.json_out)
    out.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(out, report, sort_keys=True)
    print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
