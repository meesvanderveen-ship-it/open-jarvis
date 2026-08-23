from types import SimpleNamespace
from decimal import Decimal

from bot.config import MODE_C_MARKET_ORDER_ACK_VALUE
from bot.phase_c_live_guard import (
    evaluate_mode_c_market_order_guard,
    evaluate_phase_c_live_entry_readiness,
    mode_c_market_order_readiness,
    summarize_phase_c_readiness,
)


PRODUCT_RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "quote_min_size": "1.00",
}


def _cfg(**overrides):
    base = dict(
        enable_phase_c_live_small_limit_orders=False,
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        enable_live_exit_orders=False,
        phase_c_allowed_tickers=["BTC-USDC"],
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_order_quote=Decimal("100.00"),
        phase_c_max_open_entry_orders=1,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_max_cancels_per_cycle=1,
        phase_c_max_replaces_per_cycle=0,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_entry_order_min_expiry_minutes=15,
        phase_c_entry_order_default_expiry_minutes=60,
        phase_c_entry_order_max_expiry_hours=6,
        phase_c_disable_exit_limit_orders=True,
        phase_c_paper_shadow_log=True,
        market_order_enabled=False,
        enable_market_orders=False,
        allow_market_orders=False,
        mode_c_market_order_ack="",
        replication_enabled=False,
        replication_lifecycle_enabled=False,
        replication_lifecycle_http_enabled=False,
        max_open_positions=3,
        autonomous_max_open_orders=3,
        max_new_orders_per_cycle=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _candidate():
    execution_plan = {
        "read_only": True,
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": "0.001",
        },
    }
    order = {
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "size_quote": "20.00",
        "limit_price": "100",
        "product_rules": PRODUCT_RULES,
    }
    analysis = {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "20.00", "valid_trade_plan": True},
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "side": "BUY",
            "entry_zone_low": "99.50",
            "entry_zone_high": "100.00",
            "invalidation_price": "98.00",
            "take_profit_1": "104.00",
            "max_quote_size": "20.00",
            "trigger": "fresh reclaim ready",
        },
        "feature_pack": {
            "market": {
                "best_bid": "99.74",
                "best_ask": "99.76",
                "mid_price": "99.75",
                "spread_pct": "0.0002",
            },
            "orderbook_context": {
                "snapshot_available": True,
                "best_bid": "99.74",
                "best_ask": "99.76",
                "mid_price": "99.75",
            },
            "decision_context": {
                "product_rules": PRODUCT_RULES,
                "pending_order_intent": {
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                }
            }
        },
    }
    risk = {"accepted": True, "mode": "live_phase_c"}
    return analysis, execution_plan, order, risk


def test_phase_c_guard_default_blocks_live_submit_without_side_effects():
    analysis, execution_plan, order, risk = _candidate()
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert result["live_submission_attempted"] is False
    assert "phase_c_live_small_limit_orders_disabled" in result["hard_block_reasons"]
    assert result["safety_policy"]["no_coinbase_submit_in_this_guard"] is True


def test_phase_c_guard_can_pass_only_when_every_required_check_is_present():
    analysis, execution_plan, order, risk = _candidate()
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is True
    assert result["live_submission_attempted"] is False
    assert result["hard_block_reasons"] == []
    assert "resting_entry_preview_replaces_pending_intent_for_prepared_entry" in result["passed_checks"]
    assert "deterministic_live_risk_approval_present" in result["passed_checks"]
    assert "orderbook_entry_candidate_true" in result["passed_checks"]


def test_phase_c_guard_blocks_buy_below_min_live_quote():
    analysis, execution_plan, order, risk = _candidate()
    order["size_quote"] = "19.99"
    analysis["judge"]["size_quote"] = "19.99"
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "quote_size_below_min_live_order_quote" in result["hard_block_reasons"]


def test_phase_c_guard_blocks_buy_above_max_live_quote():
    analysis, execution_plan, order, risk = _candidate()
    order["size_quote"] = "100.01"
    analysis["judge"]["size_quote"] = "100.01"
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "quote_size_above_max_live_order_quote" in result["hard_block_reasons"]


