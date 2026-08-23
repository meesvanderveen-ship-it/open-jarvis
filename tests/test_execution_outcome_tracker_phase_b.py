from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from bot.execution_outcome_tracker import ExecutionOutcomeTracker, build_paper_execution_outcome
from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore


@dataclass
class DummyConfig:
    enable_limit_order_manager: bool = True
    enable_live_limit_orders: bool = False
    enable_live_entry_orders: bool = False
    enable_live_exit_orders: bool = False


def _feature_pack(best_bid="99", best_ask="100", mid="99.5"):
    return {
        "market": {"mid_price": mid, "best_bid": best_bid, "best_ask": best_ask},
        "orderbook_context": {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid},
    }


def test_build_paper_execution_outcome_for_filled_buy_is_execution_only():
    order = {
        "client_order_id": "paper-test",
        "ticker": "ETH-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "status": "filled",
        "limit_price": "100",
        "avg_fill_price": "100",
        "reason": "unit_test",
    }
    evaluation = {
        "action": "fill",
        "status": "filled",
        "reason": "paper_limit_buy_crossed_best_ask",
        "fill_price": "100",
        "market_snapshot": {"best_bid": "99", "best_ask": "100", "mid_price": "99.5"},
    }
    outcome = build_paper_execution_outcome(order, evaluation)
    assert outcome["trade_thesis_evaluated"] is False
    assert outcome["execution_thesis_evaluated"] is True
    assert outcome["paper_only"] is True
    assert outcome["primary_label"] == "good_limit_execution"
    assert outcome["allowed_use"] == "soft_context_only"
    assert outcome["overfit_warning"] == "single_paper_sample_do_not_change_hard_rules"
    assert outcome["growbot_river_learning_context"]["captured_at_source_time"] is True
    assert outcome["growbot_river_learning_context"]["data_policy"]["execution_authority"] is False


def test_tracker_writes_jsonl(tmp_path):
    tracker = ExecutionOutcomeTracker(log_path=tmp_path / "execution_outcomes.jsonl")
    outcome = tracker.record_paper_order_outcome(
        {"client_order_id": "paper-expired", "ticker": "ADA-USDC", "side": "BUY", "status": "expired"},
        {"action": "expire", "status": "expired", "reason": "paper_order_expired"},
    )
    assert outcome["primary_label"] == "expired_correctly"
    rows = [json.loads(line) for line in (tmp_path / "execution_outcomes.jsonl").read_text().splitlines()]
    assert rows[0]["ticker"] == "ADA-USDC"
    assert rows[0]["primary_label"] == "expired_correctly"


def test_paper_manager_records_execution_outcome_on_fill(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    tracker = ExecutionOutcomeTracker(log_path=tmp_path / "execution_outcomes.jsonl")
    manager = PaperLimitOrderManager(cfg=DummyConfig(), order_store=store, execution_outcome_tracker=tracker)

    store.upsert_order(
        {
            "client_order_id": "paper-fill",
            "ticker": "ETH-USDC",
            "side": "BUY",
            "execution_action": "place_limit_buy",
            "status": "submitted",
            "limit_price": "100",
            "size_base": "0.5",
            "size_quote": "50",
            "expires_at": "2099-01-01T00:00:00+00:00",
            "invalidation_price": "95",
            "paper_only": True,
        },
        event_type="unit_seed",
    )

    review = manager.review_open_orders({"ETH-USDC": _feature_pack(best_bid="99", best_ask="100", mid="99.5")})
    assert review["actions"][0]["action"] == "fill"
    assert review["actions"][0]["execution_outcome"]["primary_label"] == "good_limit_execution"
    rows = [json.loads(line) for line in (tmp_path / "execution_outcomes.jsonl").read_text().splitlines()]
    assert rows[0]["client_order_id"] == "paper-fill"
