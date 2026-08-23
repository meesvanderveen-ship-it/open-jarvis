#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.coinbase_client import CoinbaseClient
from bot.coinbase_order_snapshot import fetch_coinbase_order_snapshot
from bot.config import BotConfig
from bot.order_store import OrderStore


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        return Decimal(str(value).strip() or default)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _find_local_order(
    store: OrderStore,
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Optional[Dict[str, Any]]:
    selected_ticker = str(ticker or "").strip().upper().replace("/", "-")
    selected_client = str(client_order_id or "").strip()
    selected_exchange = str(exchange_order_id or "").strip()

    if selected_client:
        order = store.get_order(selected_client)
        if isinstance(order, dict):
            return order

    for order in store.all_orders():
        if selected_ticker and str(order.get("ticker") or "").strip().upper() != selected_ticker:
            continue
        if selected_exchange and str(order.get("exchange_order_id") or order.get("order_id") or "").strip() == selected_exchange:
            return order
    return None


def _fill_fees_and_liquidity(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    fills = (((snapshot or {}).get("fills_summary") or {}).get("fills") or [])
    total_fees = Decimal("0")
    liquidity_markers: List[str] = []
    for fill in fills:
        raw = fill.get("raw") if isinstance(fill, dict) else {}
        commission = _to_decimal(
            (raw or {}).get("commission")
            or (((raw or {}).get("commission_detail_total") or {}).get("total_commission")),
            "0",
        )
        total_fees += max(Decimal("0"), commission)
        liquidity = str((raw or {}).get("liquidity_indicator") or "").strip().upper()
        if liquidity and liquidity not in liquidity_markers:
            liquidity_markers.append(liquidity)
    return {
        "fees": str(total_fees),
        "liquidity": liquidity_markers,
    }


def _suggested_local_action(normalized_status: str) -> str:
    status = str(normalized_status or "").strip().lower()
    if status == "open":
        return "keep_open"
    if status == "partially_filled":
        return "mark_partially_filled"
    if status == "filled":
        return "mark_filled"
    if status == "rejected":
        return "mark_rejected"
    if status in {"cancelled", "expired", "cancel_pending"}:
        return "mark_cancelled"
    return "unknown_no_apply"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only D.3 live exit order Coinbase snapshot")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", default="")
    parser.add_argument("--exchange-order-id", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def build_report(*, ticker: str, client_order_id: str, exchange_order_id: str) -> Dict[str, Any]:
    ticker = str(ticker or "").strip().upper().replace("/", "-")
    store = OrderStore()
    local_order = _find_local_order(
        store,
        ticker=ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
    )
    resolved_exchange_id = str(
        exchange_order_id
        or ((local_order or {}).get("exchange_order_id") or (local_order or {}).get("order_id") or "")
    ).strip()

    report: Dict[str, Any] = {
        "ticker": ticker,
        "client_order_id": str(client_order_id or (local_order or {}).get("client_order_id") or "").strip(),
        "exchange_order_id": resolved_exchange_id,
        "order_id": resolved_exchange_id,
        "local_order_found": bool(local_order),
        "local_order_status": str((local_order or {}).get("status") or ""),
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": False,
        "raw_status": "",
        "normalized_status": "",
        "filled_base": "0",
        "filled_quote": "0",
        "remaining_size": str((local_order or {}).get("remaining_size") or (local_order or {}).get("size_base") or "0"),
        "avg_fill_price": "0",
        "fill_count": 0,
        "fees": "0",
        "liquidity": [],
        "suggested_local_action": "unknown_no_apply",
        "blockers": [],
        "warnings": [],
        "no_state_write": True,
        "safety_policy": {
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_mutate_state": True,
            "read_only_coinbase_snapshot_only": True,
        },
    }

    if not resolved_exchange_id:
        report["blockers"].append("exchange_order_id_missing")
        return _json_safe(report)

    report["coinbase_call_attempted"] = True
    try:
        snapshot = fetch_coinbase_order_snapshot(
            coinbase_client=CoinbaseClient(),
            order_id=resolved_exchange_id,
            local_order=local_order,
            include_fills=True,
        )
        report["coinbase_call_succeeded"] = True
        report["raw_status"] = str(snapshot.get("raw_status") or snapshot.get("status") or "")
        report["normalized_status"] = str(snapshot.get("normalized_status") or "")
        report["filled_base"] = str(snapshot.get("filled_base") or "0")
        report["filled_quote"] = str(snapshot.get("filled_quote") or "0")
        report["avg_fill_price"] = str(snapshot.get("avg_fill_price") or "0")
        report["fill_count"] = int((((snapshot.get("fills_summary") or {}).get("fill_count")) or 0))
        if local_order:
            local_remaining = _to_decimal(local_order.get("remaining_size") or local_order.get("size_base"), "0")
            filled = _to_decimal(snapshot.get("filled_base"), "0")
            if local_remaining > Decimal("0") and filled > Decimal("0") and filled < local_remaining:
                report["remaining_size"] = str(max(Decimal("0"), local_remaining - filled))
            elif local_remaining > Decimal("0") and report["normalized_status"] in {"open", "partially_filled"}:
                report["remaining_size"] = str(local_remaining)
            elif report["normalized_status"] == "filled":
                report["remaining_size"] = "0"
        extras = _fill_fees_and_liquidity(snapshot)
        report["fees"] = extras["fees"]
        report["liquidity"] = extras["liquidity"]
        report["suggested_local_action"] = _suggested_local_action(report["normalized_status"])
        report["snapshot"] = snapshot
    except Exception as exc:
        report["warnings"].append(f"coinbase_snapshot_error:{type(exc).__name__}")
        report["error"] = f"{type(exc).__name__}: {exc}"
    return _json_safe(report)


def main() -> int:
    args = parse_args()
    cfg = BotConfig()
    cfg.validate()
    report = build_report(
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
    )
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 0 if report.get("coinbase_call_succeeded") else 2


if __name__ == "__main__":
    raise SystemExit(main())
