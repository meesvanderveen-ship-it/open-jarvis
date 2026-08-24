from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.atomic_io import process_lock
from bot.coinbase_order_snapshot import classify_coinbase_order_type
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import (
    _C43_LIFECYCLE_APPLY_AUTHORITY,
    _derive_entry_protective_levels,
    build_phase_c43_deterministic_live_risk_snapshot,
    build_phase_c43_guard_and_submit_preparation,
    reconcile_phase_c43_fills_to_positions,
)

PRODUCT_RULES = {"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"}


def cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        phase_c_allowed_tickers=["BTC-USDC", "SUI-USDC"],
        phase_c_max_order_quote="25.00",
        min_live_order_quote_usdc="20.00",
        max_live_order_quote_usdc="100.00",
        phase_c_max_open_entry_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_max_cancels_per_cycle=2,
        phase_c_max_replaces_per_cycle=1,
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
        autonomous_max_cancels_per_cycle=2,
        autonomous_max_replaces_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=True,
        autonomous_allow_exits=False,
        order_store_max_records=200,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def candidate():
    analysis = {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "25.00", "valid_trade_plan": True},
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "side": "BUY",
            "entry_zone_low": "49950.00",
            "entry_zone_high": "50050.00",
            "invalidation_price": "49000.00",
            "take_profit_1": "52000.00",
            "max_quote_size": "25.00",
            "trigger": "fresh reclaim ready",
        },
        "feature_pack": {
            "market": {
                "best_bid": "49999.00",
                "best_ask": "50001.00",
                "mid_price": "50000.00",
                "spread_pct": "0.00004",
            },
            "orderbook_context": {
                "snapshot_available": True,
                "best_bid": "49999.00",
                "best_ask": "50001.00",
                "mid_price": "50000.00",
            },
            "decision_context": {
                "product_rules": PRODUCT_RULES,
                "pending_order_intent": {
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                }
            }
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "read_only": True,
        "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.01"},
    }
    order_intent = {
        "ticker": "BTC-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "size_quote": "25.00",
        "limit_price": "50000",
        "intent_id": "intent-1",
        "product_rules": PRODUCT_RULES,
    }
    return analysis, execution_plan, order_intent


def resting_wait_candidate():
    analysis = {
        "judge": {
            "decision": "wait",
            "side": "NONE",
            "size_quote": "0",
            "trigger_wait_reason": "trigger_not_ready: wait for retest",
        },
        "trade_plan": {
            "plan_action": "prepare_reclaim_retest_limit_entry",
            "side": "BUY",
            "setup_type": "reclaim_retest",
            "entry_zone_low": "99.50",
            "entry_zone_high": "100.00",
            "do_not_chase_above": "100.80",
            "invalidation_price": "98.00",
            "stop_loss": "98.00",
            "take_profit_1": "104.00",
            "max_quote_size": "20.00",
            "trigger": "trigger_not_ready: wait for reclaim retest",
        },
        "feature_pack": {
            "market": {"best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75", "spread_pct": "0.0002"},
            "orderbook_context": {"snapshot_available": True, "best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75"},
            "decision_context": {"product_rules": PRODUCT_RULES, "recent_exchange_rejections": []},
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "read_only": True,
        "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.0002"},
        "plan_action": "prepare_reclaim_retest_limit_entry",
    }
    order_intent = {
        "ticker": "BTC-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": "20.00",
        "limit_price": "99.75",
        "intent_id": "intent-resting-1",
        "product_rules": PRODUCT_RULES,
    }
    return analysis, execution_plan, order_intent


class FakeCoinbaseClient:
    def __init__(self):
        self.orders = []

    def submit_limit_buy_order(self, ticker, quote_size, base_size, limit_price, client_order_id=None, post_only=True):
        self.orders.append({
            "ticker": ticker,
            "side": "BUY",
            "quote_size": str(quote_size),
            "base_size": str(base_size),
            "limit_price": str(limit_price),
            "client_order_id": client_order_id,
            "post_only": post_only,
        })
        return {"success": True, "order_id": "cb-order-1", "client_order_id": client_order_id}


class FakeStateStore:
    def __init__(self):
        self.created = []

    def create_position(self, **kwargs):
        self.created.append(kwargs)
        return {"status": "open", **kwargs}


