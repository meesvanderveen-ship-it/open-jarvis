from __future__ import annotations

from decimal import Decimal

from bot.preselection_calibration import evaluate_final_judge_escalation
from bot.trade_planner import build_starter_probe_plan_from_context


def _evaluate(payload):
    return evaluate_final_judge_escalation(payload, min_trade_quote=Decimal("20.00"), max_spread_pct=Decimal("0.0060"))


def _input(**overrides):
    payload = {
        "feature_pack": {
            "market": {"spread_pct": "0.001", "max_spread_pct": "0.006"},
            "risk_context": {"available_quote_balance": "100", "engine_state": {}},
            "entry_gate": {"decision": "analyze", "priority": "normal", "confidence": 56, "setup_type": "reclaim_reversal"},
        },
        "synth": {"composite_confidence": 59, "setup_type": "reclaim_reversal", "key_trigger": "support reclaim", "invalidation": "below support"},
        "bull": {"bull_case_score": 54},
        "bear": {"bear_case_score": 67},
        "breakout": {"breakout_quality_score": 50, "breakout_confirmation_score": 42, "breakout_invalidation_level": "95"},
        "trend": {"trend_strength_score": 50, "trend_alignment_score": 48, "entry_zone_low": 99, "entry_zone_high": 101, "trend_stop_logic": "below 95"},
        "meanrev": {"entry_zone_low": 98, "entry_zone_high": 100, "meanrev_stop_logic": "below 95"},
    }
    payload.update(overrides)
    return payload


def _planner_input(**overrides):
    payload = _input()
    payload["ticker"] = "BTC-USDC"
    payload["feature_pack"]["ticker"] = "BTC-USDC"
    payload["feature_pack"]["current_price"] = "100"
    payload["feature_pack"]["market"].update({
        "mid_price": "100",
        "best_bid": "99.99",
        "best_ask": "100.01",
        "spread_pct": "0.001",
        "max_spread_pct": "0.006",
    })
    payload["feature_pack"]["orderbook_context"] = {
        "snapshot_available": True,
        "freshness_status": "fresh",
        "mid_price": "100",
        "best_bid": "99.99",
        "best_ask": "100.01",
        "spread_pct": "0.001",
        "liquidity_score": "80",
    }
    payload["feature_pack"]["risk_context"] = {
        "available_quote_balance": "100",
        "engine_state": {},
    }
    payload["synth"]["invalidation"] = "below 98"
    payload["breakout"]["breakout_invalidation_level"] = "98"
    payload["trend"]["trend_stop_logic"] = "below 98"
    payload["meanrev"]["meanrev_stop_logic"] = "below 98"
    payload.update(overrides)
    return payload


def test_bearish_context_and_neural_shadow_do_not_veto_good_defined_candidate() -> None:
    ok, metrics = _evaluate(_input())
    assert ok is True
    assert metrics["escalate_to_final_judge"] is True
    assert "bear_score_dominant_warning" in metrics["warnings"]


def test_watch_candidate_can_escalate_when_near_support_with_invalidation() -> None:
    payload = _input()
    payload["feature_pack"]["entry_gate"]["decision"] = "watch"
    payload["feature_pack"]["entry_gate"]["priority"] = "high"
    ok, metrics = _evaluate(payload)
    assert ok is True
    assert metrics["entry_zone_quality"] > 0
    assert metrics["invalidation_quality"] > 0


def test_hard_blockers_remain_hard() -> None:
    payload = _input()
    payload["feature_pack"]["market"]["spread_pct"] = "0.02"
    ok, metrics = _evaluate(payload)
    assert ok is False
    assert "spread_too_wide" in metrics["top_blocker"]
    payload = _input(synth={"composite_confidence": 70, "setup_type": "reclaim_reversal", "key_trigger": "x"})
    payload["breakout"].pop("breakout_invalidation_level")
    payload["trend"].pop("trend_stop_logic")
    payload["meanrev"].pop("meanrev_stop_logic")
    ok, metrics = _evaluate(payload)
    assert ok is False
    assert metrics["top_blocker"] == "defined_invalidation_missing_for_final_judge_escalation"


