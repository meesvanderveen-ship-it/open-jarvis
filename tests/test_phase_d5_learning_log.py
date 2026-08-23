from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report
from bot.phase_d5_learning_log import (
    build_phase_d5_learning_event,
    build_phase_d5_learning_log_report,
    events_to_jsonl,
)


NOW = datetime(2026, 5, 29, 16, 0, tzinfo=timezone.utc)


def _lifecycle(status="open", **overrides):
    payload = {
        "ticker": "BTC-USDC",
        "client_order_id": "phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443",
        "exchange_order_id": "6f6fa436-f5b9-4df5-bb23-ddf35a27a56a",
        "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "lifecycle_status": status,
        "submitted_at": "2026-05-29T06:44:43+00:00",
        "first_seen_open_at": "2026-05-29T06:44:44+00:00",
        "planned_entry_price": "80000",
        "planned_exit_price": "76000.00",
        "planned_size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "filled_base": "0",
        "filled_quote": "0",
        "fill_count": 0,
    }
    payload.update(overrides)
    return payload


def _metrics(status="open", **overrides):
    lifecycle = _lifecycle(status, **overrides.pop("lifecycle_overrides", {}))
    fills = {
        "filled_base": lifecycle.get("filled_base", "0"),
        "filled_quote": lifecycle.get("filled_quote", "0"),
        "avg_fill_price": lifecycle.get("avg_fill_price", "0"),
        "fees": lifecycle.get("fees", "0"),
        "fill_count": lifecycle.get("fill_count", 0),
    }
    fills.update(overrides.pop("fills", {}))
    return build_phase_d5_execution_metrics_report(
        lifecycle_event=lifecycle,
        plan_fields={"planned_entry_price": "80000", "planned_exit_price": "76000.00", "planned_size_base": "0.00006489"},
        market_refs={"decision_mid": "74000", "decision_best_bid": "73999.99", "decision_best_ask": "74000.01"},
        fills=fills,
        d4_decision=overrides.pop("d4", None),
        now=NOW,
    )


def _d45(branch="open_keep_open", **overrides):
    payload = {
        "phase": "D45_exit_operations_hardening_v1",
        "lifecycle_branch": branch,
        "recommended_operator_action": "wait_for_trigger",
        "next_route": "keep_open",
        "active_order_summary": {
            "ticker": "BTC-USDC",
            "client_order_id": "phased4-BTCUSDC-TP1-repl-bc3330fe-20260529064443",
            "exchange_order_id": "6f6fa436-f5b9-4df5-bb23-ddf35a27a56a",
            "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
            "limit_price": "76000.00",
            "remaining_size": "0.00006489",
        },
        "trigger_evaluation": {
            "market": {
                "market_mid": "74000",
                "distance_abs": "2000.00",
                "distance_pct_of_limit": "0.02631578947368421052631578947",
                "band": "approaching_target",
            }
        },
        "blockers": [],
        "learning_to_execution_allowed": False,
        "state_write_performed": False,
    }
    payload.update(overrides)
    return payload


def _assert_report_only(event):
    assert event["learning_to_execution_allowed"] is False
    assert event["parameter_change_allowed"] is False
    assert event["report_only"] is True
    assert event["no_coinbase_call"] is True
    assert event["no_live_action"] is True
    assert event["state_write_performed"] is False


def test_open_no_fill_learning_event_contains_target_and_stale_fields():
    event = build_phase_d5_learning_event(
        event_type="open_no_fill_observation",
        lifecycle_event=_lifecycle("open"),
        d5_metrics_report=_metrics("open"),
        d45_report=_d45(),
        operator_decision="wait_for_trigger",
        now=NOW,
    )

    assert event["lifecycle_branch"] == "OPEN"
    assert event["target_distance_abs"] == "2000.00"
    assert event["target_distance_band"] == "approaching_target"
    assert event["no_fill_duration_seconds"]
    assert event["stale_order_age_seconds"]
    assert event["operator_decision"] == "wait_for_trigger"
    _assert_report_only(event)


