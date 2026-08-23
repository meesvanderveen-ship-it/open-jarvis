from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_parameter_inventory import (
    CATEGORY_LABELS,
    build_parameter_candidates,
    build_phase_d6_parameter_inventory_report,
)


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["runtime_config_mutation_allowed"] is False
    assert report["strategy_parameter_mutation_allowed"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def test_inventory_covers_all_workflow_categories_and_is_report_only():
    report = build_phase_d6_parameter_inventory_report()

    assert report["status"] == "d6_parameter_candidate_inventory_ready"
    assert set(report["category_labels"]) == set(CATEGORY_LABELS)
    assert set(report["category_counts"]) == set(CATEGORY_LABELS)
    assert all(count > 0 for count in report["category_counts"].values())
    assert report["candidate_count"] >= 50
    assert "inventory_only_not_parameter_ranking" in report["warnings"]
    assert "do_not_infer_parameter_change" in report["prohibited_interpretations"]
    _assert_safe(report)


def test_each_candidate_has_required_schema_and_no_change_permission():
    candidates = build_parameter_candidates()
    assert candidates

    for item in candidates:
        assert item["parameter_name"]
        assert item["category"] in CATEGORY_LABELS
        assert item["source_file"].startswith("bot/")
        assert item["source_symbol"]
        assert item["parameter_type"]
        assert item["safety_class"] in {
            "research_only_candidate",
            "human_review_required",
            "high_risk_manual_only",
            "never_auto_change",
        }
        assert isinstance(item["evidence_source_needed"], list)
        assert item["evidence_source_needed"]
        assert item["parameter_change_allowed"] is False


def test_high_risk_and_never_auto_change_boundaries_are_explicit():
    report = build_phase_d6_parameter_inventory_report()
    by_name = {item["parameter_name"]: item for item in report["parameters"]}

    assert by_name["max_daily_loss_usdc"]["safety_class"] == "never_auto_change"
    assert by_name["allow_averaging_down"]["eligible_for_future_review"] is False
    assert by_name["phase_d3_require_reduce_only_local"]["safety_class"] == "never_auto_change"
    assert by_name["live_execution_flags"]["eligible_for_future_review"] is False
    assert by_name["judge_min_gate_confidence"]["safety_class"] == "high_risk_manual_only"


def test_category_filter_is_not_ranking_or_recommendation():
    report = build_phase_d6_parameter_inventory_report(categories=["d3_controlled_exit", "d4_dynamic_order_management"])

    assert report["categories_filter"] == ["d3_controlled_exit", "d4_dynamic_order_management"]
    assert {item["category"] for item in report["parameters"]} == {
        "d3_controlled_exit",
        "d4_dynamic_order_management",
    }
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    _assert_safe(report)


def test_unknown_category_fails_closed():
    with pytest.raises(ValueError, match="unsupported_parameter_inventory_category"):
        build_phase_d6_parameter_inventory_report(categories=["best_parameters"])


def test_cli_stdout_only_and_no_state_write(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    sentinel = repo / "state" / "d6_parameter_inventory_test_sentinel.tmp"
    if sentinel.exists():
        sentinel.unlink()

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_parameter_inventory.py",
            "--category",
            "ai_prompt_judge,d5_execution_learning",
            "--json",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["candidate_count"] > 0
    assert {item["category"] for item in report["parameters"]} == {
        "ai_prompt_judge",
        "d5_execution_learning",
    }
    assert not sentinel.exists()
    _assert_safe(report)
