from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.controlled_stop_market_exit_plan import build_controlled_stop_market_exit_plan
from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_VALUE
from bot.order_store import OrderStore
from bot.state_store import StateStore


def _state(tmp_path: Path, monkeypatch) -> StateStore:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(
        path=tmp_path / "state" / "open_orders.json",
        log_path=tmp_path / "logs" / "order_events.jsonl",
    )


def _seed_position(state: StateStore, **overrides) -> None:
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "recovery_linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "position_size_base": "0.00015416",
        "bot_managed_base": "0.00015416",
        "reserved_base_open_exit_orders": "0.00015416",
        "entry_price": "74100",
        "stop_price": "74100",
        "last_heartbeat_reason": "stop_breached_or_below_invalidation",
        "monitoring_enabled": True,
    }
    payload.update(overrides)
    state.upsert_position("BTC-USDC", payload)


def _seed_tp(orders: OrderStore, **overrides) -> None:
    payload = {
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "exchange_order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        "order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00015416",
        "remaining_size": "0.00015416",
        "limit_price": "71554.19",
    }
    payload.update(overrides)
    orders.upsert_order(payload)


def _report(tmp_path: Path, monkeypatch, *, current_price: str = "71000", cancel_verified: bool = False):
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    return build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": current_price, "reasons": ["stop_breached_or_below_invalidation"]},
        order_store=orders,
        state_store=state,
        cancel_verified=cancel_verified,
    )


def _cfg(**overrides):
    base = {
        "enable_controlled_stop_market_exits": False,
        "enable_autonomous_stop_exit_cancel": False,
        "enable_autonomous_stop_exit_submit": False,
        "enable_autonomous_stop_exit_apply": False,
        "mode_b_controlled_stop_exit_ack": "",
        "controlled_stop_exit_max_quote_usd": "25.00",
        "controlled_stop_exit_require_open_tp_cancel_first": True,
        "controlled_stop_exit_order_type": "near_market_limit_ioc",
        "controlled_stop_exit_max_slippage_pct": "0.0100",
        "market_order_enabled": False,
        "enable_market_orders": False,
        "allow_market_orders": False,
        "mode_c_market_order_ack": "",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_stop_breach_and_open_tp_above_market_plan_ready(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch)

    assert report["status"] == "controlled_stop_exit_plan_ready"
    assert report["stop_breached_or_below_invalidation"] is True
    assert report["open_tp_order_above_market"] is True
    assert report["stale_tp_blocks_stop_exit"] is True
    assert report["controlled_stop_exit_next_step"] == "cancel_existing_tp_first"
    assert report["safe_to_apply_stop_exit_now"] is False
    assert report["exit_target_source_policy"]["is_stale_target"] is True
    assert report["proposed_next_action"] == "ack_cancel_existing_tp_first"
    assert report["second_sell_blocked_until_cancel_verified"] is True
    assert report["controlled_market_sell_preview"]["sell_base"] == "0"
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["state_write_performed"] is False


def test_duplicate_open_exit_blocks_second_sell(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    _seed_tp(
        orders,
        client_order_id="phased3-BTCUSDC-TP2-bc3330fe-0T2153114172199999",
        exchange_order_id="81edc268-cf15-4f25-b30b-f0d5b3abb30e",
    )

    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "blocked_review_required"
    assert report["duplicate_exit_detected"] is True
    assert "duplicate_open_d3_exit_orders_block_second_sell" in report["blockers"]
    assert report["controlled_market_sell_preview"]["submit_requires_separate_ack"] is True


def test_oversell_blocks_controlled_stop_exit_plan(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, position_size_base="0.00010000", bot_managed_base="0.00010000")
    _seed_tp(orders, size_base="0.00015416", remaining_size="0.00015416")

    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        order_store=orders,
        state_store=state,
    )

    assert report["status"] == "blocked_review_required"
    assert report["oversell_detected"] is True
    assert "open_d3_exit_reservation_exceeds_position_base" in report["blockers"]


def test_no_second_sell_before_cancel_verification(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch)

    assert report["second_sell_blocked_until_cancel_verified"] is True
    assert report["controlled_market_sell_preview"]["ready_after_cancel_verified"] is False
    assert report["controlled_market_sell_preview"]["sell_base"] == report["available_base_minus_reserved_base"]


def test_cancel_verified_prepares_stop_exit_sell_preview(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, cancel_verified=True)

    assert report["cancel_existing_tp_preview"]["cancel_verified"] is True
    assert report["controlled_market_sell_preview"]["ready_after_cancel_verified"] is True
    assert report["controlled_market_sell_preview"]["sell_base"] == report["position_base"]
    assert report["no_coinbase_submit"] is True
    assert report["state_write_performed"] is False


def test_market_or_ioc_sell_blocked_when_quote_cap_exceeded(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, position_size_base="0.00100000", bot_managed_base="0.00100000")
    _seed_tp(orders)

    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_cfg(),
        order_store=orders,
        state_store=state,
        cancel_verified=True,
    )

    assert report["status"] == "blocked_review_required"
    assert "controlled_stop_exit_quote_cap_exceeded" in report["blockers"]
    assert report["safety_checks"]["market_or_ioc_under_quote_cap"] is False