def test_c43_risk_accepts_valid_small_buy():
    analysis, execution_plan, order_intent = candidate()
    risk = build_phase_c43_deterministic_live_risk_snapshot(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        product_rules=PRODUCT_RULES,
    )
    assert risk["accepted"] is True
    assert "quote_within_autonomous_cap" in risk["passed_checks"]


def test_coinbase_order_details_classify_limit_post_only_and_market_ioc():
    limit = classify_coinbase_order_type(
        {
            "order_type": "LIMIT",
            "time_in_force": "GOOD_UNTIL_CANCELLED",
            "order_configuration": {
                "limit_limit_gtc": {
                    "base_size": "0.01419647",
                    "limit_price": "1761.00",
                    "post_only": True,
                }
            },
        }
    )
    market = classify_coinbase_order_type(
        {
            "order_type": "MARKET",
            "order_configuration": {"market_market_ioc": {"quote_size": "25.00"}},
        }
    )
    assert limit["conclusion"] == "post_only_limit"
    assert limit["confidence"] == "high"
    assert limit["post_only"] is True
    assert market["conclusion"] == "market_order"
    assert market["order_configuration_keys"] == ["market_market_ioc"]


def test_c43_risk_blocks_quote_above_25():
    analysis, execution_plan, order_intent = candidate()
    order_intent["size_quote"] = "26.00"
    analysis["judge"]["size_quote"] = "26.00"
    risk = build_phase_c43_deterministic_live_risk_snapshot(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        product_rules=PRODUCT_RULES,
    )
    assert risk["accepted"] is False
    assert "quote_missing_or_above_autonomous_cap" in risk["blockers"]


def test_c43_preview_ready_resting_buy_is_preview_only_without_approve_trade():
    analysis, execution_plan, order_intent = resting_wait_candidate()
    risk = build_phase_c43_deterministic_live_risk_snapshot(
        cfg=cfg(phase_c_allowed_tickers=["BTC-USDC"]),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        product_rules=PRODUCT_RULES,
    )
    assert risk["accepted"] is False
    assert "resting_entry_preview_available_preview_only" in risk["passed_checks"]
    assert "fresh_judge_approve_trade_buy_valid_plan_required_for_live_entry" in risk["blockers"]
    assert risk["pending_entry_lifecycle_preview"]["entry_preview_eligible"] is True


def test_c43_resting_wait_submit_stays_off_without_resting_live_flag(tmp_path: Path, monkeypatch):
    lock_path = tmp_path / "runtime_mutation.lock"
    monkeypatch.setenv("RUN_TRADER_LOOP_LOCK_PATH", str(lock_path))
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = resting_wait_candidate()
    client = FakeCoinbaseClient()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(phase_c_allowed_tickers=["BTC-USDC"], enable_resting_limit_entry_live_submit=False),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=False,
        product_rules=PRODUCT_RULES,
    )
    assert result["status"] == "c43_autonomous_live_entry_blocked"
    assert result["live_submission_attempted"] is False
    assert client.orders == []
    assert "fresh_judge_approve_trade_buy_valid_plan_required_for_live_entry" in result["risk_snapshot"]["blockers"]
    assert not lock_path.exists()


def test_c43_submitter_submits_and_records_order_when_all_green(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    client = FakeCoinbaseClient()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )
    assert result["live_order_submitted"] is True
    assert client.orders
    open_orders = store.open_entry_orders("BTC-USDC")
    assert len(open_orders) == 1
    assert open_orders[0]["mode"] == "live"
    assert open_orders[0]["status"] == "submitted"
    assert open_orders[0]["exchange_order_id"] == "cb-order-1"
    assert client.orders[0]["side"] == "BUY"
    assert result["mutation_lock"] == {"acquired": True, "reentrant": False}


def test_c43_submit_reenters_runner_mutation_lock(tmp_path: Path, monkeypatch):
    lock_path = tmp_path / "runtime_mutation.lock"
    monkeypatch.setenv("RUN_TRADER_LOOP_LOCK_PATH", str(lock_path))
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    client = FakeCoinbaseClient()

    with process_lock(lock_path):
        result = build_phase_c43_guard_and_submit_preparation(
            cfg=cfg(),
            ticker="BTC-USDC",
            analysis=analysis,
            execution_plan=execution_plan,
            order_intent=order_intent,
            coinbase_client=client,
            order_store=store,
            submit_live=True,
            product_rules=PRODUCT_RULES,
        )

    assert result["live_order_submitted"] is True
    assert result["mutation_lock"] == {"acquired": True, "reentrant": True}
    assert len(client.orders) == 1


