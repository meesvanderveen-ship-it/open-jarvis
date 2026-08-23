from pathlib import Path
import tempfile

from bot.pending_order_intents import PendingOrderIntentStore, build_watchlist_intent_from_analysis


class DummyConfig:
    enable_paper_watchlist_intents_from_gate_watch = True
    paper_pending_intent_min_gate_confidence = 50
    paper_pending_intent_ttl_hours = 12


def _analysis(confidence=58):
    return {
        "entry_gate": {
            "decision": "analyze",
            "confidence": confidence,
            "setup_type": "trend_continuation",
            "reasons": ["Price is near 1h Donchian resistance 10.65 and needs acceptance above 10.65."],
        },
        "judge": {"decision": "wait", "confidence": confidence, "strategy": "entry_gate_watch"},
    }


def _feature_pack(price="10.50", resistance="10.65"):
    return {
        "current_price": price,
        "nearest_support": "10.00",
        "nearest_resistance": resistance,
    }


def test_b71_summary_excludes_replaced_trigger_ready_intents():
    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(path=Path(td) / "pending.json", log_path=Path(td) / "events.jsonl")

        first = build_watchlist_intent_from_analysis(
            cfg=DummyConfig(),
            ticker="LINK-USDC",
            analysis=_analysis(),
            feature_pack=_feature_pack("10.50", "10.65"),
            cycle_source="test",
        )
        assert first is not None
        store.store_intent(first)
        review = store.evaluate_intents({"LINK-USDC": _feature_pack("10.70", "10.65")}, mark_needs_fresh_analysis=True)
        assert review["actions"][0]["evaluation"]["status"] == "needs_fresh_analysis"

        # Storing a new same-ticker intent replaces the old promotion-ready one.
        second = build_watchlist_intent_from_analysis(
            cfg=DummyConfig(),
            ticker="LINK-USDC",
            analysis=_analysis(),
            feature_pack=_feature_pack("10.40", "10.85"),
            cycle_source="test",
        )
        assert second is not None
        store.store_intent(second)

        summary = store.summary()
        assert summary["by_status"].get("replaced") == 1
        assert summary["active_intents"] == 1
        assert summary["open_intents"] == 1
        assert summary["by_active_status"].get("active") == 1
        assert summary["trigger_ready"] == []
        assert summary["needs_fresh_analysis"] == []
        assert summary["promotion_ready"] == []


def test_b71_summary_shows_only_current_needs_fresh_analysis():
    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(path=Path(td) / "pending.json", log_path=Path(td) / "events.jsonl")
        intent = build_watchlist_intent_from_analysis(
            cfg=DummyConfig(),
            ticker="XRP-USDC",
            analysis=_analysis(),
            feature_pack=_feature_pack("10.50", "10.65"),
            cycle_source="test",
        )
        assert intent is not None
        store.store_intent(intent)
        store.evaluate_intents({"XRP-USDC": {"current_price": "10.70", "nearest_support": "10.00", "nearest_resistance": "10.65"}}, mark_needs_fresh_analysis=True)

        summary = store.summary()
        assert summary["active_intents"] == 1
        assert summary["by_active_status"] == {"needs_fresh_analysis": 1}
        assert summary["needs_fresh_analysis"][0]["ticker"] == "XRP-USDC"
        assert summary["promotion_ready"][0]["ticker"] == "XRP-USDC"
        assert summary["trigger_ready"] == []
        assert summary["needs_fresh_analysis"][0]["requires_fresh_judge_and_risk"] is True
