from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_data_coverage import (
    D6_DEFAULT_TICKERS,
    build_phase_d6_data_coverage_report,
)


AS_OF = "2026-05-29"


def _entry(report, *, ticker="BTC-USDC", timeframe="1H", study_window="3y"):
    for item in report["entries"]:
        if item["ticker"] == ticker and item["timeframe"] == timeframe and item["study_window"] == study_window:
            return item
    raise AssertionError(f"missing entry {ticker} {timeframe} {study_window}")


def _assert_report_only(payload):
    assert payload["research_only"] is True
    assert payload["no_coinbase_call"] is True
    assert payload["no_live_action"] is True
    assert payload["state_write_performed"] is False
    assert payload["learning_to_execution_allowed"] is False
    assert payload["parameter_change_allowed"] is False


def test_default_universe_and_windows_are_generated():
    report = build_phase_d6_data_coverage_report(as_of=AS_OF)

    assert report["status"] == "d6_data_coverage_inventory_ready"
    assert report["tickers"] == D6_DEFAULT_TICKERS
    assert "BTC-USDC" in report["tickers"]
    assert "UNI-USDC" in report["tickers"]
    assert report["timeframes"] == ["1H", "4H", "1D", "15M"]
    assert report["study_windows"] == ["3y", "5y"]
    assert report["entry_count"] == 18 * 4 * 2
    _assert_report_only(report)
    assert report["no_bulk_data_fetch"] is True
    assert report["safety_policy"]["does_not_read_live_trading_state"] is True


def test_expected_candle_counts_and_chunk_counts_are_plausible():
    report = build_phase_d6_data_coverage_report(
        as_of=AS_OF,
        tickers=["BTC-USDC"],
        timeframes=["1H", "4H", "1D", "15M"],
        years=[3, 5],
    )

    one_hour_3y = _entry(report, timeframe="1H", study_window="3y")
    four_hour_3y = _entry(report, timeframe="4H", study_window="3y")
    one_day_3y = _entry(report, timeframe="1D", study_window="3y")
    fifteen_min_3y = _entry(report, timeframe="15M", study_window="3y")
    one_hour_5y = _entry(report, timeframe="1H", study_window="5y")

    assert one_hour_3y["expected_candle_count"] == 26304
    assert four_hour_3y["expected_candle_count"] == 6576
    assert one_day_3y["expected_candle_count"] == 1096
    assert fifteen_min_3y["expected_candle_count"] == 105216
    assert one_hour_5y["expected_candle_count"] == 43824

    assert one_hour_3y["planned_chunk_count"] == 76
    assert four_hour_3y["planned_chunk_count"] == 19
    assert one_day_3y["planned_chunk_count"] == 4
    assert fifteen_min_3y["planned_chunk_count"] == 301
    assert one_hour_5y["planned_chunk_count"] == 126

    assert one_hour_3y["max_candles_per_request"] == 350
    assert one_hour_3y["chunks"][0]["expected_candle_count"] == 350
    assert one_hour_3y["chunks"][-1]["expected_candle_count"] <= 350
    assert one_hour_3y["coverage_class"] == "planned"
    _assert_report_only(one_hour_3y)


def test_override_tickers_timeframes_and_years():
    report = build_phase_d6_data_coverage_report(
        as_of=AS_OF,
        tickers=["btc/usdc", "ETH-USDC", "BTC-USDC"],
        timeframes=["1hour", "1D"],
        years=["3"],
    )

    assert report["tickers"] == ["BTC-USDC", "ETH-USDC"]
    assert report["timeframes"] == ["1H", "1D"]
    assert report["study_windows"] == ["3y"]
    assert report["entry_count"] == 4
    assert _entry(report, ticker="ETH-USDC", timeframe="1D")["coinbase_granularity"] == "ONE_DAY"


def test_cli_stdout_and_explicit_output_are_research_only(tmp_path: Path):
    sentinel = tmp_path / "sentinel.txt"
    out_file = tmp_path / "coverage.json"
    sentinel.write_text("unchanged", encoding="utf-8")

    stdout_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_data_coverage.py",
            "--as-of",
            AS_OF,
            "--tickers",
            "BTC-USDC,ETH-USDC",
            "--timeframes",
            "1H,1D",
            "--years",
            "3,5",
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    stdout_report = json.loads(stdout_result.stdout)
    assert stdout_report["entry_count"] == 2 * 2 * 2
    _assert_report_only(stdout_report)

    output_result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_data_coverage.py",
            "--as-of",
            AS_OF,
            "--tickers",
            "BTC-USDC",
            "--timeframes",
            "4H",
            "--years",
            "3",
            "--output",
            str(out_file),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )
    assert output_result.stdout == ""
    assert sentinel.read_text(encoding="utf-8") == "unchanged"
    output_report = json.loads(out_file.read_text(encoding="utf-8"))
    assert output_report["entry_count"] == 1
    assert output_report["entries"][0]["timeframe"] == "4H"
    _assert_report_only(output_report)


def test_cli_refuses_state_output_path(tmp_path: Path):
    state_dir = tmp_path / "state"
    bad_output = state_dir / "coverage.json"
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_data_coverage.py",
            "--as-of",
            AS_OF,
            "--tickers",
            "BTC-USDC",
            "--output",
            str(bad_output),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert not bad_output.exists()
    assert "d6_output_path_must_not_be_under_state" in result.stderr


def test_invalid_lower_timeframe_is_out_of_scope():
    with pytest.raises(ValueError, match="unsupported_timeframe"):
        build_phase_d6_data_coverage_report(as_of=AS_OF, tickers=["BTC-USDC"], timeframes=["5M"], years=[3])