def test_c43_submitter_uses_quote_50_with_100_caps_and_keeps_rails(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    analysis["judge"]["size_quote"] = "50.00"
    order_intent["size_quote"] = "50.00"
    order_intent["limit_price"] = "100.00"
    client = FakeCoinbaseClient()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(
            phase_c_max_order_quote="100.00",
            autonomous_max_order_quote="100.00",
            phase_c_max_open_entry_orders=3,
            autonomous_max_open_orders=3,
            max_open_positions=3,
        ),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )
    assert result["live_order_submitted"] is True
    assert result["risk_snapshot"]["max_quote"] == "100.00"
    assert result["risk_snapshot"]["max_open_orders"] == 3
    assert result["risk_snapshot"]["max_new_orders_per_cycle"] == 1
    assert Decimal(client.orders[0]["base_size"]) == Decimal("0.5")
    assert store.open_entry_orders("BTC-USDC")[0]["size_quote"] == "50.00"


def test_c43_missing_client_limit_method_does_not_write_open_order(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=object(),
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert result["local_order_record"] is None
    assert "coinbase_limit_buy_submit_route_not_supported" in result["submit_result"]["hard_block_reasons"]
    assert store.open_entry_orders("BTC-USDC") == []


def test_c43_response_without_exchange_order_id_does_not_write_open_order(tmp_path: Path):
    class NoOrderIdClient:
        def submit_limit_buy_order(self, **kwargs):
            return {"success": True}

    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=NoOrderIdClient(),
        order_store=store,
        submit_live=True,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"},
    )
    assert result["live_submission_attempted"] is True
    assert result["live_order_submitted"] is False
    assert result["submit_result"]["status"] == "phase_c_live_order_submit_unconfirmed_no_order_id"
    assert store.open_entry_orders("BTC-USDC") == []


def test_c43_buy_fix_does_not_touch_sell_route(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    analysis["judge"]["side"] = "SELL"
    execution_plan["execution_action"] = "place_limit_sell_close"
    order_intent["side"] = "SELL"
    order_intent["execution_action"] = "place_limit_sell_close"
    client = FakeCoinbaseClient()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"},
    )
    assert result["live_order_submitted"] is False
    assert client.orders == []
    assert store.open_entry_orders("BTC-USDC") == []


def test_c43_submitter_does_not_submit_when_actual_submit_disabled(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    client = FakeCoinbaseClient()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(enable_phase_c_actual_coinbase_submit=False),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"},
    )
    assert result["live_order_submitted"] is False
    assert not client.orders


def test_c43_submitter_requires_externally_loaded_runtime_authority(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    client = FakeCoinbaseClient()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(phase_c43_runtime_submit_ack=""),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )

    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "phase_c43_runtime_submit_ack_missing_or_invalid" in result["submit_result"]["hard_block_reasons"]
    assert client.orders == []
    assert store.open_entry_orders("BTC-USDC") == []


def test_c43_reconcile_filled_order_opens_position(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-test",
        "exchange_order_id": "cb-order-1",
        "order_id": "cb-order-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "limit_price": "50000",
    })
    state = FakeStateStore()
    report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-test",
            "order_id": "cb-order-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0005",
            "average_filled_price": "50000",
        }],
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )
    assert report["actions"][0]["action"] == "filled_to_position"
    assert state.created
    assert state.created[0]["ticker"] == "BTC-USDC"
    assert store.get_order("phasec-BTCUSDC-test")["status"] == "filled"


def test_c43_reconcile_filled_order_sets_setup_type_not_just_source_setup_type(tmp_path: Path):
    # position_manager._get_position_setup_type() reads position["setup_type"]
    # (not source_setup_type) to pick a trailing-stop tier. Before this fix,
    # only source_setup_type was ever written here, so every live position
    # silently used the generic "unclear" trailing tier regardless of its
    # real setup.
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-SOLUSDC-test",
        "exchange_order_id": "cb-order-2",
        "order_id": "cb-order-2",
        "ticker": "SOL-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "60.00",
        "size_base": "0.75",
        "limit_price": "80.00",
        "trade_plan_snapshot": {"setup_type": "reclaim_reversal"},
    })
    state = FakeStateStore()
    reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-SOLUSDC-test",
            "order_id": "cb-order-2",
            "product_id": "SOL-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.75",
            "average_filled_price": "80.00",
        }],
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )
    assert state.created
    assert state.created[0]["extra"]["setup_type"] == "reclaim_reversal"
    assert state.created[0]["extra"]["source_setup_type"] == "reclaim_reversal"


