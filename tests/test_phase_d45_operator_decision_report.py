from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.phase_d45_operator_decision_report import build_phase_d45_operator_decision_report


NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
CLIENT_ORDER_ID = "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000"
EXCHANGE_ORDER_ID = "daa5ef77-9967-4fb0-b0c7-4f7c0680b512"
LINKED_POSITION_ID = "76310097-849e-481c-b587-ba44bc3330fe"


class WriteTrapClient:
    def __init__(self):
        self.cancelled = []
        self.placed = []

    def cancel_order(self, *args, **kwargs):
        self.cancelled.append((args, kwargs))
        raise AssertionError("cancel_order must not be called")

    def place_limit_order(self, *args, **kwargs):
        self.placed.append((args, kwargs))
        raise AssertionError("place_limit_order must not be called")


def _lifecycle(status="open", **overrides):
    payload = {
        "ticker": "BTC-USDC",
        "client_order_id": CLIENT_ORDER_ID,
        "exchange_order_id": EXCHANGE_ORDER_ID,
        "linked_position_id": LINKED_POSITION_ID,
        "lifecycle_status": status,
        "size_base": "0.00006489",
        "remaining_size": "0.00006489",
        "limit_price": "84800.00",
        "filled_base": "0",
        "fill_count": 0,
    }
    payload.update(overrides)
    return payload


def _d4_preview(action="keep_open", **overrides):
    payload = {
        "status": "d4_trailing_preview_keep_open",
        "proposed_action": action,
        "proposed_replacement_price": "",
        "activation_state": "inactive",
        "reason": "price_below_activation",
        "blockers": [],
        "warnings": [],
    }
    if action == "preview_reprice_candidate":
        payload.update({
            "status": "d4_trailing_preview_candidate_ready",
            "proposed_replacement_price": "84280.00",
            "activation_state": "active",
            "reason": "trailing_stop_triggered_candidate_preview_only",
        })
    payload.update(overrides)
    return payload


def _d4_planner(action="no_op_keep_open", **overrides):
    payload = {
        "status": "d4_cancel_replace_plan_noop_keep_open",
        "proposed_action": action,
        "replacement_price": "",
        "replacement_size_base": "0.00006489",
        "cancel_first_required": True,
        "replace_only_after_confirmed_cancel": True,
        "required_future_ack": "",
        "blockers": [],
        "warnings": [],
    }
    if action == "dry_run_cancel_replace_plan_ready":
        payload.update({
            "status": "d4_cancel_replace_plan_ready",
            "replacement_price": "84280.00",
            "required_future_ack": "I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT",
        })
    payload.update(overrides)
    return payload


def _d5(label="no_fill_open", **overrides):
    payload = {
        "status": "d5_execution_metrics_report_ready",
        "lifecycle_status": "open",
        "fill_quality_label": label,
        "realized_vs_planned_edge_pct": "",
        "no_fill_duration_seconds": "7190.0",
        "learning_to_execution_allowed": False,
        "warnings": [],
    }
    payload.update(overrides)
    return payload


def _report(*, lifecycle=None, preview=None, planner=None, d5=None, mode="decision_only", client=None):
    return build_phase_d45_operator_decision_report(
        lifecycle_event=lifecycle or _lifecycle(),
        d4_preview_report=preview,
        d4_planner_report=planner,
        d5_metrics_report=d5,
        operator_mode=mode,
        coinbase_client=client,
        now=NOW,
    )


def _assert_report_safety(report):
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["learning_to_execution_allowed"] is False


def test_open_no_fill_keep_open_waits_for_trigger():
    report = _report(preview=_d4_preview(), planner=_d4_planner(), d5=_d5())

    assert report["lifecycle_branch"] == "open_keep_open"
    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert report["required_future_ack"] == ""
    _assert_report_safety(report)


def test_open_no_fill_d4_candidate_consider_reprice_future_ack():
    report = _report(
        preview=_d4_preview("preview_reprice_candidate"),
        planner=_d4_planner("dry_run_cancel_replace_plan_ready"),
        d5=_d5(),
        mode="future_reprice_consideration",
    )

    assert report["recommended_operator_action"] == "consider_reprice_decision"
    assert report["required_future_ack"] == "I_UNDERSTAND_AND_APPROVE_D4_TRAILING_CANCEL_REPLACE_ONE_SHOT"
    assert report["d4_planner_summary"]["cancel_first_required"] is True
    _assert_report_safety(report)


