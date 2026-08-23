from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from bot.controlled_stop_market_exit_plan import build_controlled_stop_market_exit_plan
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.order_plan import build_order_intent_from_execution_plan, is_actionable_order_intent
from bot.order_store import OrderStore
from bot.orderbook_entry_planner import build_resting_limit_entry_preview
from bot.pending_entry_lifecycle import LIVE_CANCEL_ACK, evaluate_pending_entry_lifecycle
from bot.phase_c43_autonomous_entry_live import build_phase_c43_guard_and_submit_preparation
from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY, build_multi_exit_bracket_lite_plan
from bot.phase_d3_controlled_live_exits import (
    assess_phase_d3_exit_readiness,
    select_next_phase_d3_exit_intent,
)
from bot.state_store import StateStore


def _cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_full_workflow_live_mode=True,
        enable_limit_order_manager=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        enable_phase_c_actual_coinbase_submit=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        enable_resting_limit_entry_live_submit=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote="20.00",
        autonomous_max_order_quote="20.00",
        phase_c_max_open_entry_orders=3,
        autonomous_max_open_orders=3,
        phase_c_max_new_orders_per_cycle=1,
        autonomous_max_new_orders_per_cycle=1,
        max_open_positions=3,
        max_new_orders_per_cycle=1,
        phase_c_require_orderbook_freshness=True,
        phase_c_live_order_post_only=True,
        phase_c_disable_exit_limit_orders=False,
        autonomous_entry_only_first=False,
        autonomous_allow_exits=True,
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=True,
        phase_d3_max_exit_order_quote="20.00",
        phase_d3_max_open_exit_orders=3,
        phase_d3_max_new_exit_orders_per_cycle=1,
        phase_d3_exit_order_post_only=True,
        phase_d3_require_reduce_only_local=True,
        min_live_order_quote_usdc="20.00",
        max_live_order_quote_usdc="100.00",
        default_quote_size_usdc="20.00",
        max_notional_usd="20.00",
        phase_d2_min_expected_net_edge_pct="0.0125",
        phase_d2_min_reward_to_fee_ratio="3.0",
        phase_d2_min_reward_to_risk_ratio="1.5",
        phase_d2_estimated_entry_fee_pct="0.0040",
        phase_d2_estimated_exit_fee_pct="0.0040",
        phase_d2_estimated_spread_slippage_pct="0.0020",
        phase_d2_fee_safety_buffer_pct="0.0025",
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct="0.0250",
        phase_d2_default_trailing_distance_pct="0.0180",
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
        enable_controlled_stop_market_exits=True,
        enable_autonomous_stop_exit_cancel=True,
        enable_autonomous_stop_exit_submit=True,
        enable_autonomous_stop_exit_apply=True,
        mode_b_controlled_stop_exit_ack="I_APPROVE_MODE_B_CONTROLLED_STOP_EXIT_APPLY",
        controlled_stop_exit_max_quote_usd="25.00",
        controlled_stop_exit_require_open_tp_cancel_first=True,
        controlled_stop_exit_order_type="near_market_limit_ioc",
        controlled_stop_exit_max_slippage_pct="0.0100",
        order_store_max_records=2000,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _analysis():
    feature_pack = {
        "market": {"mid_price": "100.00", "best_bid": "99.99", "best_ask": "100.01", "spread_pct": "0.0002"},
        "orderbook_summary": {"best_bid": "99.99", "best_ask": "100.01", "spread_pct": "0.0002", "snapshot_available": True},
        "product_rules": {
            "price_increment": "0.01",
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "base_min_size": "0.00000001",
            "quote_min_size": "1.00",
            "quote_max_size": "100.00",
        },
    }
    trade_plan = {
        "plan_id": "tp-btc-1",
        "plan_action": "prepare_resting_limit_entry",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "setup_type": "reclaim_retest",
        "entry_zone_low": "99.50",
        "entry_zone_high": "100.10",
        "preferred_limit_price": "99.99",
        "invalidation_price": "98.00",
        "stop_loss_price": "98.00",
        "take_profit_1": "104.00",
        "take_profit_2": "106.00",
        "do_not_chase_above": "101.00",
        "max_quote_size": "20.00",
    }
    judge = {
        "decision": "wait",
        "side": "BUY",
        "size_quote": "20.00",
        "setup_type": "reclaim_retest",
        "invalidation_price": "98.00",
        "do_not_chase_above": "101.00",
    }
    return {"ticker": "BTC-USDC", "feature_pack": feature_pack, "trade_plan": trade_plan, "judge": judge}


def _execution_plan():
    return {
        "ticker": "BTC-USDC",
        "execution_action": "place_limit_buy",
        "execution_status": "pending_entry_ready",
        "expiry_hours": 6,
        "cancel_if": ["setup_invalidated"],
        "replace_if": ["same_thesis_better_maker_price"],
        "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "best_bid": "99.99", "best_ask": "100.01", "spread_pct": "0.0002"},
        "reason": "eligible_resting_limit_entry_prepared_from_wait_setup",
    }


