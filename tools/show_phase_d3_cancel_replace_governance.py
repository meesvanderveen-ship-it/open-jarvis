#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
from typing import Any, Dict, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.config import BotConfig
from bot.order_store import OrderStore
from bot.state_store import StateStore
from tools.show_phase_d3_open_exit_order_governance import (
    FUTURE_CANCEL_ACK,
    FUTURE_REPLACE_ACK,
    build_report as build_open_exit_governance_report,
)


def _json_safe(value: Any) -> Any:
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
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _load_json_fixture(path: str) -> Dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _env_flag_enabled(name: str) -> bool:
    value = str(os.getenv(name, "")).strip().lower()
    return value in {"1", "true", "yes", "y", "on"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Preview-only cancel/replace governance for one open D.3 exit order")
    parser.add_argument("--ticker", default="BTC-USDC")
    parser.add_argument("--client-order-id", required=True)
    parser.add_argument("--exchange-order-id", required=True)
    parser.add_argument("--linked-position-id", required=True)
    parser.add_argument("--snapshot-fixture", default="")
    parser.add_argument("--market-fixture", default="")
    parser.add_argument("--product-fixture", default="")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def _safe_sequence() -> list[str]:
    return [
        "future controlled cancel existing D.3 order",
        "read-only poll until Coinbase CANCELLED",
        "governed local D.3 closeout and reservation release",
        "new D.3 live-rules preview",
        "new fingerprint review",
        "only then optional one-shot new SELL with ACKs",
    ]


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
    stale = build_open_exit_governance_report(
        ticker=ticker,
        client_order_id=client_order_id,
        exchange_order_id=exchange_order_id,
        linked_position_id=linked_position_id,
        snapshot_fixture=snapshot_fixture,
        market_fixture=market_fixture,
        product_fixture=product_fixture,
        snapshot_override=snapshot_override,
        market_override=market_override,
        product_rules_override=product_rules_override,
        order_store=order_store,
        state_store=state_store,
    )

    snapshot = stale.get("coinbase_snapshot") if isinstance(stale.get("coinbase_snapshot"), dict) else {}
    nested_snapshot = snapshot.get("snapshot") if isinstance(snapshot.get("snapshot"), dict) else {}
    raw_order = nested_snapshot.get("raw_order") if isinstance(nested_snapshot.get("raw_order"), dict) else {}

    report: Dict[str, Any] = {
        "ticker": stale.get("ticker"),
        "client_order_id": stale.get("client_order_id"),
        "exchange_order_id": stale.get("exchange_order_id"),
        "linked_position_id": stale.get("linked_position_id"),
        "cancel_replace_governance_status": "d3_cancel_replace_governance_blocked",
        "current_order_status": stale.get("coinbase_status") or stale.get("local_order_status") or "",
        "filled_base": snapshot.get("filled_base") or "0",
        "pending_cancel": bool(raw_order.get("pending_cancel")),
        "open_d3_orders_count": stale.get("open_d3_orders_count"),
        "stale_governance_recommendation": stale.get("recommendation"),
        "replication_enabled": _env_flag_enabled("REPLICATION_ENABLED"),
        "cancel_candidate_preview_only": False,
        "replace_candidate_preview_only": False,
        "required_future_cancel_ack": FUTURE_CANCEL_ACK,
        "required_future_replace_ack": FUTURE_REPLACE_ACK,
        "safe_sequence_steps": _safe_sequence(),
        "blockers": [],
        "warnings": [],
        "no_state_write": True,
        "no_coinbase_cancel": True,
        "no_coinbase_replace": True,
        "no_coinbase_submit": True,
        "safety_policy": {
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_replace": True,
            "does_not_mutate_state": True,
            "preview_only_governance": True,
            "replication_isolation_required": True,
        },
        "stale_open_governance": stale,
    }

    blockers = list(stale.get("blockers") or [])
    warnings = list(stale.get("warnings") or [])
    report["warnings"] = warnings

    current_status = str(report["current_order_status"] or "").strip().lower()
    filled_base = str(report["filled_base"] or "0")
    pending_cancel = bool(report["pending_cancel"])
    replication_enabled = bool(report["replication_enabled"])
    stale_recommendation = str(report["stale_governance_recommendation"] or "").strip().lower()
    position_size_base = _to_decimal(stale.get("position_size_base"), "0")
    available_base = _to_decimal(stale.get("available_base_after_reservations"), "0")
    reserved_base = _to_decimal(stale.get("reserved_base_open_exit_orders"), "0")
    bot_managed_base = _to_decimal(stale.get("bot_managed_base"), "0")
    computed_base_semantics_match = (available_base + reserved_base) == bot_managed_base
    available_matches_position_size = available_base == position_size_base

    if stale.get("open_d3_orders_count") != 1:
        blockers.append("open_d3_order_count_not_one")
    if str((stale.get("position_status") or "")).strip().lower() != "open":
        blockers.append("local_position_not_open")
    if (
        not bool(stale.get("available_reserved_matches_bot_manageable_base"))
        or not computed_base_semantics_match
        or not available_matches_position_size
    ):
        blockers.append("base_semantics_incoherent")
    if not str(stale.get("exchange_order_id") or "").strip():
        blockers.append("exchange_order_id_missing")
    if stale.get("linked_position_id") != linked_position_id:
        blockers.append("linked_position_id_mismatch")

    if pending_cancel:
        blockers.append("order_pending_cancel_monitor_only")

    if replication_enabled:
        blockers.append("replication_enabled_blocks_d3_cancel_replace_governance")
        warnings.append("replication_follower_must_not_control_master_d3_lifecycle")
        report["safe_sequence_steps"] = []

    if current_status != "open":
        blockers.append("order_not_open_reconcile_first")

    if str(filled_base).strip() not in {"", "0", "0.0", "0.00"}:
        blockers.append("filled_base_nonzero_reconcile_first")

    replace_candidate = (
        current_status == "open"
        and not pending_cancel
        and str(filled_base).strip() in {"", "0", "0.0", "0.00"}
        and stale_recommendation == "replace_candidate_preview_only"
        and not blockers
    )
    cancel_candidate = (
        current_status == "open"
        and not pending_cancel
        and str(filled_base).strip() in {"", "0", "0.0", "0.00"}
        and stale_recommendation in {"cancel_candidate_preview_only", "replace_candidate_preview_only"}
        and not blockers
    )

    report["cancel_candidate_preview_only"] = cancel_candidate
    report["replace_candidate_preview_only"] = replace_candidate
    report["blockers"] = sorted(set(blockers))

    if pending_cancel:
        report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_monitor_pending_cancel"
    elif report["blockers"]:
        if "replication_enabled_blocks_d3_cancel_replace_governance" in report["blockers"]:
            report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_blocked_replication_enabled"
        elif "order_not_open_reconcile_first" in report["blockers"] or "filled_base_nonzero_reconcile_first" in report["blockers"]:
            report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_reconcile_first"
        else:
            report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_blocked"
    elif replace_candidate:
        report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_replace_candidate_preview_only"
    elif cancel_candidate:
        report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_cancel_candidate_preview_only"
    else:
        report["cancel_replace_governance_status"] = "d3_cancel_replace_governance_keep_open"

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
