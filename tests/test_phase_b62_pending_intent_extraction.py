from bot.config import BotConfig
from bot.pending_order_intents import (
    build_watchlist_intent_from_analysis,
    _watchlist_candidate_diagnostics,
)


def test_gate_watch_intent_uses_text_level_fallback_when_feature_levels_missing():
    cfg = BotConfig()
    analysis = {
        "entry_gate": {
            "decision": "watch",
            "priority": "normal",
            "setup_type": "trend_continuation",
            "confidence": 56,
            "reasons": [
                "Price is sitting near 1h resistance (Donchian20 high ~9.81, 1h BB upper ~9.823); require breakout/acceptance confirms.",
                "If price rejects, use support around 9.62 as invalidation context.",
            ],
            "warnings": ["No active pending_trade_plan trigger is ready."],
        },
        "judge": {"decision": "wait", "confidence": 56},
    }
    feature_pack = {
        "market": {"mid_price": "9.70"},
        "structure": {},
        "orderbook_context": {"best_bid": "9.69", "best_ask": "9.71"},
    }

    diagnostics = _watchlist_candidate_diagnostics(
        cfg=cfg,
        ticker="AVAX-USDC",
        analysis=analysis,
        feature_pack=feature_pack,
    )
    assert diagnostics["eligible"] is True
    assert diagnostics["text_resistance"] is not None
    assert diagnostics["text_support"] is not None

    intent = build_watchlist_intent_from_analysis(
        cfg=cfg,
        ticker="AVAX-USDC",
        analysis=analysis,
        feature_pack=feature_pack,
    )
    assert intent is not None
    assert intent["ticker"] == "AVAX-USDC"
    assert intent["source_kind"] == "gate_watch_order_intent"
    assert intent["requires_fresh_judge_and_risk"] is True
    assert intent["paper_only"] is True
    assert intent["live_order_submitted"] is False
    assert intent["trigger_price"] is not None
    assert intent["level_extraction"]["method"] == "feature_pack_plus_text_fallback"


def test_gate_watch_intent_skip_reason_is_explicit_below_confidence():
    cfg = BotConfig()
    analysis = {
        "entry_gate": {
            "decision": "watch",
            "confidence": 46,
            "reasons": ["Price is near resistance 1.4566 but confirmation is weak."],
        },
        "judge": {"decision": "wait", "confidence": 46},
    }
    diagnostics = _watchlist_candidate_diagnostics(
        cfg=cfg,
        ticker="XRP-USDC",
        analysis=analysis,
        feature_pack={"market": {"mid_price": "1.45"}},
    )
    assert diagnostics["eligible"] is False
    assert diagnostics["reason"].startswith("below_min_gate_confidence")