def test_filled_learning_event_captures_fill_slippage_and_fees():
    lifecycle = _lifecycle(
        "filled",
        filled_at="2026-05-29T10:00:00+00:00",
        closed_at="2026-05-29T10:00:00+00:00",
        filled_base="0.00006489",
        filled_quote="4.93164000",
        avg_fill_price="76000",
        fees="0.00616455",
        fill_count=1,
        remaining_size="0",
    )
    event = build_phase_d5_learning_event(
        event_type="filled_observation",
        lifecycle_event=lifecycle,
        d5_metrics_report=_metrics("filled", lifecycle_overrides=lifecycle),
        d45_report=_d45("fill_evidence", recommended_operator_action="prepare_fill_lifecycle_apply"),
        final_outcome="filled",
        now=NOW,
    )

    assert event["lifecycle_branch"] == "FILLED"
    assert event["actual_fill_price"] == "76000"
    assert event["fill_count"] == 1
    assert event["filled_base"] == "0.00006489"
    assert event["fees"] == "0.00616455"
    assert event["slippage_vs_decision_mid_pct"]
    assert event["final_outcome"] == "filled"
    _assert_report_only(event)


def test_terminal_and_reprice_cancel_replace_events_are_exportable():
    terminal = build_phase_d5_learning_event(
        event_type="terminal_observation",
        lifecycle_event=_lifecycle("cancelled", cancelled_at="2026-05-29T11:00:00+00:00"),
        d5_metrics_report=_metrics("cancelled", lifecycle_overrides={"cancelled_at": "2026-05-29T11:00:00+00:00"}),
        d45_report=_d45("terminal_evidence", recommended_operator_action="prepare_terminal_closeout"),
        final_outcome="terminal_no_fill",
        now=NOW,
    )
    reprice = build_phase_d5_learning_event(
        event_type="reprice_cancel_replace_observation",
        lifecycle_event=_lifecycle("open"),
        d5_metrics_report=_metrics("open", d4={"cancel_replace_outcome": "replacement_opened"}),
        d4_decision_report={
            "decision": "reprice_76000",
            "reason": "far_from_target_recovery_derisk",
            "cancel_replace_outcome": "old_cancelled_replacement_opened",
        },
        operator_decision="approved_cancel_first_reprice",
        final_outcome="replacement_open",
        now=NOW,
    )
    report = build_phase_d5_learning_log_report(events=[terminal, reprice], source="fixture", now=NOW)
    jsonl = events_to_jsonl(report["events"])
    rows = [json.loads(line) for line in jsonl.splitlines()]

    assert terminal["lifecycle_branch"] == "CANCELLED"
    assert terminal["final_outcome"] == "terminal_no_fill"
    assert reprice["reprice_decision"] == "reprice_76000"
    assert reprice["reprice_reason"] == "far_from_target_recovery_derisk"
    assert reprice["cancel_replace_outcome"] == "old_cancelled_replacement_opened"
    assert report["event_count"] == 2
    assert rows[0]["parameter_change_allowed"] is False
    assert rows[1]["learning_to_execution_allowed"] is False


def test_p0_blockers_set_safety_drift_without_allowing_parameter_change():
    event = build_phase_d5_learning_event(
        event_type="safety_observation",
        lifecycle_event=_lifecycle("open"),
        d45_report=_d45(
            "blocked_p0_safety_drift",
            blockers=["duplicate_open_d3_exit_orders_for_position", "reservation_not_equal_remaining_size"],
        ),
        now=NOW,
    )

    assert event["lifecycle_branch"] == "UNKNOWN"
    assert event["safety_drift"] is True
    assert "duplicate_open_d3_exit_orders_for_position" in event["blockers"]
    _assert_report_only(event)


def test_cli_exports_jsonl_from_fixtures_without_touching_state(tmp_path: Path):
    lifecycle_file = tmp_path / "lifecycle.json"
    metrics_file = tmp_path / "metrics.json"
    d45_file = tmp_path / "d45.json"
    out_file = tmp_path / "learning.jsonl"
    sentinel = tmp_path / "sentinel.txt"
    lifecycle_file.write_text(json.dumps(_lifecycle("open")), encoding="utf-8")
    metrics_file.write_text(json.dumps(_metrics("open")), encoding="utf-8")
    d45_file.write_text(json.dumps(_d45()), encoding="utf-8")
    sentinel.write_text("unchanged", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d5_learning_log.py",
            "--lifecycle-fixture",
            str(lifecycle_file),
            "--d5-metrics-fixture",
            str(metrics_file),
            "--d45-fixture",
            str(d45_file),
            "--event-type",
            "open_no_fill_observation",
            "--operator-decision",
            "wait_for_trigger",
            "--jsonl",
            "--output",
            str(out_file),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    row = json.loads(out_file.read_text(encoding="utf-8").strip())

    assert result.stdout == ""
    assert row["event_type"] == "open_no_fill_observation"
    assert row["parameter_change_allowed"] is False
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    _assert_report_only(row)

