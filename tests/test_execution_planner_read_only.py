from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.execution_planner import ReadOnlyExecutionPlanner, normalize_execution_plan


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def json_response(self, *args, **kwargs):
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.payload


def _cfg(**overrides):
    values = {
        "enable_read_only_execution_planner": True,
        "execution_planner_call_on_wait": False,
        "allow_gpt_dynamic_order_expiry": True,
        "openai_execution_planner_model": "gpt-5.5",
        "openai_judge_model": "gpt-5.5",
        "entry_limit_order_min_expiry_hours": 1,
        "entry_limit_order_default_expiry_hours": 6,
        "entry_limit_order_max_expiry_hours": 12,
        "exit_limit_order_min_expiry_hours": 1,
        "exit_limit_order_default_expiry_hours": 24,
        "exit_limit_order_max_expiry_hours": 72,
        "add_to_position_order_min_expiry_hours": 1,
        "add_to_position_order_default_expiry_hours": 4,
        "add_to_position_order_max_expiry_hours": 8,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _analysis(decision="approve_trade", side="BUY"):
    return {
        "ticker": "ETH-USDC",
        "judge": {"decision": decision, "side": side, "confidence": 80, "size_quote": 20, "setup_type": "trend_continuation"},
        "trade_plan": {
            "plan_action": "limit_buy",
            "entry_zone_low": "3000",
            "entry_zone_high": "3050",
            "do_not_chase_above": "3060",
            "stop_loss": "2950",
            "take_profit_1": "3150",
            "invalidation": "2940",
        },
        "feature_pack": {
            "ticker": "ETH-USDC",
            "market": {"best_bid": "3001", "best_ask": "3002", "mid_price": "3001.5"},
            "orderbook_context": {"snapshot_available": True, "best_bid": "3001", "best_ask": "3002", "mid_price": "3001.5"},
            "risk_context": {"available_quote_balance": "100", "max_spread_pct": "0.01"},
        },
    }


def test_normalize_execution_plan_clamps_expiry_and_marks_read_only():
    plan = normalize_execution_plan(
        {
            "data_sufficiency": "sufficient",
            "execution_action": "place_limit_buy",
            "execution_quality_score": 150,
            "fill_probability_estimate": "high",
            "adverse_selection_risk": "low",
            "expiry_hours": 99,
            "expiry_reason": "test",
            "cancel_if": ["breaks invalidation"],
            "replace_if": ["spread improves"],
            "reason": "good limit zone",
        },
        cfg=_cfg(),
        ticker="ETH-USDC",
        source="unit-test",
        fallback_action="place_limit_buy",
    )

    assert plan["read_only"] is True
    assert plan["execution_quality_score"] == 100
    assert plan["expiry_hours"] == 12
    assert "expiry_clamped_from_99_to_12_hours" in plan["risk_layer_notes"]
    assert "phase_a_read_only_no_coinbase_order_will_be_placed" in plan["risk_layer_notes"]


def test_read_only_execution_planner_calls_llm_and_logs_without_side_effects():
    logs = []
    llm = FakeLLM({
        "data_sufficiency": "sufficient",
        "execution_action": "place_limit_buy",
        "execution_quality_score": 78,
        "fill_probability_estimate": "medium",
        "adverse_selection_risk": "medium",
        "expiry_hours": 6,
        "expiry_reason": "entry setup can stale quickly",
        "cancel_if": ["price breaks invalidation"],
        "replace_if": ["better retest forms"],
        "reason": "limit buy near support is preferable to chasing",
    })
    planner = ReadOnlyExecutionPlanner(cfg=_cfg(), llm_client=llm, log_writer=lambda name, payload: logs.append((name, payload)))

    plan = planner.plan(ticker="ETH-USDC", analysis=_analysis(), cycle_source="unit_test")

    assert plan is not None
    assert plan["read_only"] is True
    assert plan["execution_action"] == "place_limit_buy"
    assert plan["expiry_hours"] == 6
    assert llm.calls
    assert logs and logs[0][0] == "execution_plans.jsonl"
    assert plan["planner_input_summary"]["judge_decision"] == "approve_trade"


def test_read_only_execution_planner_skips_wait_by_default():
    planner = ReadOnlyExecutionPlanner(cfg=_cfg(execution_planner_call_on_wait=False), llm_client=FakeLLM({}))
    plan = planner.plan(ticker="ETH-USDC", analysis=_analysis(decision="wait", side="NONE"))
    assert plan is None