def test_phase_c_guard_rejects_without_live_risk_approval_even_when_flags_are_on():
    analysis, execution_plan, order, _risk = _candidate()
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=None,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "deterministic_live_risk_approval_missing" in result["hard_block_reasons"]


def test_phase_c_guard_blocks_market_order_entry_route():
    analysis, execution_plan, order, risk = _candidate()
    execution_plan["execution_action"] = "place_market_buy"
    order["execution_action"] = "place_market_buy"
    order["order_type"] = "market"
    order["order_configuration"] = {"market_market_ioc": {"quote_size": "20.00"}}
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "phase_c_market_order_entry_blocked" in result["hard_block_reasons"]


def test_phase_c_guard_requires_orderbook_snapshot_for_resting_entry_route():
    analysis, execution_plan, order, risk = _candidate()
    execution_plan["orderbook_summary"] = {"snapshot_available": False}
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "orderbook_snapshot_missing" in result["hard_block_reasons"]
    assert "blocked_stale_opportunity" in result["hard_block_reasons"]


def test_phase_c_guard_orderbook_candidate_false_blocks_resting_live_entry():
    analysis, execution_plan, order, risk = _candidate()
    analysis["trade_plan"].pop("entry_zone_low")
    analysis["trade_plan"].pop("entry_zone_high")
    analysis["trade_plan"].pop("take_profit_1")
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_orderbook_entry_candidate_false" in result["hard_block_reasons"]


def test_phase_c_guard_wait_decision_blocks_live_submit():
    analysis, execution_plan, order, risk = _candidate()
    analysis["judge"].update({"decision": "wait", "side": "NONE", "valid_trade_plan": False})
    analysis["trade_plan"]["valid_trade_plan"] = False
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_wait_decision_cannot_live_submit" in result["hard_block_reasons"]
    assert "blocked_valid_trade_plan_false" in result["hard_block_reasons"]


def test_phase_c_guard_preview_only_blocks_live_submit():
    analysis, execution_plan, order, risk = _candidate()
    order["preview_only"] = True
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_preview_only_cannot_live_submit" in result["hard_block_reasons"]


def test_phase_c_guard_valid_trade_plan_false_blocks_live_submit():
    analysis, execution_plan, order, risk = _candidate()
    analysis["judge"]["valid_trade_plan"] = False
    analysis["trade_plan"]["valid_trade_plan"] = False
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_valid_trade_plan_false" in result["hard_block_reasons"]


def test_phase_c_guard_valid_trade_plan_string_false_blocks_live_submit():
    analysis, execution_plan, order, risk = _candidate()
    analysis["judge"]["valid_trade_plan"] = "false"
    analysis["trade_plan"]["valid_trade_plan"] = "false"
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_valid_trade_plan_false" in result["hard_block_reasons"]


def test_phase_c_guard_prepare_resting_limit_entry_false_blocks_live_submit():
    analysis, execution_plan, order, risk = _candidate()
    order["prepare_resting_limit_entry"] = False
    execution_plan["prepare_resting_limit_entry"] = False
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_prepare_resting_limit_entry_false" in result["hard_block_reasons"]


def test_phase_c_guard_prepare_resting_limit_entry_string_false_blocks_live_submit():
    analysis, execution_plan, order, risk = _candidate()
    order["prepare_resting_limit_entry"] = "false"
    execution_plan["prepare_resting_limit_entry"] = "false"
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_prepare_resting_limit_entry_false" in result["hard_block_reasons"]


def test_phase_c_guard_open_position_same_ticker_blocks_new_entry():
    analysis, execution_plan, order, risk = _candidate()
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        open_positions=[{"ticker": "BTC-USDC", "status": "open", "position_size_base": "0.01"}],
        product_rules=PRODUCT_RULES,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_open_position_same_ticker" in result["hard_block_reasons"]


def test_phase_c_guard_missing_product_rules_blocks_submit():
    analysis, execution_plan, order, risk = _candidate()
    analysis["feature_pack"]["decision_context"].pop("product_rules")
    order.pop("product_rules")
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(
            enable_phase_c_live_small_limit_orders=True,
            enable_live_limit_orders=True,
            enable_live_entry_orders=True,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
    )
    assert result["guard_allows_live_submit"] is False
    assert "blocked_missing_product_rules" in result["hard_block_reasons"]


