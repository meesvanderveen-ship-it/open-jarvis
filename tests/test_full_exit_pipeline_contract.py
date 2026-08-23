from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bot.order_store import OrderStore
from bot.phase_d2_position_executor import (
    D2_PLAN_STATUS_BLOCKED,
    D2_PLAN_STATUS_READY,
    build_phase_d2_position_executor_report,
)
from bot.phase_d3_controlled_live_exits import (
    assess_phase_d3_exit_readiness,
    build_phase_d3_exit_payload,
    select_next_phase_d3_exit_intent,
)
from bot.phase_d3_open_exit_lifecycle_manager import build_phase_d3_open_exit_lifecycle_report
from bot.phase_d3_open_exit_lifecycle_manager import D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK
from bot.state_store import StateStore


def _cfg():
    return SimpleNamespace(
        enable_phase_d3_controlled_live_exits=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_d3_max_exit_order_quote="100.00",
        phase_d3_max_open_exit_orders=4,
        phase_d3_max_new_exit_orders_per_cycle=1,
        enable_phase_d3_actual_exit_submit=True,
        enable_live_exit_orders=True,
        autonomous_allow_exits=True,
        phase_c_disable_exit_limit_orders=False,
        phase_d3_exit_order_post_only=True,
        min_live_order_quote_usdc="20.00",
    )


def _position(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "100.00",
        "position_size_base": "1.00",
        "bot_managed_base": "1.00",
        "position_size_quote": "100.00",
        "stop_price": "97.50",
        "invalidation_price": "97.50",
    }
    payload.update(overrides)
    return payload


def _plan(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "position_id": "pos-1",
        "status": D2_PLAN_STATUS_READY,
    }
    payload.update(overrides)
    return payload


def _intent(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "position_id": "pos-1",
        "side": "SELL",
        "execution_action": "place_limit_sell",
        "size_base": "0.50",
        "limit_price": "110.00",
        "estimated_quote_value": "55.00",
        "reduce_only_local": True,
        "label": "TP1",
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "events.jsonl")


def test_exit_blocks_position_risk_incomplete_and_missing_invalidation(tmp_path: Path) -> None:
    readiness = assess_phase_d3_exit_readiness(
        cfg=_cfg(),
        position=_position(invalidation_price="0", protective_stop_status="position_risk_incomplete"),
        plan=_plan(),
        exit_intent=_intent(),
        order_store=_orders(tmp_path),
    )

    assert readiness["ready"] is False
    assert "position_risk_incomplete_stop_or_invalidation_missing" in readiness["blockers"]
    assert readiness["submit_armed"] is False


def test_d2_creates_sell_plan_for_risk_complete_position() -> None:
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        position=_position(),
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1.00"},
    )

    assert report["status"] == D2_PLAN_STATUS_READY
    assert report["plan_ready_no_live_exit_submit"] is True
    assert report["plan"]["risk"]["risk_state_complete"] is True
    assert report["plan"]["exits"]


def test_d2_blocks_risk_incomplete_with_controlled_close_or_reconstruction_route() -> None:
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        position=_position(invalidation_price="0", protective_stop_status="position_risk_incomplete"),
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1.00"},
    )

    assert report["status"] == D2_PLAN_STATUS_BLOCKED
    assert "position_risk_incomplete_stop_or_invalidation_missing" in report["blockers"]
    assert report["risk_incomplete_action_route"]["route"] == "controlled_close_or_risk_reconstruction"
    assert report["risk_incomplete_action_route"]["normal_d3_live_exit_allowed"] is False


