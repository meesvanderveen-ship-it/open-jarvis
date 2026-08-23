from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from bot.order_store import OrderStore
from bot.phase_c43_tiny_residual_recovery import (
    PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
    POSITION_ACTION_DUST_CLOSE_REASON,
    POSITION_ACTION_DUST_RECOVERY_REASON,
    build_phase_c43_tiny_residual_recovery_report,
)
from bot.phase_d2_position_executor import is_d2_manageable_open_position
from bot.state_store import StateStore


def _state(tmp_path: Path) -> StateStore:
    return StateStore()


def _orders(tmp_path: Path) -> OrderStore:
    return OrderStore(path=tmp_path / "state" / "open_orders.json", log_path=tmp_path / "logs" / "order_events.jsonl")


class FakeCoinbaseClient:
    def __init__(self, available_base: str = "0.0001297967431275") -> None:
        self.available_base = available_base

    def get_spot_position(self, product_id: str):
        assert product_id == "BTC-USDC"
        return {
            "available_base_balance": self.available_base,
            "hold_base_balance": "0",
            "available_quote_balance": "438.18",
            "hold_quote_balance": "0",
        }


def _seed_position(
    state: StateStore,
    *,
    close_reason: str = "inventory_sync_live_notional_below_min_trade_quote",
    synthetic_close_reason: str = "inventory_sync_live_notional_below_min_trade_quote",
    last_heartbeat_status: str = "closed_tiny_residual",
    last_heartbeat_reason: str = "inventory_sync_live_notional_below_min_trade_quote",
) -> None:
    state.upsert_position(
        "BTC-USDC",
        {
            "ticker": "BTC-USDC",
            "status": "closed",
            "order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "entry_price": "77042.43",
            "position_size_base": "0",
            "position_size_quote": "0",
            "bot_managed_base": "0",
            "dust_residual_base": "0.0001297967431275",
            "dust_residual_quote": "9.9555030025505861625",
            "close_reason": close_reason,
            "synthetic_close_reason": synthetic_close_reason,
            "synthetic_closed_at": "2026-05-26T01:00:00.516982+00:00",
            "close_time": "2026-05-26T01:00:00.516982+00:00",
            "last_heartbeat_status": last_heartbeat_status,
            "last_heartbeat_reason": last_heartbeat_reason,
            "monitoring_enabled": False,
            "opened_via_phase_c43_live_order": True,
            "entry_reason": "phase_c43_live_limit_buy_filled",
        },
    )


def _seed_order(orders: OrderStore) -> None:
    state_path = orders.path
    state = {"orders": {
        "phasec-BTCUSDC-smoke-20260526003354": {
            "client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
            "ticker": "BTC-USDC",
            "side": "BUY",
            "status": "filled",
            "filled_size_base": "0.00012979",
            "filled_quote_value": "9.9993369897",
            "position_created": True,
            "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "d2_plan_created": True,
            "d3_preview_created": True,
            "order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "opened_via_phase_c43": True,
            "execution_action": "place_limit_buy",
            "updated_at": "2026-05-26T00:36:20.613029+00:00",
        }
    }}
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _build_report(tmp_path: Path, **kwargs):
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    return build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
        **kwargs,
    )


