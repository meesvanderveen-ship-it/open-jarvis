from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.phase_d45_historical_exit_operations_report import build_phase_d45_historical_exit_operations_report


NOW = datetime(2026, 5, 29, 14, 30, tzinfo=timezone.utc)
ACTIVE_CLIENT = "phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443"
ACTIVE_EXCHANGE = "6f6fa436-f5b9-4df5-bb23-ddf35a27a56a"
OLD_CLIENT = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
OLD_EXCHANGE = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
LINKED_POSITION = "76310097-849e-481c-b587-ba44bc3330fe"


def _old_order(**overrides):
    payload = {
        "client_order_id": OLD_CLIENT,
        "exchange_order_id": OLD_EXCHANGE,
        "order_id": OLD_EXCHANGE,
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "phase": "D3_controlled_live_reduce_only_exits",
        "status": "cancelled",
        "linked_position_id": LINKED_POSITION,
        "limit_price": "84800.00",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "filled_quote": "0",
        "fill_count": 0,
        "post_only": True,
        "reduce_only_local": True,
        "created_at": "2026-05-28T16:36:57.376427+00:00",
        "cancelled_at": "2026-05-29T06:44:43.883722+00:00",
        "closed_at": "2026-05-29T06:44:43.883722+00:00",
    }
    payload.update(overrides)
    return payload


def _active_order(**overrides):
    payload = {
        "client_order_id": ACTIVE_CLIENT,
        "exchange_order_id": ACTIVE_EXCHANGE,
        "order_id": ACTIVE_EXCHANGE,
        "ticker": "BTC-USDC",
        "product_id": "BTC-USDC",
        "side": "SELL",
        "phase": "D3_controlled_live_reduce_only_exits",
        "status": "submitted",
        "linked_position_id": LINKED_POSITION,
        "limit_price": "76000.00",
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "filled_quote": "0",
        "fill_count": 0,
        "post_only": True,
        "reduce_only_local": True,
        "replacement_of_client_order_id": OLD_CLIENT,
        "replacement_of_exchange_order_id": OLD_EXCHANGE,
        "created_at": "2026-05-29T06:44:43.883722+00:00",
        "submitted_at": "2026-05-29T06:44:43.883722+00:00",
        "updated_at": "2026-05-29T06:44:44.255046+00:00",
    }
    payload.update(overrides)
    return payload


def _position(**overrides):
    payload = {
        "ticker": "BTC-USDC",
        "status": "open",
        "entry_price": "80000",
        "position_size_base": "0.0000649067431275",
        "bot_managed_base": "0.0001297967431275",
        "reserved_base_open_exit_orders": "0.00006489",
        "last_d4_cancel_replace_replacement_client_order_id": ACTIVE_CLIENT,
        "last_d4_cancel_replace_replacement_exchange_order_id": ACTIVE_EXCHANGE,
        "last_d4_cancel_replace_replaced_client_order_id": OLD_CLIENT,
        "last_d4_cancel_replace_replaced_exchange_order_id": OLD_EXCHANGE,
    }
    payload.update(overrides)
    return payload


def _orders(*orders):
    return {"orders": {order["client_order_id"]: order for order in orders}}


def _positions(position=None):
    return {"positions": {"BTC-USDC": position or _position()}}


def _build(**kwargs):
    return build_phase_d45_historical_exit_operations_report(
        orders_payload=kwargs.pop("orders_payload", _orders(_old_order(), _active_order())),
        positions_payload=kwargs.pop("positions_payload", _positions()),
        ticker="BTC-USDC",
        active_client_order_id=ACTIVE_CLIENT,
        active_exchange_order_id=ACTIVE_EXCHANGE,
        linked_position_id=LINKED_POSITION,
        market_mid=kwargs.pop("market_mid", ""),
        now=NOW,
        **kwargs,
    )


def _assert_safety(report):
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["state_write_performed"] is False
    assert report["learning_to_execution_allowed"] is False


def test_reconstructs_old_cancelled_and_replacement_active_path():
    report = _build()

    assert report["status"] == "d45_historical_exit_operations_report_ready"
    assert report["active_order"]["client_order_id"] == ACTIVE_CLIENT
    assert report["active_order"]["exchange_order_id"] == ACTIVE_EXCHANGE
    assert report["active_order"]["limit_price"] == "76000.00"
    assert report["old_order"]["exchange_order_id"] == OLD_EXCHANGE
    assert report["old_order"]["normalized_status"] == "cancelled"
    assert report["historical_lifecycle_summary"]["old_order_cancelled_zero_fill"] is True
    assert report["historical_lifecycle_summary"]["replacement_is_active"] is True
    assert [row["event"] for row in report["timeline"][:3]] == [
        "original_tp1_submitted",
        "original_tp1_cancelled_zero_fill",
        "replacement_tp1_submitted",
    ]
    _assert_safety(report)


