#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.execution_outcome_tracker import ExecutionOutcomeTracker
from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore


class PaperOnlyConfig:
    enable_limit_order_manager = True
    enable_live_limit_orders = False
    enable_live_entry_orders = False
    enable_live_exit_orders = False
    enable_paper_no_fill_followup_analysis = True
    paper_no_fill_followup_min_move_pct = "0.0050"
    order_store_max_records = 2000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _feature_pack(*, best_bid: str, best_ask: str, mid: str) -> Dict[str, Any]:
    return {
        "market": {"price": mid, "mid_price": mid, "best_bid": best_bid, "best_ask": best_ask},
        "orderbook_context": {"snapshot_available": True, "freshness_status": "fresh", "best_bid": best_bid, "best_ask": best_ask, "mid_price": mid},
    }


def base_no_fill_order(scenario: str) -> Dict[str, Any]:
    side = "BUY"
    action = "place_limit_buy"
    limit = "100"
    invalidation = "95"
    if scenario.startswith("sell_"):
        side = "SELL"
        action = "place_limit_sell_close"
        invalidation = None
    status = "invalidated" if "invalidated" in scenario else "expired"
    return {
        "intent_id": f"diagnostic-no-fill-{scenario}",
        "ticker": f"TEST-NOFILL-{scenario.upper().replace('_', '')}",
        "side": side,
        "order_type": "limit",
        "execution_action": action,
        "limit_price": limit,
        "size_quote": "50",
        "size_base": "0.5",
        "linked_trade_plan_id": "diagnostic-no-fill-plan",
        "linked_position_id": None,
        "created_at": past_iso(6),
        "updated_at": past_iso(1),
        "expires_at": past_iso(1),
        "invalidation_price": invalidation,
        "client_order_id": f"paper-diagnostic-no-fill-{scenario}",
        "status": status,
        "filled_size": "0",
        "remaining_size": "0.5",
        "remaining_quote": "50",
        "avg_fill_price": None,
        "reason": f"phase_b3_no_fill_diagnostic_{scenario}",
        "gpt_output": {"execution_action": action, "reason": f"phase_b3_no_fill_diagnostic_{scenario}"},
        "risk_check_result": {"mode": "paper_only_phase_b3_diagnostic", "accepted": True, "reject_reasons": [], "warnings": []},
        "paper_only": True,
        "live_order_submitted": False,
        "last_lifecycle_evaluation": {"action": "expire" if status == "expired" else "invalidate", "status": status, "reason": f"seeded_{status}_for_followup"},
    }