def test_dry_run_writes_nothing(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    report = _build_report(tmp_path, apply=False)
    before = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")
    after = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")
    assert report["status"] == "phase_c43_tiny_residual_recovery_dry_run"
    assert report["state_write_performed"] is False
    assert report["blockers"] == []
    assert report["live_base_evidence"]["status"] == "recovery_live_base_evidence_ready"
    assert before == after


def test_rejected_ghost_sell_is_ignored_for_recovery(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    orders.upsert_order(
        {
            "client_order_id": "ghost-d3",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "rejected",
            "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "execution_action": "place_limit_sell",
            "order_id": "",
            "exchange_order_id": "",
            "remaining_size": "0",
            "remaining_quote": "0",
        },
        event_type="phase_d3_live_exit_order_marked_rejected",
    )
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert report["status"] == "phase_c43_tiny_residual_recovery_dry_run"
    assert report["sell_evidence"]["proof_of_sell_exists"] is False
    assert report["sell_evidence"]["ignored_rejected_ghost_sell_orders"][0]["client_order_id"] == "ghost-d3"
    assert "recovery_sell_evidence_detected" not in report["blockers"]


def test_apply_blocks_wrong_position_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="wrong",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        apply=True,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_position_id_not_allowed" in report["blockers"]


def test_apply_blocks_without_ack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    report = _build_report(tmp_path, apply=True)
    assert report["status"] == "phase_c43_tiny_residual_recovery_blocked"
    assert report["apply_ack_required"] == PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK
    assert report["apply_ack_valid"] is False
    assert "recovery_apply_ack_required" in report["blockers"]


def test_apply_blocks_wrong_client_order_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="wrong",
        expected_live_base="0.0001297967431275",
        apply=True,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_client_order_id_not_allowed" in report["blockers"]


def test_apply_blocks_when_dust_residual_and_expected_live_base_nonpositive(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state.upsert_position("BTC-USDC", {"dust_residual_base": "0"})
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0",
        apply=True,
        apply_ack=PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(available_base="0"),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_dust_residual_base_nonpositive" in report["blockers"]


def test_apply_blocks_when_sell_evidence_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state_json = json.loads((tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8"))
    state_json["orders"]["sell-1"] = {
        "client_order_id": "sell-1",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "filled",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "execution_action": "place_limit_sell",
        "order_id": "sell-1",
        "exchange_order_id": "sell-1",
    }
    (tmp_path / "state" / "open_orders.json").write_text(json.dumps(state_json, indent=2), encoding="utf-8")
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        apply=True,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_sell_evidence_detected" in report["blockers"]


def test_apply_blocks_when_live_base_mismatch(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        apply=True,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(available_base="0.0001200000000000"),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_live_base_available_mismatch" in report["blockers"]


def test_apply_blocks_when_open_d3_exit_order_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state_json = json.loads((tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8"))
    state_json["orders"]["sell-open"] = {
        "client_order_id": "sell-open",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "execution_action": "place_limit_sell",
    }
    (tmp_path / "state" / "open_orders.json").write_text(json.dumps(state_json, indent=2), encoding="utf-8")
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        apply=True,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_open_d3_exit_order_exists" in report["blockers"]


def test_dry_run_allows_exactly_one_matching_open_d3_exit_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state_json = json.loads((tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8"))
    state_json["orders"]["sell-open"] = {
        "client_order_id": "sell-open",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "execution_action": "place_limit_sell",
        "phase": "D3_controlled_live_reduce_only_exits",
        "exchange_order_id": "cb-d3-open",
        "order_id": "cb-d3-open",
        "d3_exit_label": "TP1",
        "remaining_size": "0.00006489",
    }
    (tmp_path / "state" / "open_orders.json").write_text(json.dumps(state_json, indent=2), encoding="utf-8")
    class HeldBaseCoinbaseClient(FakeCoinbaseClient):
        def get_spot_position(self, product_id: str):
            row = super().get_spot_position(product_id)
            row["hold_base_balance"] = "0.00006489"
            return row

    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        state_store=state,
        order_store=orders,
        coinbase_client=HeldBaseCoinbaseClient(available_base="0.0000649067431275"),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert report["status"] == "phase_c43_tiny_residual_recovery_dry_run"
    assert report["blockers"] == []
    assert report["open_d3_exit_recovery_context"]["allowed_for_recovery"] is True
    assert report["sell_evidence"]["proof_of_sell_exists"] is False
    assert report["live_base_evidence"]["status"] == "recovery_live_base_evidence_ready"
    assert report["live_base_evidence"]["open_d3_expected_total_match"] is True
    assert report["proposed_updates"]["position_size_base"] == "0.0001297967431275"


def test_recovery_blocks_nonmatching_open_d3_exit_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state_json = json.loads((tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8"))
    state_json["orders"]["sell-open"] = {
        "client_order_id": "sell-open",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "other-pos",
        "execution_action": "place_limit_sell",
        "phase": "D3_controlled_live_reduce_only_exits",
        "exchange_order_id": "cb-d3-other",
        "order_id": "cb-d3-other",
        "d3_exit_label": "TP1",
        "remaining_size": "0.00006489",
    }
    (tmp_path / "state" / "open_orders.json").write_text(json.dumps(state_json, indent=2), encoding="utf-8")
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_open_d3_exit_order_exists" in report["blockers"]


def test_recovery_blocks_open_d3_exit_order_missing_exchange_order_id(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state_json = json.loads((tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8"))
    state_json["orders"]["sell-open"] = {
        "client_order_id": "sell-open",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "execution_action": "place_limit_sell",
        "phase": "D3_controlled_live_reduce_only_exits",
        "exchange_order_id": "",
        "order_id": "",
        "d3_exit_label": "TP1",
        "remaining_size": "0.00006489",
    }
    (tmp_path / "state" / "open_orders.json").write_text(json.dumps(state_json, indent=2), encoding="utf-8")
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_open_d3_exit_order_exists" in report["blockers"]


def test_apply_blocks_when_open_c43_entry_order_exists(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(state)
    _seed_order(orders)
    state_json = json.loads((tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8"))
    state_json["orders"]["buy-open"] = {
        "client_order_id": "buy-open",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "status": "submitted",
        "execution_action": "place_limit_buy",
    }
    (tmp_path / "state" / "open_orders.json").write_text(json.dumps(state_json, indent=2), encoding="utf-8")
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        apply=True,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert "recovery_open_c43_entry_order_exists" in report["blockers"]


def test_apply_restores_fields_correctly_and_moves_close_markers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    report = _build_report(
        tmp_path,
        apply=True,
        apply_ack=PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
    )
    assert report["status"] == "phase_c43_tiny_residual_recovery_applied"
    applied = report["applied_position"]
    assert applied["status"] == "open"
    assert applied["position_size_base"] == "0.0001297967431275"
    assert applied["bot_managed_base"] == "0.0001297967431275"
    assert applied["position_size_quote"] == "9.9555030025505861625"
    assert applied["recovered_from_closed_tiny_residual"] is True
    assert applied["recovered_from_synthetic_tiny_residual_close"] is True
    assert applied["previous_close_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert applied["previous_synthetic_close_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert applied["recovery_source"] == "read_only_coinbase_base_balance"
    assert applied["historical_close_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert applied["historical_synthetic_close_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert applied["historical_synthetic_closed_at"] == "2026-05-26T01:00:00.516982+00:00"
    assert applied["historical_close_time"] == "2026-05-26T01:00:00.516982+00:00"
    assert applied["last_heartbeat_status"] == "recovered_tiny_residual"
    assert applied["previous_last_heartbeat_status"] == "closed_tiny_residual"
    assert applied["previous_last_heartbeat_reason"] == "inventory_sync_live_notional_below_min_trade_quote"
    assert applied["close_reason"] == ""
    assert applied["synthetic_close_reason"] == ""
    assert applied["synthetic_closed_at"] is None
    assert is_d2_manageable_open_position(applied, ticker="BTC-USDC") is True


def test_d3_preview_after_recovery_remains_no_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    report = _build_report(tmp_path, apply=False)
    d3 = report["d3_preview_after_recovery"]
    assert d3["live_submission_attempted"] is False
    assert d3["live_order_submitted"] is False


def test_strategy_engine_does_not_immediately_reclose_recovered_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    StrategyEngine = pytest.importorskip("bot.strategy_engine").StrategyEngine
    report = _build_report(
        tmp_path,
        apply=True,
        apply_ack=PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
    )
    restored = report["applied_position"]
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.state = _state(tmp_path)
    engine.order_store = _orders(tmp_path)
    engine.position_epsilon_base = Decimal("0.00000001")
    engine.min_trade_quote_usdc = Decimal("10")
    engine._to_decimal = StrategyEngine._to_decimal
    engine._now_iso = lambda: "2026-05-26T01:30:00+00:00"
    engine._apply_current_inventory_policy_to_payload = lambda payload: None
    synced = engine._sync_local_position_to_live_balance(
        ticker="BTC-USDC",
        position=restored,
        live_available_base=Decimal("0.0001297967431275"),
        current_price=Decimal("76700"),
        note="inventory_sync_live_balance_refresh",
    )
    assert synced["status"] == "open"
    assert synced["tiny_residual_close_skipped_for_phase_c43_pilot_review"] is True


def test_dry_run_accepts_position_action_dust_close_reason(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(
        state,
        close_reason=POSITION_ACTION_DUST_CLOSE_REASON,
        synthetic_close_reason="",
        last_heartbeat_status="closed",
        last_heartbeat_reason=POSITION_ACTION_DUST_CLOSE_REASON,
    )
    _seed_order(orders)
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert report["status"] == "phase_c43_tiny_residual_recovery_dry_run"
    assert report["blockers"] == []
    assert report["proposed_updates"]["recovery_reason"] == POSITION_ACTION_DUST_RECOVERY_REASON
    assert report["proposed_updates"]["recovered_from_position_action_dust_close"] is True


def test_apply_with_ack_restores_position_action_dust_close(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    state = _state(tmp_path)
    orders = _orders(tmp_path)
    _seed_position(
        state,
        close_reason=POSITION_ACTION_DUST_CLOSE_REASON,
        synthetic_close_reason="",
        last_heartbeat_status="closed",
        last_heartbeat_reason=POSITION_ACTION_DUST_CLOSE_REASON,
    )
    _seed_order(orders)
    report = build_phase_c43_tiny_residual_recovery_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        client_order_id="phasec-BTCUSDC-smoke-20260526003354",
        expected_live_base="0.0001297967431275",
        apply=True,
        apply_ack=PHASE_C43_TINY_RESIDUAL_RECOVERY_ACK,
        state_store=state,
        order_store=orders,
        coinbase_client=FakeCoinbaseClient(),
        order_events_path=tmp_path / "logs" / "order_events.jsonl",
        live_exit_orders_path=tmp_path / "logs" / "live_exit_orders.jsonl",
    )
    assert report["status"] == "phase_c43_tiny_residual_recovery_applied"
    assert report["applied_position"]["recovered_from_position_action_dust_close"] is True
    assert report["applied_position"]["recovery_reason"] == POSITION_ACTION_DUST_RECOVERY_REASON
