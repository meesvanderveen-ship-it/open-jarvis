#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot
from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.phase_c43_one_entry_smoke_test import extract_product_rules
from bot.phase_d3_reservation_governance import build_phase_d3_reservation_governance_snapshot
from bot.state_store import StateStore

ZERO = Decimal("0")
FUTURE_CANCEL_ACK = "I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_CANCEL_GOVERNANCE"
FUTURE_REPLACE_ACK = "I_UNDERSTAND_AND_APPROVE_D3_OPEN_EXIT_REPLACE_GOVERNANCE"


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
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _parse_dt(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _pct_distance(limit_price: Decimal, reference: Decimal) -> Decimal:
    if limit_price <= ZERO or reference <= ZERO:
        return ZERO
    return ((limit_price - reference) / reference) * Decimal("100")


def _find_local_order(
    store: OrderStore,
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Optional[Dict[str, Any]]:
    selected_ticker = _normalize_ticker(ticker)
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()
    if selected_client:
        order = store.get_order(selected_client)
        if isinstance(order, dict):
            return order
    for order in store.all_orders():
        if selected_ticker and _normalize_ticker(order.get("ticker")) != selected_ticker:
            continue
        order_exchange_id = str(order.get("exchange_order_id") or order.get("order_id") or "").strip()
        if selected_exchange and order_exchange_id == selected_exchange:
            return dict(order)
    return None


def _load_json_fixture(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _resolve_snapshot(
    *,
    ticker: str,
    exchange_order_id: str,
    local_order: Optional[Dict[str, Any]],
    snapshot_fixture: str,
) -> Dict[str, Any]:
    if snapshot_fixture:
        payload = _load_json_fixture(snapshot_fixture)
        return {
            "coinbase_call_attempted": bool(payload.get("coinbase_call_attempted", True)),
            "coinbase_call_succeeded": bool(payload.get("coinbase_call_succeeded", True)),
            **payload,
        }

    if not exchange_order_id:
        return {
            "coinbase_call_attempted": False,
            "coinbase_call_succeeded": False,
            "normalized_status": "",
            "raw_status": "",
            "filled_base": "0",
            "filled_quote": "0",
            "remaining_size": str((local_order or {}).get("remaining_size") or (local_order or {}).get("size_base") or "0"),
        }

    snapshot = fetch_coinbase_order_snapshot(
        coinbase_client=CoinbaseClient(),
        order_id=exchange_order_id,
        local_order=local_order,
        include_fills=True,
    )
    fills_summary = snapshot.get("fills_summary") or {}
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "raw_status": snapshot.get("raw_status") or snapshot.get("status") or "",
        "normalized_status": snapshot.get("normalized_status") or "",
        "filled_base": snapshot.get("filled_base") or "0",
        "filled_quote": snapshot.get("filled_quote") or "0",
        "remaining_size": str((local_order or {}).get("remaining_size") or (local_order or {}).get("size_base") or "0"),
        "avg_fill_price": snapshot.get("avg_fill_price") or "0",
        "fill_count": int(fills_summary.get("fill_count") or 0),
        "snapshot": snapshot,
    }


def _resolve_market_snapshot(*, ticker: str, market_fixture: str) -> Dict[str, Any]:
    if market_fixture:
        payload = _load_json_fixture(market_fixture)
        return {
            "coinbase_call_attempted": bool(payload.get("coinbase_call_attempted", True)),
            "coinbase_call_succeeded": bool(payload.get("coinbase_call_succeeded", True)),
            **payload,
        }
    ticker_snapshot = CoinbaseClient().get_public_ticker(ticker)
    bid = _to_decimal(ticker_snapshot.get("best_bid"), "0")
    ask = _to_decimal(ticker_snapshot.get("best_ask"), "0")
    mid = _to_decimal(ticker_snapshot.get("price") or ticker_snapshot.get("mid_price"), "0")
    if mid <= ZERO and bid > ZERO and ask > ZERO:
        mid = (bid + ask) / Decimal("2")
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "best_bid": str(bid),
        "best_ask": str(ask),
        "mid_price": str(mid),
        "raw_ticker": ticker_snapshot,
    }


def _resolve_product_rules(*, ticker: str, product_fixture: str) -> Dict[str, Any]:
    if product_fixture:
        payload = _load_json_fixture(product_fixture)
        return {
            "coinbase_call_attempted": bool(payload.get("coinbase_call_attempted", True)),
            "coinbase_call_succeeded": bool(payload.get("coinbase_call_succeeded", True)),
            **payload,
        }

    product = CoinbaseClient().get_product(ticker)
    rules = extract_product_rules(product)
    return {
        "coinbase_call_attempted": True,
        "coinbase_call_succeeded": True,
        "base_increment": str(rules.get("base_increment") or "0"),
        "quote_increment": str(rules.get("quote_increment") or "0"),
        "price_increment": str(
            product.get("price_increment")
            or product.get("price_increment_size")
            or rules.get("quote_increment")
            or "0"
        ),
        "min_order_quote": str(
            product.get("quote_min_size")
            or product.get("quote_min_order_size")
            or product.get("min_market_funds")
            or product.get("min_order_quote")
            or "0"
        ),
        "min_order_base": str(
            product.get("base_min_size")
            or product.get("base_min_order_size")
            or product.get("min_order_base")
            or "0"
        ),
        "raw_product": product,
    }


def _recommendation(
    *,
    snapshot_status: str,
    age_hours: Decimal,
    distance_mid_pct: Decimal,
    distance_ask_pct: Decimal,
    blockers: list[str],
) -> str:
    if snapshot_status != "open":
        return "reconcile_first"
    if blockers:
        return "reconcile_first"
    if age_hours >= Decimal("4") and distance_mid_pct >= Decimal("2.5") and distance_ask_pct >= Decimal("2.5"):
        return "cancel_candidate_preview_only"
    if age_hours >= Decimal("2") and distance_mid_pct >= Decimal("1.0"):
        return "stale_open_review"
    if age_hours >= Decimal("1") and distance_mid_pct >= Decimal("0.25"):
        return "replace_candidate_preview_only"
    return "keep_open"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only governance preview for one open D.3 live exit order")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--snapshot-fixture", default="")
    parser.add_argument("--market-fixture", default="")
    parser.add_argument("--product-fixture", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
    linked_position_id: str,
    snapshot_fixture: str = "",
    market_fixture: str = "",
    product_fixture: str = "",
    snapshot_override: Optional[Dict[str, Any]] = None,
    market_override: Optional[Dict[str, Any]] = None,
    product_rules_override: Optional[Dict[str, Any]] = None,
    order_store: Optional[OrderStore] = None,
    state_store: Optional[StateStore] = None,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    selected_position_id = str(linked_position_id or "").strip()
    store = order_store or OrderStore()
    positions = state_store or StateStore()
    local_order = _find_local_order(
        store,
        ticker=selected_ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    position = positions.get_position(selected_ticker) or {}

    report: Dict[str, Any] = {
        "ticker": selected_ticker,
        "client_order_id": str(client_order_id or "").strip(),
        "exchange_order_id": str(exchange_order_id or "").strip(),
        "linked_position_id": selected_position_id,
        "local_order_status": str((local_order or {}).get("status") or ""),
        "coinbase_status": "",
        "order_age_minutes": "0",
        "order_age_hours": "0",
        "limit_price": str((local_order or {}).get("limit_price") or "0"),
        "current_bid": "0",
        "current_ask": "0",
        "current_mid": "0",
        "distance_to_bid_pct": "0",
        "distance_to_ask_pct": "0",
        "distance_to_mid_pct": "0",
        "base_increment": "0",
        "price_increment": "0",
        "quote_increment": "0",
        "min_order_quote": "0",
        "remaining_size": str((local_order or {}).get("remaining_size") or (local_order or {}).get("size_base") or "0"),
        "estimated_remaining_quote_at_limit": "0",
        "estimated_remaining_quote_at_bid": "0",
        "open_d3_orders_count": len(store.open_exit_orders(ticker=selected_ticker)),
        "position_status": str(position.get("status") or ""),
        "position_size_base": str(position.get("position_size_base") or "0"),
        "bot_managed_base": str(position.get("bot_managed_base") or "0"),
        "available_base_after_reservations": "0",
        "reserved_base_open_exit_orders": "0",
        "available_plus_reserved_base": "0",
        "available_reserved_matches_bot_manageable_base": False,
        "recommendation": "reconcile_first",
        "blockers": [],
        "warnings": [],
        "required_ack_for_future_cancel": FUTURE_CANCEL_ACK,
        "required_ack_for_future_replace": FUTURE_REPLACE_ACK,
        "no_state_write": True,
        "no_coinbase_submit": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "safety_policy": {
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_mutate_state": True,
            "preview_only_governance": True,
        },
    }

    if not isinstance(local_order, dict):
        report["blockers"].append("local_d3_order_not_found")
        return _json_safe(report)
    if str(local_order.get("linked_position_id") or "").strip() != selected_position_id:
        report["blockers"].append("linked_position_id_mismatch")

    snapshot = (
        dict(snapshot_override)
        if isinstance(snapshot_override, dict)
        else _resolve_snapshot(
            ticker=selected_ticker,
            exchange_order_id=str(exchange_order_id or "").strip(),
            local_order=local_order,
            snapshot_fixture=snapshot_fixture,
        )
    )
    report["coinbase_snapshot"] = snapshot
    snapshot_status = str(snapshot.get("normalized_status") or "").strip().lower()
    report["coinbase_status"] = snapshot_status

    if not snapshot.get("coinbase_call_succeeded", True):
        report["blockers"].append("live_order_snapshot_unavailable")
        report["warnings"].append("coinbase_snapshot_unavailable")

    if snapshot_status and snapshot_status != "open":
        report["recommendation"] = "reconcile_first"
        return _json_safe(report)

    product_rules = (
        dict(product_rules_override)
        if isinstance(product_rules_override, dict)
        else _resolve_product_rules(ticker=selected_ticker, product_fixture=product_fixture)
    )
    report["product_rules"] = product_rules
    report["base_increment"] = str(product_rules.get("base_increment") or "0")
    report["price_increment"] = str(product_rules.get("price_increment") or "0")
    report["quote_increment"] = str(product_rules.get("quote_increment") or "0")
    report["min_order_quote"] = str(product_rules.get("min_order_quote") or "0")
    if not product_rules.get("coinbase_call_succeeded", True):
        report["blockers"].append("product_rules_missing")

    market_snapshot = (
        dict(market_override)
        if isinstance(market_override, dict)
        else _resolve_market_snapshot(ticker=selected_ticker, market_fixture=market_fixture)
    )
    report["market_snapshot"] = market_snapshot
    bid = _to_decimal(market_snapshot.get("best_bid"), "0")
    ask = _to_decimal(market_snapshot.get("best_ask"), "0")
    mid = _to_decimal(market_snapshot.get("mid_price"), "0")
    report["current_bid"] = str(bid)
    report["current_ask"] = str(ask)
    report["current_mid"] = str(mid)
    if not market_snapshot.get("coinbase_call_succeeded", True) or bid <= ZERO or ask <= ZERO or mid <= ZERO:
        report["blockers"].append("market_snapshot_missing")

    reservation = build_phase_d3_reservation_governance_snapshot(
        ticker=selected_ticker,
        position=position,
        order_store=store,
        plan=None,
        exchange_rules={
            "base_increment": report["base_increment"],
            "quote_increment": report["quote_increment"],
            "quote_min_size": report["min_order_quote"],
        },
    )
    report["reservation_governance"] = reservation
    report["available_base_after_reservations"] = str(reservation.get("available_base_after_reservations") or "0")
    report["reserved_base_open_exit_orders"] = str(reservation.get("reserved_base_open_exit_orders") or "0")
    report["available_plus_reserved_base"] = str(reservation.get("available_plus_reserved_base") or "0")
    report["available_reserved_matches_bot_manageable_base"] = bool(
        reservation.get("available_reserved_matches_bot_manageable_base")
    )

    if report["open_d3_orders_count"] != 1:
        report["blockers"].append("open_d3_order_count_not_one")
    if str(position.get("status") or "").strip().lower() != "open":
        report["blockers"].append("local_position_not_open")
    if not report["available_reserved_matches_bot_manageable_base"]:
        report["blockers"].append("base_semantics_incoherent")

    created_at = _parse_dt(local_order.get("created_at"))
    if created_at is None:
        created_at = _parse_dt((((snapshot.get("snapshot") or {}).get("raw_order") or {}).get("created_time")))
    if created_at is not None:
        age_minutes = max(ZERO, Decimal(str((datetime.now(timezone.utc) - created_at).total_seconds())) / Decimal("60"))
        age_hours = age_minutes / Decimal("60")
        report["order_age_minutes"] = str(age_minutes.quantize(Decimal("0.01")))
        report["order_age_hours"] = str(age_hours.quantize(Decimal("0.01")))
    else:
        age_hours = ZERO
        report["warnings"].append("order_age_unavailable")

    remaining_size = _to_decimal(report["remaining_size"], "0")
    limit_price = _to_decimal(report["limit_price"], "0")
    report["estimated_remaining_quote_at_limit"] = str((remaining_size * limit_price).quantize(Decimal("0.0000000001")))
    report["estimated_remaining_quote_at_bid"] = str((remaining_size * bid).quantize(Decimal("0.0000000001"))) if bid > ZERO else "0"
    report["distance_to_bid_pct"] = str(_pct_distance(limit_price, bid).quantize(Decimal("0.0001"))) if bid > ZERO else "0"
    report["distance_to_ask_pct"] = str(_pct_distance(limit_price, ask).quantize(Decimal("0.0001"))) if ask > ZERO else "0"
    report["distance_to_mid_pct"] = str(_pct_distance(limit_price, mid).quantize(Decimal("0.0001"))) if mid > ZERO else "0"

    report["recommendation"] = _recommendation(
        snapshot_status=snapshot_status,
        age_hours=age_hours,
        distance_mid_pct=_to_decimal(report["distance_to_mid_pct"], "0"),
        distance_ask_pct=_to_decimal(report["distance_to_ask_pct"], "0"),
        blockers=report["blockers"],
    )
    return _json_safe(report)


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_report(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
        linked_position_id=args.linked_position_id,
        snapshot_fixture=args.snapshot_fixture,
        market_fixture=args.market_fixture,
        product_fixture=args.product_fixture,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if not report.get("blockers") else 2


if __name__ == "__main__":
    raise SystemExit(main())