def test_c43_reconcile_new_fill_not_blocked_by_prior_closed_position_same_ticker(tmp_path: Path):
    # positions.json keeps a permanent record per ticker (not per trade): once a
    # position closes, its record stays under that ticker key with status="closed".
    # A fresh live fill on the same ticker under a *different* order id is a
    # legitimate re-entry, not an ambiguous double-open, and must not be blocked
    # just because a closed record happens to still occupy that ticker key.
    class ClosedPositionStateStore(FakeStateStore):
        def get_position(self, ticker):
            return {
                "ticker": ticker,
                "status": "closed",
                "order_id": "old-closed-order-id",
                "phase_c43_client_order_id": "phasec-SOLUSDC-old-closed",
                "phase_c43_exchange_order_id": "cb-order-old-closed",
                "close_reason": "d3_live_exit_order_filled_position_flattened",
            }

    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-SOLUSDC-new",
        "exchange_order_id": "cb-order-new",
        "order_id": "cb-order-new",
        "ticker": "SOL-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "113.78",
        "size_base": "1.41131232",
        "limit_price": "80.62",
    })
    state = ClosedPositionStateStore()
    report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-SOLUSDC-new",
            "order_id": "cb-order-new",
            "product_id": "SOL-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "1.41131232",
            "average_filled_price": "80.62",
        }],
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )
    assert report["actions"][0]["action"] == "filled_to_position"
    assert report["actions"][0]["position_transition"] == "created_from_fill"
    assert state.created
    assert store.get_order("phasec-SOLUSDC-new")["status"] == "filled"


def test_c43_reconcile_partial_fill_does_not_open_position(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-test",
        "exchange_order_id": "cb-order-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "size_quote": "25.00",
        "limit_price": "50000",
    })
    state = FakeStateStore()
    report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-test",
            "order_id": "cb-order-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "OPEN",
            "filled_size": "0.0001",
            "average_filled_price": "50000",
        }],
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )
    assert report["actions"][0]["action"] == "partial_fill_recorded"
    assert state.created == []
    assert store.get_order("phasec-BTCUSDC-test")["status"] == "partially_filled"


def test_c43_fill_preview_does_not_write_order_or_position(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-preview",
        "exchange_order_id": "cb-preview-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "limit_price": "50000",
    })
    state = FakeStateStore()

    report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-preview",
            "order_id": "cb-preview-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0005",
            "average_filled_price": "50000",
        }],
    )

    assert report["apply_local"] is False
    assert report["actions"][0]["action"] == "fill_to_position_proposed"
    assert state.created == []
    assert store.get_order("phasec-BTCUSDC-preview")["status"] == "submitted"


def test_direct_c43_apply_is_blocked_without_c44_authority(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-direct-block",
        "exchange_order_id": "cb-direct-block-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "limit_price": "50000",
    })
    state = FakeStateStore()

    report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=[{
            "client_order_id": "phasec-BTCUSDC-direct-block",
            "order_id": "cb-direct-block-1",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0005",
            "average_filled_price": "50000",
        }],
        apply_local=True,
    )

    assert report["status"] == "apply_local_blocked_requires_c44_lifecycle_orchestrator"
    assert report["authority_blockers"] == ["c43_local_apply_owned_by_c44_lifecycle_orchestrator"]
    assert state.created == []
    assert store.get_order("phasec-BTCUSDC-direct-block")["status"] == "submitted"


