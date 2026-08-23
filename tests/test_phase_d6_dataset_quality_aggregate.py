from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_dataset_quality_aggregate import (
    aggregate_to_markdown,
    build_phase_d6_dataset_quality_aggregate_report,
    write_json_aggregate,
    write_markdown_aggregate,
)


def _candle(product: str, start: int, close: str = "100", timeframe: str = "1D"):
    return {
        "product_id": product,
        "timeframe": timeframe,
        "start": start,
        "open": close,
        "high": close,
        "low": close,
        "close": close,
        "volume": "1",
    }


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def _rows(product: str, count: int = 30, timeframe: str = "1D"):
    step = 86400 if timeframe == "1D" else 3600
    return [_candle(product, i * step, timeframe=timeframe) for i in range(count)]


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


def test_aggregate_summarizes_multiple_good_files(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC", timeframe="1H"))

    report = build_phase_d6_dataset_quality_aggregate_report(candle_paths=[btc, eth])

    assert report["status"] == "d6_dataset_quality_aggregate_ready"
    assert report["summary"]["file_count"] == 2
    assert report["summary"]["quality_counts"]["good"] == 2
    assert report["summary"]["aggregate_quality_class"] == "good"
    assert report["summary"]["tickers"] == ["BTC-USDC", "ETH-USDC"]
    assert report["summary"]["timeframes"] == ["1D", "1H"]
    assert report["summary"]["ready_for_baseline_bundle"] is True
    assert report["summary"]["ready_for_walk_forward_scaffold"] is True
    assert len(report["reports"]) == 2
    _assert_safe(report)


def test_aggregate_blocks_poor_or_invalid_file(tmp_path: Path):
    good = _write(tmp_path / "research" / "good.json", _rows("BTC-USDC"))
    invalid = _write(tmp_path / "research" / "invalid.json", {"not": "a list"})

    report = build_phase_d6_dataset_quality_aggregate_report(candle_paths=[good, invalid])

    assert report["summary"]["quality_counts"]["good"] == 1
    assert report["summary"]["quality_counts"]["invalid"] == 1
    assert report["summary"]["aggregate_quality_class"] == "invalid"
    assert report["summary"]["ready_for_baseline_bundle"] is False
    assert report["summary"]["ready_for_walk_forward_scaffold"] is False
    assert report["summary"]["blockers"][0].startswith("invalid_dataset:")
    assert "poor_or_invalid_dataset_present" in report["warnings"]
    _assert_safe(report)


def test_aggregate_counts_warnings_and_totals(tmp_path: Path):
    day = 86400
    messy = _write(
        tmp_path / "research" / "messy.json",
        [
            _candle("BTC-USDC", 0),
            _candle("BTC-USDC", day),
            _candle("BTC-USDC", day, close="101"),
            _candle("BTC-USDC", day * 5),
            _candle("BTC-USDC", day * 6, close="-1"),
        ],
    )

    report = build_phase_d6_dataset_quality_aggregate_report(candle_paths=[messy])

    assert report["summary"]["file_count"] == 1
    assert report["summary"]["total_gap_count"] == 1
    assert report["summary"]["total_duplicate_count"] == 1
    assert report["summary"]["total_invalid_ohlcv_count"] == 1
    assert report["summary"]["warning_counts"]["duplicate_start_rows_detected"] == 1
    assert report["summary"]["warning_counts"]["invalid_ohlcv_rows_detected"] == 1
    _assert_safe(report)


def test_markdown_and_writers_refuse_state_and_env(tmp_path: Path):
    good = _write(tmp_path / "research" / "good.json", _rows("BTC-USDC"))
    report = build_phase_d6_dataset_quality_aggregate_report(candle_paths=[good])
    markdown = aggregate_to_markdown(report)

    assert "# D.6 Dataset Quality Aggregate" in markdown
    assert "| BTC-USDC | 1D | good |" in markdown
    assert "no_coinbase_call" in markdown

    json_out = tmp_path / "reports" / "d6" / "quality-aggregate.json"
    md_out = tmp_path / "reports" / "d6" / "quality-aggregate.md"
    assert write_json_aggregate(report, json_out) == json_out
    assert write_markdown_aggregate(report, md_out) == md_out
    assert json.loads(json_out.read_text(encoding="utf-8"))["summary"]["file_count"] == 1

    with pytest.raises(ValueError, match="state"):
        write_json_aggregate(report, tmp_path / "state" / "quality.json")
    with pytest.raises(ValueError, match="env"):
        write_markdown_aggregate(report, tmp_path / ".env")


def test_aggregate_refuses_state_input_and_deduplicates_paths(tmp_path: Path):
    good = _write(tmp_path / "research" / "good.json", _rows("BTC-USDC"))
    report = build_phase_d6_dataset_quality_aggregate_report(candle_paths=[good, good])
    assert report["summary"]["file_count"] == 1

    state = _write(tmp_path / "state" / "candles.json", _rows("BTC-USDC"))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_dataset_quality_aggregate_report(candle_paths=[state])


def test_cli_stdout_and_explicit_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC"))
    json_out = tmp_path / "reports" / "d6" / "aggregate.json"
    md_out = tmp_path / "reports" / "d6" / "aggregate.md"

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_dataset_quality_aggregate.py",
            "--candles",
            f"{btc},{eth}",
            "--output",
            str(json_out),
            "--markdown-output",
            str(md_out),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    stdout_report = json.loads(result.stdout)
    disk_report = json.loads(json_out.read_text(encoding="utf-8"))
    assert stdout_report["summary"]["file_count"] == 2
    assert disk_report["summary"]["quality_counts"]["good"] == 2
    assert "D.6 Dataset Quality Aggregate" in md_out.read_text(encoding="utf-8")
    _assert_safe(stdout_report)
