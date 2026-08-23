from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_dataset_quality import (
    build_phase_d6_dataset_quality_report,
    write_dataset_quality_report,
)


def _candle(start: int, close: str = "100", **overrides):
    payload = {
        "product_id": "BTC-USDC",
        "timeframe": "1D",
        "start": start,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1",
    }
    payload.update(overrides)
    return payload


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_live_action"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["no_bulk_fetch"] is True
    assert report["no_optimization"] is True
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_quality_report_good_dataset(tmp_path: Path):
    day = 86400
    path = _write(tmp_path / "research" / "candles.json", [_candle(i * day) for i in range(30)])

    report = build_phase_d6_dataset_quality_report(candles_path=path)

    assert report["status"] == "d6_dataset_quality_report_ready"
    assert report["product_id"] == "BTC-USDC"
    assert report["timeframe"] == "1D"
    assert report["candle_count"] == 30
    assert report["first_candle_start"] == 0
    assert report["last_candle_start"] == day * 29
    assert report["observed_span_seconds"] == day * 29
    assert report["expected_candle_count"] == 30
    assert report["missing_candle_estimate"] == 0
    assert report["gap_count"] == 0
    assert report["duplicate_count"] == 0
    assert report["non_monotonic_count"] == 0
    assert report["invalid_ohlcv_count"] == 0
    assert report["quality_class"] == "good"
    assert report["warnings"] == []
    _assert_safe(report)


def test_quality_report_counts_duplicates_non_monotonic_gaps_and_invalid_rows(tmp_path: Path):
    day = 86400
    rows = [
        _candle(day * 2),
        _candle(0),
        _candle(day),
        _candle(day, close="101"),
        _candle(day * 5),
        _candle(day * 6, close="-1"),
        {"product_id": "BTC-USDC"},
    ]
    path = _write(tmp_path / "research" / "messy.json", rows)

    report = build_phase_d6_dataset_quality_report(candles_path=path)

    assert report["candle_count"] == 4
    assert report["valid_candle_row_count"] == 5
    assert report["duplicate_count"] == 1
    assert report["non_monotonic_count"] == 2
    assert report["gap_count"] == 1
    assert report["expected_candle_count"] == 6
    assert report["missing_candle_estimate"] == 2
    assert report["invalid_ohlcv_count"] == 2
    assert report["invalid_reasons"]["non_positive_price"] == 1
    assert report["quality_class"] in {"poor", "usable_with_warnings"}
    assert "duplicate_start_rows_detected" in report["warnings"]
    assert "non_monotonic_rows_detected" in report["warnings"]
    assert "invalid_ohlcv_rows_detected" in report["warnings"]
    _assert_safe(report)


def test_quality_report_invalid_json_array_and_state_path_refusal(tmp_path: Path):
    bad = _write(tmp_path / "research" / "bad.json", {"not": "a list"})
    report = build_phase_d6_dataset_quality_report(candles_path=bad)
    assert report["quality_class"] == "invalid"
    assert "d6_candle_file_must_be_json_array" in report["fatal_errors"]
    _assert_safe(report)

    state_path = _write(tmp_path / "state" / "candles.json", [_candle(0)])
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_dataset_quality_report(candles_path=state_path)


def test_quality_report_stale_and_short_window_warning(tmp_path: Path):
    day = 86400
    path = _write(tmp_path / "research" / "short.json", [_candle(0), _candle(day)])

    report = build_phase_d6_dataset_quality_report(candles_path=path, as_of="1970-01-10T00:00:00Z")

    assert report["quality_class"] == "usable_with_warnings"
    assert "short_window_less_than_30_candles" in report["warnings"]
    assert "stale_last_candle" in report["warnings"]
    _assert_safe(report)


def test_write_quality_report_refuses_state_and_env_outputs(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", [_candle(i * 86400) for i in range(30)])
    report = build_phase_d6_dataset_quality_report(candles_path=path)
    output = tmp_path / "reports" / "d6" / "quality.json"

    written = write_dataset_quality_report(report, output)

    assert written == output
    assert json.loads(output.read_text(encoding="utf-8"))["quality_class"] == "good"
    with pytest.raises(ValueError, match="state"):
        write_dataset_quality_report(report, tmp_path / "state" / "quality.json")
    with pytest.raises(ValueError, match="env"):
        write_dataset_quality_report(report, tmp_path / ".env")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    path = _write(tmp_path / "research" / "candles.json", [_candle(i * 86400) for i in range(30)])
    output = tmp_path / "reports" / "d6" / "quality.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_dataset_quality.py",
            "--candles",
            str(path),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["quality_class"] == "good"
    _assert_safe(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_dataset_quality.py",
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
    assert json.loads(output.read_text(encoding="utf-8"))["no_coinbase_call"] is True