def test_reports_local_state_coherence_and_current_wait_route():
    report = _build()

    local = report["local_state"]
    assert local["status"] == "coherent"
    assert local["exactly_one_open_exit"] is True
    assert local["open_exit_count"] == 1
    assert local["reservation_coherent"] is True
    assert local["duplicate_open_exit_detected"] is False
    assert local["oversell_detected"] is False
    assert local["old_order_not_open"] is True
    assert report["current_route"]["branch"] == "open_keep_open"
    assert report["current_route"]["route"] == "wait_for_trigger"


def test_market_fixture_adds_distance_band_and_d5_no_fill_metrics():
    report = _build(market_mid="74000")

    assert report["market_distance"]["band"] == "approaching_target"
    assert report["trigger_policy"]["trigger"] is True
    assert "market_approaching_target" in report["trigger_policy"]["reasons"]
    d5 = report["d5_no_fill_stale_metrics"]
    assert d5["target_distance_abs"] == "2000.00"
    assert d5["target_distance_band"] == "approaching_target"
    assert d5["no_fill_recommendation_label"] == "monitor_later"
    assert d5["learning_to_execution_allowed"] is False
    assert d5["report_only"] is True


def test_fill_and_terminal_routes_are_summarized_without_apply():
    partial = _build(orders_payload=_orders(_old_order(), _active_order(status="partially_filled", filled_base="0.00001", fill_count=1)))
    assert partial["current_route"]["branch"] == "fill_evidence"
    assert "Lifecycle Apply on Fill Evidence" in partial["current_route"]["route"]
    _assert_safety(partial)

    terminal = _build(orders_payload=_orders(_old_order(), _active_order(status="rejected")))
    assert terminal["current_route"]["branch"] == "terminal_evidence"
    assert "Terminal Closeout Reconcile" in terminal["current_route"]["route"]
    _assert_safety(terminal)


def test_safety_drift_blocks_duplicate_and_reservation_mismatch():
    duplicate = _active_order(
        client_order_id="duplicate",
        exchange_order_id="duplicate-exchange",
        order_id="duplicate-exchange",
    )
    report = _build(
        orders_payload=_orders(_old_order(), _active_order(), duplicate),
        positions_payload=_positions(_position(reserved_base_open_exit_orders="0.00001")),
    )

    assert report["status"] == "d45_historical_exit_operations_blocked_p0"
    assert report["local_state"]["exactly_one_open_exit"] is False
    assert report["local_state"]["duplicate_open_exit_detected"] is True
    assert "open_exit_count_not_exactly_one" in report["local_state"]["blockers"]
    assert "reservation_not_equal_active_remaining" in report["local_state"]["blockers"]
    assert report["next_valid_routes"]["safety drift"] == "blocked_p0_review_required"
    _assert_safety(report)


def test_cli_reads_fixtures_and_includes_matching_log_events_without_writes(tmp_path: Path):
    orders_file = tmp_path / "open_orders.json"
    positions_file = tmp_path / "positions.json"
    events_file = tmp_path / "order_events.jsonl"
    sentinel = tmp_path / "sentinel.txt"
    orders_file.write_text(json.dumps(_orders(_old_order(), _active_order()), indent=2), encoding="utf-8")
    positions_file.write_text(json.dumps(_positions(), indent=2), encoding="utf-8")
    events_file.write_text(
        json.dumps({"generated_at": "2026-05-29T06:44:43.900000+00:00", "event_type": "replacement_submitted", "client_order_id": ACTIVE_CLIENT})
        + "\n",
        encoding="utf-8",
    )
    sentinel.write_text("unchanged", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d45_historical_exit_operations_report.py",
            "--orders-file",
            str(orders_file),
            "--positions-file",
            str(positions_file),
            "--event-log",
            str(events_file),
            "--market-mid",
            "70000",
            "--now",
            NOW.isoformat(),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert report["event_log_entries_included"] == 1
    assert report["active_order"]["client_order_id"] == ACTIVE_CLIENT
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    _assert_safety(report)
