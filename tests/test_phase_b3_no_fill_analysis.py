from pathlib import Path

from bot.execution_outcome_tracker import build_paper_no_fill_followup_outcome, ExecutionOutcomeTracker
from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore


class PaperOnlyConfig:
    enable_limit_order_manager = True
    enable_live_limit_orders = False
    enable_live_entry_orders = False
    enable_live_exit_orders = False
    enable_paper_no_fill_followup_analysis = True
    paper_no_fill_followup_min_move_pct = "0.0050"


def _feature(best_bid: str, best_ask: str, mid: str):
    return {
        "market": {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid, "price": mid},
        "orderbook_context": {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid},
    }


def _base_order(**updates):
    order = {
        "ticker": "TEST-BUY",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "client_order_id": "paper-test-buy-expired",
        "status": "expired",
        "limit_price": "100",
        "invalidation_price": "95",
        "size_quote": "50",
        "size_base": "0.5",
        "filled_size": "0",
        "remaining_size": "0.5",
        "reason": "unit_test_no_fill",
        "paper_only": True,
    }
    order.update(updates)
    return order


def test_buy_expired_later_reached_limit_is_missed_fill_opportunity():
    outcome = build_paper_no_fill_followup_outcome(
        _base_order(),
        _feature(best_bid="99", best_ask="100", mid="99.5"),
    )
    assert outcome["primary_label"] == "missed_fill_opportunity"
    assert "expired_too_early" in outcome["labels"]
    assert outcome["allowed_use"] == "soft_context_only"


def test_buy_invalidated_or_below_invalidation_is_avoided_bad_entry():
    outcome = build_paper_no_fill_followup_outcome(
        _base_order(status="invalidated"),
        _feature(best_bid="93", best_ask="94", mid="94"),
    )
    assert outcome["primary_label"] == "avoided_bad_entry"
    assert "correct_no_fill" in outcome["labels"]


def test_sell_expired_then_market_fell_is_missed_exit_opportunity():
    outcome = build_paper_no_fill_followup_outcome(
        _base_order(
            ticker="TEST-SELL",
            side="SELL",
            client_order_id="paper-test-sell-expired",
            execution_action="place_limit_sell_close",
            limit_price="100",
            invalidation_price=None,
        ),
        _feature(best_bid="97", best_ask="98", mid="97.5"),
    )
    assert outcome["primary_label"] == "missed_fill_opportunity"
    assert "market_would_have_been_better" in outcome["labels"]


def test_manager_records_no_fill_followup_once(tmp_path: Path):
    state_path = tmp_path / "open_orders.json"
    event_log = tmp_path / "order_events.jsonl"
    outcome_log = tmp_path / "execution_outcomes.jsonl"
    store = OrderStore(path=state_path, log_path=event_log)
    tracker = ExecutionOutcomeTracker(log_path=outcome_log)
    manager = PaperLimitOrderManager(cfg=PaperOnlyConfig(), order_store=store, execution_outcome_tracker=tracker)

    order = store.upsert_order(_base_order(), event_type="unit_order_seeded")
    first = manager.review_no_fill_followups({"TEST-BUY": _feature("99", "100", "99.5")}, cycle_source="unit")
    second = manager.review_no_fill_followups({"TEST-BUY": _feature("99", "100", "99.5")}, cycle_source="unit")

    assert first["reviewed"] == 1
    assert second["reviewed"] == 0
    updated = store.get_order(order["client_order_id"])
    assert updated["paper_no_fill_followup_status"] == "recorded"
    rows = tracker.load_recent(10)
    assert len(rows) == 1
    assert rows[0]["primary_label"] == "missed_fill_opportunity"