def test_controlled_stop_exit_can_close_110_usdc_position_with_120_cap(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state, position_size_base="0.00155000", bot_managed_base="0.00155000")
    _seed_tp(orders, size_base="0.00155000", remaining_size="0.00155000")

    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_cfg(controlled_stop_exit_max_quote_usd="120.00"),
        order_store=orders,
        state_store=state,
        cancel_verified=True,
    )

    assert "controlled_stop_exit_quote_cap_exceeded" not in report["blockers"]
    assert report["controlled_market_sell_preview"]["sell_base"] == report["position_base"]


def test_coinbase_lookup_failure_blocks_controlled_stop_exit(tmp_path: Path, monkeypatch) -> None:
    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_cfg(),
        order_store=_orders(tmp_path),
        state_store=_state(tmp_path, monkeypatch),
        coinbase_lookup_succeeded=False,
    )

    assert "coinbase_lookup_failed" in report["blockers"]
    assert report["safety_checks"]["coinbase_lookup_required_before_action"] is False


def test_filled_stop_exit_proposes_local_apply_only_with_fill_evidence(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, cancel_verified=True)
    assert report["local_apply_preview"]["proposed_action"] == "await_terminal_fill_evidence"
    assert report["local_apply_preview"]["state_write_allowed_now"] is False

    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    with_evidence = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_cfg(enable_controlled_stop_market_exits=True, enable_autonomous_stop_exit_apply=True),
        order_store=orders,
        state_store=state,
        cancel_verified=True,
        terminal_fill_evidence={"normalized_status": "filled", "filled_base": "0.00015416", "fill_count": 1},
    )

    assert with_evidence["local_apply_preview"]["fill_evidence_valid"] is True
    assert with_evidence["local_apply_preview"]["proposed_action"] == "apply_filled_stop_exit"
    assert with_evidence["local_apply_preview"]["state_write_allowed_now"] is False
    assert with_evidence["local_apply_preview"]["mode_b_ack_valid"] is False
    assert with_evidence["state_write_performed"] is False

    with_ack = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_cfg(
            enable_controlled_stop_market_exits=True,
            enable_autonomous_stop_exit_cancel=True,
            enable_autonomous_stop_exit_submit=True,
            enable_autonomous_stop_exit_apply=True,
            mode_b_controlled_stop_exit_ack=MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
        ),
        order_store=orders,
        state_store=state,
        cancel_verified=True,
        terminal_fill_evidence={"normalized_status": "filled", "filled_base": "0.00015416", "fill_count": 1},
    )
    assert with_ack["local_apply_preview"]["state_write_allowed_now"] is True
    assert with_ack["controlled_market_sell_preview"]["autonomous_action_mode"] == "eligible_if_all_guards_green"


def test_default_flags_off_keeps_stop_exit_preview_only(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, cancel_verified=True)

    assert report["config"]["enable_controlled_stop_market_exits"] is False
    assert report["config"]["enable_autonomous_stop_exit_apply"] is False
    assert report["controlled_market_sell_preview"]["autonomous_action_mode"] == "preview_only"
    assert report["no_coinbase_cancel"] is True


def test_mode_c_does_not_replace_mode_b_stop_exit_apply_governance(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        cfg=_cfg(
            market_order_enabled=True,
            enable_market_orders=True,
            allow_market_orders=True,
            mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
        ),
        order_store=orders,
        state_store=state,
        cancel_verified=True,
        terminal_fill_evidence={"normalized_status": "filled", "filled_base": "0.00015416", "fill_count": 1},
    )

    assert report["config"]["mode_c_market_order_flags_enabled"] is True
    assert report["config"]["mode_c_market_order_ack_valid"] is True
    assert report["local_apply_preview"]["state_write_allowed_now"] is False
    assert report["local_apply_preview"]["mode_b_ack_valid"] is False
    assert "requires_mode_b_or_explicit_stop_governance" in report["controlled_market_sell_preview"]["mode_c_market_order_relation"]


def test_unknown_cancel_status_blocks_stop_sell_and_local_state_write(tmp_path: Path, monkeypatch) -> None:
    report = _report(tmp_path, monkeypatch, cancel_verified=True)
    blocked = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        order_store=_orders(tmp_path),
        state_store=_state(tmp_path, monkeypatch),
        cancel_verified=True,
        cancel_exchange_status="unknown",
    )
    assert report["state_write_performed"] is False
    assert "tp_cancel_status_not_verified_cancelled" in blocked["blockers"]
    assert blocked["state_write_performed"] is False


def test_partial_fill_during_cancel_requires_partial_reconcile_first(tmp_path: Path, monkeypatch) -> None:
    state = _state(tmp_path, monkeypatch)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_tp(orders)
    report = build_controlled_stop_market_exit_plan(
        ticker="BTC-USDC",
        linked_position_id="76310097-849e-481c-b587-ba44bc3330fe",
        market_context={"current_price": "71000", "reasons": ["stop_breached_or_below_invalidation"]},
        order_store=orders,
        state_store=state,
        cancel_verified=True,
        cancel_exchange_status="cancelled",
        partial_fill_during_cancel=True,
    )
    assert "partial_fill_during_cancel_reconcile_partial_first" in report["blockers"]
    assert report["cancel_existing_tp_preview"]["partial_fill_during_cancel"] is True