def test_c43_fill_recovers_after_crash_between_position_and_order_link(tmp_path: Path, monkeypatch):
    class RecoveryState:
        def __init__(self):
            self.positions = {}
            self.create_calls = 0

        def get_position(self, ticker):
            return self.positions.get(str(ticker).upper())

        def create_position(self, *, ticker, side, order_id, entry_price, position_size_base, position_size_quote, entry_reason="", extra=None):
            self.create_calls += 1
            position = {
                "ticker": str(ticker).upper(),
                "status": "open",
                "order_id": order_id,
                "position_size_base": position_size_base,
                **(extra or {}),
            }
            self.positions[str(ticker).upper()] = position
            return position

    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    client_order_id = "phasec-BTCUSDC-crash-recovery"
    exchange_order_id = "cb-crash-recovery-1"
    store.upsert_order({
        "client_order_id": client_order_id,
        "exchange_order_id": exchange_order_id,
        "order_id": exchange_order_id,
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "limit_price": "50000",
    })
    snapshot = [{
        "client_order_id": client_order_id,
        "order_id": exchange_order_id,
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "FILLED",
        "filled_size": "0.0005",
        "average_filled_price": "50000",
    }]
    state = RecoveryState()
    original_update = store.update_order

    monkeypatch.setattr(store, "update_order", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("fault_after_position_write")))
    with pytest.raises(RuntimeError, match="fault_after_position_write"):
        reconcile_phase_c43_fills_to_positions(
            cfg=cfg(),
            order_store=store,
            state_store=state,
            live_orders_snapshot=snapshot,
            apply_local=True,
            _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
        )

    assert state.create_calls == 1
    assert store.get_order(client_order_id)["status"] == "submitted"

    monkeypatch.setattr(store, "update_order", original_update)
    report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg(),
        order_store=store,
        state_store=state,
        live_orders_snapshot=snapshot,
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )

    assert state.create_calls == 1
    assert report["actions"][0]["position_transition"] == "recovered_existing_position"
    assert store.get_order(client_order_id)["status"] == "filled"
    assert store.get_order(client_order_id)["position_created"] is True

class FakeRejectCoinbaseClient:
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
        return {
            "success": False,
            "error_response": {
                "error": "INVALID_LIMIT_PRICE_POST_ONLY",
                "message": "Invalid limit price for post-only order",
                "preview_failure_reason": "PREVIEW_INVALID_LIMIT_PRICE_POST_ONLY",
            },
        }


def test_c43_submitter_records_coinbase_reject_as_final_not_open(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    client = FakeRejectCoinbaseClient()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"},
    )

    assert result["live_submission_attempted"] is True
    assert result["live_order_submitted"] is False
    assert result["status"] == "c43_autonomous_live_entry_attempted_not_submitted"
    assert result["submit_result"]["status"] == "phase_c_live_order_rejected_by_coinbase"
    assert result["local_order_record"]["status"] == "submit_rejected"
    assert result["local_order_record"]["remaining_quote"] == "0"
    assert result["local_order_record"]["remaining_size"] == "0"
    assert result["local_order_record"]["exchange_order_id"] == ""
    assert result["local_order_record"]["position_created"] is False
    assert store.open_entry_orders("BTC-USDC") == []
    assert store.final_orders("BTC-USDC")[0]["status"] == "submit_rejected"


def test_c43_blocks_live_submit_when_approve_trade_lacks_valid_plan(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    analysis["judge"]["valid_trade_plan"] = False
    analysis["trade_plan"]["valid_trade_plan"] = False
    client = FakeCoinbaseClient()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )

    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "fresh_judge_approve_trade_buy_valid_plan_required_for_live_entry" in result["risk_snapshot"]["blockers"]
    assert "blocked_valid_trade_plan_false" in result["risk_snapshot"]["blockers"]
    assert "fresh_judge_buy_approval_valid_plan_required_for_live_entry" in result["guard_result"]["hard_block_reasons"]
    assert client.orders == []


def test_c43_blocks_live_submit_when_valid_plan_is_string_false(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    analysis["judge"]["valid_trade_plan"] = "false"
    analysis["trade_plan"]["valid_trade_plan"] = "false"
    client = FakeCoinbaseClient()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )

    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "blocked_valid_trade_plan_false" in result["risk_snapshot"]["blockers"]
    assert "blocked_valid_trade_plan_false" in result["guard_result"]["hard_block_reasons"]
    assert client.orders == []


