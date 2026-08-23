from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_split_aware_baseline import (
    build_phase_d6_split_aware_baseline_report,
    write_split_aware_baseline_report,
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
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_holdout_split_aware_buy_hold_report_is_deterministic_and_safe(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))

    report = build_phase_d6_split_aware_baseline_report(
        candles_path=path,
        split_mode="holdout",
        train_count=60,
        validation_count=20,
        test_count=20,
        initial_quote="1000",
        fee_pct="0",
    )

    assert report["status"] == "d6_split_aware_baseline_report_ready"
    assert report["product_id"] == "BTC-USDC"
    assert report["timeframe"] == "1D"
    assert report["baseline_type"] == "buy_hold"
    assert report["split_count"] == 1
    split = report["per_split"][0]
    assert split["train"]["return_metrics"]["net_return_pct"] == "59"
    assert split["validation"]["return_metrics"]["net_return_pct"] == "11.875"
    assert split["test"]["return_metrics"]["net_return_pct"] == "10.5555555555555555555555556"
    assert report["summary"]["average_validation_net_return_pct"] == "11.875"
    assert report["summary"]["average_test_net_return_pct"] == "10.5555555555555555555555556"
    assert report["summary"]["usable_for_future_research"] is True
    assert "not_strategy_recommendation" in report["warnings"]
    _assert_safe(report)


def test_rolling_and_expanding_reports_include_multiple_split_metrics(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(120))

    rolling = build_phase_d6_split_aware_baseline_report(
        candles_path=path,
        split_mode="rolling",
        train_count=50,
        validation_count=10,
        test_count=10,
        step_count=20,
        max_splits=3,
        fee_pct="0",
    )
    expanding = build_phase_d6_split_aware_baseline_report(
        candles_path=path,
        split_mode="expanding",
        train_count=50,
        validation_count=10,
        test_count=10,
        step_count=20,
        max_splits=3,
        fee_pct="0",
    )

    assert rolling["split_count"] == 3
    assert [s["split_index"] for s in rolling["per_split"]] == [0, 1, 2]
    assert expanding["split_count"] == 3
    assert [s["train"]["range"]["end_index_exclusive"] for s in expanding["per_split"]] == [50, 70, 90]
    _assert_safe(rolling)
    _assert_safe(expanding)


def test_insufficient_candles_blocks_report_without_state_or_live_action(tmp_path: Path):
    path = _write(tmp_path / "research" / "short.json", _rows(20))

    report = build_phase_d6_split_aware_baseline_report(
        candles_path=path,
        train_count=15,
        validation_count=5,
        test_count=5,
    )

    assert report["status"] == "d6_split_aware_baseline_report_blocked"
    assert report["split_count"] == 0
    assert "insufficient_candles_for_requested_split" in report["blockers"]
    assert report["summary"]["usable_for_future_research"] is False
    assert "walk_forward_split_unusable" in report["warnings"]
    _assert_safe(report)


def test_rejects_unsupported_baseline_and_invalid_money_inputs(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))

    with pytest.raises(ValueError, match="unsupported_d6_split_aware_baseline"):
        build_phase_d6_split_aware_baseline_report(candles_path=path, baseline="simple_ma")
    with pytest.raises(ValueError, match="initial_quote_must_be_positive"):
        build_phase_d6_split_aware_baseline_report(candles_path=path, initial_quote="0")
    with pytest.raises(ValueError, match="fee_pct_must_be_between_0_and_1"):
        build_phase_d6_split_aware_baseline_report(candles_path=path, fee_pct="1")


def test_refuses_state_paths_and_writes_only_explicit_research_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))
    report = build_phase_d6_split_aware_baseline_report(
        candles_path=path,
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    output = tmp_path / "reports" / "d6" / "split-aware.json"

    assert write_split_aware_baseline_report(report, output) == output
    written = json.loads(output.read_text(encoding="utf-8"))
    assert written["baseline_type"] == "buy_hold"
    assert written["no_coinbase_call"] is True

    state = _write(tmp_path / "state" / "candles.json", _rows(100))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_split_aware_baseline_report(candles_path=state)
    with pytest.raises(ValueError, match="state"):
        write_split_aware_baseline_report(report, tmp_path / "state" / "split-aware.json")
    with pytest.raises(ValueError, match="env"):
        write_split_aware_baseline_report(report, tmp_path / ".env")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))
    output = tmp_path / "reports" / "d6" / "split-aware.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_split_aware_baseline.py",
            "--candles",
            str(path),
            "--split-mode",
            "holdout",
            "--train-count",
            "60",
            "--validation-count",
            "20",
            "--test-count",
            "20",
            "--fee-pct",
            "0",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["summary"]["average_validation_net_return_pct"] == "11.875"
    _assert_safe(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_split_aware_baseline.py",
            "--candles",
            str(path),
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
