from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from bot.phase_d5_execution_metrics import build_phase_d5_execution_metrics_report


NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


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


def _plan(**overrides):
    payload = {
        "planned_entry_price": "80000",
        "planned_exit_price": "84800.00",
        "planned_size_base": "0.00006489",
        "exit_label": "TP1",
    }
    payload.update(overrides)
    return payload


def _event(status: str, **overrides):
    payload = {
        "ticker": "BTC-USDC",
        "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-8T1636569429220000",
        "exchange_order_id": "daa5ef77-9967-4fb0-b0c7-4f7c0680b512",
        "lifecycle_status": status,
        "order_created_at": "2026-05-29T10:00:00+00:00",
        "submitted_at": "2026-05-29T10:00:05+00:00",
        "first_seen_open_at": "2026-05-29T10:00:10+00:00",
    }
    payload.update(overrides)
    return payload


def _fills(**overrides):
    payload = {
        "filled_base": "0",
        "filled_quote": "0",
        "avg_fill_price": "0",
        "fees": "0",
        "fill_count": 0,
    }
    payload.update(overrides)
    return payload


def _market(**overrides):
    payload = {
        "decision_mid": "84800",
        "decision_best_bid": "84799.99",
        "decision_best_ask": "84800.00",
        "fill_reference_mid": "84800",
    }
    payload.update(overrides)
    return payload


def _report(*, event=None, plan=None, market=None, fills=None, d4=None, client=None):
    return build_phase_d5_execution_metrics_report(
        lifecycle_event=event or _event("open"),
        plan_fields=plan or _plan(),
        market_refs=_market() if market is None else market,
        fills=fills or _fills(),
        d4_decision=d4,
        coinbase_client=client,
        now=NOW,
    )


def _assert_analysis_only(report):
    assert report["learning_to_execution_allowed"] is False
    assert report["learning_recommendation_mode"] == "report_only"
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False


def test_open_no_fill_current_tp1_not_training_eligible():
    report = _report(event=_event("open"), fills=_fills())

    assert report["lifecycle_status"] == "open"
    assert report["fill_quality_label"] == "no_fill_open"
    assert report["is_complete_lifecycle_event"] is False
    assert report["is_training_eligible"] is False
    assert report["no_fill_duration_seconds"] == "7190.0"
    assert "open_lifecycle_not_training_eligible" in report["blockers"]
    _assert_analysis_only(report)


def test_filled_above_planned_is_filled_good_with_positive_edge():
    report = _report(
        event=_event("filled", filled_at="2026-05-29T10:05:00+00:00", closed_at="2026-05-29T10:05:00+00:00"),
        fills=_fills(
            filled_base="0.00006489",
            filled_quote="5.5338648000",
            avg_fill_price="85280.00",
            fees="0.0069",
            fill_count=1,
            first_fill_at="2026-05-29T10:04:30+00:00",
            final_fill_at="2026-05-29T10:05:00+00:00",
        ),
    )

    assert report["fill_quality_label"] == "filled_good"
    assert report["is_complete_lifecycle_event"] is True
    assert report["realized_exit_price"] == "85280.00"
    assert report["realized_vs_planned_edge_pct"] == "0.005660377358490566037735849057"
    assert report["fill_latency_seconds"] == "265.0"
    _assert_analysis_only(report)


def test_filled_below_planned_is_filled_bad_without_auto_action():
    report = _report(
        event=_event("filled", filled_at="2026-05-29T10:05:00+00:00"),
        fills=_fills(
            filled_base="0.00006489",
            filled_quote="5.4507600000",
            avg_fill_price="84000.00",
            fees="0.0068",
            fill_count=1,
            first_fill_at="2026-05-29T10:04:30+00:00",
            final_fill_at="2026-05-29T10:05:00+00:00",
        ),
    )

    assert report["fill_quality_label"] == "filled_bad"
    assert report["realized_vs_planned_edge_pct"].startswith("-0.009433962264")
    _assert_analysis_only(report)


def test_partial_open_not_training_eligible():
    report = _report(
        event=_event("partial"),
        fills=_fills(
            filled_base="0.00001",
            filled_quote="0.848",
            avg_fill_price="84800",
            fill_count=1,
            first_fill_at="2026-05-29T10:04:30+00:00",
        ),
    )

    assert report["lifecycle_status"] == "partial"
    assert report["fill_quality_label"] == "partial"
    assert report["is_complete_lifecycle_event"] is False
    assert "partial_lifecycle_without_terminal_not_training_eligible" in report["blockers"]
    _assert_analysis_only(report)


