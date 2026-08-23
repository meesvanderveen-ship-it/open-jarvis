from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_baseline_backtest import (
    build_phase_d6_baseline_backtest_report,
    load_d6_candles,
    write_report,
)


def _candle(start: int, close: str, **overrides):
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


def _write_candles(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _fixture_rows():
    day = 86400
    return [
        _candle(0 + day * 2, "110"),
        _candle(0, "100"),
        _candle(day, "105", open="104"),
        _candle(day, "106", open="105"),
        _candle(day * 3, "120"),
        _candle(day * 4, "115"),
    ]


def _assert_report_only(report):
    assert report["research_only"] is True
    assert report["no_live_action"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["no_bulk_fetch"] is True
    assert report["no_optimization"] is True
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False


def test_loader_validates_sorts_deduplicates_and_detects_gaps(tmp_path: Path):
    path = _write_candles(tmp_path / "research" / "candles.json", _fixture_rows())
    loaded = load_d6_candles(path)

    assert loaded["product_id"] == "BTC-USDC"
    assert loaded["timeframe"] == "1D"
    assert loaded["candle_count"] == 5
    assert [c["start"] for c in loaded["candles"]] == [0, 86400, 172800, 259200, 345600]
    assert loaded["candles"][1]["close"] == 106
    assert loaded["gap_count"] == 0


def test_loader_detects_gap_and_rejects_invalid_state_path(tmp_path: Path):
    path = _write_candles(
        tmp_path / "research" / "gap.json",
        [_candle(0, "100"), _candle(86400 * 3, "120")],
    )
    loaded = load_d6_candles(path)
    assert loaded["gap_count"] == 1

    state_path = _write_candles(tmp_path / "state" / "candles.json", [_candle(0, "100")])
    with pytest.raises(ValueError, match="state"):
        load_d6_candles(state_path)


def test_loader_rejects_missing_required_fields(tmp_path: Path):
    path = _write_candles(tmp_path / "research" / "bad.json", [{"product_id": "BTC-USDC"}])
    with pytest.raises(ValueError, match="candle_missing_required_fields"):
        load_d6_candles(path)


def test_buy_hold_baseline_report_is_deterministic_and_report_only(tmp_path: Path):
    path = _write_candles(tmp_path / "research" / "candles.json", _fixture_rows())
    report = build_phase_d6_baseline_backtest_report(
        candles_path=path,
        baseline="buy_hold",
        initial_quote="1000",
        fee_pct="0.001",
    )

    assert report["status"] == "d6_baseline_backtest_report_ready"
    assert report["ticker"] == "BTC-USDC"
    assert report["timeframe"] == "1D"
    assert report["candle_count"] == 5
    assert report["baseline_type"] == "buy_hold"
    assert report["trades_count"] == 1
    assert report["round_trips"] == 1
    assert report["final_quote"] == "1147.70115"
    assert report["net_return"] == "0.14770115"
    assert report["max_drawdown"] == "0.04166666666666666666666666667"
    assert "no_post_only_fill_model_yet" in report["warnings"]
    _assert_report_only(report)


def test_simple_ma_scaffold_has_fixed_parameters_and_no_optimization(tmp_path: Path):
    rows = [_candle(i * 86400, str(100 + i)) for i in range(25)]
    rows.extend(_candle((25 + i) * 86400, str(125 - i)) for i in range(10))
    path = _write_candles(tmp_path / "research" / "ma.json", rows)
    report = build_phase_d6_baseline_backtest_report(
        candles_path=path,
        baseline="simple_ma",
        initial_quote="1000",
        fee_pct="0",
    )

    assert report["baseline_type"] == "simple_ma"
    assert report["simple_ma"]["fast_window"] == 5
    assert report["simple_ma"]["slow_window"] == 20
    assert report["simple_ma"]["fixed_scaffold_parameters"] is True
    assert report["no_optimization"] is True
    assert report["trades_count"] >= 2
    _assert_report_only(report)


def test_write_report_refuses_state_output_and_writes_explicit_report(tmp_path: Path):
    path = _write_candles(tmp_path / "research" / "candles.json", _fixture_rows())
    report = build_phase_d6_baseline_backtest_report(candles_path=path)
    output = tmp_path / "reports" / "d6" / "baseline.json"
    written = write_report(report, output)

    assert written == output
    assert json.loads(output.read_text(encoding="utf-8"))["baseline_type"] == "buy_hold"

    with pytest.raises(ValueError, match="state"):
        write_report(report, tmp_path / "state" / "baseline.json")


def test_cli_stdout_and_explicit_output(tmp_path: Path):
    path = _write_candles(tmp_path / "research" / "candles.json", _fixture_rows())
    output = tmp_path / "reports" / "baseline.json"

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/run_phase_d6_baseline_backtest.py",
            "--candles",
            str(path),
            "--baseline",
            "buy_hold",
            "--initial-quote",
            "1000",
            "--fee-pct",
            "0.001",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["final_quote"] == "1147.70115"
    _assert_report_only(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/run_phase_d6_baseline_backtest.py",
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
    assert output.exists()
    output_report = json.loads(output.read_text(encoding="utf-8"))
    assert output_report["no_coinbase_call"] is True
