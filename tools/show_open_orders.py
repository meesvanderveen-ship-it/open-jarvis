#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.order_lifecycle import OPEN_ORDER_STATUSES, is_open_order_status

# Public compatibility alias for callers that import this tool. Its canonical
# source is bot.order_lifecycle, shared with OrderStore and D3 reservation code.
OPEN_STATUSES = OPEN_ORDER_STATUSES


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def load_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"orders": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"orders": {}}
    return data if isinstance(data, dict) else {"orders": {}}


def load_orders(path: Path) -> List[Dict[str, Any]]:
    data = load_state(path)
    orders = data.get("orders", {}) if isinstance(data, dict) else {}
    if isinstance(orders, list):
        out = [dict(v) for v in orders if isinstance(v, dict)]
    elif isinstance(orders, dict):
        out = [dict(v) for v in orders.values() if isinstance(v, dict)]
    else:
        out = []
    out.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    return out


def is_diagnostic(order: Dict[str, Any]) -> bool:
    cid = str(order.get("client_order_id", ""))
    ticker = str(order.get("ticker", ""))
    reason = str(order.get("reason", ""))
    return cid.startswith("paper-diagnostic-") or ticker.startswith("TEST-") or reason.startswith("phase_b")


def build_summary(orders: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_status: Dict[str, int] = {}
    by_ticker: Dict[str, Dict[str, int]] = {}
    reserved_quote: Dict[str, Decimal] = {}
    reserved_base: Dict[str, Decimal] = {}
    diagnostics = 0
    open_count = 0
    for order in orders:
        status = str(order.get("status", "unknown")).lower()
        side = str(order.get("side", "")).upper()
        ticker = str(order.get("ticker", "UNKNOWN")).upper()
        by_status[status] = by_status.get(status, 0) + 1
        if is_diagnostic(order):
            diagnostics += 1
        if is_open_order_status(status):
            open_count += 1
            bucket = by_ticker.setdefault(ticker, {"total": 0, "buy": 0, "sell": 0})
            bucket["total"] += 1
            if side == "BUY":
                bucket["buy"] += 1
                reserved_quote[ticker] = reserved_quote.get(ticker, Decimal("0")) + max(Decimal("0"), _to_decimal(order.get("remaining_quote") or order.get("size_quote")))
            elif side == "SELL":
                bucket["sell"] += 1
                reserved_base[ticker] = reserved_base.get(ticker, Decimal("0")) + max(Decimal("0"), _to_decimal(order.get("remaining_size") or order.get("size_base")))
    return {
        "total_orders": len(orders),
        "open_orders": open_count,
        "by_status": by_status,
        "open_by_ticker": by_ticker,
        "reserved_quote_by_ticker": {k: str(v) for k, v in reserved_quote.items()},
        "reserved_base_by_ticker": {k: str(v) for k, v in reserved_base.items()},
        "diagnostic_order_count": diagnostics,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Toon paper/open order state voor de Coinbase bot.")
    parser.add_argument("--path", default="state/open_orders.json")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--open-only", action="store_true")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    orders_all = load_orders(Path(args.path))
    summary = build_summary(orders_all)
    orders = orders_all
    if args.open_only:
        orders = [o for o in orders if is_open_order_status(o.get("status"))]
    orders = orders[: max(1, args.limit)]

    if args.json:
        print(json.dumps({"summary": summary, "orders": orders}, ensure_ascii=False, indent=2))
        return 0

    if args.summary:
        print("Paper/open order summary")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if summary.get("diagnostic_order_count"):
            print("WAARSCHUWING: er staan diagnostic/test orders in open_orders.json.")
        return 0

    if not orders:
        print("Geen orders gevonden.")
        if summary.get("diagnostic_order_count"):
            print("WAARSCHUWING: diagnostic/test orders aanwezig in state, maar niet in deze selectie.")
        return 0

    for order in orders:
        print("-" * 96)
        print(f"{order.get('ticker')} | {order.get('side')} | {order.get('execution_action')} | {order.get('status')}")
        print(f"client_order_id: {order.get('client_order_id')}")
        print(f"limit_price: {order.get('limit_price')} | size_quote: {order.get('size_quote')} | size_base: {order.get('size_base')}")
        print(f"filled: {order.get('filled_size')} | remaining: {order.get('remaining_size')} | avg_fill: {order.get('avg_fill_price')}")
        print(f"created: {order.get('created_at')} | expires: {order.get('expires_at')} | updated: {order.get('updated_at')}")
        print(f"reason: {order.get('reason')}")
        risk = order.get("risk_check_result") or {}
        phase_b4 = risk.get("phase_b4_paper_rails") if isinstance(risk, dict) else None
        if phase_b4:
            print(f"phase_b4_rails: {phase_b4}")
        last = order.get("last_lifecycle_evaluation")
        if last:
            print(f"last_lifecycle: {last}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
