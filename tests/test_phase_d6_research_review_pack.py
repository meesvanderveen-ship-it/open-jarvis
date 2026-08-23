from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_research_review_pack import (
    build_phase_d6_research_review_pack,
    normalize_cost_scenarios,
    review_pack_to_markdown,
    write_json_review_pack,
    write_markdown_review_pack,
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


def _assert_safe(pack):
    assert pack["research_only"] is True
    assert pack["no_live_action"] is True
    assert pack["no_coinbase_call"] is True
    assert pack["state_write_performed"] is False
    assert pack["no_bulk_fetch"] is True
    assert pack["no_optimization"] is True
    assert pack["parameter_search_performed"] is False
    assert pack["signal_generation_performed"] is False
    assert pack["live_recommendation"] is False
    assert pack["learning_to_execution_allowed"] is False
    assert pack["parameter_change_allowed"] is False
    assert pack["fixed_parameters_only"] is True
    assert pack["strategy_parameter_mutation_allowed"] is False
    assert pack["runtime_config_mutation_allowed"] is False
    assert pack["human_review_required"] is True
    assert pack["parameter_review_approved"] is False
    assert pack["contains_rankings"] is False
    assert pack["contains_recommendations"] is False
    assert pack["contains_live_instructions"] is False


def test_review_pack_bundles_quality_baseline_signal_and_cost_evidence(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC"))

    pack = build_phase_d6_research_review_pack(
        candle_paths=[btc, eth],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert pack["status"] == "d6_research_review_pack_ready"
    assert pack["input_summary"]["candle_file_count"] == 2
    assert pack["input_summary"]["scenario_count"] == 2
    assert pack["dataset_quality_summary"]["file_count"] == 2
    assert pack["dataset_quality_summary"]["aggregate_quality_class"] == "good"
    assert pack["baseline_evidence_summary"]["report_count"] == 4
    assert pack["signal_evidence_summary"]["report_count"] == 4
    assert pack["cost_assumption_summary"]["scenario_names"] == ["zero_cost_reference", "standard_fee_only"]
    assert pack["trial_accounting_preview"]["total_evidence_report_count"] == 8
    assert pack["trial_accounting_preview"]["ranking_performed"] is False
    assert len(pack["baseline_evidence_rows"]) == 4
    assert len(pack["signal_evidence_rows"]) == 4
    assert "do_not_infer_parameter_change" in pack["prohibited_interpretations"]
    assert "add_formal_overfitting_trial_accounting_guardrails" in pack["suggested_next_research_steps"]
    _assert_safe(pack)


def test_review_pack_preserves_non_ranking_human_review_boundaries(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    pack = build_phase_d6_research_review_pack(
        candle_paths=[btc],
        cost_scenarios=["zero_cost_reference", "conservative_slippage"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert "not_ticker_ranking" in pack["warnings"]
    assert "not_cost_scenario_ranking" in pack["warnings"]
    assert "not_signal_ranking" in pack["warnings"]
    assert "multiple_cost_scenarios_present_not_ranked" in pack["trial_accounting_preview"]["warnings"]
    assert "single_fixed_signal_only" in pack["trial_accounting_preview"]["warnings"]
    assert pack["contains_rankings"] is False
    assert pack["contains_recommendations"] is False
    assert pack["parameter_review_approved"] is False
    _assert_safe(pack)


def test_markdown_contains_review_and_safety_sections(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    pack = build_phase_d6_research_review_pack(
        candle_paths=[btc],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    markdown = review_pack_to_markdown(pack)

    assert "# D.6 Research Review Pack" in markdown
    assert "Prohibited Interpretations" in markdown
    assert "contains_live_instructions" in markdown
    assert "parameter_review_approved" in markdown


def test_normalizes_scenarios_and_rejects_invalid_or_empty():
    assert normalize_cost_scenarios(["standard_fee_only", "standard_fee_only", "stress_cost"]) == [
        "standard_fee_only",
        "stress_cost",
    ]
    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        normalize_cost_scenarios(["best_cost"])
    with pytest.raises(ValueError, match="at_least_one_cost_scenario"):
        normalize_cost_scenarios([])


def test_refuses_state_paths_and_env_outputs(tmp_path: Path):
    state_candles = _write(tmp_path / "state" / "candles.json", _rows("BTC-USDC"))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_research_review_pack(candle_paths=[state_candles])

    good = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    pack = build_phase_d6_research_review_pack(
        candle_paths=[good],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    with pytest.raises(ValueError, match="state"):
        write_json_review_pack(pack, tmp_path / "state" / "review.json")
    with pytest.raises(ValueError, match="state"):
        write_markdown_review_pack(pack, tmp_path / "state" / "review.md")
    with pytest.raises(ValueError, match="env"):
        write_json_review_pack(pack, tmp_path / ".env")


def test_writes_only_explicit_research_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    pack = build_phase_d6_research_review_pack(
        candle_paths=[btc],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    json_output = tmp_path / "reports" / "d6" / "review-pack.json"
    md_output = tmp_path / "reports" / "d6" / "review-pack.md"

    assert write_json_review_pack(pack, json_output) == json_output
    assert write_markdown_review_pack(pack, md_output) == md_output
    assert json.loads(json_output.read_text(encoding="utf-8"))["human_review_required"] is True
    assert "Research Review Pack" in md_output.read_text(encoding="utf-8")
    _assert_safe(pack)


def test_cli_writes_explicit_json_and_markdown_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    json_output = tmp_path / "reports" / "d6" / "review-pack.json"
    md_output = tmp_path / "reports" / "d6" / "review-pack.md"
    result = subprocess.run(
        [
            sys.executable,
            "tools/build_phase_d6_research_review_pack.py",
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

    stdout_pack = json.loads(result.stdout)
    disk_pack = json.loads(json_output.read_text(encoding="utf-8"))
    assert stdout_pack["baseline_evidence_summary"]["report_count"] == 2
    assert stdout_pack["signal_evidence_summary"]["report_count"] == 2
    assert disk_pack["trial_accounting_preview"]["total_evidence_report_count"] == 4
    assert md_output.exists()
    _assert_safe(stdout_pack)
