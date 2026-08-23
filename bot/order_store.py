from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.atomic_io import atomic_write_json
from bot.order_lifecycle import (
    FINAL_ORDER_STATUSES,
    OPEN_ORDER_STATUSES,
    is_final_order_status,
    is_open_order_status,
    normalize_order_status,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
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


class OrderStore:
    """JSON-backed paper/open-order state store.

    Phase B uses this for paper limit-order simulation only. It does not submit
    live Coinbase orders. Later live phases can reuse the same schema.
    """

    def __init__(
        self,
        path: str | Path = "state/open_orders.json",
        log_path: str | Path = "logs/order_events.jsonl",
        max_orders: int = 2000,
    ) -> None:
        self.path = Path(path)
        self.log_path = Path(log_path)
        self.max_orders = int(max_orders)

    def _read_state(self) -> Dict[str, Any]:
        try:
            if not self.path.exists():
                return {"orders": {}}
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"orders": {}}
            data.setdefault("orders", {})
            if not isinstance(data["orders"], dict):
                data["orders"] = {}
            return data
        except Exception:
            return {"orders": {}}

    def _write_state(self, data: Dict[str, Any]) -> None:
        safe = _json_safe(data)
        atomic_write_json(self.path, safe, sort_keys=True)

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {
            "generated_at": _now_iso(),
            "event_type": event_type,
            **_json_safe(payload),
        }
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def all_orders(self) -> List[Dict[str, Any]]:
        orders = self._read_state().get("orders", {})
        if not isinstance(orders, dict):
            return []
        return [dict(v) for v in orders.values() if isinstance(v, dict)]

    def get_order(self, order_id: str) -> Optional[Dict[str, Any]]:
        if not order_id:
            return None
        order = self._read_state().get("orders", {}).get(order_id)
        return dict(order) if isinstance(order, dict) else None

    def open_orders(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        normalized_ticker = str(ticker or "").strip().upper()
        out: List[Dict[str, Any]] = []
        for order in self.all_orders():
            if not is_open_order_status(order.get("status")):
                continue
            if normalized_ticker and str(order.get("ticker", "")).strip().upper() != normalized_ticker:
                continue
            out.append(order)
        out.sort(key=lambda x: str(x.get("created_at") or ""))
        return out


    def final_orders(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        normalized_ticker = str(ticker or "").strip().upper()
        out: List[Dict[str, Any]] = []
        for order in self.all_orders():
            if not is_final_order_status(order.get("status")):
                continue
            if normalized_ticker and str(order.get("ticker", "")).strip().upper() != normalized_ticker:
                continue
            out.append(order)
        out.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""))
        return out



    def open_entry_orders(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return open paper/live-intent entry orders.

        Phase B.4 uses this for duplicate protection and reserved-balance
        accounting. It is intentionally schema-light: any open BUY order is an
        entry reservation in spot mode.
        """
        return [o for o in self.open_orders(ticker=ticker) if str(o.get("side", "")).strip().upper() == "BUY"]

    def open_exit_orders(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        """Return open paper/live-intent exit orders.

        Any open SELL order reserves base in local reduce-only spot logic.
        """
        return [o for o in self.open_orders(ticker=ticker) if str(o.get("side", "")).strip().upper() == "SELL"]

    def has_duplicate_entry_order(self, *, ticker: str) -> bool:
        return bool(self.open_entry_orders(ticker=ticker))

    def has_duplicate_exit_order(self, *, ticker: str, execution_action: Optional[str] = None, linked_position_id: Optional[str] = None) -> bool:
        action = str(execution_action or "").strip().lower()
        linked_id = str(linked_position_id or "").strip()
        for order in self.open_exit_orders(ticker=ticker):
            if action and str(order.get("execution_action", "")).strip().lower() != action:
                continue
            if linked_id and str(order.get("linked_position_id") or "").strip() != linked_id:
                continue
            return True
        return False

    def total_reserved_quote(self) -> str:
        total = Decimal("0")
        for value in self.reserved_quote_by_ticker().values():
            total += _to_decimal(value, "0")
        return str(total)

    def available_quote_after_reserved_orders(self, total_quote: Any) -> str:
        total = max(Decimal("0"), _to_decimal(total_quote, "0"))
        reserved = _to_decimal(self.total_reserved_quote(), "0")
        return str(max(Decimal("0"), total - reserved))

    def available_base_after_reserved_exit_orders(self, *, ticker: str, total_base: Any) -> str:
        ticker = str(ticker or "").strip().upper()
        total = max(Decimal("0"), _to_decimal(total_base, "0"))
        reserved = _to_decimal(self.reserved_base_by_ticker().get(ticker), "0")
        return str(max(Decimal("0"), total - reserved))

    def open_order_counts(self) -> Dict[str, Any]:
        open_orders = self.open_orders()
        by_ticker: Dict[str, Dict[str, int]] = {}
        by_status: Dict[str, int] = {}
        for order in open_orders:
            ticker = str(order.get("ticker", "UNKNOWN")).upper()
            side = str(order.get("side", "UNKNOWN")).upper()
            status = str(order.get("status", "unknown")).lower()
            bucket = by_ticker.setdefault(ticker, {"total": 0, "buy": 0, "sell": 0})
            bucket["total"] += 1
            if side == "BUY":
                bucket["buy"] += 1
            elif side == "SELL":
                bucket["sell"] += 1
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "total_open_orders": len(open_orders),
            "by_ticker": by_ticker,
            "by_status": by_status,
        }

    def diagnostic_order_count(self) -> int:
        def is_diagnostic(order: Dict[str, Any]) -> bool:
            cid = str(order.get("client_order_id", ""))
            ticker = str(order.get("ticker", ""))
            reason = str(order.get("reason", ""))
            return (
                cid.startswith("paper-diagnostic-")
                or ticker.startswith("TEST-")
                or reason.startswith("phase_b_diagnostic_")
                or reason.startswith("phase_b3_diagnostic_")
            )
        return sum(1 for order in self.all_orders() if is_diagnostic(order))

    def has_duplicate_open_order(self, *, ticker: str, side: str, execution_action: Optional[str] = None) -> bool:
        ticker = str(ticker or "").strip().upper()
        side = str(side or "").strip().upper()
        action = str(execution_action or "").strip().lower()
        for order in self.open_orders(ticker=ticker):
            if str(order.get("side", "")).strip().upper() != side:
                continue
            if action and str(order.get("execution_action", "")).strip().lower() != action:
                continue
            return True
        return False

    def upsert_order(self, order: Dict[str, Any], *, event_type: str = "order_upserted") -> Dict[str, Any]:
        state = self._read_state()
        orders = state.setdefault("orders", {})
        order_id = str(order.get("client_order_id") or order.get("order_id") or "").strip()
        if not order_id:
            raise ValueError("order must contain client_order_id or order_id")
        record = dict(order)
        record["client_order_id"] = order_id
        status = normalize_order_status(record.get("status"))
        record["status"] = status
        mode = str(record.get("mode") or record.get("source_mode") or "").strip().lower()
        live_like = mode in {"live", "phase_c_live", "autonomous_small_live"} or str(order_id).startswith(("phasec-", "phased3-", "phased4-"))
        exchange_order_id = str(record.get("exchange_order_id") or "").strip()
        if live_like and is_open_order_status(status) and not exchange_order_id:
            raise ValueError("live open order records require exchange_order_id")
        record["updated_at"] = _now_iso()
        orders[order_id] = record

        # Keep state bounded by dropping oldest final records first.
        if len(orders) > self.max_orders:
            sorted_orders = sorted(orders.items(), key=lambda kv: str((kv[1] or {}).get("updated_at") or ""))
            for key, value in sorted_orders:
                if len(orders) <= self.max_orders:
                    break
                if is_final_order_status((value or {}).get("status")):
                    orders.pop(key, None)

        self._write_state(state)
        self.append_event(event_type, {"order": record})
        return record

    def update_order(self, order_id: str, updates: Dict[str, Any], *, event_type: str = "order_updated") -> Optional[Dict[str, Any]]:
        state = self._read_state()
        orders = state.setdefault("orders", {})
        order = orders.get(order_id)
        if not isinstance(order, dict):
            return None
        order.update(dict(updates or {}))
        order["updated_at"] = _now_iso()
        orders[order_id] = order
        self._write_state(state)
        self.append_event(event_type, {"client_order_id": order_id, "updates": updates, "order": order})
        return dict(order)

    def reserved_quote_by_ticker(self) -> Dict[str, str]:
        totals: Dict[str, Decimal] = {}
        for order in self.open_orders():
            if str(order.get("side", "")).upper() != "BUY":
                continue
            ticker = str(order.get("ticker", "")).upper()
            remaining_quote = _to_decimal(order.get("remaining_quote") or order.get("size_quote"), "0")
            totals[ticker] = totals.get(ticker, Decimal("0")) + max(Decimal("0"), remaining_quote)
        return {k: str(v) for k, v in totals.items()}

    def reserved_base_by_ticker(self) -> Dict[str, str]:
        totals: Dict[str, Decimal] = {}
        for order in self.open_orders():
            if str(order.get("side", "")).upper() != "SELL":
                continue
            ticker = str(order.get("ticker", "")).upper()
            remaining_base = _to_decimal(order.get("remaining_size") or order.get("size_base"), "0")
            totals[ticker] = totals.get(ticker, Decimal("0")) + max(Decimal("0"), remaining_base)
        return {k: str(v) for k, v in totals.items()}

    def summary(self) -> Dict[str, Any]:
        orders = self.all_orders()
        by_status: Dict[str, int] = {}
        for order in orders:
            status = str(order.get("status", "unknown")).lower()
            by_status[status] = by_status.get(status, 0) + 1
        return {
            "generated_at": _now_iso(),
            "total_orders": len(orders),
            "open_orders": len(self.open_orders()),
            "by_status": by_status,
            "reserved_quote_by_ticker": self.reserved_quote_by_ticker(),
            "reserved_base_by_ticker": self.reserved_base_by_ticker(),
            "total_reserved_quote": self.total_reserved_quote(),
            "open_order_counts": self.open_order_counts(),
            "diagnostic_order_count": self.diagnostic_order_count(),
        }
