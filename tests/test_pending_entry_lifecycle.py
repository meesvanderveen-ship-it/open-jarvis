from __future__ import annotations

from datetime import datetime, timedelta, timezone

from bot.pending_entry_lifecycle import (
    LIVE_CANCEL_ACK,
    evaluate_pending_entry_lifecycle,
    is_pending_entry_order,
    replacement_allowed_same_thesis,
)


def _order(**overrides):
    created = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    order = {
        "client_order_id": "phasec-ETHUSDC-test",
        "exchange_order_id": "cb-1",
        "ticker": "ETH-USDC",
        "product_id": "ETH-USDC",
        "side": "BUY",
        "status": "submitted",
        "execution_action": "place_limit_buy",
        "created_at": created,
        "limit_price": "100",
        "invalidation_level": "98",
        "do_not_chase_above": "101",
        "size_quote": "20",
        "setup_type": "reclaim_retest",
        "trade_plan_snapshot": {
            "plan_action": "prepare_buy",
            "side": "BUY",
            "setup_type": "reclaim_retest",
            "entry_zone_low": "99.5",
            "entry_zone_high": "100.2",
            "invalidation_price": "98",
            "take_profit_1": "104",
            "do_not_chase_above": "101",
        },
    }
    order.update(overrides)
    return order


def _market(**overrides):
    market = {"mid_price": "100", "best_bid": "99.99", "best_ask": "100.01", "spread_pct": "0.0002", "liquidity_score": "100"}
    market.update(overrides)
    return market


def test_open_buy_setup_still_valid_keep_open() -> None:
    result = evaluate_pending_entry_lifecycle(order=_order(), current_market=_market())
    assert result["lifecycle_action"] == "keep_open"
    assert result["cancel_required"] is False
    assert result["coinbase_cancel_attempted"] is False


def test_invalidation_breached_before_fill_cancel_preview() -> None:
    result = evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(mid_price="97.9"))
    assert result["lifecycle_action"] == "cancel_preview"
    assert result["specific_action"] == "cancel_preview_setup_invalidated"
    assert result["cancel_required"] is True
    assert "setup_invalidated_price_breached_invalidation" in result["blockers"]


def test_current_judge_no_setup_or_bad_market_cancel_preview() -> None:
    result = evaluate_pending_entry_lifecycle(
        order=_order(),
        current_market=_market(),
        current_analysis={"judge": {"decision": "wait"}, "trade_plan": {"plan_action": "no_plan", "no_plan_reason": "no setup"}},
    )
    assert result["cancel_required"] is True
    assert "current_judge_no_setup_or_no_plan" in result["blockers"]
    bad = evaluate_pending_entry_lifecycle(
        order=_order(),
        current_market=_market(),
        current_analysis={"judge": {"decision": "wait", "judge_reasons": ["bad_market spread_too_wide"]}, "trade_plan": {"plan_action": "prepare_buy"}},
    )
    assert "current_judge_bad_market" in bad["blockers"]


def test_higher_timeframe_invalidates_cancel_preview() -> None:
    result = evaluate_pending_entry_lifecycle(
        order=_order(),
        current_market=_market(),
        current_analysis={"judge": {"decision": "wait", "judge_reasons": ["higher timeframe invalidated by 4h/1d bearish"]}, "trade_plan": {"plan_action": "prepare_buy"}},
    )
    assert result["specific_action"] == "cancel_preview_higher_timeframe_invalidated"


def test_ttl_spread_liquidity_price_moved_away_and_same_ticker_position_cancel() -> None:
    old = _order(created_at=(datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat())
    assert "order_ttl_exceeded" in evaluate_pending_entry_lifecycle(order=old, current_market=_market())["blockers"]
    assert "spread_too_wide" in evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(spread_pct="0.02"))["blockers"]
    assert "liquidity_worsened" in evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(liquidity_score="1"), env={"PENDING_ENTRY_MIN_LIQUIDITY_SCORE": "10"})["blockers"]
    assert "price_moved_away_without_fill" in evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(mid_price="103"))["blockers"]
    pos = [{"ticker": "ETH-USDC", "status": "open", "position_size_base": "0.1"}]
    assert "same_ticker_position_exists" in evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(), open_positions=pos)["blockers"]


def test_exchange_filled_or_partial_fill_handoff_no_cancel() -> None:
    filled = evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(), exchange_order_status={"status": "FILLED", "filled_size": "0.2"})
    assert filled["cancel_required"] is False
    assert filled["handoff_to_fill_reconcile"] is True
    assert filled["reason"] == "handoff_to_fill_reconcile"
    partial = evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(), exchange_order_status={"status": "OPEN", "filled_size": "0.1"})
    assert partial["partial_fill_reconcile_required"] is True
    assert partial["cancel_required"] is False


def test_d3_sell_exit_order_is_ignored_by_pending_entry_lifecycle() -> None:
    d3 = _order(side="SELL", phase="D3_controlled_live_reduce_only_exits", execution_action="place_limit_sell", status="submitted")
    assert is_pending_entry_order(d3) is False
    result = evaluate_pending_entry_lifecycle(order=d3, current_market=_market())
    assert result["lifecycle_action"] == "noop"
    assert result["reason"] == "not_pending_entry_order"


def test_live_cancel_requires_flag_and_ack_and_preview_has_no_state_write() -> None:
    cancel = evaluate_pending_entry_lifecycle(order=_order(), current_market=_market(mid_price="97.9"), env={})
    assert cancel["coinbase_cancel_allowed"] is False
    assert cancel["coinbase_cancel_attempted"] is False
    assert cancel["state_write_allowed"] is False
    armed = evaluate_pending_entry_lifecycle(
        order=_order(),
        current_market=_market(mid_price="97.9"),
        env={"ENABLE_PENDING_ENTRY_LIVE_CANCEL": "true", "PENDING_ENTRY_LIVE_CANCEL_ACK": LIVE_CANCEL_ACK},
    )
    assert armed["coinbase_cancel_allowed"] is True
    assert armed["coinbase_cancel_attempted"] is False
    assert armed["state_write_attempted"] is False


def test_duplicate_cancel_idempotent_and_replacement_same_thesis_rules() -> None:
    pending = evaluate_pending_entry_lifecycle(order=_order(status="cancel_pending", cancel_requested_at="2026-06-16T00:00:00Z"), current_market=_market(mid_price="97.9"))
    assert pending["reason"] == "duplicate_cancel_blocked_idempotent"
    assert pending["cancel_required"] is False
    ok = replacement_allowed_same_thesis(_order(replace_count=0), {"ticker": "ETH-USDC", "setup_type": "reclaim_retest"})
    assert ok["allowed"] is True
    blocked = replacement_allowed_same_thesis(_order(replace_count=1), {"ticker": "ETH-USDC", "setup_type": "breakout"}, max_replaces=1)
    assert blocked["allowed"] is False
    assert "max_replace_count_reached" in blocked["blockers"]
    assert "replacement_setup_thesis_changed" in blocked["blockers"]
