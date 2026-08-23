from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_baseline_report_bundle import (
    build_phase_d6_baseline_report_bundle,
    bundle_to_markdown,
    write_json_bundle,
    write_markdown_bundle,
)


def _candle(product: str, start: int, close: str, timeframe: str = "1D"):
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


def _write(path: Path, rows) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows), encoding="utf-8")
    return path


def _rows(product: str, base: int = 100):
    day = 86400
    return [_candle(product, i * day, str(base + i)) for i in range(25)]


def _assert_bundle_safe(bundle):
    assert bundle["research_only"] is True
    assert bundle["no_live_action"] is True
    assert bundle["no_coinbase_call"] is True
    assert bundle["state_write_performed"] is False
    assert bundle["no_bulk_fetch"] is True
    assert bundle["no_optimization"] is True
    assert bundle["parameter_search_performed"] is False
    assert bundle["learning_to_execution_allowed"] is False
    assert bundle["parameter_change_allowed"] is False


def test_bundle_generates_compact_reports_for_multiple_files_and_baselines(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC", 200))
    bundle = build_phase_d6_baseline_report_bundle(
        candle_paths=[btc, eth],
        baselines=["buy_hold", "simple_ma"],
        initial_quote="1000",
        fee_pct="0",
    )

    assert bundle["status"] == "d6_baseline_report_bundle_ready"
    assert bundle["summary"]["candle_file_count"] == 2
    assert bundle["summary"]["baseline_count"] == 2
    assert bundle["summary"]["report_count"] == 4
    assert bundle["summary"]["tickers"] == ["BTC-USDC", "ETH-USDC"]
    assert bundle["summary"]["baseline_types"] == ["buy_hold", "simple_ma"]
    assert len(bundle["reports"]) == 4
    assert {row["baseline_type"] for row in bundle["reports"]} == {"buy_hold", "simple_ma"}
    assert all("warnings" in row for row in bundle["reports"])
    _assert_bundle_safe(bundle)


def test_bundle_markdown_contains_table_and_safety_flags(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    bundle = build_phase_d6_baseline_report_bundle(candle_paths=[btc], baselines=["buy_hold"])
    markdown = bundle_to_markdown(bundle)

    assert "# D.6 Baseline Report Bundle" in markdown
    assert "| BTC-USDC | 1D | buy_hold |" in markdown
    assert "no_coinbase_call" in markdown
    assert "parameter_change_allowed" in markdown


def test_bundle_refuses_state_paths_for_input_and_output(tmp_path: Path):
    state_candles = _write(tmp_path / "state" / "candles.json", _rows("BTC-USDC", 100))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_baseline_report_bundle(candle_paths=[state_candles])

    good = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    bundle = build_phase_d6_baseline_report_bundle(candle_paths=[good])
    with pytest.raises(ValueError, match="state"):
        write_json_bundle(bundle, tmp_path / "state" / "bundle.json")
    with pytest.raises(ValueError, match="state"):
        write_markdown_bundle(bundle, tmp_path / "state" / "bundle.md")


def test_bundle_refuses_env_paths(tmp_path: Path):
    good = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    bundle = build_phase_d6_baseline_report_bundle(candle_paths=[good])
    with pytest.raises(ValueError, match="env"):
        write_json_bundle(bundle, tmp_path / ".env")


def test_cli_writes_explicit_json_and_markdown_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    json_output = tmp_path / "reports" / "d6" / "bundle.json"
    md_output = tmp_path / "reports" / "d6" / "bundle.md"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_phase_d6_baseline_report_bundle.py",
            "--candles",
            str(btc),
            "--baseline",
            "buy_hold,simple_ma",
            "--output",
            str(json_output),
            "--markdown-output",
            str(md_output),
            "--json",
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
        check=True,
    )

    stdout_bundle = json.loads(result.stdout)
    disk_bundle = json.loads(json_output.read_text(encoding="utf-8"))
    assert stdout_bundle["summary"]["report_count"] == 2
    assert disk_bundle["summary"]["report_count"] == 2
    assert md_output.exists()
    assert "D.6 Baseline Report Bundle" in md_output.read_text(encoding="utf-8")
    _assert_bundle_safe(stdout_bundle)


def test_cli_refuses_state_output(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_phase_d6_baseline_report_bundle.py",
            "--candles",
            str(btc),
            "--output",
            str(tmp_path / "state" / "bundle.json"),
        ],
        cwd=Path(__file__).resolve().parents[1],
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "state" in result.stderr