def test_phase_c_summary_reports_current_promotion_context_without_submit_permission():
    summary = summarize_phase_c_readiness(
        cfg=_cfg(),
        pending_summary={
            "total_intents": 4,
            "open_intents": 2,
            "trigger_ready": [],
            "needs_fresh_analysis": [{"ticker": "ADA-USDC"}],
            "promotion_ready": [{"ticker": "ADA-USDC"}],
        },
        order_summary={"total_orders": 0, "open_orders": 0, "diagnostic_order_count": 0},
    )
    assert summary["safety_policy"]["summary_is_read_only"] is True
    assert summary["pending_order_intents"]["open_intents"] == 2
    assert summary["pending_order_intents"]["promotion_ready_current"] == [{"ticker": "ADA-USDC"}]
    assert "phase_c_master_switch_disabled" in summary["blockers"]


def test_mode_c_market_orders_false_remains_valid_disabled():
    readiness = mode_c_market_order_readiness(cfg=_cfg())
    assert readiness["status"] == "disabled"
    assert readiness["ready"] is False
    assert readiness["blockers"] == []


def test_mode_c_market_orders_true_without_ack_blocks():
    readiness = mode_c_market_order_readiness(
        cfg=_cfg(market_order_enabled=True, enable_market_orders=True, allow_market_orders=True)
    )
    assert readiness["ready"] is False
    assert "market_orders_enabled_without_ack" in readiness["blockers"]
    assert "mode_c_market_order_ack_missing" in readiness["blockers"]


def test_mode_c_market_orders_with_replication_blocks():
    readiness = mode_c_market_order_readiness(
        cfg=_cfg(
            market_order_enabled=True,
            enable_market_orders=True,
            allow_market_orders=True,
            mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
            replication_enabled=True,
        )
    )
    assert readiness["ready"] is False
    assert "market_orders_enabled_with_replication" in readiness["blockers"]


def test_mode_c_market_buy_quote_rails_and_guard_ready():
    analysis, execution_plan, order, risk = _candidate()
    execution_plan["execution_action"] = "place_market_buy"
    order["execution_action"] = "place_market_buy"
    order.pop("limit_price")
    analysis["trade_plan"] = {"trigger": "breakout reclaim", "stop_loss": "95", "target": "110"}
    cfg = _cfg(
        market_order_enabled=True,
        enable_market_orders=True,
        allow_market_orders=True,
        mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
    )

    low = dict(order, size_quote="19.99")
    result_low = evaluate_mode_c_market_order_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        side="BUY",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=low,
        live_risk_result=risk,
    )
    assert "market_order_quote_below_min" in result_low["hard_block_reasons"]

    high = dict(order, size_quote="100.01")
    result_high = evaluate_mode_c_market_order_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        side="BUY",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=high,
        live_risk_result=risk,
    )
    assert "market_order_quote_above_max" in result_high["hard_block_reasons"]

    result = evaluate_mode_c_market_order_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        side="BUY",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
    )
    assert result["guard_allows_market_order"] is True
    assert result["order_type"] == "market"
    assert "fresh_judge_buy_approval_present" in result["passed_checks"]
    assert "deterministic_live_risk_approval_present" in result["passed_checks"]


def test_mode_c_market_sell_requires_position_and_blocks_oversell():
    cfg = _cfg(
        market_order_enabled=True,
        enable_market_orders=True,
        allow_market_orders=True,
        mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
    )
    risk = {"accepted": True, "mode": "live"}
    no_position = evaluate_mode_c_market_order_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        side="SELL",
        order_intent={"side": "SELL", "base_size": "0.01", "estimated_price": "50000"},
        live_risk_result=risk,
        existing_position=None,
    )
    assert "market_sell_without_position" in no_position["hard_block_reasons"]

    oversell = evaluate_mode_c_market_order_guard(
        cfg=cfg,
        ticker="BTC-USDC",
        side="SELL",
        order_intent={"side": "SELL", "base_size": "0.02", "estimated_price": "5000"},
        live_risk_result=risk,
        existing_position={"ticker": "BTC-USDC", "status": "open", "bot_managed_base": "0.01"},
    )
    assert "market_sell_oversell" in oversell["hard_block_reasons"]
