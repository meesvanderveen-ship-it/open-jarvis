from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_c43_one_entry_smoke_test import (
    C43_ONE_ENTRY_SMOKE_ACK,
    assess_c43_smoke_preconditions,
    extract_product_rules,
    run_c43_one_live_entry_smoke_test,
)


def cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_d3_actual_exit_submit=False,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c_allowed_tickers=["BTC-USDC", "SUI-USDC"],
        phase_c_max_order_quote="25.00",
        phase_c_max_open_entry_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_disable_exit_limit_orders=True,
        phase_c_live_order_post_only=True,
        autonomous_max_order_quote="25.00",
        autonomous_max_open_orders=4,
        autonomous_max_new_orders_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=True,
        autonomous_allow_exits=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeCoinbaseClient:
    def __init__(self):
        self.orders = []

    def submit_limit_buy_order(self, ticker, quote_size, base_size, limit_price, client_order_id=None, post_only=True):
        self.orders.append({
            "ticker": ticker,
            "side": "BUY",
            "base_size": str(base_size),
            "limit_price": str(limit_price),
            "client_order_id": client_order_id,
            "post_only": post_only,
        })
        return {"success": True, "success_response": {"order_id": "cb-smoke-1", "client_order_id": client_order_id}}


def test_preconditions_block_when_replication_enabled(monkeypatch):
    monkeypatch.setenv("REPLICATION_ENABLED", "true")
    result = assess_c43_smoke_preconditions(
        cfg=cfg(),
        ticker="BTC-USDC",
        quote_size=Decimal("20.00"),
        limit_price=Decimal("50000"),
        submit_live=True,
        human_ack=C43_ONE_ENTRY_SMOKE_ACK,
    )
    assert result["accepted"] is False
    assert "replication_enabled_forbidden_for_master_only_smoke" in result["blockers"]


def test_preconditions_require_ack_for_submit(monkeypatch):
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    result = assess_c43_smoke_preconditions(
        cfg=cfg(),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("50000"),
        submit_live=True,
        human_ack="wrong",
    )
    assert result["accepted"] is False
    assert "human_ack_missing_or_wrong" in result["blockers"]


def test_smoke_preview_never_submits(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    client = FakeCoinbaseClient()
    result = run_c43_one_live_entry_smoke_test(
        cfg=cfg(),
        ticker="BTC-USDC",
        quote_size=Decimal("10.00"),
        limit_price=Decimal("50000"),
        submit_live=False,
        human_ack="",
        coinbase_client=client,
        order_store=store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )
    assert result["live_order_submitted"] is False
    assert client.orders == []
    assert (tmp_path / "phase_c_live_submit.jsonl").exists()


def test_smoke_submit_request_is_retired_without_coinbase_call(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    client = FakeCoinbaseClient()
    result = run_c43_one_live_entry_smoke_test(
        cfg=cfg(),
        ticker="BTC-USDC",
        quote_size=Decimal("20.00"),
        limit_price=Decimal("50000"),
        submit_live=True,
        human_ack=C43_ONE_ENTRY_SMOKE_ACK,
        coinbase_client=client,
        order_store=store,
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1.00"},
        audit_path=tmp_path / "phase_c_live_submit.jsonl",
    )
    assert result["live_order_submitted"] is False
    assert result["live_submission_attempted"] is False
    assert result["status"] == "smoke_blocked"
    assert "manual_c43_smoke_live_submit_retired_use_canonical_strategy_workflow" in result["preflight"]["blockers"]
    assert client.orders == []
    assert store.open_entry_orders("BTC-USDC") == []


def test_extract_product_rules_accepts_coinbase_names():
    rules = extract_product_rules({
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "base_min_size": "0.00000001",
        "quote_min_size": "1.00",
    })
    assert rules["base_increment"] == "0.00000001"
    assert rules["quote_increment"] == "0.01"
