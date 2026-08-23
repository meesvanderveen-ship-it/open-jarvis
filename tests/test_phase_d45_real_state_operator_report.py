from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

from tools.show_phase_d45_real_state_operator_report import (
    DEFAULT_CLIENT_ORDER_ID,
    DEFAULT_EXCHANGE_ORDER_ID,
    build_report,
)


TICKER = "BTC-USDC"
POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


def _active_order(**overrides):
    order = {
        "client_order_id": DEFAULT_CLIENT_ORDER_ID,
        "exchange_order_id": DEFAULT_EXCHANGE_ORDER_ID,
        "order_id": DEFAULT_EXCHANGE_ORDER_ID,
        "ticker": TICKER,
        "product_id": TICKER,
        "side": "SELL",
        "phase": "D3_controlled_live_reduce_only_exits",
        "status": "submitted",
        "linked_position_id": POSITION_ID,
        "d3_exit_label": "TP1",
        "limit_price": "84800.00",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "fill_count": 0,
        "created_at": "2026-05-28T16:36:57.376427+00:00",
    }
    order.update(overrides)
    return order


def _position(**overrides):
    position = {
        "ticker": TICKER,
        "status": "open",
        "entry_price": "80000",
        "position_size_base": "0.00006489",
        "reserved_base_open_exit_orders": "0.00006489",
    }
    position.update(overrides)
    return position


def _write_state(tmp_path: Path, *, orders, position=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    orders_file = tmp_path / "open_orders.json"
    positions_file = tmp_path / "positions.json"
    orders_file.write_text(json.dumps({"orders": {o["client_order_id"]: o for o in orders}}, indent=2), encoding="utf-8")
    positions_file.write_text(json.dumps({TICKER: position or _position()}, indent=2), encoding="utf-8")
    return orders_file, positions_file


def _args(orders_file: Path, positions_file: Path, **overrides):
    base = {
        "ticker": TICKER,
        "client_order_id": DEFAULT_CLIENT_ORDER_ID,
        "exchange_order_id": DEFAULT_EXCHANGE_ORDER_ID,
        "orders_file": str(orders_file),
        "positions_file": str(positions_file),
        "operator_mode": "decision_only",
    }
    base.update(overrides)
    return Namespace(**base)


def test_active_open_no_fill_maps_to_wait_for_trigger(tmp_path):
    orders_file, positions_file = _write_state(tmp_path, orders=[_active_order()])

    report = build_report(_args(orders_file, positions_file))

    assert report["order_found"] is True
    assert report["lifecycle_branch"] == "open_keep_open"
    assert report["d5_metrics_summary"]["fill_quality_label"] == "no_fill_open"
    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert report["warnings"] == []
    assert report["d4_preview_summary"]["warnings"] == ["market_snapshot_missing_local_only"]
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["learning_to_execution_allowed"] is False


def test_partial_or_filled_routes_to_fill_lifecycle_apply(tmp_path):
    for status in ("partially_filled", "filled"):
        orders_file, positions_file = _write_state(
            tmp_path / status,
            orders=[_active_order(status=status, filled_base="0.00001000", fill_count=1, remaining_size="0.00005489")],
        )

        report = build_report(_args(orders_file, positions_file))

        assert report["lifecycle_branch"] == "fill_evidence"
        assert report["recommended_operator_action"] == "prepare_fill_lifecycle_apply"
        assert report["no_live_action"] is True


def test_cancelled_expired_rejected_route_to_terminal_closeout(tmp_path):
    for status in ("cancelled", "expired", "rejected"):
        orders_file, positions_file = _write_state(
            tmp_path / status,
            orders=[_active_order(status=status, remaining_size="0.00006489")],
        )

        report = build_report(_args(orders_file, positions_file))

        assert report["lifecycle_branch"] == "terminal_evidence"
        assert report["recommended_operator_action"] == "prepare_terminal_closeout"
        assert report["state_write_performed"] is False


def test_missing_order_blocks_review(tmp_path):
    other = _active_order(client_order_id="other", exchange_order_id="other-exchange", order_id="other-exchange")
    orders_file, positions_file = _write_state(tmp_path, orders=[other])

    report = build_report(_args(orders_file, positions_file))

    assert report["order_found"] is False
    assert report["recommended_operator_action"] == "blocked_p0_review_required"
    assert "open_d3_exit_order_not_found" in report["blockers"]


def test_duplicate_open_exits_blocks_p0_review(tmp_path):
    duplicate = _active_order(
        client_order_id="phased3-BTCUSDC-TP2-test",
        exchange_order_id="exchange-duplicate",
        order_id="exchange-duplicate",
    )
    orders_file, positions_file = _write_state(tmp_path, orders=[_active_order(), duplicate])

    report = build_report(_args(orders_file, positions_file))

    assert report["open_d3_exit_count_for_position"] == 2
    assert report["recommended_operator_action"] == "blocked_p0_review_required"
    assert "duplicate_open_d3_exit_orders_for_position" in report["blockers"]


def test_reservation_mismatch_blocks_p0_review(tmp_path):
    orders_file, positions_file = _write_state(
        tmp_path,
        orders=[_active_order()],
        position=_position(reserved_base_open_exit_orders="0"),
    )

    report = build_report(_args(orders_file, positions_file))

    assert report["recommended_operator_action"] == "blocked_p0_review_required"
    assert "reserved_base_open_exit_orders_less_than_open_exit_remaining_size" in report["blockers"]


def test_cli_reads_fixtures_and_writes_no_state_files(tmp_path):
    orders_file, positions_file = _write_state(tmp_path, orders=[_active_order()])
    before_orders = orders_file.read_text(encoding="utf-8")
    before_positions = positions_file.read_text(encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d45_real_state_operator_report.py",
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
    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert orders_file.read_text(encoding="utf-8") == before_orders
    assert positions_file.read_text(encoding="utf-8") == before_positions
