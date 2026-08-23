from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_cost_aware_baseline_bundle import (
    build_phase_d6_cost_aware_baseline_bundle,
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


def _rows(product: str, base: int = 100, count: int = 100):
    day = 86400
    return [_candle(product, i * day, str(base + i)) for i in range(count)]


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


def test_bundle_generates_compact_rows_for_files_and_scenarios(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC", 200))

    bundle = build_phase_d6_cost_aware_baseline_bundle(
        candle_paths=[btc, eth],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert bundle["status"] == "d6_cost_aware_baseline_bundle_ready"
    assert bundle["summary"]["candle_file_count"] == 2
    assert bundle["summary"]["scenario_count"] == 2
    assert bundle["summary"]["report_count"] == 4
    assert bundle["summary"]["products"] == ["BTC-USDC", "ETH-USDC"]
    assert bundle["summary"]["scenario_names"] == ["zero_cost_reference", "standard_fee_only"]
    assert bundle["summary"]["contains_rankings"] is False
    assert bundle["summary"]["contains_recommendations"] is False
    assert len(bundle["reports"]) == 4
    assert {row["cost_scenario"] for row in bundle["reports"]} == {"zero_cost_reference", "standard_fee_only"}
    assert all(row["baseline_type"] == "buy_hold" for row in bundle["reports"])
    assert all(row["warning_count"] > 0 for row in bundle["reports"])
    _assert_safe(bundle)


def test_bundle_values_are_deterministic_for_zero_and_standard_cost(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))

    bundle = build_phase_d6_cost_aware_baseline_bundle(
        candle_paths=[btc],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    by_scenario = {row["cost_scenario"]: row for row in bundle["reports"]}
    assert by_scenario["zero_cost_reference"]["average_test_net_return_pct"] == "10.5555555555555555555555556"
    assert by_scenario["standard_fee_only"]["average_test_net_return_pct"] == "9.67288"
    assert by_scenario["standard_fee_only"]["round_trip_cost_pct"] == "0.008"
    assert by_scenario["zero_cost_reference"]["round_trip_cost_pct"] == "0"
    _assert_safe(bundle)


def test_bundle_markdown_contains_not_ranking_safety(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    bundle = build_phase_d6_cost_aware_baseline_bundle(
        candle_paths=[btc],
        cost_scenarios=["standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    markdown = bundle_to_markdown(bundle)

    assert "# D.6 Cost-Aware Baseline Bundle" in markdown
    assert "| BTC-USDC | 1D | standard_fee_only |" in markdown
    assert "contains_rankings" in markdown
    assert "live_recommendation" in markdown


def test_normalizes_scenarios_and_rejects_invalid_or_empty():
    assert normalize_cost_scenarios(["standard_fee_only", "standard_fee_only", "stress_cost"]) == [
        "standard_fee_only",
        "stress_cost",
    ]
    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        normalize_cost_scenarios(["best_cost"])
    with pytest.raises(ValueError, match="at_least_one_cost_scenario"):
        normalize_cost_scenarios([])


def test_refuses_state_paths_for_input_and_output(tmp_path: Path):
    state_candles = _write(tmp_path / "state" / "candles.json", _rows("BTC-USDC", 100))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_cost_aware_baseline_bundle(candle_paths=[state_candles])

    good = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    bundle = build_phase_d6_cost_aware_baseline_bundle(
        candle_paths=[good],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    with pytest.raises(ValueError, match="state"):
        write_json_bundle(bundle, tmp_path / "state" / "bundle.json")
    with pytest.raises(ValueError, match="state"):
        write_markdown_bundle(bundle, tmp_path / "state" / "bundle.md")
    with pytest.raises(ValueError, match="env"):
        write_json_bundle(bundle, tmp_path / ".env")


def test_cli_writes_explicit_json_and_markdown_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    json_output = tmp_path / "reports" / "d6" / "cost-aware-bundle.json"
    md_output = tmp_path / "reports" / "d6" / "cost-aware-bundle.md"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_phase_d6_cost_aware_baseline_bundle.py",
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
    assert "Cost-Aware Baseline Bundle" in md_output.read_text(encoding="utf-8")
    _assert_safe(stdout_bundle)


def test_cli_refuses_state_output(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC", 100))
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_phase_d6_cost_aware_baseline_bundle.py",
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
