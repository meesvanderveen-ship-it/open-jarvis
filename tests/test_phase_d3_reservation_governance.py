from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d3_reservation_governance import build_phase_d3_reservation_governance_snapshot


def _position():
    return {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "100.00",
        "position_size_base": "0.25",
        "bot_managed_base": "0.25",
        "position_size_quote": "25.00",
    }


def _store(tmp_path: Path) -> OrderStore:
    return OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl")


def _plan(limit_price: str = "105.00"):
    return {
        "ticker": "BTC-USDC",
        "position_id": "pos-1",
        "exits": [
            {"label": "TP1", "base_size": "0.10", "limit_price": limit_price, "trailing_stop": False},
            {"label": "RUNNER", "base_size": "0.15", "limit_price": None, "trailing_stop": True},
        ],
    }


def test_no_position_is_fail_closed(tmp_path: Path):
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=None,
        order_store=_store(tmp_path),
        plan=_plan(),
    )
    assert snapshot["position_present"] is False
    assert snapshot["future_controlled_sell_pilot_coherent"] is False
    assert snapshot["fail_closed_recommendation"] is True


def test_position_without_open_exits_can_be_coherent_when_min_size_passes(tmp_path: Path):
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=_position(),
        order_store=_store(tmp_path),
        plan=_plan(limit_price="105.00"),
        exchange_rules={"quote_min_size": "10.00", "base_increment": "0.00000001"},
    )
    assert snapshot["reserved_base_open_exit_orders"] == "0"
    assert snapshot["available_base_after_reservations"] == "0.25"
    assert snapshot["duplicate_labels_detected"] is False
    assert snapshot["duplicate_actions_detected"] is False
    assert snapshot["min_size_ready"] is True
    assert snapshot["future_controlled_sell_pilot_coherent"] is True


def test_open_sell_order_reserving_all_base_blocks_coherence(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "pos-1",
        "execution_action": "place_limit_sell",
        "remaining_size": "0.25",
        "d3_exit_label": "TP1",
    })
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=_position(),
        order_store=store,
        plan=_plan(),
        exchange_rules={"quote_min_size": "10.00"},
    )
    assert snapshot["available_base_after_reservations"] == "0"
    assert snapshot["future_controlled_sell_pilot_coherent"] is False
    assert "no_available_base_after_existing_exit_reservations" in snapshot["blockers"]


def test_available_plus_reserved_matches_total_managed_base_with_open_hold(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "pos-1",
        "execution_action": "place_limit_sell",
        "remaining_size": "0.04",
        "d3_exit_label": "TP1",
    })
    position = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "position_size_base": "0.06",
        "bot_managed_base": "0.10",
        "position_size_quote": "6.00",
    }
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=position,
        order_store=store,
        plan=_plan(limit_price="105.00"),
        exchange_rules={"quote_min_size": "1.00", "base_increment": "0.00000001"},
    )
    assert snapshot["available_base_after_reservations"] == "0.06"
    assert snapshot["reserved_base_open_exit_orders"] == "0.04"
    assert snapshot["available_plus_reserved_base"] == "0.10"
    assert snapshot["available_reserved_matches_bot_manageable_base"] is True
    assert snapshot["bot_manageable_base"] == "0.10"


def test_duplicate_labels_are_detected_and_block(tmp_path: Path):
    store = _store(tmp_path)
    for suffix in ("a", "b"):
        store.upsert_order({
            "client_order_id": f"phased3-BTCUSDC-TP1-pos-1-{suffix}",
            "ticker": "BTC-USDC",
            "side": "SELL",
            "status": "submitted",
            "linked_position_id": "pos-1",
            "execution_action": "place_limit_sell",
            "remaining_size": "0.05",
            "d3_exit_label": "TP1",
        })
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=_position(),
        order_store=store,
        plan=_plan(),
        exchange_rules={"quote_min_size": "10.00"},
    )
    assert snapshot["duplicate_labels_detected"] is True
    assert snapshot["future_controlled_sell_pilot_coherent"] is False


def test_duplicate_actions_are_detected_and_block(tmp_path: Path):
    store = _store(tmp_path)
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-a",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "pos-1",
        "execution_action": "place_limit_sell",
        "remaining_size": "0.02",
        "d3_exit_label": "TP1",
    })
    store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP2-pos-1-b",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "linked_position_id": "pos-1",
        "execution_action": "place_limit_sell",
        "remaining_size": "0.02",
        "d3_exit_label": "TP2",
    })
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=_position(),
        order_store=store,
        plan=_plan(),
        exchange_rules={"quote_min_size": "10.00"},
    )
    assert snapshot["duplicate_actions_detected"] is True
    assert snapshot["future_controlled_sell_pilot_coherent"] is False


def test_below_min_quote_is_not_ready(tmp_path: Path):
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=_position(),
        order_store=_store(tmp_path),
        plan=_plan(limit_price="1.00"),
        exchange_rules={"quote_min_size": "100.00"},
    )
    assert snapshot["min_size_ready"] is False
    assert snapshot["future_controlled_sell_pilot_coherent"] is False


def test_incomplete_data_fails_closed(tmp_path: Path):
    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position={"ticker": "BTC-USDC", "status": "open"},
        order_store=_store(tmp_path),
        plan={},
        exchange_rules={},
    )
    assert snapshot["future_controlled_sell_pilot_coherent"] is False
    assert snapshot["fail_closed_recommendation"] is True


def test_read_only_fake_store_write_methods_are_not_called():
    class FakeReadOnlyStore:
        def open_exit_orders(self, ticker=None):
            return []

        def upsert_order(self, *args, **kwargs):
            raise AssertionError("upsert_order should not be called")

        def update_order(self, *args, **kwargs):
            raise AssertionError("update_order should not be called")

    snapshot = build_phase_d3_reservation_governance_snapshot(
        ticker="BTC-USDC",
        position=_position(),
        order_store=FakeReadOnlyStore(),  # type: ignore[arg-type]
        plan=_plan(),
        exchange_rules={"quote_min_size": "10.00"},
    )
    assert snapshot["safety_policy"]["does_not_mutate_state"] is True
    assert snapshot["safety_policy"]["does_not_write_persistent_ledger"] is True
