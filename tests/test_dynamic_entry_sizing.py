from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.dynamic_entry_sizing import calculate_dynamic_entry_quote
from bot.order_plan import build_order_intent_from_execution_plan, is_actionable_order_intent
from bot.phase_c43_autonomous_entry_live import build_phase_c43_guard_and_submit_preparation


PRODUCT_RULES = {
    "quote_min_size": "1.00",
    "base_increment": "0.00000001",
    "price_increment": "0.01",
    "quote_increment": "0.01",
}


def _cfg(**overrides):
    values = {
        "enable_dynamic_entry_sizing": True,
        "min_live_order_quote_usdc": Decimal("50.00"),
        "max_live_order_quote_usdc": Decimal("100.00"),
        "min_dynamic_entry_quote_usdc": Decimal("50.00"),
        "max_dynamic_entry_quote_usdc": Decimal("100.00"),
        "phase_c_max_order_quote": Decimal("100.00"),
        "autonomous_max_order_quote": Decimal("100.00"),
        "max_notional_usd": Decimal("100.00"),
        "phase_c_live_order_post_only": True,
        "phase_c_disable_exit_limit_orders": True,
        "execution_mode": "live",
        "enable_limit_order_manager": True,
        "enable_live_limit_orders": True,
        "enable_live_entry_orders": True,
        "enable_live_exit_orders": False,
        "enable_phase_c_live_small_limit_orders": True,
        "enable_phase_c_live_submit_infrastructure": True,
        "enable_phase_c_actual_coinbase_submit": False,
        "enable_autonomous_small_live_orderbook_mode": True,
        "enable_phase_c43_autonomous_entry_submitter": True,
        "phase_c43_runtime_submit_ack": "",
        "phase_c_allowed_tickers": ["BTC-USDC"],
        "phase_c_max_open_entry_orders": 3,
        "phase_c_max_new_orders_per_cycle": 1,
        "autonomous_max_open_orders": 3,
        "autonomous_max_new_orders_per_cycle": 1,
        "autonomous_entry_only_first": True,
        "autonomous_allow_exits": False,
        "autonomous_require_post_only": True,
        "phase_c_require_orderbook_freshness": True,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _analysis(*, confidence: int = 60, edge: int = 0, objective: int = 0):
    return {
        "judge": {
            "decision": "approve_trade",
            "side": "BUY",
            "confidence": confidence,
            "expected_edge_score": edge,
            "objective_score": objective,
            "size_quote": "20.00",
            "valid_trade_plan": True,
            "setup_type": "reclaim_retest",
        },
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "side": "BUY",
            "entry_price": "100.00",
            "entry_zone_low": "99.00",
            "invalidation_price": "98.00",
            "take_profit_1": "104.00",
            "setup_type": "reclaim_retest",
        },
        "trend": {"higher_timeframe_alignment": "bullish_aligned"},
        "regime": {"market_regime": "stable_trend"},
        "feature_pack": {
            "risk_context": {"available_quote_balance": "500.00"},
            "decision_context": {"product_rules": PRODUCT_RULES},
        },
    }


def test_weak_valid_setup_stays_at_minimum_quote():
    report = calculate_dynamic_entry_quote(cfg=_cfg(), analysis=_analysis())
    assert report["accepted"] is True
    assert Decimal(report["clamped_quote"]) >= Decimal("50.00")
    assert Decimal(report["clamped_quote"]) < Decimal("65.00")
    assert "deterministic_dynamic_entry_sizing" in report["final_reason"]


def test_very_strong_setup_clamps_to_100_usdc():
    analysis = _analysis(confidence=98, edge=98, objective=98)
    analysis["orderbook_entry_preview"] = {
        "expected_reward_to_fee": "7.0",
        "expected_reward_to_risk": "4.0",
    }
    analysis["recent_reflections"] = {"win_rate": "0.70"}
    report = calculate_dynamic_entry_quote(
        cfg=_cfg(),
        analysis=analysis,
        execution_plan={
            "orderbook_summary": {
                "freshness_status": "fresh",
                "spread_pct": "0.0002",
                "depth_score": "100",
                "imbalance": "0.8",
            }
        },
    )
    assert report["accepted"] is True
    assert report["clamped_quote"] == "100.00"
    assert Decimal(report["learning_adjustment"]) > Decimal("0")


def test_insufficient_balance_for_50_blocks_entry_instead_of_downsizing():
    analysis = _analysis()
    analysis["feature_pack"]["risk_context"]["available_quote_balance"] = "49.99"
    report = calculate_dynamic_entry_quote(cfg=_cfg(), analysis=analysis)
    assert report["accepted"] is False
    assert report["clamped_quote"] == "0"
    assert "insufficient_quote_balance_for_min_dynamic_entry" in report["blockers"]