def scenario_order_and_followup(scenario: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    order = base_no_fill_order(scenario)
    if scenario == "buy_missed_later_touched":
        followup = _feature_pack(best_bid="99", best_ask="100", mid="99.5")
    elif scenario == "buy_missed_rallied":
        followup = _feature_pack(best_bid="104", best_ask="105", mid="104.5")
    elif scenario == "buy_avoided_bad_entry":
        order["status"] = "invalidated"
        followup = _feature_pack(best_bid="93", best_ask="94", mid="94")
    elif scenario == "buy_correct_no_fill":
        followup = _feature_pack(best_bid="98", best_ask="100.2", mid="99.1")
    elif scenario == "sell_missed_later_touched":
        followup = _feature_pack(best_bid="100", best_ask="101", mid="100.5")
    elif scenario == "sell_missed_fell":
        followup = _feature_pack(best_bid="96", best_ask="97", mid="96.5")
    else:
        raise ValueError(f"Onbekend scenario: {scenario}")
    return order, followup


def run_scenarios(*, scenarios: List[str], state_path: Path, log_path: Path, outcome_log_path: Path) -> Dict[str, Any]:
    store = OrderStore(path=state_path, log_path=log_path)
    tracker = ExecutionOutcomeTracker(log_path=outcome_log_path)
    manager = PaperLimitOrderManager(cfg=PaperOnlyConfig(), order_store=store, execution_outcome_tracker=tracker)

    feature_packs: Dict[str, Dict[str, Any]] = {}
    for scenario in scenarios:
        order, followup = scenario_order_and_followup(scenario)
        store.upsert_order(order, event_type="paper_no_fill_diagnostic_order_seeded")
        feature_packs[str(order["ticker"]).upper()] = followup

    before = len(tracker.load_recent(100000))
    review = manager.review_no_fill_followups(feature_packs, cycle_source="phase_b3_diagnostic_no_fill_followup")
    after = len(tracker.load_recent(100000))
    return {
        "generated_at": now_iso(),
        "mode": "paper_no_fill_diagnostic_only_no_coinbase_calls",
        "state_path": str(state_path),
        "log_path": str(log_path),
        "outcome_log_path": str(outcome_log_path),
        "reviewed": review.get("reviewed"),
        "execution_outcomes_written": max(0, after - before),
        "summary": store.summary(),
        "review": review,
        "orders": store.all_orders(),
        "recent_outcomes": tracker.load_recent(20),
    }


def print_summary(result: Dict[str, Any]) -> None:
    print("Phase-B.3 paper no-fill follow-up diagnose")
    print("mode:", result.get("mode"))
    print("state_path:", result.get("state_path"))
    print("log_path:", result.get("log_path"))
    print("outcome_log_path:", result.get("outcome_log_path"))
    print("reviewed:", result.get("reviewed"))
    print("execution_outcomes_written:", result.get("execution_outcomes_written"))
    print("summary:", json.dumps(result.get("summary"), ensure_ascii=False))
    print()
    print(f"{'client_order_id':42} {'side':5} {'status':12} {'label':26} reason")
    print("-" * 125)
    by_cid = {str(row.get("client_order_id")): row for row in result.get("recent_outcomes", [])}
    for order in result.get("orders", []):
        outcome = by_cid.get(str(order.get("client_order_id")), {})
        print(
            f"{str(order.get('client_order_id'))[:42]:42} "
            f"{str(order.get('side'))[:5]:5} "
            f"{str(order.get('status'))[:12]:12} "
            f"{str(outcome.get('primary_label') or '')[:26]:26} "
            f"{str(outcome.get('reason') or '')[:70]}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Test fase-B.3 no-fill/missed-fill analyse zonder Coinbase/live orders.")
    parser.add_argument("--scenario", action="append", choices=[
        "buy_missed_later_touched",
        "buy_missed_rallied",
        "buy_avoided_bad_entry",
        "buy_correct_no_fill",
        "sell_missed_later_touched",
        "sell_missed_fell",
    ])
    parser.add_argument("--project-state", action="store_true")
    parser.add_argument("--confirm-write", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    scenarios = args.scenario or [
        "buy_missed_later_touched",
        "buy_missed_rallied",
        "buy_avoided_bad_entry",
        "buy_correct_no_fill",
        "sell_missed_later_touched",
        "sell_missed_fell",
    ]

    if args.project_state and not args.confirm_write:
        print("Gebruik --confirm-write samen met --project-state. Zonder die vlag wordt niets naar echte state/logs geschreven.")
        return 2

    if args.project_state:
        result = run_scenarios(
            scenarios=scenarios,
            state_path=PROJECT_ROOT / "state" / "open_orders.json",
            log_path=PROJECT_ROOT / "logs" / "order_events.jsonl",
            outcome_log_path=PROJECT_ROOT / "logs" / "execution_outcomes.jsonl",
        )
    else:
        with tempfile.TemporaryDirectory(prefix="phase_b3_no_fill_") as tmp:
            tmp_path = Path(tmp)
            result = run_scenarios(
                scenarios=scenarios,
                state_path=tmp_path / "open_orders.json",
                log_path=tmp_path / "order_events.jsonl",
                outcome_log_path=tmp_path / "execution_outcomes.jsonl",
            )
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print_summary(result)
            return 0

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