def test_c43_blocks_duplicate_same_ticker_open_live_entry_before_submit(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    store.upsert_order({
        "client_order_id": "phasec-BTCUSDC-existing",
        "exchange_order_id": "cb-existing-order",
        "order_id": "cb-existing-order",
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "mode": "live",
        "source_mode": "autonomous_small_live",
        "size_quote": "25.00",
        "size_base": "0.0005",
        "remaining_quote": "25.00",
        "remaining_size": "0.0005",
        "limit_price": "50000",
        "execution_action": "place_limit_buy",
    })
    analysis, execution_plan, order_intent = candidate()
    client = FakeCoinbaseClient()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(phase_c_max_open_entry_orders=4, autonomous_max_open_orders=4),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
    )

    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert result["submit_allowed_by_c43"] is False
    assert "duplicate_open_live_entry_order_same_ticker" in result["risk_snapshot"]["blockers"]
    assert result["risk_snapshot"]["open_live_entry_order_tickers"] == ["BTC-USDC"]
    assert client.orders == []
    assert len(store.open_entry_orders("BTC-USDC")) == 1


def test_c43_blocks_open_position_same_ticker_before_submit(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    analysis, execution_plan, order_intent = candidate()
    client = FakeCoinbaseClient()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
        open_positions=[{"ticker": "BTC-USDC", "status": "open", "position_size_base": "0.01"}],
    )

    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "blocked_open_position_same_ticker" in result["risk_snapshot"]["blockers"]
    assert "blocked_open_position_same_ticker" in result["guard_result"]["hard_block_reasons"]
    assert client.orders == []
    assert store.open_entry_orders("BTC-USDC") == []


def test_c43_live_open_order_record_requires_exchange_order_id(tmp_path: Path):
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")

    try:
        store.upsert_order({
            "client_order_id": "phasec-BTCUSDC-missing-exchange-id",
            "ticker": "BTC-USDC",
            "side": "BUY",
            "status": "submitted",
            "mode": "live",
            "source_mode": "autonomous_small_live",
            "size_quote": "25.00",
            "size_base": "0.0005",
            "limit_price": "50000",
        })
    except ValueError as exc:
        assert str(exc) == "live open order records require exchange_order_id"
    else:
        raise AssertionError("live open order without exchange_order_id should be rejected")


def test_derive_protective_levels_widens_stop_tighter_than_floor():
    # Real SOL-USDC example: entry 80.42, LLM stop 79.98 (~0.55% away) --
    # tighter than the 2% floor, so it must be widened, not accepted as-is.
    levels = _derive_entry_protective_levels(
        local_order={},
        trade_plan={"stop_loss": "79.98", "invalidation": "79.98"},
        entry_price="80.42",
        min_stop_distance_pct=Decimal("0.02"),
    )
    expected_floor = Decimal("80.42") * Decimal("0.98")
    assert Decimal(levels["stop_price"]) == expected_floor
    assert Decimal(levels["invalidation_price"]) == expected_floor
    assert levels["risk_state_complete"] is True
    assert levels["risk_source"] == "widened_to_minimum_stop_distance_floor"


def test_derive_protective_levels_leaves_already_wide_stop_untouched():
    levels = _derive_entry_protective_levels(
        local_order={},
        trade_plan={"stop_loss": "76.40", "invalidation": "76.40"},  # ~5% below entry
        entry_price="80.42",
        min_stop_distance_pct=Decimal("0.02"),
    )
    assert Decimal(levels["stop_price"]) == Decimal("76.40")
    assert levels["risk_source"] == "explicit_entry_risk"


def test_derive_protective_levels_floor_applies_on_top_of_missing_stop_fallback():
    # No usable candidate at all -> existing 2.5% conservative fallback fires
    # first; since 2.5% > 2% floor, the floor must not further widen it.
    levels = _derive_entry_protective_levels(
        local_order={},
        trade_plan={},
        entry_price="100.00",
        min_stop_distance_pct=Decimal("0.02"),
    )
    assert Decimal(levels["stop_price"]) == Decimal("97.500")
    assert levels["risk_source"] == "conservative_entry_fill_fallback"


def test_derive_protective_levels_zero_floor_is_a_no_op():
    levels = _derive_entry_protective_levels(
        local_order={},
        trade_plan={"stop_loss": "79.98", "invalidation": "79.98"},
        entry_price="80.42",
        min_stop_distance_pct=Decimal("0"),
    )
    assert Decimal(levels["stop_price"]) == Decimal("79.98")
    assert levels["risk_source"] == "explicit_entry_risk"
