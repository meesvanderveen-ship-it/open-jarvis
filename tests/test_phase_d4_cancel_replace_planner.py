from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.phase_d4_cancel_replace_planner import build_phase_d4_cancel_replace_plan


NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


class WriteTrapClient:
    def __init__(self):
        self.cancelled = []
        self.placed = []
        self.replaced = []

    def cancel_order(self, *args, **kwargs):
        self.cancelled.append((args, kwargs))
        raise AssertionError("cancel_order must not be called")

    def place_limit_order(self, *args, **kwargs):
        self.placed.append((args, kwargs))
        raise AssertionError("place_limit_order must not be called")

    def replace_order(self, *args, **kwargs):
        self.replaced.append((args, kwargs))
        raise AssertionError("replace_order must not be called")


def _order(**overrides):
    payload = {
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "order_id": EXCHANGE_ORDER_ID,
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": LINKED_POSITION_ID,
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "filled_quote": "0",
        "fill_count": 0,
        "limit_price": "84800.00",
        "post_only": True,
        "reduce_only_local": True,
    }
    payload.update(overrides)
    return payload


def _position(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "recovery_linked_position_id": LINKED_POSITION_ID,
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0.00006489",
    }
    payload.update(overrides)
    return payload


def _rules(**overrides):
    payload = {
        "base_increment": "0.00000001",
        "price_increment": "0.01",
        "min_order_quote": "1",
    }
    payload.update(overrides)
    return payload


def _preview_candidate(**overrides):
    payload = {
        "status": "d4_trailing_preview_candidate_ready",
        "ticker": "BTC-USDC",
        "linked_position_id": LINKED_POSITION_ID,
        "current_order_id": CLIENT_ORDER_ID,
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "current_exit_price": "84800.00",
        "current_market_mid": "83000.00",
        "activation_state": "active",
        "proposed_replacement_price": "84280.00",
        "proposed_replacement_quote": "5.4689292000",
        "proposed_action": "preview_reprice_candidate",
        "reason": "trailing_stop_triggered_candidate_preview_only",
        "blockers": [],
        "warnings": ["preview_only_no_cancel_replace_submit"],
        "no_coinbase_call": True,
        "no_live_action": True,
        "state_write_performed": False,
        "cancel_replace_allowed": False,
        "requires_future_ack": True,
        "post_only_feasible": True,
    }
    payload.update(overrides)
    return payload


def _preview_keep_open(**overrides):
    payload = _preview_candidate(
        status="d4_trailing_preview_keep_open",
        proposed_replacement_price="",
        proposed_replacement_quote="0",
        proposed_action="keep_open",
        reason="trailing_stop_not_triggered",
        requires_future_ack=False,
    )
    payload.update(overrides)
    return payload


def _plan(*, preview=None, order=None, position=None, rules=None, open_orders=None, fake_status=None, client=None, mode="dry_run_only"):
    current_order = order if order is not None else _order()
    orders = open_orders if open_orders is not None else [current_order]
    return build_phase_d4_cancel_replace_plan(
        preview_report=preview or _preview_candidate(),
        current_order=current_order,
        linked_position_id=LINKED_POSITION_ID,
        position=position or _position(),
        product_rules=rules or _rules(),
        open_orders=orders,
        fake_order_status_snapshot=fake_status,
        operator_mode=mode,
        coinbase_client=client,
        now=NOW,
    )


def _assert_dry_safety(report):
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["live_cancel_allowed"] is False
    assert report["live_replace_allowed"] is False
    assert report["cancel_first_required"] is True
    assert report["replace_only_after_confirmed_cancel"] is True


def test_preview_keep_open_planner_noop_without_ack():
    report = _plan(preview=_preview_keep_open())

    assert report["status"] == "d4_cancel_replace_plan_noop_keep_open"
    assert report["proposed_action"] == "no_op_keep_open"
    assert report["requires_future_ack"] is False
    assert report["required_future_ack"] == ""
    assert report["future_execution_outline"] == []
    _assert_dry_safety(report)


def test_preview_candidate_ready_builds_dry_run_cancel_replace_plan():
    report = _plan()

    assert report["status"] == "d4_cancel_replace_plan_ready"
    assert report["proposed_action"] == "dry_run_cancel_replace_plan_ready"
    assert report["replacement_price"] == "84280.00"
    assert report["replacement_size_base"] == "0.00006489"
    assert report["estimated_quote"] == "5.4689292000"
    assert report["requires_future_ack"] is True
    assert report["required_future_ack"]
    _assert_dry_safety(report)


def test_current_order_with_fills_blocks_and_routes_to_d3_lifecycle_first():
    report = _plan(order=_order(filled_base="0.00001", fill_count=1))

    assert report["status"] == "d4_cancel_replace_plan_blocked"
    assert report["proposed_action"] == "blocked"
    assert "current_order_has_fills_route_to_d3_lifecycle_first" in report["blockers"]
    _assert_dry_safety(report)


