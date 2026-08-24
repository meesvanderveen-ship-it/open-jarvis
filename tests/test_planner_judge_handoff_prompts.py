from __future__ import annotations

from bot import prompts
from bot.trade_planner import is_valid_entry_trade_plan


def test_planner_prompt_requires_prepare_buy_for_positive_ev_defined_risk():
    prompt = prompts.TRADE_PLANNER_PROMPT
    assert "positive-EV context exists" in prompt
    assert "prepare_buy" in prompt
    assert "starter/probe" in prompt
    assert "10-20% of risk_context.portfolio_value_usdc" in prompt
    assert "quote_size_below_min_live_order_quote" in prompt
    assert "no_plan must name the concrete blocker" in prompt


def test_final_judge_prompt_enforces_objective_score_and_size_band():
    prompt = prompts.CLAUDE_JUDGE_PROMPT
    assert "objective_score" in prompt
    assert "Return ONLY valid JSON" in prompt
    assert "Do not omit any required key" in prompt
    assert "expected_edge_score" in prompt
    assert "risk_penalty" in prompt
    assert "cost_penalty" in prompt
    assert "drawdown_risk" in prompt
    assert "execution_friction_penalty" in prompt
    assert "valid_trade_plan" in prompt
    assert "judge_reasons" in prompt
    assert "trigger_wait_reason" in prompt
    assert "10-20% of risk_context.portfolio_value_usdc" in prompt
    assert "Starter probe entries (near the 10% portfolio-value floor) are valid when" in prompt
    assert "objective_score is positive" in prompt
    assert "neural_shadow_policy" in prompt
    assert "Do not allow market orders." in prompt


# --- Regression tests for is_valid_entry_trade_plan (commit f13e1f7) ---
# The pre-fix validator required advisory fields (risk_notes, why_plan_is_valid, etc.)
# that are not in the LLM prompt schema, causing valid_trade_plan=False for every plan
# for 6+ days (June 21 - June 27, 2026). These tests prevent regression.

_VALID_PLAN = {
    "plan_action": "prepare_buy",
    "side": "BUY",
    "ticker": "SOL-USDC",
    "setup_type": "reclaim_reversal",
    "entry_zone_low": 72.77,
    "entry_zone_high": 73.20,
    "trigger_price": 73.20,
    "do_not_chase_above": 73.20,
    "invalidation_price": 72.47,
    "stop_loss_price": 72.47,
    "take_profit_1": 75.50,
    "max_quote_size": 50.0,
    "planner_confidence": 65,
}


def test_valid_plan_passes():
    assert is_valid_entry_trade_plan(_VALID_PLAN) is True


def test_advisory_fields_empty_still_passes():
    """Regression: advisory fields absent/empty must NOT cause validation failure."""
    plan = {**_VALID_PLAN, "risk_notes": [], "why_plan_is_valid": "", "why_size_is_small": "", "planner_blockers": [], "must_not_trade_if": []}
    assert is_valid_entry_trade_plan(plan) is True


def test_advisory_fields_missing_still_passes():
    """Regression: advisory fields completely absent must NOT cause validation failure."""
    # _VALID_PLAN has no advisory fields — already covered, but explicit test docs intent
    plan = {k: v for k, v in _VALID_PLAN.items() if k not in ("risk_notes", "why_plan_is_valid")}
    assert is_valid_entry_trade_plan(plan) is True


def test_non_entry_plan_action_fails():
    plan = {**_VALID_PLAN, "plan_action": "no_plan"}
    assert is_valid_entry_trade_plan(plan) is False


def test_wrong_side_fails():
    plan = {**_VALID_PLAN, "side": "SELL"}
    assert is_valid_entry_trade_plan(plan) is False


def test_missing_trigger_price_fails():
    plan = {**_VALID_PLAN}
    del plan["trigger_price"]
    assert is_valid_entry_trade_plan(plan) is False


def test_zero_max_quote_size_fails():
    plan = {**_VALID_PLAN, "max_quote_size": 0}
    assert is_valid_entry_trade_plan(plan) is False


def test_none_entry_zone_low_fails():
    plan = {**_VALID_PLAN, "entry_zone_low": None}
    assert is_valid_entry_trade_plan(plan) is False


def test_non_dict_input_fails():
    assert is_valid_entry_trade_plan(None) is False
    assert is_valid_entry_trade_plan("not a dict") is False


def test_prepare_reclaim_is_valid_entry_action():
    plan = {**_VALID_PLAN, "plan_action": "prepare_reclaim"}
    assert is_valid_entry_trade_plan(plan) is True


def test_prepare_breakout_is_valid_entry_action():
    plan = {**_VALID_PLAN, "plan_action": "prepare_breakout"}
    assert is_valid_entry_trade_plan(plan) is True