def test_planner_builds_starter_probe_with_soft_bearish_warnings() -> None:
    payload = _planner_input()
    payload["feature_pack"]["decision_context"] = {
        "neural_shadow_policy": {"prediction": "prefer_no_trade", "execution_allowed": False}
    }
    plan = build_starter_probe_plan_from_context(
        payload,
        ticker="BTC-USDC",
        min_size_quote=Decimal("20.00"),
        max_size_quote=Decimal("100.00"),
    )
    assert plan["plan_action"] in {"prepare_buy", "prepare_reclaim"}
    assert plan["plan_type"] in {"starter_probe", "starter_reclaim_probe"}
    assert plan["side"] == "BUY"
    assert plan["entry_zone_low"] == 99.0
    assert plan["entry_zone_high"] == 101.0
    assert plan["invalidation_price"] == 98.0
    assert plan["stop_loss_price"] == 98.0
    assert plan["take_profit_1"]
    assert plan["max_quote_size"] == 20.0
    assert plan["why_plan_is_valid"]
    assert plan["why_size_is_small"]
    assert plan["planner_confidence"] > 0
    assert plan["planner_blockers"] == []
    assert "bear_score_dominant_soft_warning" in plan["soft_warnings"]
    assert "neural_shadow_prefer_no_trade_soft_warning" in plan["soft_warnings"]


def test_planner_stays_no_plan_for_hard_blockers() -> None:
    stale = _planner_input()
    stale["feature_pack"]["orderbook_context"]["freshness_status"] = "stale"
    plan = build_starter_probe_plan_from_context(stale, ticker="BTC-USDC", min_size_quote=Decimal("20.00"), max_size_quote=Decimal("100.00"))
    assert plan["plan_action"] == "no_plan"
    assert "stale_market_data" in plan["hard_blockers"]

    no_invalidation = _planner_input(synth={"composite_confidence": 59, "setup_type": "reclaim_reversal", "key_trigger": "support reclaim"})
    no_invalidation["breakout"].pop("breakout_invalidation_level")
    no_invalidation["trend"].pop("trend_stop_logic")
    no_invalidation["meanrev"].pop("meanrev_stop_logic")
    plan = build_starter_probe_plan_from_context(no_invalidation, ticker="BTC-USDC", min_size_quote=Decimal("20.00"), max_size_quote=Decimal("100.00"))
    assert plan["plan_action"] == "no_plan"
    assert "invalidation_price" in plan["missing_fields"]

    wide_spread = _planner_input()
    wide_spread["feature_pack"]["market"]["spread_pct"] = "0.02"
    plan = build_starter_probe_plan_from_context(wide_spread, ticker="BTC-USDC", min_size_quote=Decimal("20.00"), max_size_quote=Decimal("100.00"))
    assert plan["plan_action"] == "no_plan"
    assert any("spread_too_wide" in x for x in plan["hard_blockers"])

    no_liquidity = _planner_input()
    no_liquidity["feature_pack"]["orderbook_context"]["liquidity_score"] = "0"
    plan = build_starter_probe_plan_from_context(no_liquidity, ticker="BTC-USDC", min_size_quote=Decimal("20.00"), max_size_quote=Decimal("100.00"))
    assert plan["plan_action"] == "no_plan"
    assert "no_liquidity" in plan["hard_blockers"]

    chase = _planner_input(pending_trade_plan={"do_not_chase_above": "99"})
    plan = build_starter_probe_plan_from_context(chase, ticker="BTC-USDC", min_size_quote=Decimal("20.00"), max_size_quote=Decimal("100.00"))
    assert plan["plan_action"] == "no_plan"
    assert "do_not_chase_hard_violation" in plan["hard_blockers"]

    breakdown = _planner_input()
    breakdown["feature_pack"]["current_price"] = "94"
    breakdown["feature_pack"]["market"]["mid_price"] = "94"
    breakdown["feature_pack"]["orderbook_context"]["mid_price"] = "94"
    plan = build_starter_probe_plan_from_context(breakdown, ticker="BTC-USDC", min_size_quote=Decimal("20.00"), max_size_quote=Decimal("100.00"))
    assert plan["plan_action"] == "no_plan"
    assert "breakdown_through_invalidation" in plan["hard_blockers"]
