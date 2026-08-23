from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_d6_oos_degradation import (
    build_phase_d6_oos_degradation_report,
    degradation_to_markdown,
    load_review_pack,
    normalize_cost_scenarios,
    write_json_degradation,
    write_markdown_degradation,
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


def _degrading_rows(product: str, count: int = 100):
    day = 86400
    closes = []
    for i in range(count):
        if i < 60:
            closes.append(100 + i * 2)
        elif i < 80:
            closes.append(220 - (i - 60) * 2)
        else:
            closes.append(180 - (i - 80) * 3)
    return [_candle(product, i * day, str(max(close, 20))) for i, close in enumerate(closes)]


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
    assert report["parameter_review_allowed"] is False
    assert report["parameter_review_approved"] is False
    assert report["broader_signal_expansion_requires_human_approval"] is True
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False


def test_oos_degradation_from_explicit_candles_has_train_validation_test_rows(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _degrading_rows("BTC-USDC"))

    report = build_phase_d6_oos_degradation_report(
        candle_paths=[btc],
        cost_scenarios=["zero_cost_reference"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    assert report["status"] == "d6_oos_degradation_report_ready"
    assert report["source_summary"]["source_mode"] == "built_from_explicit_local_candles"
    assert report["source_summary"]["train_metrics_available"] is True
    assert report["degradation_summary"]["row_count"] == 2
    assert report["baseline_degradation_rows"][0]["average_train_net_return_pct"] is not None
    assert report["baseline_degradation_rows"][0]["train_to_test_degradation_pct_points"] is not None
    assert report["signal_degradation_rows"][0]["average_train_net_return_pct"] is not None
    assert "single_file_oos_context" in report["guardrail_warnings"]
    assert "single_signal_oos_context" in report["guardrail_warnings"]
    _assert_safe(report)


def test_review_pack_input_is_compact_and_warns_train_metrics_unavailable(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _degrading_rows("BTC-USDC"))
    review_pack = build_phase_d6_research_review_pack(
        candle_paths=[btc],
        cost_scenarios=["zero_cost_reference", "standard_fee_only"],
        train_count=60,
        validation_count=20,
        test_count=20,
    )

    report = build_phase_d6_oos_degradation_report(review_pack=review_pack)

    assert report["source_summary"]["source_mode"] == "review_pack_object"
    assert report["source_summary"]["train_metrics_available"] is False
    assert report["degradation_summary"]["row_count"] == 4
    assert report["baseline_degradation_rows"][0]["average_train_net_return_pct"] is None
    assert "train_metrics_unavailable_for_some_or_all_rows" in report["guardrail_warnings"]
    _assert_safe(report)


def test_oos_classifies_severe_degradation_from_fixture_object():
    review_pack = {
        "phase": "fixture_review_pack",
        "input_summary": {"candle_file_count": 1, "scenario_count": 1},
        "trial_accounting_preview": {
            "candle_file_count": 1,
            "cost_scenario_count": 1,
            "signal_count": 1,
            "baseline_report_count": 1,
            "signal_report_count": 0,
            "total_evidence_report_count": 1,
        },
        "baseline_evidence_rows": [
            {
                "product_id": "BTC-USDC",
                "timeframe": "1D",
                "cost_scenario": "zero_cost_reference",
                "baseline_type": "buy_hold",
                "split_count": 1,
                "average_validation_net_return_pct": "20",
                "average_test_net_return_pct": "0",
                "usable_for_future_research": True,
                "blocker_count": 0,
            }
        ],
        "signal_evidence_rows": [],
    }

    report = build_phase_d6_oos_degradation_report(review_pack=review_pack)

    assert report["degradation_summary"]["overall_degradation_class"] == "severe_degradation"
    assert report["baseline_degradation_rows"][0]["degradation_class"] == "severe_degradation"
    assert "severe_oos_degradation_present" in report["guardrail_warnings"]
    _assert_safe(report)


def test_normalizes_scenarios_and_rejects_invalid_or_empty():
    assert normalize_cost_scenarios(["standard_fee_only", "standard_fee_only", "stress_cost"]) == [
        "standard_fee_only",
        "stress_cost",
    ]
    with pytest.raises(ValueError, match="unsupported_d6_cost_scenario"):
        normalize_cost_scenarios(["best_cost"])
    with pytest.raises(ValueError, match="at_least_one_cost_scenario"):
        normalize_cost_scenarios([])


def test_requires_review_pack_or_candle_paths_and_refuses_state_paths(tmp_path: Path):
    with pytest.raises(ValueError, match="requires_review_pack_or_candle_paths"):
        build_phase_d6_oos_degradation_report()

    state_candles = _write(tmp_path / "state" / "candles.json", _degrading_rows("BTC-USDC"))
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_oos_degradation_report(candle_paths=[state_candles])

    with pytest.raises(ValueError, match="state"):
        load_review_pack(tmp_path / "state" / "review-pack.json")


def test_markdown_and_explicit_outputs_refuse_state_and_env(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _degrading_rows("BTC-USDC"))
    report = build_phase_d6_oos_degradation_report(
        candle_paths=[btc],
        train_count=60,
        validation_count=20,
        test_count=20,
    )
    markdown = degradation_to_markdown(report)
    assert "# D.6 Out-of-Sample Degradation Checks" in markdown
    assert "parameter_review_allowed" in markdown

    json_output = tmp_path / "reports" / "d6" / "oos.json"
    md_output = tmp_path / "reports" / "d6" / "oos.md"
    assert write_json_degradation(report, json_output) == json_output
    assert write_markdown_degradation(report, md_output) == md_output
    assert json.loads(json_output.read_text(encoding="utf-8"))["parameter_review_allowed"] is False
    assert "Out-of-Sample" in md_output.read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="state"):
        write_json_degradation(report, tmp_path / "state" / "oos.json")
    with pytest.raises(ValueError, match="env"):
        write_json_degradation(report, tmp_path / ".env")


def test_cli_writes_explicit_json_and_markdown_outputs(tmp_path: Path):
    btc = _write(tmp_path / "research" / "btc.json", _degrading_rows("BTC-USDC"))
    json_output = tmp_path / "reports" / "d6" / "oos.json"
    md_output = tmp_path / "reports" / "d6" / "oos.md"
    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_oos_degradation.py",
            "--candles",
            str(btc),
            "--cost-scenario",
            "zero_cost_reference",
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
    assert stdout_report["degradation_summary"]["row_count"] == 2
    assert disk_report["parameter_review_allowed"] is False
    assert md_output.exists()
    _assert_safe(stdout_report)