def test_d3_builds_limit_post_only_sell_payload_for_valid_d2_plan(tmp_path: Path) -> None:
    report = build_phase_d2_position_executor_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        position=_position(),
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1.00"},
    )
    intent = select_next_phase_d3_exit_intent(
        cfg=_cfg(),
        plan=report["plan"],
        position=_position(),
        order_store=_orders(tmp_path),
        exchange_rules={"base_increment": "0.00000001", "price_increment": "0.01", "quote_min_size": "1.00"},
    )
    payload = build_phase_d3_exit_payload(cfg=_cfg(), exit_intent=intent)

    assert intent["side"] == "SELL"
    assert intent["execution_action"] == "place_limit_sell"
    assert intent["post_only"] is True
    assert payload["order_type"] == "limit_limit_gtc"
    assert "market_market_ioc" not in payload["coinbase_payload_preview"]["order_configuration"]
    assert payload["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]["post_only"] is True


def test_exit_blocks_missing_d2_plan(tmp_path: Path) -> None:
    readiness = assess_phase_d3_exit_readiness(
        cfg=_cfg(),
        position=_position(),
        plan=_plan(status=D2_PLAN_STATUS_BLOCKED),
        exit_intent=_intent(),
        order_store=_orders(tmp_path),
    )

    assert readiness["ready"] is False
    assert "d2_plan_not_ready" in readiness["blockers"]


def test_exit_blocks_explicit_missing_verified_base(tmp_path: Path) -> None:
    readiness = assess_phase_d3_exit_readiness(
        cfg=_cfg(),
        position=_position(current_base_balance_verified=False),
        plan=_plan(),
        exit_intent=_intent(),
        order_store=_orders(tmp_path),
    )

    assert readiness["ready"] is False
    assert "verified_base_balance_required_for_sell" in readiness["blockers"]


def test_exit_blocks_oversell_and_duplicate_d3_exit(tmp_path: Path) -> None:
    orders = _orders(tmp_path)
    orders.upsert_order(
        {
            "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
            "exchange_order_id": "cb-exit-existing",
            "order_id": "cb-exit-existing",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
            "phase": "D3_controlled_live_reduce_only_exits",
            "linked_position_id": "pos-1",
            "execution_action": "place_limit_sell",
            "d3_exit_label": "TP1",
            "size_base": "0.75",
            "remaining_size": "0.75",
            "limit_price": "110.00",
        }
    )

    readiness = assess_phase_d3_exit_readiness(
        cfg=_cfg(),
        position=_position(),
        plan=_plan(),
        exit_intent=_intent(size_base="0.50"),
        order_store=orders,
    )

    assert readiness["ready"] is False
    assert "sell_base_exceeds_available_unreserved_base" in readiness["blockers"]
    assert "duplicate_open_exit_order_for_position_action" in readiness["blockers"]


def test_terminal_fill_missing_blocks_local_close_apply(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    monkeypatch.setenv("ENABLE_LIVE_EXIT_ORDERS", "false")
    monkeypatch.setenv("AUTONOMOUS_ALLOW_EXITS", "false")
    monkeypatch.setenv("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false")
    monkeypatch.setenv("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "true")
    (tmp_path / "state").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    state = StateStore()
    state.upsert_position("BTC-USDC", _position())
    orders = OrderStore(path=tmp_path / "state/open_orders.json", log_path=tmp_path / "logs/order_events.jsonl")
    orders.upsert_order(
        {
            "client_order_id": "phased3-BTCUSDC-TP1-pos-1",
            "exchange_order_id": "cb-exit-1",
            "order_id": "cb-exit-1",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
            "phase": "D3_controlled_live_reduce_only_exits",
            "linked_position_id": "pos-1",
            "execution_action": "place_limit_sell",
            "d3_exit_label": "TP1",
            "size_base": "0.50",
            "remaining_size": "0.50",
            "limit_price": "110.00",
        }
    )

    report = build_phase_d3_open_exit_lifecycle_report(
        ticker="BTC-USDC",
        client_order_id="phased3-BTCUSDC-TP1-pos-1",
        exchange_order_id="cb-exit-1",
        linked_position_id="pos-1",
        order_store=orders,
        state_store=state,
        snapshot={
            "coinbase_call_succeeded": True,
            "raw_status": "FILLED",
            "normalized_status": "filled",
            "filled_base": "0",
            "filled_quote": "0",
            "avg_fill_price": "0",
            "fill_count": 0,
            "remaining_size": "0",
        },
        apply_local=True,
        apply_ack=D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK,
    )

    assert report["state_write_performed"] is False
    assert "fill_evidence_required_for_partial_or_filled_apply" in report["blockers"]
