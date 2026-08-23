#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore


@dataclass
class DiagnosticConfig:
    enable_limit_order_manager: bool = True
    enable_live_limit_orders: bool = False
    enable_live_entry_orders: bool = False
    enable_live_exit_orders: bool = False
    enable_paper_reserved_balance_checks: bool = True
    enable_paper_order_budget_enforcement: bool = True
    max_order_actions_per_cycle: int = 5
    max_new_orders_per_cycle: int = 5
    max_cancels_per_cycle: int = 3
    max_replaces_per_cycle: int = 2
    max_open_paper_orders_total: int = 3
    max_open_paper_entry_orders_per_ticker: int = 1
    max_open_paper_exit_orders_per_ticker: int = 2
    order_store_max_records: int = 100


def feature_pack(available_quote: str = "100", available_base: str = "1") -> Dict[str, Any]:
    return {
        "market": {"mid_price": "100", "best_bid": "99", "best_ask": "101"},
        "orderbook_context": {"best_bid": "99", "best_ask": "101", "mid_price": "100"},
        "risk_context": {
            "available_quote_balance": available_quote,
            "available_base_balance": available_base,
        },
    }


def buy_analysis(size_quote: str = "50") -> Dict[str, Any]:
    return {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": size_quote, "confidence": 75},
        "trade_plan": {
            "plan_action": "prepare_reclaim",
            "entry_zone_low": "98",
            "entry_zone_high": "100",
            "do_not_chase_above": "102",
            "stop_loss": "95",
            "take_profit_1": "110",
        },
    }


def execution_plan() -> Dict[str, Any]:
    return {
        "execution_action": "place_limit_buy",
        "data_sufficiency": "sufficient",
        "execution_quality_score": 75,
        "fill_probability_estimate": "medium",
        "adverse_selection_risk": "low",
        "expiry_hours": 6,
        "expiry_reason": "phase_b4_diagnostic",
        "cancel_if": ["breaks invalidation"],
        "replace_if": ["spread improves"],
        "reason": "phase_b4_diagnostic_budget_reserved_balance_test",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnoseer fase-B.4 paper reserved balances en orderbudgetten zonder Coinbase-calls.")
    parser.add_argument("--project-state", action="store_true", help="Schrijf naar echte state/open_orders.json en logs/order_events.jsonl")
    parser.add_argument("--confirm-write", action="store_true", help="Verplicht bij --project-state")
    args = parser.parse_args()

    if args.project_state and not args.confirm_write:
        print("Gebruik --confirm-write als je bewust de echte project-state wilt gebruiken.")
        return 2

    tmpdir = None
    if args.project_state:
        state_path = Path("state/open_orders.json")
        log_path = Path("logs/order_events.jsonl")
        mode = "project_state_confirmed_no_coinbase_calls"
    else:
        tmpdir = tempfile.TemporaryDirectory(prefix="phase_b4_budget_reserved_")
        root = Path(tmpdir.name)
        state_path = root / "open_orders.json"
        log_path = root / "order_events.jsonl"
        mode = "temporary_diagnostic_no_coinbase_calls"

    store = OrderStore(path=state_path, log_path=log_path, max_orders=100)
    manager = PaperLimitOrderManager(cfg=DiagnosticConfig(), order_store=store)
    manager.begin_cycle("phase_b4_diagnostic")

    first = manager.maybe_create_order_from_execution_plan(
        ticker="TEST-B4A-USDC",
        analysis=buy_analysis("50"),
        execution_plan=execution_plan(),
        feature_pack=feature_pack("100"),
    )
    duplicate = manager.maybe_create_order_from_execution_plan(
        ticker="TEST-B4A-USDC",
        analysis=buy_analysis("30"),
        execution_plan=execution_plan(),
        feature_pack=feature_pack("100"),
    )

    # Reset budget to isolate reserved-balance rejection from new-order budget.
    manager.begin_cycle("phase_b4_diagnostic_reserved_balance")
    reserved_reject = manager.maybe_create_order_from_execution_plan(
        ticker="TEST-B4B-USDC",
        analysis=buy_analysis("60"),
        execution_plan=execution_plan(),
        feature_pack=feature_pack("100"),
    )

    # Reset and isolate budget exhaustion.
    manager.cfg.max_new_orders_per_cycle = 1
    manager.begin_cycle("phase_b4_diagnostic_budget")
    budget_first = manager.maybe_create_order_from_execution_plan(
        ticker="TEST-B4C-USDC",
        analysis=buy_analysis("10"),
        execution_plan=execution_plan(),
        feature_pack=feature_pack("200"),
    )
    budget_second = manager.maybe_create_order_from_execution_plan(
        ticker="TEST-B4D-USDC",
        analysis=buy_analysis("10"),
        execution_plan=execution_plan(),
        feature_pack=feature_pack("200"),
    )

    payload = {
        "mode": mode,
        "state_path": str(state_path),
        "log_path": str(log_path),
        "results": {
            "first_submit": (first or {}).get("status"),
            "duplicate_guard": (duplicate or {}).get("status"),
            "reserved_balance_guard": (reserved_reject or {}).get("status"),
            "budget_first": (budget_first or {}).get("status"),
            "budget_second": (budget_second or {}).get("status"),
        },
        "store_summary": store.summary(),
        "budget_status": manager.budget_status(),
    }
    print("Phase-B.4 paper budget/reserved-balance diagnose")
    print(json.dumps(payload, ensure_ascii=False, indent=2))

    if tmpdir is not None:
        tmpdir.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