def test_portfolio_priced_sizes_between_10_and_20_pct_by_quality():
    analysis = _analysis()
    analysis["feature_pack"]["risk_context"]["portfolio_value_usdc"] = "2000.00"
    analysis["feature_pack"]["risk_context"]["available_quote_balance"] = "2000.00"
    cfg = _cfg(min_position_pct_of_portfolio=Decimal("0.10"), max_position_pct_of_portfolio=Decimal("0.20"))

    weak_report = calculate_dynamic_entry_quote(cfg=cfg, analysis=analysis)
    assert weak_report["portfolio_priced"] is True
    assert Decimal(weak_report["min_quote"]) == Decimal("200.00")
    assert Decimal(weak_report["max_quote"]) == Decimal("400.00")
    assert Decimal("200.00") <= Decimal(weak_report["clamped_quote"]) < Decimal("300.00")

    strong_analysis = _analysis(confidence=98, edge=98, objective=98)
    strong_analysis["feature_pack"]["risk_context"]["portfolio_value_usdc"] = "2000.00"
    strong_analysis["feature_pack"]["risk_context"]["available_quote_balance"] = "2000.00"
    strong_analysis["orderbook_entry_preview"] = {"expected_reward_to_fee": "7.0", "expected_reward_to_risk": "4.0"}
    strong_report = calculate_dynamic_entry_quote(
        cfg=cfg,
        analysis=strong_analysis,
        execution_plan={
            "orderbook_summary": {
                "freshness_status": "fresh",
                "spread_pct": "0.0002",
                "depth_score": "100",
                "imbalance": "0.8",
            }
        },
    )
    assert Decimal(strong_report["clamped_quote"]) == Decimal("400.00")


def test_larger_portfolio_sizes_proportionally_larger_at_same_quality():
    small = _analysis()
    small["feature_pack"]["risk_context"]["portfolio_value_usdc"] = "1000.00"
    small["feature_pack"]["risk_context"]["available_quote_balance"] = "1000.00"
    big = _analysis()
    big["feature_pack"]["risk_context"]["portfolio_value_usdc"] = "10000.00"
    big["feature_pack"]["risk_context"]["available_quote_balance"] = "10000.00"
    cfg = _cfg()

    small_report = calculate_dynamic_entry_quote(cfg=cfg, analysis=small)
    big_report = calculate_dynamic_entry_quote(cfg=cfg, analysis=big)

    # Same setup quality (identical fixtures otherwise) -> same fraction of
    # each portfolio's own range, so a 10x bigger portfolio sizes exactly
    # 10x bigger for the identical setup.
    assert small_report["quality_fraction"] == big_report["quality_fraction"]
    assert Decimal(big_report["clamped_quote"]) == Decimal(small_report["clamped_quote"]) * 10


def test_no_portfolio_pricing_falls_back_to_configured_usdc_rails():
    analysis = _analysis()  # no portfolio_value_usdc in risk_context
    report = calculate_dynamic_entry_quote(cfg=_cfg(), analysis=analysis)
    assert report["portfolio_priced"] is False
    assert report["min_quote"] == "50.00"
    assert report["max_quote"] == "100.00"


def test_insufficient_free_cash_blocks_even_with_large_portfolio_value():
    # Portfolio equity can be high (illiquid crypto holdings) while free
    # USDC cash is low -- sizing must key off available cash, not the total.
    analysis = _analysis()
    analysis["feature_pack"]["risk_context"]["portfolio_value_usdc"] = "2000.00"
    analysis["feature_pack"]["risk_context"]["available_quote_balance"] = "50.00"
    report = calculate_dynamic_entry_quote(cfg=_cfg(), analysis=analysis)
    assert report["accepted"] is False
    assert report["clamped_quote"] == "0"
    assert "insufficient_quote_balance_for_min_dynamic_entry" in report["blockers"]


def test_c43_wires_deterministic_quote_before_payload_preparation(tmp_path):
    analysis = _analysis(confidence=80, edge=75, objective=75)
    execution_plan = {
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "read_only": True,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": "0.0002",
            "best_bid": "99.99",
            "best_ask": "100.01",
            "mid_price": "100.00",
            "depth_score": "90",
            "imbalance": "0.4",
        },
    }
    order_intent = {
        "ticker": "BTC-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "size_quote": "20.00",
        "limit_price": "100.00",
        "intent_id": "dynamic-size-test",
        "product_rules": PRODUCT_RULES,
    }
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        product_rules=PRODUCT_RULES,
        submit_live=False,
    )
    sizing = result["dynamic_entry_sizing"]
    payload = result["submit_result"]["payload"]
    assert sizing["accepted"] is True
    assert Decimal(sizing["clamped_quote"]) >= Decimal("50.00")
    assert Decimal(sizing["clamped_quote"]) <= Decimal("100.00")
    assert payload["size_quote_requested"] == sizing["clamped_quote"]
    assert payload["dynamic_entry_sizing"]["final_reason"] == sizing["final_reason"]


def test_order_intent_is_resized_before_c43_actionability_check():
    analysis = _analysis(confidence=80, edge=75, objective=75)
    execution_plan = {
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "expiry_hours": 1,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": "0.0002",
            "best_bid": "99.99",
            "best_ask": "100.01",
            "mid_price": "100.00",
            "depth_score": "90",
            "imbalance": "0.4",
        },
    }
    intent = build_order_intent_from_execution_plan(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        feature_pack=analysis["feature_pack"],
    )
    assert intent["dynamic_entry_sizing"]["accepted"] is True
    assert Decimal(intent["size_quote"]) >= Decimal("50.00")
    assert is_actionable_order_intent(intent) is True