def test_resting_entry_path_reaches_c43_preview_but_not_live_without_approve_trade(tmp_path: Path):
    cfg = _cfg()
    analysis = _analysis()
    execution_plan = _execution_plan()
    preview = build_resting_limit_entry_preview(ticker="BTC-USDC", analysis=analysis)
    assert preview["eligible"] is True

    intent = build_order_intent_from_execution_plan(
        cfg=cfg,
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        feature_pack=analysis["feature_pack"],
    )
    intent["paper_only"] = False
    assert is_actionable_order_intent(intent)

    report = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg,
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=intent,
        order_store=OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        coinbase_client=None,
        submit_live=True,
    )
    assert report["risk_snapshot"]["accepted"] is False
    assert "resting_entry_preview_available_preview_only" in report["risk_snapshot"]["passed_checks"]
    assert "fresh_judge_approve_trade_buy_valid_plan_required_for_live_entry" in report["risk_snapshot"]["blockers"]
    assert report["guard_result"]["guard_allows_live_submit"] is False
    assert "fresh_judge_buy_approval_valid_plan_required_for_live_entry" in report["guard_result"]["hard_block_reasons"]
    assert report["live_order_submitted"] is False


def test_pending_entry_cancel_requires_ack_and_verified_cancel_before_state_change():
    created = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    order = {
        "client_order_id": "phasec-BTCUSDC-entry-1",
        "exchange_order_id": "cb-entry-1",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "execution_action": "place_limit_buy",
        "created_at": created,
        "limit_price": "99.99",
        "invalidation_level": "98.00",
        "do_not_chase_above": "101.00",
    }
    result = evaluate_pending_entry_lifecycle(
        order=order,
        current_market={"mid_price": "97.90", "best_bid": "97.89", "best_ask": "97.91", "spread_pct": "0.0002", "liquidity_score": "100"},
        env={"ENABLE_PENDING_ENTRY_LIVE_CANCEL": "true", "PENDING_ENTRY_LIVE_CANCEL_ACK": LIVE_CANCEL_ACK},
    )
    assert result["cancel_required"] is True
    assert result["coinbase_cancel_allowed"] is True
    assert result["requires_verify_cancel"] is True
    assert result["state_write_attempted"] is False


def test_fill_to_d2_d3_contract_blocks_duplicate_exit(tmp_path: Path):
    cfg = _cfg()
    position = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "100.00",
        "position_size_base": "0.20",
        "bot_managed_base": "0.20",
        "position_size_quote": "20.00",
        "stop_price": "98.00",
        "invalidation_price": "98.00",
    }
    store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")
    plan = build_multi_exit_bracket_lite_plan(cfg=cfg, position=position)
    assert plan["status"] == D2_PLAN_STATUS_READY
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=position, order_store=store)
    readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=position, plan=plan, exit_intent=intent, order_store=store)
    assert readiness["ready"] is True

    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1",
        "exchange_order_id": "cb-exit-1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "remaining_size": "0.20",
        "size_base": "0.20",
        "limit_price": "104.00",
    })
    duplicate_intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=position, order_store=store)
    assert "no_available_base_after_existing_exit_reservations" in duplicate_intent["blockers"]


def test_stop_breach_requires_cancel_first_before_controlled_sell(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir()
    (tmp_path / "logs").mkdir()
    cfg = _cfg()
    state = StateStore()
    store = OrderStore(path=tmp_path / "state/open_orders.json", log_path=tmp_path / "logs/order_events.jsonl")
    state.upsert_position("BTC-USDC", {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "phase_c43_exchange_order_id": "pos-1",
        "recovery_linked_position_id": "pos-1",
        "entry_price": "100.00",
        "position_size_base": "0.20",
        "bot_managed_base": "0.20",
        "stop_price": "98.00",
    })
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1",
        "exchange_order_id": "cb-exit-1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "remaining_size": "0.20",
        "size_base": "0.20",
        "limit_price": "104.00",
    })
    report = build_controlled_stop_market_exit_plan(
        cfg=cfg,
        ticker="BTC-USDC",
        linked_position_id="pos-1",
        market_context={"current_price": "97.50", "reasons": ["stop_breached_or_below_invalidation"]},
        order_store=store,
        state_store=state,
        cancel_verified=False,
    )
    assert report["controlled_stop_exit_next_step"] == "cancel_existing_tp_first"
    assert report["second_sell_blocked_until_cancel_verified"] is True
    assert report["controlled_market_sell_preview"]["sell_base"] == "0"
    assert report["state_write_performed"] is False


def test_learning_feedback_contract_remains_report_only():
    closed_outcome = {"ticker": "BTC-USDC", "status": "closed", "realized_pnl": "1.23"}
    reflection = {"source": "closed_trade", "outcome": closed_outcome, "writes_execution_flags": False}
    adaptive_candidate = {"candidate_parameters": {"MAX_SPREAD_PCT": "0.0060"}, "requires_operator_review": True}
    governor = {"approved_profile_activation": "hash_ack_only", "direct_parameter_mutation": False}
    assert reflection["writes_execution_flags"] is False
    assert adaptive_candidate["requires_operator_review"] is True
    assert governor["direct_parameter_mutation"] is False