def test_partial_and_filled_evidence_prepare_fill_lifecycle_apply():
    for status, filled_base, fill_count in (("partial", "0.00001", 1), ("filled", "0.00006489", 1)):
        report = _report(
            lifecycle=_lifecycle(status, filled_base=filled_base, fill_count=fill_count),
            preview=_d4_preview("preview_reprice_candidate"),
            planner=_d4_planner("dry_run_cancel_replace_plan_ready"),
            d5=_d5("partial", lifecycle_status=status),
        )
        assert report["lifecycle_branch"] == "fill_evidence"
        assert report["recommended_operator_action"] == "prepare_fill_lifecycle_apply"
        assert report["required_future_ack"] == ""
        _assert_report_safety(report)


def test_terminal_evidence_prepares_terminal_closeout():
    for status in ("cancelled", "expired", "rejected"):
        report = _report(
            lifecycle=_lifecycle(status),
            preview=_d4_preview("preview_reprice_candidate"),
            planner=_d4_planner("dry_run_cancel_replace_plan_ready"),
            d5=_d5("terminal_no_fill", lifecycle_status=status),
        )
        assert report["lifecycle_branch"] == "terminal_evidence"
        assert report["recommended_operator_action"] == "prepare_terminal_closeout"
        _assert_report_safety(report)


def test_duplicate_or_oversell_blocker_forces_p0_review():
    report = _report(
        lifecycle=_lifecycle(),
        preview=_d4_preview(blockers=["duplicate_open_d3_exit_orders_for_position"]),
        planner=_d4_planner(blockers=["reserved_base_less_than_replacement_size"]),
        d5=_d5(),
    )

    assert report["recommended_operator_action"] == "blocked_p0_review_required"
    assert "duplicate_oversell_or_reservation_safety_blocker" in report["blockers"]
    _assert_report_safety(report)


def test_missing_d4_d5_fixtures_warn_without_crash():
    report = _report()

    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert "d4_preview_missing" in report["warnings"]
    assert "d4_planner_missing" in report["warnings"]
    assert "d5_metrics_missing" in report["warnings"]
    _assert_report_safety(report)


def test_d5_filled_good_never_authorizes_execution():
    report = _report(
        lifecycle=_lifecycle("open"),
        preview=_d4_preview(),
        planner=_d4_planner(),
        d5=_d5("filled_good", lifecycle_status="filled", realized_vs_planned_edge_pct="0.01", learning_to_execution_allowed=False),
    )

    assert report["recommended_operator_action"] == "wait_for_trigger"
    assert report["d5_metrics_summary"]["learning_to_execution_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    _assert_report_safety(report)


def test_cli_reads_fixtures_and_writes_no_state_files(tmp_path: Path):
    lifecycle_file = tmp_path / "lifecycle.json"
    preview_file = tmp_path / "preview.json"
    planner_file = tmp_path / "planner.json"
    d5_file = tmp_path / "d5.json"
    state_file = tmp_path / "state_should_not_change.json"
    lifecycle_file.write_text(json.dumps(_lifecycle(), indent=2), encoding="utf-8")
    preview_file.write_text(json.dumps(_d4_preview("preview_reprice_candidate"), indent=2), encoding="utf-8")
    planner_file.write_text(json.dumps(_d4_planner("dry_run_cancel_replace_plan_ready"), indent=2), encoding="utf-8")
    d5_file.write_text(json.dumps(_d5(), indent=2), encoding="utf-8")
    state_file.write_text("unchanged", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d45_operator_decision_report.py",
            "--lifecycle-fixture",
            str(lifecycle_file),
            "--d4-preview-fixture",
            str(preview_file),
            "--d4-planner-fixture",
            str(planner_file),
            "--d5-metrics-fixture",
            str(d5_file),
            "--operator-mode",
            "future_reprice_consideration",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert report["recommended_operator_action"] == "consider_reprice_decision"
    assert state_file.read_text(encoding="utf-8") == "unchanged"
    _assert_report_safety(report)


def test_fake_client_write_trap_not_called():
    client = WriteTrapClient()
    report = _report(preview=_d4_preview(), planner=_d4_planner(), d5=_d5(), client=client)

    assert "coinbase_client_ignored_report_only" in report["warnings"]
    assert client.cancelled == []
    assert client.placed == []
    _assert_report_safety(report)
