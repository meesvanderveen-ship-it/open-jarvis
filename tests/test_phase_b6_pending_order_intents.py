from pathlib import Path
import tempfile

from bot.config import BotConfig
from bot.pending_order_intents import (
    PendingOrderIntentStore,
    build_pending_intent_from_execution_plan,
    build_watchlist_intent_from_analysis,
)


def feature_pack(price="100"):
    return {
        "market": {"mid_price": price, "price": price},
        "structure": {"nearest_support": "98", "nearest_resistance": "105"},
        "orderbook_context": {"best_bid": "99", "best_ask": "101", "mid_price": price},
    }


def analysis():
    return {
        "feature_pack": feature_pack("100"),
        "entry_gate": {"decision": "watch", "confidence": 64, "setup_type": "reclaim", "reasons": ["watch"]},
        "judge": {"decision": "wait", "confidence": 64},
        "trade_plan": {
            "plan_action": "prepare_reclaim",
            "entry_zone_low": "99",
            "entry_zone_high": "101",
            "trigger_price": "101",
            "stop_loss": "97",
            "do_not_chase_above": "106",
            "confidence": 66,
        },
    }


def test_pending_plan_only_intent_is_not_order_and_can_trigger():
    cfg = BotConfig()
    plan = build_pending_intent_from_execution_plan(
        cfg=cfg,
        ticker="TEST-B6-USDC",
        analysis=analysis(),
        execution_plan={"execution_action": "pending_plan_only", "expiry_hours": 6, "reason": "test"},
        feature_pack=feature_pack("100"),
    )
    assert plan is not None
    assert plan["side"] == "NONE"
    assert plan["live_order_submitted"] is False
    assert plan["requires_fresh_judge_and_risk"] is True

    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(path=Path(td) / "pending.json", log_path=Path(td) / "events.jsonl")
        stored = store.store_intent(plan)
        assert stored is not None
        review = store.evaluate_intents({"TEST-B6-USDC": feature_pack("100")})
        assert review["reviewed"] == 1
        assert store.summary()["by_status"].get("trigger_ready") == 1


def test_watchlist_intent_from_gate_watch_replaces_same_ticker():
    cfg = BotConfig()
    watch = build_watchlist_intent_from_analysis(
        cfg=cfg,
        ticker="TEST-B6B-USDC",
        analysis=analysis(),
        feature_pack=feature_pack("100"),
    )
    assert watch is not None
    assert watch["order_type"] == "watchlist_pending_intent"

    with tempfile.TemporaryDirectory() as td:
        store = PendingOrderIntentStore(path=Path(td) / "pending.json", log_path=Path(td) / "events.jsonl", enable_dedupe_refresh=False)
        first = store.store_intent({**watch, "intent_id": "one"})
        second = store.store_intent({**watch, "intent_id": "two"})
        assert first is not None and second is not None
        summary = store.summary()
        assert summary["by_status"].get("replaced") == 1
        assert summary["active_intents"] == 1
