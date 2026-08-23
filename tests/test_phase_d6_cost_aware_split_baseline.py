from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_cost_aware_split_baseline import (
    build_phase_d6_cost_aware_split_baseline_report,
    write_cost_aware_split_baseline_report,
)


def _candle(start: int, close: str = "100", timeframe: str = "1D"):
    return {
        "product_id": "BTC-USDC",
        "timeframe": timeframe,
        "start": start,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1",
    }


def _write(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _rows(count: int, timeframe: str = "1D"):
    step = 86400 if timeframe == "1D" else 3600
    return [_candle(i * step, str(100 + i), timeframe=timeframe) for i in range(count)]


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_live_action"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["no_bulk_fetch"] is True
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["signal_generation_performed"] is False
    assert report["live_recommendation"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_holdout_standard_fee_only_is_cost_adjusted_and_safe(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))

    report = build_phase_d6_cost_aware_split_baseline_report(
        candles_path=path,
        cost_scenario="standard_fee_only",
        split_mode="holdout",
        train_count=60,
        validation_count=20,
        test_count=20,
        initial_quote="1000",
    )

    assert report["status"] == "d6_cost_aware_split_baseline_report_ready"
    assert report["baseline_type"] == "buy_hold"
    assert report["cost_scenario"] == "standard_fee_only"
    assert report["derived_costs"]["round_trip_cost_pct"] == "0.008"
    assert report["split_count"] == 1
    split = report["per_split"][0]
    assert split["train"]["return_metrics"]["net_return_pct"] == "57.730544"
    assert split["validation"]["return_metrics"]["net_return_pct"] == "10.98179"
    assert split["test"]["return_metrics"]["net_return_pct"] == "9.67288"
    assert split["test"]["cost_metrics"]["total_cost_quote_estimate"] == "8.404533333333333333333333332"
    assert report["summary"]["average_validation_net_return_pct"] == "10.98179"
    assert report["summary"]["average_test_net_return_pct"] == "9.67288"
    assert "not_cost_scenario_ranking" in report["warnings"]
    _assert_safe(report)


def test_zero_cost_matches_gross_buy_hold_returns_and_warns(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))

    report = build_phase_d6_cost_aware_split_baseline_report(
        candles_path=path,
        cost_scenario="zero_cost_reference",
        split_mode="holdout",
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    split = report["per_split"][0]
    assert split["train"]["return_metrics"]["net_return_pct"] == "59"
    assert split["validation"]["return_metrics"]["net_return_pct"] == "11.875"
    assert split["test"]["return_metrics"]["net_return_pct"] == "10.5555555555555555555555556"
    assert "unrealistic_zero_cost_assumption" in report["warnings"]
    _assert_safe(report)


def test_rolling_stress_cost_generates_multiple_cost_aware_splits(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(120))

    report = build_phase_d6_cost_aware_split_baseline_report(
        candles_path=path,
        cost_scenario="stress_cost",
        split_mode="rolling",
        train_count=50,
        validation_count=10,
        test_count=10,
        step_count=20,
        max_splits=3,
    )

    assert report["split_count"] == 3
    assert [s["split_index"] for s in report["per_split"]] == [0, 1, 2]
    assert report["derived_costs"]["round_trip_cost_pct"] == "0.02"
    assert "stress_cost_assumption" in report["warnings"]
    _assert_safe(report)


def test_insufficient_candles_blocks_report_without_live_action(tmp_path: Path):
    path = _write(tmp_path / "research" / "short.json", _rows(20))

    report = build_phase_d6_cost_aware_split_baseline_report(
        candles_path=path,
        train_count=15,
        validation_count=5,
        test_count=5,
    )

    assert report["status"] == "d6_cost_aware_split_baseline_report_blocked"
    assert report["split_count"] == 0
    assert "insufficient_candles_for_requested_split" in report["blockers"]
    assert report["summary"]["usable_for_future_research"] is False
    _assert_safe(report)


def test_rejects_unsupported_baseline_scenario_and_invalid_initial_quote(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))

    with pytest.raises(ValueError, match="unsupported_d6_cost_aware_split_baseline"):
        build_phase_d6_cost_aware_split_baseline_report(candles_path=path, baseline="simple_ma")
    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        build_phase_d6_cost_aware_split_baseline_report(candles_path=path, cost_scenario="best_cost")
    with pytest.raises(ValueError, match="initial_quote_must_be_positive"):
        build_phase_d6_cost_aware_split_baseline_report(candles_path=path, initial_quote="0")


def test_refuses_state_paths_and_writes_only_explicit_research_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))
    report = build_phase_d6_cost_aware_split_baseline_report(
        candles_path=path,
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    output = tmp_path / "reports" / "d6" / "cost-aware.json"

    assert write_cost_aware_split_baseline_report(report, output) == output
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["cost_scenario"] == "standard_fee_only"
    assert written["no_coinbase_call"] is True

    state = _write(tmp_path / "state" / "candles.json", _rows(100))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_cost_aware_split_baseline_report(candles_path=state)
    with pytest.raises(ValueError, match="state"):
        write_cost_aware_split_baseline_report(report, tmp_path / "state" / "cost-aware.json")
    with pytest.raises(ValueError, match="env"):
        write_cost_aware_split_baseline_report(report, tmp_path / ".env")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))
    output = tmp_path / "reports" / "d6" / "cost-aware.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_cost_aware_split_baseline.py",
            "--candles",
            str(path),
            "--cost-scenario",
            "conservative_slippage",
            "--split-mode",
            "holdout",
            "--train-count",
            "60",
            "--validation-count",
            "20",
            "--test-count",
            "20",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["cost_scenario"] == "conservative_slippage"
    assert stdout_report["derived_costs"]["round_trip_cost_pct"] == "0.0105"
    _assert_safe(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_cost_aware_split_baseline.py",
            "--candles",
            str(path),
            "--cost-scenario",
            "standard_fee_only",
            "--split-mode",
            "rolling",
            "--train-count",
            "50",
            "--validation-count",
            "10",
            "--test-count",
            "10",
            "--output",
            str(output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    assert output_result.stdout == ""
    assert json.loads(output.read_text(encoding="utf-8"))["parameter_search_performed"] is False
