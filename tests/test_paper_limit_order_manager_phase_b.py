from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_lifecycle import evaluate_paper_order_lifecycle
from bot.order_store import OrderStore
from bot.order_plan import build_order_intent_from_execution_plan


@dataclass
class DummyConfig:
    enable_limit_order_manager: bool = True
    enable_live_limit_orders: bool = False
    enable_live_entry_orders: bool = False
    enable_live_exit_orders: bool = False
    order_store_max_records: int = 100


def _feature_pack(best_bid="99", best_ask="101", mid="100"):
    return {
        "market": {"mid_price": mid, "best_bid": best_bid, "best_ask": best_ask},
        "orderbook_context": {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid},
    }


def _analysis():
    return {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": 50, "confidence": 72},
        "trade_plan": {
            "plan_action": "prepare_reclaim",
            "entry_zone_low": 98,
            "entry_zone_high": 100,
            "do_not_chase_above": 102,
            "stop_loss": 95,
            "invalidation": "Below 95",
            "take_profit_1": 110,
        },
    }


def _execution_plan(action="place_limit_buy", expiry=6):
    return {
        "execution_action": action,
        "data_sufficiency": "sufficient",
        "execution_quality_score": 75,
        "fill_probability_estimate": "medium",
        "adverse_selection_risk": "low",
        "expiry_hours": expiry,
        "expiry_reason": "test expiry",
        "cancel_if": ["breaks invalidation"],
        "replace_if": ["spread improves"],
        "reason": "test plan",
    }


def test_order_intent_builds_limit_buy_from_trade_plan():
    intent = build_order_intent_from_execution_plan(
        cfg=DummyConfig(),
        ticker="ETH-USDC",
        analysis=_analysis(),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(),
    )
    assert intent["status"] == "planned"
    assert intent["side"] == "BUY"
    assert intent["order_type"] == "limit"
    assert Decimal(intent["limit_price"]) == Decimal("99")
    assert Decimal(intent["size_quote"]) == Decimal("50")
    assert intent["paper_only"] is True
    assert intent["live_order_submitted"] is False


def test_paper_manager_submits_to_store_without_live_order(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    manager = PaperLimitOrderManager(cfg=DummyConfig(), order_store=store)
    result = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_analysis(),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(),
    )
    assert result["status"] == "paper_order_submitted"
    assert len(store.open_orders("ETH-USDC")) == 1
    order = store.open_orders("ETH-USDC")[0]
    assert order["coinbase_order_id"] is None
    assert order["live_order_submitted"] is False


def test_paper_lifecycle_fills_buy_when_best_ask_crosses_limit():
    order = {
        "client_order_id": "paper-test",
        "ticker": "ETH-USDC",
        "side": "BUY",
        "status": "submitted",
        "limit_price": "100",
        "size_base": "0.5",
        "size_quote": "50",
        "expires_at": "2099-01-01T00:00:00+00:00",
        "invalidation_price": "95",
    }
    evaluation = evaluate_paper_order_lifecycle(order, _feature_pack(best_bid="99", best_ask="100", mid="99.5"))
    assert evaluation["action"] == "fill"
    assert evaluation["status"] == "filled"


def test_paper_manager_refuses_when_live_flags_are_enabled(tmp_path):
    cfg = DummyConfig(enable_live_limit_orders=True)
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    manager = PaperLimitOrderManager(cfg=cfg, order_store=store)
    assert manager.enabled() is False
    result = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_analysis(),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(),
    )
    assert result is None
    assert store.open_orders() == []
