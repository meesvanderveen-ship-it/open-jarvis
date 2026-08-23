from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_walk_forward_splits import (
    build_phase_d6_walk_forward_split_report,
    write_walk_forward_split_report,
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
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_holdout_split_report_is_deterministic_and_report_only(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))

    report = build_phase_d6_walk_forward_split_report(
        candles_path=path,
        split_mode="holdout",
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert report["status"] == "d6_walk_forward_splits_ready"
    assert report["product_id"] == "BTC-USDC"
    assert report["timeframe"] == "1D"
    assert report["split_mode"] == "holdout"
    assert report["split_count"] == 1
    split = report["splits"][0]
    assert split["train"]["start_index"] == 0
    assert split["train"]["end_index_exclusive"] == 60
    assert split["validation"]["start_index"] == 60
    assert split["validation"]["end_index_exclusive"] == 80
    assert split["test"]["start_index"] == 80
    assert split["test"]["end_index_exclusive"] == 100
    assert report["usable_for_future_research"] is True
    _assert_safe(report)


def test_rolling_split_generates_multiple_fixed_windows(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(120))

    report = build_phase_d6_walk_forward_split_report(
        candles_path=path,
        split_mode="rolling",
        train_count=50,
        validation_count=10,
        test_count=10,
        step_count=20,
        max_splits=3,
    )

    assert report["split_count"] == 3
    assert [s["train"]["start_index"] for s in report["splits"]] == [0, 20, 40]
    assert [s["test"]["end_index_exclusive"] for s in report["splits"]] == [70, 90, 110]
    _assert_safe(report)


def test_expanding_split_grows_training_window(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(130))

    report = build_phase_d6_walk_forward_split_report(
        candles_path=path,
        split_mode="expanding",
        train_count=50,
        validation_count=10,
        test_count=10,
        step_count=20,
        max_splits=4,
    )

    assert report["split_count"] == 4
    assert [s["train"]["start_index"] for s in report["splits"]] == [0, 0, 0, 0]
    assert [s["train"]["end_index_exclusive"] for s in report["splits"]] == [50, 70, 90, 110]
    assert [s["test"]["end_index_exclusive"] for s in report["splits"]] == [70, 90, 110, 130]
    _assert_safe(report)


def test_insufficient_or_bad_quality_blocks_split(tmp_path: Path):
    short = _write(tmp_path / "research" / "short.json", _rows(20))
    short_report = build_phase_d6_walk_forward_split_report(
        candles_path=short,
        train_count=15,
        validation_count=5,
        test_count=5,
    )
    assert short_report["status"] == "d6_walk_forward_splits_blocked"
    assert "insufficient_candles_for_requested_split" in short_report["blockers"]
    assert short_report["split_count"] == 0
    _assert_safe(short_report)

    invalid = _write(tmp_path / "research" / "invalid.json", [_candle(0, close="-1"), _candle(86400)])
    with pytest.raises(ValueError, match="d6_candle_file_empty_after_validation|candle_close_must_be_positive"):
        build_phase_d6_walk_forward_split_report(candles_path=invalid, train_count=1, validation_count=0, test_count=1)


def test_refuses_state_input_and_output(tmp_path: Path):
    good = _write(tmp_path / "research" / "candles.json", _rows(50))
    report = build_phase_d6_walk_forward_split_report(
        candles_path=good,
        train_count=30,
        validation_count=10,
        test_count=10,
    )
    output = tmp_path / "reports" / "d6" / "splits.json"
    assert write_walk_forward_split_report(report, output) == output
    assert json.loads(output.read_text(encoding="utf-8"))["split_count"] == 1

    state = _write(tmp_path / "state" / "candles.json", _rows(50))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_walk_forward_split_report(candles_path=state)
    with pytest.raises(ValueError, match="state"):
        write_walk_forward_split_report(report, tmp_path / "state" / "splits.json")
    with pytest.raises(ValueError, match="env"):
        write_walk_forward_split_report(report, tmp_path / ".env")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", _rows(100))
    output = tmp_path / "reports" / "d6" / "splits.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_walk_forward_splits.py",
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
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["split_count"] == 1
    _assert_safe(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_walk_forward_splits.py",
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
    assert json.loads(output.read_text(encoding="utf-8"))["no_coinbase_call"] is True
