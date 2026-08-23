from __future__ import annotations

import json
from pathlib import Path

from bot.phase_state_hygiene_cleanup_preview import (
    STATE_HYGIENE_CLEANUP_APPLY_ACK,
    build_state_hygiene_cleanup_preview,
    build_state_hygiene_cleanup_preview_from_files,
)


TICKER = "BTC-USDC"
POSITION_ID = "pos-1"


def _position(**overrides):
    row = {
        "ticker": TICKER,
        "id": POSITION_ID,
        "status": "closed",
        "position_size_base": "0",
        "bot_managed_base": "0",
        "reserved_base_open_exit_orders": "0",
    }
    row.update(overrides)
    return row


def _open_d3_order(**overrides):
    row = {
        "client_order_id": "phased3-BTCUSDC-TP1-test",
        "exchange_order_id": "exchange-test",
        "order_id": "exchange-test",
        "ticker": TICKER,
        "product_id": TICKER,
        "side": "SELL",
        "phase": "D3_controlled_live_reduce_only_exits",
        "status": "open",
        "linked_position_id": POSITION_ID,
        "remaining_size": "0.00006490",
        "size_base": "0.00006490",
    }
    row.update(overrides)
    return row


def _payloads(*, position=None, orders=None):
    return {
        "orders_payload": {"orders": {order["client_order_id"]: order for order in (orders or [])}},
        "positions_payload": {TICKER: position or _position()},
    }


def _write_payloads(tmp_path: Path, *, position=None, orders=None):
    payloads = _payloads(position=position, orders=orders)
    orders_file = tmp_path / "open_orders.json"
    positions_file = tmp_path / "positions.json"
    orders_file.write_text(json.dumps(payloads["orders_payload"], indent=2), encoding="utf-8")
    positions_file.write_text(json.dumps(payloads["positions_payload"], indent=2), encoding="utf-8")
    return orders_file, positions_file


def _build(*, position=None, orders=None):
    return build_state_hygiene_cleanup_preview(**_payloads(position=position, orders=orders))


def test_no_mismatch_is_ok_and_no_cleanup_needed():
    report = _build(position=_position(reserved_base_open_exit_orders="0"), orders=[])

    assert report["status"] == "OK"
    assert report["cleanup_preview"] == []
    assert report["cleanup_preview_count"] == 0
    assert report["state_write_performed"] is False
    assert report["apply_now"] is False
    assert report["ack_boundary"]["future_apply_requires_exact_ack"] == STATE_HYGIENE_CLEANUP_APPLY_ACK


def test_stale_denormalized_reservation_with_no_open_d3_is_watch_preview_only():
    report = _build(position=_position(reserved_base_open_exit_orders="0.00006490"), orders=[])

    assert report["status"] == "WATCH"
    assert report["safe_cleanup_preview_count"] == 1
    preview = report["cleanup_preview"][0]
    assert preview["field_path"] == "positions.BTC-USDC.reserved_base_open_exit_orders"
    assert preview["proposed_before"] == "0.0000649"
    assert preview["proposed_after"] == "0"
    assert preview["proposed_diff"] == {
        "field_path": "positions.BTC-USDC.reserved_base_open_exit_orders",
        "before": "0.0000649",
        "after": "0",
    }
    assert preview["reason"] == "stale_denormalized_reservation_on_closed_position_no_open_d3_exit"
    assert preview["safe_to_apply_later"] is True
    assert preview["apply_now"] is False
    assert preview["required_future_ack"] == STATE_HYGIENE_CLEANUP_APPLY_ACK


def test_open_d3_exit_keeps_matching_reservation_and_does_not_zero():
    report = _build(
        position=_position(
            status="open",
            position_size_base="0.00006490",
            bot_managed_base="0.00006490",
            reserved_base_open_exit_orders="0.00006490",
        ),
        orders=[_open_d3_order()],
    )

    assert report["status"] == "OK"
    assert report["cleanup_preview"] == []
    governance = report["derived_reservation_governance"][0]
    assert governance["derived_open_d3_exit_count"] == 1
    assert governance["derived_reserved_base_from_open_d3_exit_orders"] == "0.0000649"
    assert governance["local_denormalized_reserved_base"] == "0.0000649"
    assert governance["mismatch"] is False


def test_open_d3_exit_mismatch_blocks_instead_of_zeroing_reservation():
    report = _build(
        position=_position(
            status="open",
            position_size_base="0.00006490",
            bot_managed_base="0.00006490",
            reserved_base_open_exit_orders="0",
        ),
        orders=[_open_d3_order()],
    )

    assert report["status"] == "STOP_NOW"
    preview = report["cleanup_preview"][0]
    assert preview["proposed_before"] == "0"
    assert preview["proposed_after"] == "0"
    assert preview["safe_to_apply_later"] is False
    assert preview["apply_now"] is False
    assert "open_d3_exit_reservation_mismatch_requires_lifecycle_review" in preview["blockers"]


def test_unsafe_closed_position_mismatch_is_stop_now():
    report = _build(
        position=_position(
            status="closed",
            position_size_base="0",
            bot_managed_base="0.00001000",
            reserved_base_open_exit_orders="0.00006490",
        ),
        orders=[],
    )

    assert report["status"] == "STOP_NOW"
    preview = report["cleanup_preview"][0]
    assert preview["reason"] == "reservation_mismatch_unsafe_or_unknown"
    assert preview["safe_to_apply_later"] is False
    assert preview["apply_now"] is False
    assert "reservation_mismatch_unsafe_or_unknown" in preview["blockers"]


def test_apply_now_is_always_false_and_ack_is_present_for_future_apply():
    report = _build(position=_position(reserved_base_open_exit_orders="0.00006490"), orders=[])

    assert report["apply_now"] is False
    assert report["cleanup_apply_performed"] is False
    assert report["ack_boundary"]["apply_now"] is False
    assert report["ack_boundary"]["no_apply_performed"] is True
    assert report["required_future_ack"] == STATE_HYGIENE_CLEANUP_APPLY_ACK
    assert all(preview["apply_now"] is False for preview in report["cleanup_preview"])


def test_file_builder_writes_no_state(tmp_path):
    orders_file, positions_file = _write_payloads(
        tmp_path,
        position=_position(reserved_base_open_exit_orders="0.00006490"),
        orders=[],
    )
    before_orders = orders_file.read_text(encoding="utf-8")
    before_positions = positions_file.read_text(encoding="utf-8")

    report = build_state_hygiene_cleanup_preview_from_files(
        orders_file=orders_file,
        positions_file=positions_file,
    )

    assert report["status"] == "WATCH"
    assert report["state_write_performed"] is False
    assert orders_file.read_text(encoding="utf-8") == before_orders
    assert positions_file.read_text(encoding="utf-8") == before_positions
