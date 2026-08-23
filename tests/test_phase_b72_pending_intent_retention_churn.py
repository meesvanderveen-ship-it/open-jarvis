from pathlib import Path
import tempfile

from bot.pending_order_intents import PendingOrderIntentStore, build_watchlist_intent_from_analysis


class DummyConfig:
    enable_paper_watchlist_intents_from_gate_watch = True
    paper_pending_intent_min_gate_confidence = 50
    paper_pending_intent_ttl_hours = 12


def _analysis(confidence=58, resistance="10.65"):
    return {
        "entry_gate": {
            "decision": "analyze",
            "confidence": confidence,
            "setup_type": "trend_continuation",
            "reasons": [f"Price is near 1h Donchian resistance {resistance} and needs acceptance above {resistance}."],
        },
        "judge": {"decision": "wait", "confidence": confidence, "strategy": "entry_gate_watch"},
    }


def _feature_pack(price="10.50", support="10.00", resistance="10.65"):
    return {
        "current_price": price,
        "nearest_support": support,
        "nearest_resistance": resistance,
    }


def _intent(resistance="10.65", price="10.50"):
    item = build_watchlist_intent_from_analysis(
        cfg=DummyConfig(),
        ticker="LINK-USDC",
        analysis=_analysis(resistance=resistance),
        feature_pack=_feature_pack(price=price, resistance=resistance),
        cycle_source="test",
    )
    assert item is not None
    return item


def test_b72_similar_active_intent_is_refreshed_not_replaced():
    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(
            path=Path(td) / "pending.json",
            log_path=Path(td) / "events.jsonl",
            enable_dedupe_refresh=True,
            dedupe_tolerance_pct="0.0050",
        )
        first = store.store_intent(_intent("10.650", "10.500"))
        second = store.store_intent(_intent("10.651", "10.501"))

        assert first is not None
        assert second is not None
        assert second["intent_id"] == first["intent_id"]
        assert second["status"] == "active"
        assert second["refresh_count"] == 1
        summary = store.summary()
        assert summary["total_intents"] == 1
        assert summary["by_status"] == {"active": 1}
        assert summary["retention"]["enable_dedupe_refresh"] is True


def test_b72_promotion_ready_intent_is_not_deduped_or_downgraded():
    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(
            path=Path(td) / "pending.json",
            log_path=Path(td) / "events.jsonl",
            enable_dedupe_refresh=True,
            dedupe_tolerance_pct="0.0050",
        )
        first = store.store_intent(_intent("10.650", "10.500"))
        assert first is not None
        review = store.evaluate_intents({"LINK-USDC": _feature_pack(price="10.70", resistance="10.65")}, mark_needs_fresh_analysis=True)
        assert review["actions"][0]["evaluation"]["status"] == "needs_fresh_analysis"

        replacement = store.store_intent(_intent("10.651", "10.501"))
        assert replacement is not None
        assert replacement["intent_id"] != first["intent_id"]
        summary = store.summary()
        assert summary["by_status"].get("replaced") == 1
        assert summary["by_status"].get("active") == 1
        assert summary["needs_fresh_analysis"] == []
        assert summary["promotion_ready"] == []


def test_b72_retention_keeps_only_recent_replaced_per_ticker():
    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(
            path=Path(td) / "pending.json",
            log_path=Path(td) / "events.jsonl",
            max_replaced_per_ticker=2,
            enable_dedupe_refresh=False,
        )
        for idx, resistance in enumerate(["10.60", "10.70", "10.80", "10.90", "11.00"]):
            stored = store.store_intent(_intent(resistance=resistance, price=str(10.0 + idx / 100)))
            assert stored is not None

        summary = store.summary()
        assert summary["by_status"].get("active") == 1
        assert summary["by_status"].get("replaced") == 2
        assert summary["retention"]["replaced_by_ticker"].get("LINK-USDC") == 2
        assert summary["total_intents"] == 3
