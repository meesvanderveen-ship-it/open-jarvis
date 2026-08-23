from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_level0_signal_backtest import (
    build_phase_d6_level0_signal_backtest_report,
    write_level0_signal_backtest_report,
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


def _rows(closes):
    day = 86400
    return [_candle(i * day, str(close)) for i, close in enumerate(closes)]


def _cross_rows(count: int = 100):
    closes = []
    for i in range(count):
        if i < 25:
            closes.append(100 - i)
        elif i < 65:
            closes.append(75 + (i - 25) * 3)
        else:
            closes.append(max(20, 195 - (i - 65) * 4))
    return _rows(closes)


def _flat_rows(count: int = 100):
    return _rows([100] * count)


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
    assert report["fixed_parameters_only"] is True
    assert report["strategy_parameter_mutation_allowed"] is False
    assert report["runtime_config_mutation_allowed"] is False


def test_level0_holdout_signal_report_is_fixed_cost_aware_and_safe(tmp_path: Path):
    path = _write(tmp_path / "research" / "cross.json", _cross_rows())

    report = build_phase_d6_level0_signal_backtest_report(
        candles_path=path,
        cost_scenario="zero_cost_reference",
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert report["status"] == "d6_level0_signal_backtest_report_ready"
    assert report["signal_name"] == "fixed_sma_cross_5_20"
    assert report["fixed_parameters"]["fast_window"] == 5
    assert report["fixed_parameters"]["slow_window"] == 20
    assert report["cost_scenario"] == "zero_cost_reference"
    assert report["split_count"] == 1
    split = report["per_split"][0]
    assert split["train"]["trade_metrics"]["trades_count"] >= 1
    assert split["train"]["exposure_metrics"]["exposed_bars"] > 0
    assert "forced_exit_at_range_end" in split["train"]["warnings"]
    assert report["baseline_reference"]["baseline_type"] == "buy_hold"
    assert report["summary"]["usable_for_future_research"] is True
    assert "fixed_signal_scaffold_only" in report["warnings"]
    _assert_safe(report)


def test_flat_fixture_has_zero_exposure_and_no_live_signal_emission(tmp_path: Path):
    path = _write(tmp_path / "research" / "flat.json", _flat_rows())

    report = build_phase_d6_level0_signal_backtest_report(
        candles_path=path,
        cost_scenario="standard_fee_only",
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    train = report["per_split"][0]["train"]
    assert train["trade_metrics"]["trades_count"] == 0
    assert train["return_metrics"]["net_return_pct"] == "0"
    assert "zero_exposure" in train["warnings"]
    assert report["signal_generation_performed"] is False
    _assert_safe(report)


def test_rolling_mode_produces_multiple_signal_splits(tmp_path: Path):
    path = _write(tmp_path / "research" / "cross.json", _cross_rows(130))

    report = build_phase_d6_level0_signal_backtest_report(
        candles_path=path,
        cost_scenario="conservative_slippage",
        split_mode="rolling",
        train_count=50,
        validation_count=10,
        test_count=10,
        step_count=20,
        max_splits=3,
    )

    assert report["split_count"] == 3
    assert [split["split_index"] for split in report["per_split"]] == [0, 1, 2]
    assert report["cost_assumptions"]["derived_costs"]["round_trip_cost_pct"] == "0.0105"
    _assert_safe(report)


def test_insufficient_candles_blocks_report(tmp_path: Path):
    path = _write(tmp_path / "research" / "short.json", _cross_rows(20))

    report = build_phase_d6_level0_signal_backtest_report(
        candles_path=path,
        train_count=15,
        validation_count=5,
        test_count=5,
    )

    assert report["status"] == "d6_level0_signal_backtest_report_blocked"
    assert report["split_count"] == 0
    assert "insufficient_candles_for_requested_split" in report["blockers"]
    assert report["summary"]["usable_for_future_research"] is False
    _assert_safe(report)


def test_rejects_unsupported_signal_scenario_and_initial_quote(tmp_path: Path):
    path = _write(tmp_path / "research" / "cross.json", _cross_rows())

    with pytest.raises(ValueError, match="unsupported_d6_level0_signal"):
        build_phase_d6_level0_signal_backtest_report(candles_path=path, signal_name="best_signal")
    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        build_phase_d6_level0_signal_backtest_report(candles_path=path, cost_scenario="best_cost")
    with pytest.raises(ValueError, match="initial_quote_must_be_positive"):
        build_phase_d6_level0_signal_backtest_report(candles_path=path, initial_quote="0")


def test_refuses_state_paths_and_writes_only_explicit_research_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "cross.json", _cross_rows())
    report = build_phase_d6_level0_signal_backtest_report(
        candles_path=path,
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    output = tmp_path / "reports" / "d6" / "level0.json"

    assert write_level0_signal_backtest_report(report, output) == output
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["signal_name"] == "fixed_sma_cross_5_20"
    assert written["no_coinbase_call"] is True

    state = _write(tmp_path / "state" / "candles.json", _cross_rows())
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_level0_signal_backtest_report(candles_path=state)
    with pytest.raises(ValueError, match="state"):
        write_level0_signal_backtest_report(report, tmp_path / "state" / "level0.json")
    with pytest.raises(ValueError, match="env"):
        write_level0_signal_backtest_report(report, tmp_path / ".env")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "cross.json", _cross_rows())
    output = tmp_path / "reports" / "d6" / "level0.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_level0_signal_backtest.py",
            "--candles",
            str(path),
            "--cost-scenario",
            "zero_cost_reference",
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
    assert stdout_report["signal_name"] == "fixed_sma_cross_5_20"
    _assert_safe(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_level0_signal_backtest.py",
            "--candles",
            str(path),
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
