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
    """Minimal safe config for local phase-B lifecycle diagnostics.

    This tool never touches Coinbase. It uses the same OrderStore,
    PaperLimitOrderManager and ExecutionOutcomeTracker classes as the bot, but
    forces all live limit-order flags off so the test stays paper-only even on a
    live master server.
    """

    enable_limit_order_manager = True
    enable_live_limit_orders = False
    enable_live_entry_orders = False
    enable_live_exit_orders = False
    order_store_max_records = 2000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def future_iso(hours: int = 6) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def past_iso(hours: int = 1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def base_order(*, scenario: str, status: str = "submitted") -> Dict[str, Any]:
    created = now_iso()
    return {
        "intent_id": f"diagnostic-intent-{scenario}",
        "ticker": f"TEST-{scenario.upper().replace('_', '')}",
        "side": "BUY",
        "order_type": "limit",
        "execution_action": "place_limit_buy",
        "limit_price": "100",
        "size_quote": "50",
        "size_base": "0.5",
        "linked_trade_plan_id": "diagnostic-trade-plan",
        "linked_position_id": None,
        "created_at": created,
        "updated_at": created,
        "expires_at": future_iso(6),
        "invalidation_price": "95",
        "do_not_chase_above": "102",
        "cancel_if": ["diagnostic cancel condition"],
        "replace_if": ["diagnostic replace condition"],
        "coinbase_order_id": None,
        "client_order_id": f"paper-diagnostic-{scenario}",
        "status": status,
        "filled_size": "0",
        "remaining_size": "0.5",
        "remaining_quote": "50",
        "avg_fill_price": None,
        "reason": f"phase_b_diagnostic_{scenario}",
        "gpt_output": {
            "data_sufficiency": "sufficient",
            "execution_action": "place_limit_buy",
            "execution_quality_score": 80,
            "fill_probability_estimate": "medium",
            "adverse_selection_risk": "low",
            "expiry_hours": 6,
            "expiry_reason": "diagnostic only",
            "cancel_if": ["diagnostic cancel condition"],
            "replace_if": ["diagnostic replace condition"],
            "reason": f"phase_b_diagnostic_{scenario}",
        },
        "risk_check_result": {
            "mode": "paper_only_phase_b_diagnostic",
            "accepted": True,
            "reject_reasons": [],
            "warnings": [],
            "deterministic_risk_rails_still_required_before_live_phase": True,
        },
        "paper_only": True,
        "live_order_submitted": False,
    }


def scenario_order_and_feature_pack(scenario: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    order = base_order(scenario=scenario)

    if scenario == "buy_fill":
        feature_pack = _feature_pack(best_bid="99", best_ask="100", mid="99.5")
    elif scenario == "buy_keep":
        feature_pack = _feature_pack(best_bid="98", best_ask="101", mid="99.5")
    elif scenario == "buy_expire":
        order["expires_at"] = past_iso(1)
        feature_pack = _feature_pack(best_bid="98", best_ask="101", mid="99.5")
    elif scenario == "buy_invalidate":
        feature_pack = _feature_pack(best_bid="93", best_ask="94", mid="94")
    elif scenario == "sell_fill":
        order.update({
            "side": "SELL",
            "execution_action": "place_limit_sell_close",
            "limit_price": "100",
            "size_quote": "50",
            "size_base": "0.5",
            "remaining_size": "0.5",
            "remaining_quote": "50",
            "invalidation_price": None,
            "gpt_output": {
                **dict(order.get("gpt_output") or {}),
                "execution_action": "place_limit_sell_close",
            },
        })
        feature_pack = _feature_pack(best_bid="101", best_ask="102", mid="101.5")
    else:
        raise ValueError(f"Onbekend scenario: {scenario}")

    return order, feature_pack


def _feature_pack(*, best_bid: str, best_ask: str, mid: str) -> Dict[str, Any]:
    return {
        "market": {
            "price": mid,
            "mid_price": mid,
            "best_bid": best_bid,
            "best_ask": best_ask,
        },
        "orderbook_context": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread_pct": "0.001",
        },
    }


def _count_jsonl(path: Path) -> int:
    if not path.exists():
        return 0
    count = 0
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                count += 1
    return count


def run_scenarios(
    *,
    scenarios: List[str],
    state_path: Path,
    log_path: Path,
    outcome_log_path: Path | None = None,
) -> Dict[str, Any]:
    if outcome_log_path is None:
        outcome_log_path = log_path.with_name("execution_outcomes.jsonl")
    store = OrderStore(path=state_path, log_path=log_path)
    tracker = ExecutionOutcomeTracker(log_path=outcome_log_path)
    manager = PaperLimitOrderManager(
        cfg=PaperOnlyConfig(),
        order_store=store,
        execution_outcome_tracker=tracker,
    )

    feature_packs: Dict[str, Dict[str, Any]] = {}
    submitted: List[Dict[str, Any]] = []
    reviews: List[Dict[str, Any]] = []

    outcome_count_before = _count_jsonl(outcome_log_path)

    for scenario in scenarios:
        order, feature_pack = scenario_order_and_feature_pack(scenario)
        stored = store.upsert_order(order, event_type="paper_diagnostic_order_submitted")
        submitted.append(stored)
        feature_packs[str(order["ticker"]).upper()] = feature_pack
        review = manager.review_open_orders(feature_packs)
        reviews.append(review)

    outcome_count_after = _count_jsonl(outcome_log_path)

    return {
        "generated_at": now_iso(),
        "mode": "paper_diagnostic_only_no_coinbase_calls",
        "state_path": str(state_path),
        "log_path": str(log_path),
        "outcome_log_path": str(outcome_log_path),
        "submitted_count": len(submitted),
        "reviews": reviews,
        "summary": store.summary(),
        "orders": store.all_orders(),
        "execution_outcomes_written": max(0, outcome_count_after - outcome_count_before),
        "execution_outcome_total_rows": outcome_count_after,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Test fase-B paper order lifecycle zonder Coinbase/live orders. Schrijft vanaf B.2 ook execution outcomes."
    )
    parser.add_argument(
        "--scenario",
        action="append",
        choices=["buy_fill", "buy_keep", "buy_expire", "buy_invalidate", "sell_fill"],
        help="Scenario om te draaien. Mag meerdere keren. Default: alle scenario's.",
    )
    parser.add_argument(
        "--project-state",
        action="store_true",
        help="Schrijf naar echte state/open_orders.json, logs/order_events.jsonl en logs/execution_outcomes.jsonl. Default gebruikt tijdelijke map.",
    )
    parser.add_argument(
        "--confirm-write",
        action="store_true",
        help="Verplicht bij --project-state om per ongeluk echte paper-state/logs te vervuilen.",
    )
    parser.add_argument("--json", action="store_true", help="Print volledige JSON-output.")
    args = parser.parse_args()

    scenarios = args.scenario or ["buy_fill", "buy_keep", "buy_expire", "buy_invalidate", "sell_fill"]

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
        with tempfile.TemporaryDirectory(prefix="phase_b_paper_lifecycle_") as tmp:
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


def print_summary(result: Dict[str, Any]) -> None:
    print("Phase-B paper lifecycle diagnose")
    print("mode:", result.get("mode"))
    print("state_path:", result.get("state_path"))
    print("log_path:", result.get("log_path"))
    print("outcome_log_path:", result.get("outcome_log_path"))
    print("execution_outcomes_written:", result.get("execution_outcomes_written"))
    print("execution_outcome_total_rows:", result.get("execution_outcome_total_rows"))
    print("summary:", json.dumps(result.get("summary"), ensure_ascii=False))
    print()
    print(f"{'client_order_id':34} {'side':5} {'status':13} {'limit':10} {'avg_fill':10} reason")
    print("-" * 100)
    for order in result.get("orders", []):
        print(
            f"{str(order.get('client_order_id'))[:34]:34} "
            f"{str(order.get('side'))[:5]:5} "
            f"{str(order.get('status'))[:13]:13} "
            f"{str(order.get('limit_price'))[:10]:10} "
            f"{str(order.get('avg_fill_price'))[:10]:10} "
            f"{str(order.get('reason'))[:80]}"
        )


if __name__ == "__main__":
    raise SystemExit(main())
