from __future__ import annotations

from bot.autonomous_order_manager import build_pending_entry_lifecycle_preview
from bot.orderbook_entry_planner import build_resting_limit_entry_preview, classify_entry_decision


def _analysis(**overrides):
    plan = {
        "plan_action": "prepare_buy",
        "side": "BUY",
        "setup_type": "reclaim_retest",
        "entry_zone_low": "99.50",
        "entry_zone_high": "100.00",
        "do_not_chase_above": "100.80",
        "invalidation_price": "98.00",
        "stop_loss": "98.00",
        "take_profit_1": "104.00",
        "max_quote_size": "20.00",
        "trigger": "trigger_not_ready: wait for reclaim retest",
    }
    judge = {
        "decision": "wait",
        "side": "NONE",
        "size_quote": "0",
        "setup_type": "reclaim_retest",
        "trigger_wait_reason": "trigger_not_ready: fresh reclaim confirmation missing",
        "judge_reasons": ["trigger_not_ready but setup has retest level"],
    }
    feature = {
        "market": {"best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75", "spread_pct": "0.0002"},
        "orderbook_context": {"snapshot_available": True, "best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75"},
        "decision_context": {
            "product_rules": {
                "product_id": "ETH-USDC",
                "price_increment": "0.01",
                "base_increment": "0.00000001",
                "quote_increment": "0.01",
                "base_min_size": "0.00000001",
                "quote_min_size": "1.00",
            },
            "recent_exchange_rejections": [],
        },
    }
    data = {"ticker": "ETH-USDC", "trade_plan": plan, "judge": judge, "feature_pack": feature}
    for key, value in overrides.items():
        if key == "trade_plan":
            data["trade_plan"].update(value)
        elif key == "judge":
            data["judge"].update(value)
        elif key == "feature_pack":
            data["feature_pack"]["market"].update(value.get("market", {}))
            data["feature_pack"]["orderbook_context"].update(value.get("orderbook_context", {}))
        else:
            data[key] = value
    return data


def test_trigger_not_ready_with_concrete_retest_level_is_eligible_preview() -> None:
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis())
    assert preview["eligible"] is True
    assert preview["product_rules"]["precision_context_available"] is True
    assert preview["execution_feasibility"]["can_construct_valid_limit_buy_payload"] is True
    assert preview["would_submit"] is False
    assert preview["post_only"] is True
    assert preview["entry_order_policy"] == "resting_limit_maker_preview"
    assert preview["entry_decision_label"] == "valid_setup_resting_entry_candidate"
    assert preview["recommended_entry_type"] == "prepare_reclaim_retest_limit_entry"
    assert preview["entry_route_type"] == "reclaim_retest_limit"
    assert preview["pending_entry_preview_created"] is True


def test_trigger_not_ready_without_entry_level_is_not_eligible() -> None:
    analysis = _analysis(trade_plan={"entry_zone_low": None, "entry_zone_high": None})
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=analysis, bid=None)
    assert preview["eligible"] is False
    assert "entry_level_missing" in preview["blockers"]
    assert preview["entry_route_type"] == "no_order"


def test_do_not_chase_above_allows_only_lower_resting_limit() -> None:
    analysis = _analysis(trade_plan={"do_not_chase_above": "99.90"})
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=analysis, current_mid="100.00")
    assert preview["eligible"] is True
    assert "current_mid_above_do_not_chase_only_lower_resting_limit_allowed" in preview["warnings"]


def test_support_pullback_with_invalidation_and_target_is_eligible() -> None:
    analysis = _analysis(trade_plan={"setup_type": "range_support", "trigger": "support pullback hold"})
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=analysis)
    assert preview["eligible"] is True


def test_missing_invalidation_and_target_block() -> None:
    preview = build_resting_limit_entry_preview(
        ticker="ETH-USDC",
        analysis=_analysis(trade_plan={"invalidation_price": None, "stop_loss": None, "take_profit_1": None}),
    )
    assert preview["eligible"] is False
    assert "invalidation_level_missing" in preview["blockers"]
    assert "target_level_missing" in preview["blockers"]


def test_spread_too_wide_entry_too_far_capacity_and_position_block() -> None:
    wide = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis(feature_pack={"market": {"spread_pct": "0.02"}}))
    assert "spread_too_wide" in wide["blockers"]
    far = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis(), current_mid="110")
    assert "entry_outside_max_mid_distance_but_inside_technical_retest_route" in far["warnings"]
    cap = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis(), open_orders_count=4, max_open_orders=4)
    assert "max_open_orders_reached" in cap["blockers"]
    pos = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis(), open_positions=[{"ticker": "ETH-USDC", "status": "open", "position_size_base": "0.1"}])
    assert "open_position_same_ticker_present" in pos["blockers"]


def test_no_naked_sell_and_incomplete_schema_safe_wait() -> None:
    sell = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis(trade_plan={"side": "SELL"}))
    assert sell["eligible"] is False
    assert "buy_entries_only_no_naked_sell" in sell["blockers"]
    incomplete = {"ticker": "ETH-USDC", "judge": {"decision": "wait"}, "trade_plan": {"plan_action": "no_plan"}}
    assert classify_entry_decision(incomplete) == "wait_no_setup"
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=incomplete)
    assert preview["eligible"] is False


def test_breakout_trigger_above_market_without_retest_zone_waits_for_confirmation() -> None:
    analysis = _analysis(
        trade_plan={
            "setup_type": "breakout_retest",
            "entry_zone_low": None,
            "entry_zone_high": None,
            "preferred_limit_price": None,
            "trigger_price": "104.00",
            "trigger": "breakout confirmation above 104",
        }
    )
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=analysis)
    assert preview["eligible"] is False
    assert preview["entry_route_type"] == "breakout_confirmation_wait"
    assert "entry_level_missing" in preview["blockers"]


def test_contradictory_breakout_trigger_and_lower_do_not_chase_classifies_no_impossible_plan() -> None:
    analysis = _analysis(
        trade_plan={
            "setup_type": "breakout_retest",
            "entry_zone_low": "1765",
            "entry_zone_high": "1770",
            "do_not_chase_above": "1770",
            "trigger_price": "1848",
            "trigger": "breakout confirmation above 1848",
            "invalidation_price": "1735",
            "take_profit_1": "1900",
        },
        feature_pack={"market": {"mid_price": "1790", "best_bid": "1789.5", "best_ask": "1790.5", "spread_pct": "0.0005"}},
    )
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=analysis)
    assert preview["entry_route_type"] == "breakout_retest_limit"
    assert preview["entry_level"] in {"1767.5", "1770"}
    assert "entry_level_above_do_not_chase" not in preview["blockers"]


def test_pending_entry_lifecycle_preview_connects_fill_to_d2_d3_without_live_side_effects() -> None:
    preview = build_resting_limit_entry_preview(ticker="ETH-USDC", analysis=_analysis())
    lifecycle = build_pending_entry_lifecycle_preview(preview)
    assert lifecycle["read_only"] is True
    assert lifecycle["coinbase_call_attempted"] is False
    assert lifecycle["state_mutation_performed"] is False
    assert lifecycle["fill_to_exit_handoff"]["position_open_required_before_d2"] is True
    assert lifecycle["fill_to_exit_handoff"]["d3_requires_actual_base_and_no_duplicate_exit"] is True
