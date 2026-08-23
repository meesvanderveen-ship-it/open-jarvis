from __future__ import annotations

from bot.full_bot_orchestrator import (
    FUTURE_ACKS,
    build_exit_action_candidates,
    build_full_bot_orchestrator_report,
)
from bot.phase_d6_multi_order_intent_preview import build_reservation_preview


def _intent(ticker: str = "XRP-USDC", quote: str = "20", status: str = "near_miss_intent") -> dict:
    return {
        "ticker": ticker,
        "side": "BUY",
        "status": status,
        "setup_family": "reclaim_reversal",
        "preferred_order_type": "limit_maker",
        "proposed_size_quote": quote,
        "proposed_price": "1.1032",
        "soft_blockers": ["confidence_below_forming_intent_threshold"] if status == "near_miss_intent" else [],
    }


def _d6_preview(intents: list[dict] | None = None, near: list[dict] | None = None) -> dict:
    near = near if near is not None else [_intent()]
    intents = intents if intents is not None else []
    return {
        "phase": "D6_multi_order_intent_preview_v1",
        "status": "preview_ready",
        "classification": "WATCH",
        "total_candidates": len(intents) + len(near),
        "preview_ready_intent_count": len(intents),
        "near_miss_intent_count": len(near),
        "preview_ready_intents": intents,
        "near_miss_intents": near,
        "top_near_miss_intents": near[:5],
    }


def test_report_is_dry_run_only_and_preserves_live_gates() -> None:
    report = build_full_bot_orchestrator_report(
        d6_preview_report=_d6_preview(),
        open_orders_state={"orders": {}},
        positions_state={},
    )
    assert report["full_function_dry_run"] is True
    assert report["live_order_submit_attempted"] is False
    assert report["live_cancel_attempted"] is False
    assert report["live_replace_attempted"] is False
    assert report["market_order_attempted"] is False
    assert report["sell_order_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["strict_approve_trade_route_touched"] is False
    assert report["phase_c_strict_approve_route_remains_untouched"] is True
    assert report["d3_d4_live_exit_gates_remain_untouched"] is True


def test_near_miss_buy_is_future_review_not_live_action() -> None:
    report = build_full_bot_orchestrator_report(d6_preview_report=_d6_preview(), open_orders_state={"orders": {}}, positions_state={})
    near = [a for a in report["entry_action_candidates"] if a["action_class"] == "near_miss_maker_buy"][0]
    assert near["classification"] == "preview_only"
    assert near["live_authorized_now"] is False
    assert near["ack_boundary"] == FUTURE_ACKS["pattern_near_miss_buy"]


def test_market_buy_and_sell_remain_preview_only() -> None:
    report = build_full_bot_orchestrator_report(
        d6_preview_report=_d6_preview(),
        open_orders_state={"orders": {}},
        positions_state={"BTC-USDC": {"status": "open", "position_size_base": "0.01", "bot_managed_base": "0.01"}},
    )
    market = report["market_action_candidates"]
    assert any(a["action_class"] == "market_buy_candidate_preview" and a["classification"] == "preview_only" for a in market)
    assert any(a["action_class"] == "emergency_market_sell_preview" and a["classification"] == "preview_only" for a in market)
    assert report["safety_flags"]["market_orders_enabled"] is False


def test_sell_preview_requires_base_and_blocks_duplicate_or_oversell() -> None:
    reservation = build_reservation_preview(
        open_orders_state={"orders": {"s": {"ticker": "BTC-USDC", "side": "SELL", "status": "submitted", "remaining_size": "0.02"}}},
        positions_state={"BTC-USDC": {"status": "open", "position_size_base": "0.01", "bot_managed_base": "0.01"}},
        quote_available="100",
    )
    actions = build_exit_action_candidates(
        {"BTC-USDC": {"status": "open", "position_size_base": "0.01", "bot_managed_base": "0.01"}},
        {"orders": {"s": {"ticker": "BTC-USDC", "side": "SELL", "status": "submitted", "remaining_size": "0.02"}}},
        reservation,
    )
    assert all(a["classification"] == "blocked" for a in actions)
    assert any("duplicate_open_sell_exit_order" in a["blockers"] for a in actions)
    assert any("sell_available_base_after_reservations_zero" in a["blockers"] for a in actions)


def test_order_caps_are_enforced() -> None:
    open_orders = {
        "orders": {
            f"o{i}": {"ticker": f"T{i}-USDC", "side": "BUY", "status": "submitted", "remaining_quote": "20"}
            for i in range(5)
        }
    }
    report = build_full_bot_orchestrator_report(d6_preview_report=_d6_preview(near=[_intent("NEW-USDC")]), open_orders_state=open_orders, positions_state={})
    buy = [a for a in report["entry_action_candidates"] if a["action_class"] == "near_miss_maker_buy"][0]
    assert buy["classification"] == "blocked"
    assert "max_open_orders_total_reached" in buy["blockers"]
    assert "max_total_reserved_buy_quote_exceeded" in buy["blockers"]

    per_ticker = {"orders": {"o": {"ticker": "XRP-USDC", "side": "BUY", "status": "submitted", "remaining_quote": "20"}}}
    report2 = build_full_bot_orchestrator_report(d6_preview_report=_d6_preview(near=[_intent("XRP-USDC")]), open_orders_state=per_ticker, positions_state={})
    buy2 = [a for a in report2["entry_action_candidates"] if a["action_class"] == "near_miss_maker_buy"][0]
    assert "max_open_orders_per_ticker_reached" in buy2["blockers"]


def test_max_order_quote_and_max_new_orders_per_cycle_enforced() -> None:
    report = build_full_bot_orchestrator_report(
        d6_preview_report=_d6_preview(near=[_intent("A-USDC"), _intent("B-USDC"), _intent("C-USDC", quote="25")]),
        open_orders_state={"orders": {}},
        positions_state={},
    )
    buys = [a for a in report["entry_action_candidates"] if a["action_class"] == "near_miss_maker_buy"]
    assert "max_new_orders_per_cycle_reached" in buys[2]["blockers"]
    assert "max_quote_per_order_exceeded" in buys[2]["blockers"]


def test_learning_replication_parameter_mutation_disabled_and_ack_boundaries_present() -> None:
    report = build_full_bot_orchestrator_report(d6_preview_report=_d6_preview(), open_orders_state={"orders": {}}, positions_state={})
    assert report["safety_flags"]["learning_to_execution_allowed"] is False
    assert report["safety_flags"]["replication_enabled"] is False
    assert report["safety_flags"]["parameter_mutation_allowed"] is False
    assert report["live_authorization_matrix"]["Replication"]["classification"] == "blocked"
    assert report["live_authorization_matrix"]["Parameter mutation"]["classification"] == "blocked"
    assert set(FUTURE_ACKS).issubset(set(report["exact_future_acks_required"]))
