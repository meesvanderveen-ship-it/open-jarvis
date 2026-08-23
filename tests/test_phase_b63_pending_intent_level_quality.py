from decimal import Decimal

from bot.pending_order_intents import (
    _extract_levels_from_texts,
    build_watchlist_intent_from_analysis,
    evaluate_pending_intent,
)


class DummyConfig:
    enable_paper_watchlist_intents_from_gate_watch = True
    paper_pending_intent_min_gate_confidence = 50
    paper_pending_intent_ttl_hours = 12


def test_b63_text_level_extraction_filters_indicators_and_dedupes():
    texts = [
        "Price is sitting right under/at nearby 1h resistance (Donchian20 high 0.2707) with tight spread and bid-heavy orderbook.",
        "15m RSI is overbought (72.2), which increases whipsaw risk.",
        "Event risk is medium; wait for market confirmation near 0.2707 resistance.",
        "15m ADX 39 and 1h ADX 29 are strong but not price levels.",
    ]

    support, resistance, extracted = _extract_levels_from_texts(
        texts,
        current_price=Decimal("0.27145"),
        structured_support=Decimal("0.2618"),
        structured_resistance=Decimal("0.2690"),
    )

    values = {item["value"] for item in extracted}
    assert resistance == Decimal("0.2707")
    assert "0.2707" in values
    assert "72.2" not in values
    assert "39" not in values
    assert "29" not in values
    assert len([item for item in extracted if item["value"] == "0.2707"]) == 1


def test_b63_build_watchlist_prefers_plausible_text_resistance_over_low_feature_resistance():
    analysis = {
        "entry_gate": {
            "decision": "watch",
            "priority": "normal",
            "confidence": 52,
            "setup_type": "unclear",
            "reasons": [
                "Price is pressing into nearby resistance (1h Donchian20 high ~2299.52 / current ~2305.81), increasing risk of rejection/false breakout on entry.",
                "Short-term momentum exists (15m RSI~74, higher highs) but also suggests overextension/mean-reversion risk.",
            ],
            "warnings": [
                "Orderbook: bid-heavy but best-bid top liquidity is thin (top bid size ~0.72 vs top ask size ~4.22).",
            ],
        },
        "judge": {
            "decision": "wait",
            "confidence": 52,
            "strategy": "entry_gate_watch",
            "reasons": ["new_entry_filtered_by_deepseek_gate"],
        },
    }
    feature_pack = {
        "current_price": "2305.805",
        "nearest_support": "2237.1918428192166",
        "nearest_resistance": "2286.821157180784",
    }

    intent = build_watchlist_intent_from_analysis(
        cfg=DummyConfig(),
        ticker="ETH-USDC",
        analysis=analysis,
        feature_pack=feature_pack,
        cycle_source="test",
    )

    assert intent is not None
    assert Decimal(intent["trigger_price"]) >= Decimal("2299.52")
    extracted = intent["level_extraction"]["diagnostics"]["extracted_text_levels"]
    values = {item["value"] for item in extracted}
    assert "74" not in values
    assert "4.22" not in values
    assert intent["paper_only"] is True
    assert intent["live_order_submitted"] is False
    assert intent["requires_fresh_judge_and_risk"] is True


def test_b63_trigger_ready_is_less_eager_when_text_resistance_is_higher():
    analysis = {
        "entry_gate": {
            "decision": "analyze",
            "confidence": 58,
            "setup_type": "trend_continuation",
            "reasons": [
                "Short-term structure is bullish and price is pushing toward 1h Donchian20 high/resistance at 10.658.",
                "Setup is late/near resistance with overbought signals (15m RSI 81, 1h RSI 67.5).",
            ],
        },
        "judge": {"decision": "wait", "confidence": 58, "strategy": "mini_analysis_screened_no_expensive_judge"},
    }
    feature_pack = {
        "current_price": "10.50",
        "nearest_support": "10.03",
        "nearest_resistance": "10.485",
    }
    intent = build_watchlist_intent_from_analysis(
        cfg=DummyConfig(),
        ticker="LINK-USDC",
        analysis=analysis,
        feature_pack=feature_pack,
        cycle_source="test",
    )

    assert intent is not None
    assert intent["trigger_price"] == "10.658"
    waiting = evaluate_pending_intent(intent, {"current_price": "10.50"})
    assert waiting["status"] == "waiting"
    assert waiting["trigger_ready"] is False
    ready = evaluate_pending_intent(intent, {"current_price": "10.67"})
    assert ready["status"] == "trigger_ready"
    assert ready["should_force_full_analysis"] is True