def test_duplicate_open_d3_exits_p0_blocks():
    first = _order()
    second = _order(client_order_id="duplicate", exchange_order_id="duplicate-exchange", order_id="duplicate-exchange")
    report = _plan(order=first, open_orders=[first, second])

    assert report["status"] == "d4_cancel_replace_plan_blocked"
    assert "duplicate_open_d3_exit_orders_for_position" in report["blockers"]
    _assert_dry_safety(report)


def test_reservation_mismatch_p0_oversell_blocks():
    report = _plan(position=_position(reserved_base_open_exit_orders="0.00001"))

    assert report["status"] == "d4_cancel_replace_plan_blocked"
    assert "reserved_base_less_than_replacement_size" in report["blockers"]
    _assert_dry_safety(report)


def test_replacement_below_min_quote_blocks():
    report = _plan(rules=_rules(min_order_quote="10"))

    assert report["status"] == "d4_cancel_replace_plan_blocked"
    assert "replacement_below_min_order_quote" in report["blockers"]
    _assert_dry_safety(report)


def test_replacement_post_only_unsafe_blocks():
    report = _plan(preview=_preview_candidate(post_only_feasible=False))

    assert report["status"] == "d4_cancel_replace_plan_blocked"
    assert "replacement_post_only_unsafe" in report["blockers"]
    _assert_dry_safety(report)


def test_terminal_fake_order_status_blocks_to_terminal_closeout_route():
    for status in ("cancelled", "expired", "rejected"):
        report = _plan(fake_status={"normalized_status": status})
        assert report["status"] == "d4_cancel_replace_plan_blocked"
        assert "fake_order_status_terminal_route_to_d3_terminal_closeout" in report["blockers"]
        _assert_dry_safety(report)


def test_fill_fake_order_status_blocks_to_d3_lifecycle_route():
    for status in ("partially_filled", "filled"):
        report = _plan(fake_status={"normalized_status": status, "filled_base": "0.00001"})
        assert report["status"] == "d4_cancel_replace_plan_blocked"
        assert "fake_order_status_fill_route_to_d3_lifecycle" in report["blockers"]
        _assert_dry_safety(report)


def test_cancel_first_sequencing_is_explicit_and_replace_waits_for_confirmed_cancel():
    report = _plan()
    outline = report["future_execution_outline"]

    assert [step["name"] for step in outline] == [
        "cancel_existing_order",
        "wait_for_confirmed_cancel",
        "submit_replacement_after_confirmed_cancel",
    ]
    assert outline[0]["step"] < outline[1]["step"] < outline[2]["step"]
    assert outline[1]["fail_closed_on_uncertain_cancel"] is True
    assert outline[2]["requires_confirmed_cancel"] is True
    assert report["cancel_uncertainty_policy"] == "fail_closed_no_replace_without_confirmed_cancel"
    _assert_dry_safety(report)


def test_fake_client_write_traps_are_never_called():
    client = WriteTrapClient()
    report = _plan(client=client)

    assert report["status"] == "d4_cancel_replace_plan_ready"
    assert "coinbase_client_ignored_dry_run_only" in report["warnings"]
    assert client.cancelled == []
    assert client.placed == []
    assert client.replaced == []
    _assert_dry_safety(report)


def test_cli_tool_reads_fixtures_and_does_not_write_files(tmp_path: Path):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    orders_file = state_dir / "open_orders.json"
    positions_file = state_dir / "positions.json"
    preview_file = tmp_path / "preview.json"
    rules_file = tmp_path / "rules.json"
    orders_file.write_text(json.dumps({"orders": {CLIENT_ORDER_ID: _order()}}, indent=2), encoding="utf-8")
    positions_file.write_text(json.dumps({"positions": {"BTC-USDC": _position()}}, indent=2), encoding="utf-8")
    preview_file.write_text(json.dumps(_preview_candidate(), indent=2), encoding="utf-8")
    rules_file.write_text(json.dumps(_rules(), indent=2), encoding="utf-8")

    before_orders = orders_file.read_text(encoding="utf-8")
    before_positions = positions_file.read_text(encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d4_cancel_replace_planner.py",
            "--ticker",
            "BTC-USDC",
            "--client-order-id",
            CLIENT_ORDER_ID,
            "--exchange-order-id",
            EXCHANGE_ORDER_ID,
            "--linked-position-id",
            LINKED_POSITION_ID,
            "--orders-file",
            str(orders_file),
            "--positions-file",
            str(positions_file),
            "--preview-fixture",
            str(preview_file),
            "--product-rules-fixture",
            str(rules_file),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert report["status"] == "d4_cancel_replace_plan_ready"
    _assert_dry_safety(report)
    assert orders_file.read_text(encoding="utf-8") == before_orders
    assert positions_file.read_text(encoding="utf-8") == before_positions
