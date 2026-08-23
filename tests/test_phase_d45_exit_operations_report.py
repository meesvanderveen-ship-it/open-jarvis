from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.phase_d3_open_exit_lifecycle_manager import D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK
from bot.phase_d45_exit_operations_report import (
    FILL_APPLY_ROUTE,
    TERMINAL_CLOSEOUT_ROUTE,
    build_phase_d45_exit_operations_report,
    evaluate_trigger_policy,
)
from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report


NOW = datetime(2026, 5, 29, 14, 0, tzinfo=timezone.utc)
CLIENT_ORDER_ID = "phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443"
EXCHANGE_ORDER_ID = "6f6fa436-f5b9-4df5-bb23-ddf35a27a56a"
LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


def _local(**overrides):
    payload = {
        "lifecycle_branch": "open_keep_open",
        "recommended_operator_action": "wait_for_trigger",
        "active_order_summary": {
            "ticker": "BTC-USDC",
            "client_order_id": CLIENT_ORDER_ID,
            "exchange_order_id": EXCHANGE_ORDER_ID,
            "size_base": "0.00006489",
            "limit_price": "76000.00",
            "filled_base": "0",
            "fill_count": 0,
        },
        "open_d3_exit_count_for_position": 1,
        "reserved_base_open_exit_orders": "0.00006489",
        "remaining_size": "0.00006489",
        "blockers": [],
    }
    payload.update(overrides)
    return payload


def _poll(status="open", **overrides):
    raw = {
        "coinbase_call_succeeded": True,
        "coinbase_raw_status": status.upper(),
        "normalized_status": status,
        "filled_base": "0",
        "fill_count": 0,
        "remaining_size": "0.00006489",
        "proposed_action": "keep_open",
        "blockers": [],
    }
    raw.update(overrides)
    return raw


def _d5(mid="70000", created_at="2026-05-29T06:00:00+00:00"):
    return build_phase_d5_execution_metrics_report(
        lifecycle_event={
            "lifecycle_status": "open",
            "submitted_at": created_at,
            "first_seen_open_at": created_at,
            "filled_base": "0",
            "fill_count": 0,
            "planned_exit_price": "76000.00",
            "planned_size_base": "0.00006489",
        },
        plan_fields={"planned_exit_price": "76000.00", "planned_size_base": "0.00006489"},
        market_refs={"decision_mid": mid, "decision_best_bid": mid},
        now=NOW,
    )


def _assert_no_writes(report):
    assert report["no_coinbase_submit"] is True
    assert report["no_coinbase_cancel"] is True
    assert report["no_coinbase_replace"] is True
    assert report["no_coinbase_write"] is True
    assert report["state_write_performed"] is False
    assert report["learning_to_execution_allowed"] is False


def test_far_below_76000_no_poll_wait():
    report = build_phase_d45_exit_operations_report(
        local_report=_local(),
        market_mid="70000",
        now=NOW,
    )

    assert report["trigger_evaluation"]["trigger"] is False
    assert report["trigger_evaluation"]["market"]["band"] == "far_from_target"
    assert report["poll_executed"] is False
    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert report["next_route"] == "do_not_poll_wait_for_trigger"
    _assert_no_writes(report)


def test_near_76000_poll_justified():
    trigger = evaluate_trigger_policy(
        local_report=_local(),
        limit_price="76000.00",
        market_mid="75500",
    )

    assert trigger["trigger"] is True
    assert trigger["poll_allowed"] is True
    assert trigger["market"]["band"] == "near_target"
    assert "market_near_target" in trigger["reasons"]


def test_open_zero_fills_keep_open_after_poll():
    report = build_phase_d45_exit_operations_report(
        local_report=_local(),
        lifecycle_poll_report=_poll("open"),
        explicit_operator_request=True,
        market_mid="70000",
        d5_metrics_report=_d5("70000"),
        now=NOW,
    )

    assert report["poll_executed"] is True
    assert report["lifecycle_branch"] == "open_keep_open"
    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert report["next_route"] == "keep_open"
    _assert_no_writes(report)


def test_partial_and_filled_route_to_fill_apply_no_apply():
    for status, filled_base, fill_count in (("partial", "0.00001", 1), ("filled", "0.00006489", 1)):
        report = build_phase_d45_exit_operations_report(
            local_report=_local(),
            lifecycle_poll_report=_poll(status, filled_base=filled_base, fill_count=fill_count),
            explicit_operator_request=True,
            now=NOW,
        )

        assert report["lifecycle_branch"] == "fill_evidence"
        assert report["recommended_operator_action"] == "prepare_fill_lifecycle_apply"
        assert report["next_route"] == FILL_APPLY_ROUTE
        assert report["required_future_ack"] == D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK
        _assert_no_writes(report)


def test_terminal_statuses_route_to_terminal_closeout_no_apply():
    for status in ("cancelled", "expired", "rejected"):
        report = build_phase_d45_exit_operations_report(
            local_report=_local(),
            lifecycle_poll_report=_poll(status, proposed_action="mark_cancelled_release_reservation"),
            explicit_operator_request=True,
            now=NOW,
        )

        assert report["lifecycle_branch"] == "terminal_evidence"
        assert report["recommended_operator_action"] == "prepare_terminal_closeout"
        assert report["next_route"] == TERMINAL_CLOSEOUT_ROUTE
        assert report["required_future_ack"] == D3_OPEN_EXIT_LIFECYCLE_APPLY_ACK
        _assert_no_writes(report)


def test_safety_drift_blocks_before_poll():
    report = build_phase_d45_exit_operations_report(
        local_report=_local(
            open_d3_exit_count_for_position=2,
            blockers=["duplicate_open_d3_exit_orders_for_position"],
        ),
        lifecycle_poll_report=_poll("open"),
        explicit_operator_request=True,
        market_mid="75500",
        now=NOW,
    )

    assert report["lifecycle_branch"] == "blocked_p0_safety_drift"
    assert report["recommended_operator_action"] == "blocked_p0_review_required"
    assert "duplicate_open_d3_exit_orders_for_position" in report["blockers"]
    assert "open_exit_count_not_exactly_one" in report["blockers"]
    assert report["trigger_evaluation"]["poll_allowed"] is False
    _assert_no_writes(report)


def test_d5_no_fill_stale_metrics_remain_report_only():
    d5 = _d5("74000")

    assert d5["target_distance_abs"] == "2000.00"
    assert d5["target_distance_band"] == "approaching_target"
    assert d5["no_fill_recommendation_label"] == "monitor_later"
    assert d5["learning_to_execution_allowed"] is False
    assert d5["no_coinbase_call"] is True
    assert d5["state_write_performed"] is False


def test_cli_reads_fixtures_without_state_writes(tmp_path: Path):
    local_file = tmp_path / "local.json"
    poll_file = tmp_path / "poll.json"
    d5_file = tmp_path / "d5.json"
    untouched = tmp_path / "untouched.txt"
    local_file.write_text(json.dumps(_local()), encoding="utf-8")
    poll_file.write_text(json.dumps(_poll("open")), encoding="utf-8")
    d5_file.write_text(json.dumps(_d5("70000")), encoding="utf-8")
    untouched.write_text("same", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d45_exit_operations_report.py",
            "--local-d45-fixture",
            str(local_file),
            "--lifecycle-poll-fixture",
            str(poll_file),
            "--d5-metrics-fixture",
            str(d5_file),
            "--explicit-operator-request",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert report["lifecycle_branch"] == "open_keep_open"
    assert untouched.read_text(encoding="utf-8") == "same"
    _assert_no_writes(report)
