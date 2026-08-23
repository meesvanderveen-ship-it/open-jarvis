from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_overfitting_guardrails import (
    build_phase_d6_overfitting_guardrails_report,
    guardrails_to_markdown,
    load_review_pack,
    write_json_guardrails,
    write_markdown_guardrails,
)
from bot.phase_d6_research_review_pack import build_phase_d6_research_review_pack


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


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_live_action"] is True
    assert report["no_coinbase_call"] is True
    assert report["state_write_performed"] is False
    assert report["no_bulk_fetch"] is True
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["signal_generation_performed"] is False
    assert report["live_recommendation"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["strategy_parameter_mutation_allowed"] is False
    assert report["runtime_config_mutation_allowed"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["parameter_review_allowed"] is False
    assert report["optimization_allowed"] is False


def test_guardrails_from_review_pack_object_are_descriptive_only(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    review_pack = build_phase_d6_research_review_pack(
        candle_paths=[btc],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    report = build_phase_d6_overfitting_guardrails_report(review_pack=review_pack)

    assert report["status"] == "d6_overfitting_guardrails_ready"
    assert report["source_mode"] == "provided_review_pack_object"
    assert report["trial_accounting"]["file_count"] == 1
    assert report["trial_accounting"]["scenario_count"] == 2
    assert report["trial_accounting"]["signal_count"] == 1
    assert report["trial_accounting"]["total_evidence_report_count"] == 4
    assert report["research_degrees_of_freedom"]["estimated_degrees_of_research_freedom"] == 2
    assert report["guardrail_class"] == "exploratory_only"
    assert "limited_file_or_ticker_breadth" in report["guardrail_warnings"]
    assert "single_fixed_signal_only" in report["guardrail_warnings"]
    assert "single_split_configuration_only" in report["guardrail_warnings"]
    assert "do_not_infer_parameter_change" in report["prohibited_interpretations"]
    _assert_safe(report)


def test_guardrails_can_build_review_pack_from_explicit_local_candles(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    eth = _write(tmp_path / "research" / "eth.json", _rows("ETH-USDC"))

    report = build_phase_d6_overfitting_guardrails_report(
        candle_paths=[btc, eth],
        cost_scenarios=["standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert report["source_mode"] == "built_from_explicit_local_candles"
    assert report["trial_accounting"]["file_count"] == 2
    assert report["trial_accounting"]["scenario_count"] == 1
    assert report["trial_accounting"]["total_evidence_report_count"] == 4
    assert report["source_summary"]["dataset_quality_class"] == "good"
    assert report["parameter_review_allowed"] is False
    _assert_safe(report)


def test_guardrails_block_sources_that_claim_rankings_or_live_instructions():
    review_pack = {
        "phase": "fixture_review_pack",
        "status": "fixture",
        "input_summary": {"candle_file_count": 3, "scenario_count": 1, "split_mode": "holdout"},
        "dataset_quality_summary": {"aggregate_quality_class": "good"},
        "baseline_evidence_summary": {"report_count": 3},
        "signal_evidence_summary": {"report_count": 3, "signal_names": ["fixed_sma_cross_5_20"]},
        "trial_accounting_preview": {"signal_count": 1},
        "contains_rankings": True,
        "contains_recommendations": True,
        "contains_live_instructions": True,
    }

    report = build_phase_d6_overfitting_guardrails_report(review_pack=review_pack)

    assert report["guardrail_class"] == "insufficient_for_parameter_review"
    assert "source_contains_rankings_blocked" in report["blockers"]
    assert "source_contains_recommendations_blocked" in report["blockers"]
    assert "source_contains_live_instructions_blocked" in report["blockers"]
    _assert_safe(report)


def test_markdown_contains_guardrails_and_safety(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    report = build_phase_d6_overfitting_guardrails_report(
        candle_paths=[btc],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    markdown = guardrails_to_markdown(report)

    assert "# D.6 Overfitting / Trial-Accounting Guardrails" in markdown
    assert "guardrail_class" in markdown
    assert "parameter_review_allowed" in markdown
    assert "contains_live_instructions" in markdown


def test_requires_review_pack_or_candle_paths_and_refuses_state_paths(tmp_path: Path):
    with pytest.raises(ValueError, match="requires_review_pack_or_candle_paths"):
        build_phase_d6_overfitting_guardrails_report()

    state_candles = _write(tmp_path / "state" / "candles.json", _rows("BTC-USDC"))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_overfitting_guardrails_report(candle_paths=[state_candles])

    with pytest.raises(ValueError, match="state"):
        load_review_pack(tmp_path / "state" / "review-pack.json")


def test_writes_only_explicit_research_outputs_and_refuses_env(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    report = build_phase_d6_overfitting_guardrails_report(
        candle_paths=[btc],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    json_output = tmp_path / "reports" / "d6" / "guardrails.json"
    md_output = tmp_path / "reports" / "d6" / "guardrails.md"

    assert write_json_guardrails(report, json_output) == json_output
    assert write_markdown_guardrails(report, md_output) == md_output
    assert json.loads(json_output.read_text(encoding="utf-8"))["parameter_review_allowed"] is False
    assert "Trial-Accounting Guardrails" in md_output.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="state"):
        write_json_guardrails(report, tmp_path / "state" / "guardrails.json")
    with pytest.raises(ValueError, match="env"):
        write_json_guardrails(report, tmp_path / ".env")


def test_cli_writes_explicit_json_and_markdown_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _rows("BTC-USDC"))
    json_output = tmp_path / "reports" / "d6" / "guardrails.json"
    md_output = tmp_path / "reports" / "d6" / "guardrails.md"
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_overfitting_guardrails.py",
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

    stdout_report = json.loads(result.stdout)
    disk_report = json.loads(json_output.read_text(encoding="utf-8"))
    assert stdout_report["trial_accounting"]["total_evidence_report_count"] == 4
    assert disk_report["parameter_review_allowed"] is False
    assert md_output.exists()
    _assert_safe(stdout_report)
