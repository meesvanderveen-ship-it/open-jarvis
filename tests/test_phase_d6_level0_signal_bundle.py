from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_level0_signal_bundle import (
    build_phase_d6_level0_signal_bundle,
    bundle_to_markdown,
    normalize_cost_scenarios,
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


def _rows(product: str, count: int = 100):
    day = 86400
    closes = []
    for i in range(count):
        if i < 25:
            closes.append(100 - i)
        elif i < 65:
            closes.append(75 + (i - 25) * 3)
        else:
            closes.append(max(20, 195 - (i - 65) * 4))
    return [_candle(product, i * day, str(close)) for i, close in enumerate(closes)]


def _assert_safe(bundle):
    assert bundle["research_only"] is True
    assert bundle["no_live_action"] is True
    assert bundle["no_coinbase_call"] is True
    assert bundle["state_write_performed"] is False
    assert bundle["no_bulk_fetch"] is True
    assert bundle["no_optimization"] is True
    assert bundle["parameter_search_performed"] is False
    assert bundle["signal_generation_performed"] is False
    assert bundle["live_recommendation"] is False
    assert bundle["learning_to_execution_allowed"] is False
    assert bundle["parameter_change_allowed"] is False
    assert bundle["fixed_parameters_only"] is True
    assert bundle["strategy_parameter_mutation_allowed"] is False
    assert bundle["runtime_config_mutation_allowed"] is False
    assert bundle["contains_rankings"] is False
    assert bundle["contains_recommendations"] is False


def test_bundle_generates_compact_rows_for_files_and_scenarios(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC"))

    bundle = build_phase_d6_level0_signal_bundle(
        candle_paths=[btc, eth],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert bundle["status"] == "d6_level0_signal_bundle_ready"
    assert bundle["summary"]["candle_file_count"] == 2
    assert bundle["summary"]["scenario_count"] == 2
    assert bundle["summary"]["report_count"] == 4
    assert bundle["summary"]["products"] == ["BTC-USDC", "ETH-USDC"]
    assert bundle["summary"]["signal_names"] == ["fixed_sma_cross_5_20"]
    assert bundle["summary"]["contains_rankings"] is False
    assert bundle["summary"]["contains_recommendations"] is False
    assert len(bundle["reports"]) == 4
    assert {row["cost_scenario"] for row in bundle["reports"]} == {"zero_cost_reference", "standard_fee_only"}
    assert all(row["signal_name"] == "fixed_sma_cross_5_20" for row in bundle["reports"])
    _assert_safe(bundle)


def test_bundle_values_are_deterministic_for_zero_and_standard_cost(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))

    bundle = build_phase_d6_level0_signal_bundle(
        candle_paths=[btc],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    by_scenario = {row["cost_scenario"]: row for row in bundle["reports"]}
    assert by_scenario["zero_cost_reference"]["total_trades_count"] > 0
    assert by_scenario["zero_cost_reference"]["usable_for_future_research"] is True
    assert by_scenario["standard_fee_only"]["usable_for_future_research"] is True
    assert by_scenario["standard_fee_only"]["warning_count"] > 0
    _assert_safe(bundle)


def test_markdown_contains_non_ranking_safety(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    bundle = build_phase_d6_level0_signal_bundle(
        candle_paths=[btc],
        cost_scenarios=["standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    markdown = bundle_to_markdown(bundle)

    assert "# D.6 Level-0 Signal Bundle" in markdown
    assert "| BTC-USDC | 1D | standard_fee_only | fixed_sma_cross_5_20 |" in markdown
    assert "contains_rankings" in markdown
    assert "signal_generation_performed" in markdown


def test_normalizes_scenarios_and_rejects_invalid_or_empty():
    assert normalize_cost_scenarios(["standard_fee_only", "standard_fee_only", "stress_cost"]) == [
        "standard_fee_only",
        "stress_cost",
    ]
    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        normalize_cost_scenarios(["best_cost"])
    with pytest.raises(ValueError, match="at_least_one_cost_scenario"):
        normalize_cost_scenarios([])


def test_rejects_unsupported_signal_and_refuses_state_paths(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    with pytest.raises(ValueError, match="unsupported_d6_level0_signal"):
        build_phase_d6_level0_signal_bundle(candle_paths=[btc], signal_name="best_signal")

    state_candles = _write(tmp_path / "state" / "candles.json", _rows("BTC-USDC"))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_level0_signal_bundle(candle_paths=[state_candles])


def test_writes_only_explicit_research_outputs_and_refuses_env(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    bundle = build_phase_d6_level0_signal_bundle(
        candle_paths=[btc],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    json_output = tmp_path / "reports" / "d6" / "level0-bundle.json"
    md_output = tmp_path / "reports" / "d6" / "level0-bundle.md"

    assert write_json_bundle(bundle, json_output) == json_output
    assert write_markdown_bundle(bundle, md_output) == md_output
    assert json.loads(json_output.read_text(encoding="utf-8"))["signal_name"] == "fixed_sma_cross_5_20"
    assert "Level-0 Signal Bundle" in md_output.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="state"):
        write_json_bundle(bundle, tmp_path / "state" / "bundle.json")
    with pytest.raises(ValueError, match="env"):
        write_json_bundle(bundle, tmp_path / ".env")


def test_cli_writes_explicit_json_and_markdown_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    json_output = tmp_path / "reports" / "d6" / "level0-bundle.json"
    md_output = tmp_path / "reports" / "d6" / "level0-bundle.md"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_phase_d6_level0_signal_bundle.py",
            "--candles",
            str(btc),
            "--cost-scenario",
            "zero_cost_reference,standard_fee_only",
            "--train-count",
            "60",
            "--validation-count",
            "20",
            "--test-count",
            "20",
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
    _assert_safe(stdout_bundle)
