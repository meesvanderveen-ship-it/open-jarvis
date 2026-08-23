#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from typing import Any, Dict, Iterable, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d4_cancel_replace_planner import build_phase_d4_cancel_replace_plan
from bot.phase_d45_operator_decision_report import build_phase_d45_operator_decision_report
from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report


DEFAULT_TICKER = "BTC-USDC"
DEFAULT_CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
DEFAULT_EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
OPEN_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "partial", "cancel_pending", "replace_pending"}
TERMINAL_STATUSES = {"cancelled", "canceled", "expired", "rejected"}


def _load_json(path: str | Path) -> Dict[str, Any]:
    if not path:
        return {}
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        return Decimal(text if text else default)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _normalize_status(value: Any, *, filled_base: Any = "0") -> str:
    status = str(value or "").strip().lower()
    aliases = {
        "submitted": "open",
        "pending": "open",
        "open": "open",
        "partially_filled": "partial",
        "partial": "partial",
        "filled": "filled",
        "done": "filled" if _to_decimal(filled_base) > Decimal("0") else "cancelled",
        "cancelled": "cancelled",
        "canceled": "cancelled",
        "expired": "expired",
        "rejected": "rejected",
    }
    return aliases.get(status, status or "unknown")


def _orders_from_payload(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    raw_orders = payload.get("orders", payload)
    if isinstance(raw_orders, dict):
        return [dict(order) for order in raw_orders.values() if isinstance(order, dict)]
    if isinstance(raw_orders, list):
        return [dict(order) for order in raw_orders if isinstance(order, dict)]
    return []


def _position_from_payload(payload: Dict[str, Any], ticker: str) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    raw_positions = payload.get("positions", payload)
    if isinstance(raw_positions, dict):
        direct = raw_positions.get(selected) or raw_positions.get(ticker)
        if isinstance(direct, dict):
            return dict(direct)
        for position in raw_positions.values():
            if isinstance(position, dict) and _normalize_ticker(position.get("ticker")) == selected:
                return dict(position)
    if isinstance(raw_positions, list):
        for position in raw_positions:
            if isinstance(position, dict) and _normalize_ticker(position.get("ticker")) == selected:
                return dict(position)
    return {}


def _find_order(
    orders: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    client_order_id: str,
    exchange_order_id: str,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    for order in orders:
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        client_match = str(order.get("client_order_id") or "").strip() == client_order_id
        exchange_match = str(order.get("exchange_order_id") or order.get("order_id") or "").strip() == exchange_order_id
        if client_match or exchange_match:
            return dict(order)
    return {}


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
        status = str(order.get("status") or "").strip().lower()
        if _normalize_ticker(order.get("ticker") or order.get("product_id")) != selected_ticker:
            continue
        if str(order.get("side") or "").strip().upper() != "SELL":
            continue
        if str(order.get("phase") or "").strip() != "D3_controlled_live_reduce_only_exits":
            continue
        if status not in OPEN_STATUSES:
            continue
        if selected_position and str(order.get("linked_position_id") or "").strip() != selected_position:
            continue
        out.append(dict(order))
    return out


def _build_lifecycle_event(order: Dict[str, Any], *, ticker: str) -> Dict[str, Any]:
    filled_base = _to_decimal(order.get("filled_base") or order.get("filled_size"), "0")
    fill_count = _to_int(order.get("fill_count"), 0)
    normalized_status = _normalize_status(order.get("status"), filled_base=filled_base)
    return {
        "ticker": _normalize_ticker(order.get("ticker") or order.get("product_id") or ticker),
        "client_order_id": str(order.get("client_order_id") or ""),
        "exchange_order_id": str(order.get("exchange_order_id") or order.get("order_id") or ""),
        "order_id": str(order.get("order_id") or order.get("exchange_order_id") or ""),
        "status": normalized_status,
        "lifecycle_status": normalized_status,
        "raw_local_status": str(order.get("status") or ""),
        "filled_base": str(filled_base),
        "filled_quote": str(order.get("filled_quote") or ""),
        "avg_fill_price": str(order.get("avg_fill_price") or ""),
        "fill_count": fill_count,
        "remaining_size": str(order.get("remaining_size") or order.get("size_base") or ""),
        "size_base": str(order.get("size_base") or order.get("remaining_size") or ""),
        "limit_price": str(order.get("limit_price") or ""),
        "linked_position_id": str(order.get("linked_position_id") or ""),
        "submitted_at": str(order.get("submitted_at") or order.get("created_at") or ""),
        "order_created_at": str(order.get("created_at") or ""),
        "first_seen_open_at": str(order.get("created_at") or ""),
        "terminal_at": str(order.get("closed_at") or order.get("cancelled_at") or ""),
        "planned_exit_price": str(order.get("limit_price") or ""),
        "planned_size_base": str(order.get("size_base") or order.get("remaining_size") or ""),
        "exit_label": str(order.get("d3_exit_label") or ""),
    }


def _local_d4_preview(
    *,
    lifecycle_event: Dict[str, Any],
    warnings: List[str],
    blockers: List[str],
    now: datetime,
) -> Dict[str, Any]:
    proposed_action = "blocked" if blockers else "keep_open"
    return {
        "generated_at": now.isoformat(),
        "phase": "D4_trailing_preview_scaffold",
        "status": "d4_trailing_preview_blocked" if blockers else "d4_trailing_preview_keep_open",
        "ticker": lifecycle_event.get("ticker", DEFAULT_TICKER),
        "linked_position_id": lifecycle_event.get("linked_position_id", ""),
        "current_order_id": lifecycle_event.get("client_order_id", ""),
        "current_exit_price": lifecycle_event.get("limit_price", ""),
        "current_market_mid": "",
        "activation_state": "not_evaluated_local_market_snapshot_missing",
        "peak_reference_price": "",
        "trailing_distance": "",
        "proposed_replacement_price": "",
        "proposed_action": proposed_action,
        "reason": blockers[0] if blockers else "market_snapshot_missing_local_only",
        "blockers": list(blockers),
        "warnings": list(warnings),
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "cancel_replace_allowed": False,
        "requires_future_ack": False,
    }


def _build_d5_metrics(
    *,
    lifecycle_event: Dict[str, Any],
    position: Dict[str, Any],
    d4_decision: Dict[str, Any],
    now: datetime,
) -> Dict[str, Any]:
    plan_fields = {
        "planned_entry_price": str(position.get("entry_price") or ""),
        "planned_exit_price": str(lifecycle_event.get("limit_price") or ""),
        "planned_size_base": str(lifecycle_event.get("size_base") or lifecycle_event.get("remaining_size") or ""),
        "exit_label": str(lifecycle_event.get("exit_label") or ""),
    }
    fills = {
        "filled_base": lifecycle_event.get("filled_base", "0"),
        "filled_quote": lifecycle_event.get("filled_quote", ""),
        "avg_fill_price": lifecycle_event.get("avg_fill_price", ""),
        "fill_count": lifecycle_event.get("fill_count", 0),
        "fees": lifecycle_event.get("fees", "0"),
    }
    return build_phase_d5_execution_metrics_report(
        lifecycle_event=lifecycle_event,
        plan_fields=plan_fields,
        fills=fills,
        d4_decision=d4_decision,
        now=now,
    )


def _apply_wrapper_block(report: Dict[str, Any], *, blockers: List[str], reason: str) -> Dict[str, Any]:
    if not blockers:
        return report
    out = dict(report)
    existing = list(out.get("blockers") or [])
    for blocker in blockers:
        if blocker not in existing:
            existing.append(blocker)
    out["status"] = "d45_real_state_operator_report_blocked"
    out["recommended_operator_action"] = "blocked_p0_review_required"
    out["reason"] = reason
    out["blockers"] = existing
    out["no_coinbase_call"] = True
    out["no_live_action"] = True
    out["state_write_performed"] = False
    out["learning_to_execution_allowed"] = False
    return out


def build_report(args: argparse.Namespace) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    orders_path = Path(args.orders_file)
    positions_path = Path(args.positions_file)
    orders_payload = _load_json(orders_path)
    positions_payload = _load_json(positions_path)
    orders = _orders_from_payload(orders_payload)
    position = _position_from_payload(positions_payload, args.ticker)
    order = _find_order(
        orders,
        ticker=args.ticker,
        client_order_id=args.client_order_id,
        exchange_order_id=args.exchange_order_id,
    )

    wrapper_warnings = ["market_snapshot_missing_local_only"]
    wrapper_blockers: List[str] = []
    if not order:
        lifecycle_event = {
            "ticker": args.ticker,
            "client_order_id": args.client_order_id,
            "exchange_order_id": args.exchange_order_id,
            "status": "unknown",
            "lifecycle_status": "unknown",
            "filled_base": "0",
            "fill_count": 0,
        }
        wrapper_blockers.append("open_d3_exit_order_not_found")
    else:
        lifecycle_event = _build_lifecycle_event(order, ticker=args.ticker)

    linked_position_id = str(lifecycle_event.get("linked_position_id") or order.get("linked_position_id") if order else "")
    open_exits = _open_d3_exit_orders(orders, ticker=args.ticker, linked_position_id=linked_position_id)
    if len(open_exits) > 1:
        wrapper_blockers.append("duplicate_open_d3_exit_orders_for_position")

    remaining_size = _to_decimal(lifecycle_event.get("remaining_size") or lifecycle_event.get("size_base"), "0")
    reserved_base = _to_decimal(position.get("reserved_base_open_exit_orders"), "0")
    status = _normalize_status(lifecycle_event.get("status"), filled_base=lifecycle_event.get("filled_base"))
    if order and status == "open" and remaining_size > Decimal("0") and reserved_base < remaining_size:
        wrapper_blockers.append("reserved_base_open_exit_orders_less_than_open_exit_remaining_size")

    d4_preview = _local_d4_preview(
        lifecycle_event=lifecycle_event,
        warnings=wrapper_warnings,
        blockers=wrapper_blockers,
        now=now,
    )
    d4_planner = build_phase_d4_cancel_replace_plan(
        preview_report=d4_preview,
        current_order=order,
        linked_position_id=linked_position_id,
        position=position,
        product_rules={"min_order_quote": "0"},
        open_orders=open_exits or ([order] if order else []),
        operator_mode="dry_run_only",
        now=now,
    )
    d5_metrics = _build_d5_metrics(
        lifecycle_event=lifecycle_event,
        position=position,
        d4_decision=d4_preview,
        now=now,
    )
    report = build_phase_d45_operator_decision_report(
        lifecycle_event=lifecycle_event,
        d4_preview_report=d4_preview,
        d4_planner_report=d4_planner,
        d5_metrics_report=d5_metrics,
        operator_mode=args.operator_mode,
        now=now,
    )
    if wrapper_blockers:
        report = _apply_wrapper_block(report, blockers=wrapper_blockers, reason=wrapper_blockers[0])

    report["phase"] = "D45_real_state_read_only_operator_report"
    report["source"] = "local_state_read_only"
    report["state_files_read"] = [str(orders_path), str(positions_path)]
    report["order_found"] = bool(order)
    report["open_d3_exit_count_for_position"] = len(open_exits)
    report["reserved_base_open_exit_orders"] = str(position.get("reserved_base_open_exit_orders") or "")
    report["remaining_size"] = str(lifecycle_event.get("remaining_size") or "")
    report["local_market_snapshot_used"] = False
    report["no_coinbase_call"] = True
    report["no_live_action"] = True
    report["state_write_performed"] = False
    report["learning_to_execution_allowed"] = False
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only D.45 operator report from local state files. No Coinbase calls, no state writes."
    )
    parser.add_argument("--ticker", default=DEFAULT_TICKER)
    parser.add_argument("--client-order-id", default=DEFAULT_CLIENT_ORDER_ID)
    parser.add_argument("--exchange-order-id", default=DEFAULT_EXCHANGE_ORDER_ID)
    parser.add_argument("--orders-file", default=str(PROJECT_ROOT / "state" / "open_orders.json"))
    parser.add_argument("--positions-file", default=str(PROJECT_ROOT / "state" / "positions.json"))
    parser.add_argument("--operator-mode", default="decision_only", choices=["wait_only", "decision_only", "future_reprice_consideration"])
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        for key, value in report.items():
            print(f"{key}: {value}")
    return 2 if report.get("recommended_operator_action") == "blocked_p0_review_required" else 0


if __name__ == "__main__":
    raise SystemExit(main())
