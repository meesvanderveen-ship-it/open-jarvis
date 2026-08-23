from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from bot.limit_order_manager import PaperLimitOrderManager
from bot.order_store import OrderStore
from bot.order_plan import build_order_intent_from_execution_plan


@dataclass
class DummyConfig:
    enable_limit_order_manager: bool = True
    enable_live_limit_orders: bool = False
    enable_live_entry_orders: bool = False
    enable_live_exit_orders: bool = False
    enable_paper_reserved_balance_checks: bool = True
    enable_paper_order_budget_enforcement: bool = True
    max_order_actions_per_cycle: int = 5
    max_new_orders_per_cycle: int = 2
    max_cancels_per_cycle: int = 3
    max_replaces_per_cycle: int = 2
    max_open_paper_orders_total: int = 3
    max_open_paper_entry_orders_per_ticker: int = 1
    max_open_paper_exit_orders_per_ticker: int = 2
    order_store_max_records: int = 100


def _feature_pack(best_bid="99", best_ask="101", mid="100", available_quote="100", available_base="1"):
    return {
        "market": {"mid_price": mid, "best_bid": best_bid, "best_ask": best_ask},
        "orderbook_context": {"best_bid": best_bid, "best_ask": best_ask, "mid_price": mid},
        "risk_context": {
            "available_quote_balance": available_quote,
            "available_base_balance": available_base,
        },
    }


def _buy_analysis(size_quote="50"):
    return {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": size_quote, "confidence": 72},
        "trade_plan": {
            "plan_action": "prepare_reclaim",
            "entry_zone_low": 98,
            "entry_zone_high": 100,
            "do_not_chase_above": 102,
            "stop_loss": 95,
            "take_profit_1": 110,
        },
    }


def _sell_analysis():
    return {
        "judge": {"decision": "reduce_size", "side": "SELL", "confidence": 70},
        "trade_plan": {"take_profit_1": 100, "take_profit_2": 105, "stop_loss": 90},
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


def test_order_store_available_quote_after_reserved_orders(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    order = build_order_intent_from_execution_plan(
        cfg=DummyConfig(),
        ticker="ETH-USDC",
        analysis=_buy_analysis(size_quote="60"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    order["status"] = "submitted"
    store.upsert_order(order)
    assert Decimal(store.total_reserved_quote()) == Decimal("60")
    assert Decimal(store.available_quote_after_reserved_orders("100")) == Decimal("40")


def test_paper_manager_rejects_duplicate_entry_order(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    manager = PaperLimitOrderManager(cfg=DummyConfig(), order_store=store)
    manager.begin_cycle("test")
    first = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_buy_analysis(size_quote="30"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    second = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_buy_analysis(size_quote="30"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    assert first["status"] == "paper_order_submitted"
    assert second["status"] == "paper_order_phase_b4_rejected"
    reasons = second["intent"]["risk_check_result"]["phase_b4_paper_rails"]["reject_reasons"]
    assert "duplicate_open_paper_entry_order" in reasons or "max_open_paper_entry_orders_per_ticker_reached" in reasons


def test_paper_manager_rejects_buy_when_reserved_quote_exhausts_balance(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    cfg = DummyConfig(max_open_paper_entry_orders_per_ticker=2, max_new_orders_per_cycle=5)
    manager = PaperLimitOrderManager(cfg=cfg, order_store=store)
    manager.begin_cycle("test")
    first = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_buy_analysis(size_quote="80"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    second = manager.maybe_create_order_from_execution_plan(
        ticker="BTC-USDC",
        analysis=_buy_analysis(size_quote="30"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    assert first["status"] == "paper_order_submitted"
    assert second["status"] == "paper_order_phase_b4_rejected"
    reasons = second["intent"]["risk_check_result"]["phase_b4_paper_rails"]["reject_reasons"]
    assert "paper_quote_balance_after_reserved_orders_insufficient" in reasons


def test_paper_new_order_budget_blocks_third_order(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    cfg = DummyConfig(max_new_orders_per_cycle=1, max_open_paper_entry_orders_per_ticker=10, max_open_paper_orders_total=10)
    manager = PaperLimitOrderManager(cfg=cfg, order_store=store)
    manager.begin_cycle("test")
    first = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_buy_analysis(size_quote="10"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    second = manager.maybe_create_order_from_execution_plan(
        ticker="BTC-USDC",
        analysis=_buy_analysis(size_quote="10"),
        execution_plan=_execution_plan(),
        feature_pack=_feature_pack(available_quote="100"),
    )
    assert first["status"] == "paper_order_submitted"
    assert second["status"] == "paper_order_budget_skipped"
    assert second["reason"] == "paper_new_order_budget_exhausted"


def test_paper_sell_reserves_base_balance(tmp_path):
    store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    cfg = DummyConfig(max_open_paper_exit_orders_per_ticker=2, max_new_orders_per_cycle=5)
    manager = PaperLimitOrderManager(cfg=cfg, order_store=store)
    manager.begin_cycle("test")
    position = {"position_id": "pos-1", "position_size_base": "1.0"}
    action = {"size_base": "0.8", "limit_price": "100"}
    first = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_sell_analysis(),
        execution_plan=_execution_plan(action="place_limit_sell_reduce"),
        feature_pack=_feature_pack(available_base="1"),
        existing_position=position,
        position_action=action,
    )
    second = manager.maybe_create_order_from_execution_plan(
        ticker="ETH-USDC",
        analysis=_sell_analysis(),
        execution_plan=_execution_plan(action="place_limit_sell_close"),
        feature_pack=_feature_pack(available_base="1"),
        existing_position={"position_id": "pos-2", "position_size_base": "0.5"},
        position_action={"size_base": "0.5", "limit_price": "100"},
    )
    assert first["status"] == "paper_order_submitted"
    assert second["status"] == "paper_order_phase_b4_rejected"
    reasons = second["intent"]["risk_check_result"]["phase_b4_paper_rails"]["reject_reasons"]
    assert "paper_base_balance_after_reserved_exit_orders_insufficient" in reasons
