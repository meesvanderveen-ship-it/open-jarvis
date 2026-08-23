from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from bot.phase_d3_reservation_repair_preview import (
    D3_RESERVATION_DRIFT_REPAIR_ACK,
    build_phase_d3_reservation_repair_preview_from_files,
)
from tools.show_phase_d45_real_state_operator_report import build_report as build_d45_report


TICKER = "BTC-USDC"
CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


def _order(**overrides):
    order = {
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "order_id": EXCHANGE_ORDER_ID,
        "ticker": TICKER,
        "product_id": TICKER,
        "side": "SELL",
        "phase": "D3_controlled_live_reduce_only_exits",
        "status": "submitted",
        "linked_position_id": POSITION_ID,
        "limit_price": "84800.00",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "fill_count": 0,
    }
    order.update(overrides)
    return order


def _position(**overrides):
    position = {
        "ticker": TICKER,
        "status": "open",
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0",
    }
    position.update(overrides)
    return position


def _write_state(tmp_path: Path, *, orders=None, position=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    orders_file = tmp_path / "open_orders.json"
    positions_file = tmp_path / "positions.json"
    rows = orders if orders is not None else [_order()]
    orders_file.write_text(json.dumps({"orders": {row["client_order_id"]: row for row in rows}}, indent=2), encoding="utf-8")
    positions_file.write_text(json.dumps({TICKER: position or _position()}, indent=2), encoding="utf-8")
    return orders_file, positions_file


def _preview(orders_file: Path, positions_file: Path, **kwargs):
    params = {
        "ticker": TICKER,
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "orders_file": orders_file,
        "positions_file": positions_file,
        "apply": False,
        "repair_ack": "",
    }
    params.update(kwargs)
    return build_phase_d3_reservation_repair_preview_from_files(**params)


def _d45_args(orders_file: Path, positions_file: Path):
    return Namespace(
        ticker=TICKER,
        client_order_id=CLIENT_ORDER_ID,
        exchange_order_id=EXCHANGE_ORDER_ID,
        orders_file=str(orders_file),
        positions_file=str(positions_file),
        operator_mode="decision_only",
    )


def test_happy_path_preview_proposes_reservation_repair(tmp_path):
    orders_file, positions_file = _write_state(tmp_path)

    report = _preview(orders_file, positions_file)

    assert report["status"] == "d3_reservation_repair_preview_ready"
    assert report["current_reserved_base"] == "0"
    assert report["required_reserved_base"] == "0.00006489"
    assert report["proposed_reserved_base_after"] == "0.00006489"
    assert report["available_base_after_reservations_after"] == "0.0000649067431275"
    assert report["would_write_state"] is False
    assert report["apply_allowed"] is False
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False


def test_already_coherent_reservation_is_noop(tmp_path):
    orders_file, positions_file = _write_state(
        tmp_path,
        position=_position(reserved_base_open_exit_orders="0.00006489"),
    )

    report = _preview(orders_file, positions_file)

    assert report["status"] == "d3_reservation_repair_noop_coherent"
    assert report["suggested_action"] == "no_op"
    assert report["blockers"] == []


def test_duplicate_open_exits_blocked(tmp_path):
    duplicate = _order(
        client_order_id="phased3-BTCUSDC-TP2-test",
        exchange_order_id="exchange-duplicate",
        order_id="exchange-duplicate",
    )
    orders_file, positions_file = _write_state(tmp_path, orders=[_order(), duplicate])

    report = _preview(orders_file, positions_file)

    assert report["status"] == "d3_reservation_repair_blocked"
    assert "duplicate_open_d3_exit_orders_for_position" in report["blockers"]


def test_partial_or_fill_evidence_routes_to_d3_lifecycle(tmp_path):
    for status in ("partially_filled", "filled"):
        orders_file, positions_file = _write_state(
            tmp_path / status,
            orders=[_order(status=status, filled_base="0.00001000", fill_count=1, remaining_size="0.00005489")],
        )

        report = _preview(orders_file, positions_file)

        assert report["lifecycle_route"] == "route_to_d3_lifecycle_apply"
        assert "fill_evidence_route_to_d3_lifecycle_apply" in report["blockers"]
        assert report["lifecycle_apply_performed"] is False


def test_terminal_order_routes_to_terminal_closeout(tmp_path):
    for status in ("cancelled", "expired", "rejected"):
        orders_file, positions_file = _write_state(tmp_path / status, orders=[_order(status=status)])

        report = _preview(orders_file, positions_file)

        assert report["lifecycle_route"] == "route_to_d3_terminal_closeout"
        assert "terminal_evidence_route_to_d3_terminal_closeout" in report["blockers"]


def test_insufficient_bot_managed_base_blocks(tmp_path):
    orders_file, positions_file = _write_state(
        tmp_path,
        position=_position(position_size_base="0", bot_managed_base="0", reserved_base_open_exit_orders="0"),
    )

    report = _preview(orders_file, positions_file)

    assert report["status"] == "d3_reservation_repair_blocked"
    assert "insufficient_bot_managed_base_for_required_reservation" in report["blockers"]


def test_apply_without_ack_blocks_and_writes_nothing(tmp_path):
    orders_file, positions_file = _write_state(tmp_path)
    before = positions_file.read_text(encoding="utf-8")

    report = _preview(orders_file, positions_file, apply=True, repair_ack="")

    assert report["status"] == "d3_reservation_repair_blocked"
    assert "reservation_drift_repair_apply_ack_required" in report["blockers"]
    assert report["state_write_performed"] is False
    assert positions_file.read_text(encoding="utf-8") == before


def test_apply_with_ack_writes_only_fixture_position_state(tmp_path):
    orders_file, positions_file = _write_state(tmp_path)
    orders_before = orders_file.read_text(encoding="utf-8")

    report = _preview(
        orders_file,
        positions_file,
        apply=True,
        repair_ack=D3_RESERVATION_DRIFT_REPAIR_ACK,
    )

    assert report["status"] == "d3_reservation_repair_applied"
    assert report["state_write_performed"] is True
    assert orders_file.read_text(encoding="utf-8") == orders_before
    repaired = json.loads(positions_file.read_text(encoding="utf-8"))[TICKER]
    assert repaired["reserved_base_open_exit_orders"] == "0.00006489"


def test_d45_reports_p0_before_apply_and_wait_after_fixture_apply(tmp_path):
    orders_file, positions_file = _write_state(tmp_path)

    before = build_d45_report(_d45_args(orders_file, positions_file))
    assert before["recommended_operator_action"] == "blocked_p0_review_required"

    apply_report = _preview(
        orders_file,
        positions_file,
        apply=True,
        repair_ack=D3_RESERVATION_DRIFT_REPAIR_ACK,
    )
    assert apply_report["status"] == "d3_reservation_repair_applied"

    after = build_d45_report(_d45_args(orders_file, positions_file))
    assert after["lifecycle_branch"] == "open_keep_open"
    assert after["recommended_operator_action"] == "wait_for_trigger"


def test_cli_preview_reads_state_and_writes_nothing_without_apply(tmp_path):
    orders_file, positions_file = _write_state(tmp_path)
    before_orders = orders_file.read_text(encoding="utf-8")
    before_positions = positions_file.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/preview_or_apply_phase_d3_reservation_repair.py",
            "--orders-file",
            str(orders_file),
            "--positions-file",
            str(positions_file),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert report["status"] == "d3_reservation_repair_preview_ready"
    assert orders_file.read_text(encoding="utf-8") == before_orders
    assert positions_file.read_text(encoding="utf-8") == before_positions
