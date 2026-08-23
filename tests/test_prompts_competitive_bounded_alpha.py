import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot import prompts


STRICT_JSON_PROMPTS = [
    prompts.GPT_NANO_GATE_PROMPT,
    prompts.DEEPSEEK_PREPROCESS_PROMPT,
    prompts.REGIME_PROMPT,
    prompts.TREND_PROMPT,
    prompts.BREAKOUT_PROMPT,
    prompts.MEANREV_PROMPT,
    prompts.BULL_PROMPT,
    prompts.BEAR_PROMPT,
    prompts.SYNTH_PROMPT,
    prompts.TRADE_PLANNER_PROMPT,
    prompts.CLAUDE_JUDGE_PROMPT,
]


def test_prompts_still_demand_strict_json():
    for prompt in STRICT_JSON_PROMPTS:
        assert "Return only strict JSON" in prompt
        assert "no markdown" in prompt.lower() or "No markdown" in prompt
        assert "outside JSON" in prompt


def test_no_extra_top_level_keys_are_introduced_for_starter_classification():
    assert "Do not include extra top-level keys" in prompts.SYNTH_PROMPT
    assert (
        "Classify the setup inside text fields as no_trade, starter_candidate, "
        "or normal_candidate; do not add extra JSON keys."
    ) in prompts.SYNTH_PROMPT
    assert "Do not include extra top-level keys" in prompts.TRADE_PLANNER_PROMPT
    assert "Do not include extra top-level keys" in prompts.CLAUDE_JUDGE_PROMPT


def test_spot_only_no_naked_shorts_and_market_orders_not_encouraged():
    spot_prompts = [
        prompts.GPT_NANO_GATE_PROMPT,
        prompts.TREND_PROMPT,
        prompts.BREAKOUT_PROMPT,
        prompts.MEANREV_PROMPT,
        prompts.BULL_PROMPT,
        prompts.BEAR_PROMPT,
        prompts.SYNTH_PROMPT,
        prompts.TRADE_PLANNER_PROMPT,
        prompts.CLAUDE_JUDGE_PROMPT,
    ]
    for prompt in spot_prompts:
        assert "SPOT" in prompt
        assert "naked shorts" in prompt

    assert "SELL only reduces/closes existing meaningful base" in prompts.TRADE_PLANNER_PROMPT
    assert "SELL only to reduce or close an existing meaningful base-asset position" in prompts.CLAUDE_JUDGE_PROMPT
    assert "Do not allow market orders." in prompts.TRADE_PLANNER_PROMPT
    assert "side=BUY, size_quote between 20.00 and 100.00 USDC" in prompts.CLAUDE_JUDGE_PROMPT
    assert "if reduce_size/close_position ? NEVER side=BUY" in prompts.CLAUDE_JUDGE_PROMPT


def test_final_risk_firewall_remains_absolute():
    assert "You do not bypass risk controls" in prompts.TRADE_PLANNER_PROMPT
    assert "deterministic risk firewall may accept, reject, resize" in prompts.TRADE_PLANNER_PROMPT
    assert "deterministic risk checks remain absolute" in prompts.CLAUDE_JUDGE_PROMPT
    assert "Never override hard safety rails" in prompts.CLAUDE_JUDGE_PROMPT
    assert "risk/firewall may reduce it" in prompts.TRADE_PLANNER_PROMPT


def test_competitive_bounded_alpha_language_is_present():
    assert "positive expected value" in prompts.GPT_NANO_GATE_PROMPT
    assert "opportunity-cost" in prompts.SYNTH_PROMPT
    assert "starter/probe" in prompts.TRADE_PLANNER_PROMPT
    assert "distinguish uncertainty from actual negative edge" in prompts.BEAR_PROMPT
    assert "one-class no-trade learning hard-block analysis" in prompts.GPT_NANO_GATE_PROMPT
    assert "one-class biased, treat it as weak context only" in prompts.GPT_NANO_GATE_PROMPT
    assert "one-class prefer_no_trade/no-trade bias to dominate" in prompts.CLAUDE_JUDGE_PROMPT
