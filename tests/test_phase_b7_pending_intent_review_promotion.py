from pathlib import Path
import tempfile

from bot.pending_order_intents import (
    PendingOrderIntentStore,
    build_pending_order_intent_context,
    build_watchlist_intent_from_analysis,
)


class DummyConfig:
    enable_paper_watchlist_intents_from_gate_watch = True
    paper_pending_intent_min_gate_confidence = 50
    paper_pending_intent_ttl_hours = 12


def _feature_pack(price="10.50"):
    return {
        "current_price": price,
        "nearest_support": "10.00",
        "nearest_resistance": "10.65",
    }


def _analysis():
    return {
        "entry_gate": {
            "decision": "watch",
            "confidence": 58,
            "setup_type": "trend_continuation",
            "reasons": ["Price is near resistance 10.65 and needs acceptance above 10.65."],
        },
        "judge": {"decision": "wait", "confidence": 58, "strategy": "entry_gate_watch"},
    }


def test_b7_trigger_marks_needs_fresh_analysis_without_order_permission():
    intent = build_watchlist_intent_from_analysis(
        cfg=DummyConfig(),
        ticker="LINK-USDC",
        analysis=_analysis(),
        feature_pack=_feature_pack("10.50"),
        cycle_source="test",
    )
    assert intent is not None

    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(path=Path(td) / "pending.json", log_path=Path(td) / "events.jsonl")
        stored = store.store_intent(intent)
        assert stored is not None

        review = store.evaluate_intents(
            {"LINK-USDC": _feature_pack("10.70")},
            mark_needs_fresh_analysis=True,
        )
        assert review["reviewed"] == 1
        actions = review["actions"]
        assert actions[0]["evaluation"]["status"] == "needs_fresh_analysis"
        assert actions[0]["evaluation"]["trigger_ready"] is True
        assert actions[0]["evaluation"]["should_force_full_analysis"] is True

        ctx = store.context_for_ticker("LINK-USDC")
        assert ctx["status"] == "needs_fresh_analysis"
        assert ctx["should_force_full_analysis"] is True
        assert ctx["requires_fresh_judge_and_risk"] is True
        assert "never_authorizes_execution" in ctx["safety_policy"]
        summary = store.summary()
        assert summary["by_status"].get("needs_fresh_analysis") == 1
        assert summary["active_intents"] == 1
        assert summary["trigger_ready"] == []
        assert summary["needs_fresh_analysis"][0]["ticker"] == "LINK-USDC"
        assert summary["promotion_ready"][0]["ticker"] == "LINK-USDC"


def test_b7_missing_feature_pack_marks_stale_but_not_final():
    intent = build_watchlist_intent_from_analysis(
        cfg=DummyConfig(),
        ticker="AVAX-USDC",
        analysis=_analysis(),
        feature_pack=_feature_pack("10.50"),
        cycle_source="test",
    )
    assert intent is not None

    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(path=Path(td) / "pending.json", log_path=Path(td) / "events.jsonl")
        store.store_intent(intent)
        review = store.evaluate_intents({}, mark_needs_fresh_analysis=True)
        assert review["reviewed"] == 1
        assert review["actions"][0]["evaluation"]["status"] == "stale"
        assert review["actions"][0]["evaluation"]["should_force_full_analysis"] is False
        ctx = build_pending_order_intent_context("AVAX-USDC", store.active_intents("AVAX-USDC"))
        assert ctx["status"] == "stale"
        assert ctx["has_active_intent"] is True