def test_cancelled_zero_fill_terminal_no_fill_complete_not_execution_changing():
    report = _report(event=_event("cancelled", cancelled_at="2026-05-29T11:00:00+00:00"), fills=_fills())

    assert report["fill_quality_label"] == "terminal_no_fill"
    assert report["is_complete_lifecycle_event"] is True
    assert report["is_training_eligible"] is False
    assert report["no_fill_duration_seconds"] == "3590.0"
    _assert_analysis_only(report)


def test_expired_zero_fill_terminal_no_fill():
    report = _report(event=_event("expired", expired_at="2026-05-29T11:00:00+00:00"), fills=_fills())

    assert report["lifecycle_status"] == "expired"
    assert report["fill_quality_label"] == "terminal_no_fill"
    assert report["is_complete_lifecycle_event"] is True
    _assert_analysis_only(report)


def test_rejected_zero_fill_terminal_no_fill_rejected():
    report = _report(event=_event("rejected", rejected_at="2026-05-29T11:00:00+00:00"), fills=_fills())

    assert report["lifecycle_status"] == "rejected"
    assert report["fill_quality_label"] == "terminal_no_fill"
    assert report["is_complete_lifecycle_event"] is True
    _assert_analysis_only(report)


def test_missing_market_snapshot_warns_without_crash():
    report = _report(
        event=_event("filled", filled_at="2026-05-29T10:05:00+00:00"),
        market={},
        fills=_fills(filled_base="0.00006489", filled_quote="5.5338648000", avg_fill_price="85280.00", fill_count=1),
    )

    assert "market_decision_mid_missing_slippage_partial" in report["warnings"]
    assert "market_decision_best_bid_missing_slippage_partial" in report["warnings"]
    assert report["slippage_vs_decision_mid_pct"] == ""
    _assert_analysis_only(report)


def test_fee_calculation_estimates_bps():
    report = _report(
        event=_event("filled", filled_at="2026-05-29T10:05:00+00:00"),
        fills=_fills(
            filled_base="0.00006489",
            filled_quote="5.5338648000",
            avg_fill_price="85280.00",
            fees="0.006917331",
            fill_count=1,
        ),
    )

    assert report["fee_quote"] == "0.006917331"
    assert report["fee_bps_estimate"] == "12.50000"
    _assert_analysis_only(report)


def test_learning_to_execution_gate_always_false_report_only():
    report = _report(
        event=_event("filled", filled_at="2026-05-29T10:05:00+00:00"),
        fills=_fills(filled_base="0.00006489", filled_quote="5.5338648000", avg_fill_price="85280.00", fill_count=1),
        d4={"proposed_action": "dry_run_cancel_replace_plan_ready"},
    )

    assert report["learning_to_execution_allowed"] is False
    assert report["required_future_gate_for_execution"]
    assert report["cancel_replace_outcome"] == "dry_run_cancel_replace_plan_ready"
    _assert_analysis_only(report)


def test_cli_reads_fixtures_and_writes_no_state_files(tmp_path: Path):
    lifecycle_file = tmp_path / "lifecycle.json"
    plan_file = tmp_path / "plan.json"
    market_file = tmp_path / "market.json"
    fills_file = tmp_path / "fills.json"
    state_file = tmp_path / "state_should_not_change.json"
    lifecycle_file.write_text(json.dumps(_event("filled", filled_at="2026-05-29T10:05:00+00:00"), indent=2), encoding="utf-8")
    plan_file.write_text(json.dumps(_plan(), indent=2), encoding="utf-8")
    market_file.write_text(json.dumps(_market(), indent=2), encoding="utf-8")
    fills_file.write_text(json.dumps(_fills(filled_base="0.00006489", filled_quote="5.5338648000", avg_fill_price="85280.00", fill_count=1), indent=2), encoding="utf-8")
    state_file.write_text("unchanged", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d5_execution_metrics.py",
            "--lifecycle-fixture",
            str(lifecycle_file),
            "--plan-fixture",
            str(plan_file),
            "--market-fixture",
            str(market_file),
            "--fills-fixture",
            str(fills_file),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        text=True,
        capture_output=True,
    )
    report = json.loads(result.stdout)

    assert report["status"] == "d5_execution_metrics_report_ready"
    assert report["fill_quality_label"] == "filled_good"
    assert state_file.read_text(encoding="utf-8") == "unchanged"
    _assert_analysis_only(report)


def test_coinbase_client_write_trap_is_ignored_and_not_called():
    client = WriteTrapClient()
    report = _report(event=_event("open"), fills=_fills(), client=client)

    assert "coinbase_client_ignored_analysis_only" in report["warnings"]
    assert client.cancelled == []
    assert client.placed == []
    _assert_analysis_only(report)
