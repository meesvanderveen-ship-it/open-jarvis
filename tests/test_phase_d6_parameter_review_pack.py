from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_guardrail_summary_adapter import build_phase_d6_guardrail_summary_report
from bot.phase_d6_parameter_review_pack import build_phase_d6_parameter_review_pack


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
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_parameter_review_pack_builds_category_sections():
    evidence_bundle = {
        "phase": "D6_combined_evidence_review_bundle_v2",
        "status": "d6_combined_evidence_review_bundle_ready",
        "parameter_inventory_summary": {"candidate_count": 66, "category_counts": {"d4_dynamic_order_management": 6}},
        "d5_evidence_summary": {
            "evidence_row_count": 3,
            "parameter_category_counts": {"d5_execution_learning": 3},
            "evidence_strength_counts": {"medium": 2, "weak": 1},
        },
        "regime_summary": {"regime_window_count": 2},
        "fill_realism_summary": {
            "evidence_row_count": 2,
            "parameter_category_counts": {"d4_dynamic_order_management": 2, "market_data_features": 1},
            "evidence_strength_counts": {"medium": 2},
        },
        "warning_counts": {},
        "blocker_counts": {},
    }
    guardrails = build_phase_d6_guardrail_summary_report(
        reports=[
            {
                "phase": "D6_dataset_quality_aggregate_v1",
                "status": "ready",
                "summary": {"aggregate_quality_class": "good", "warning_counts": {}, "blockers": []},
                "research_only": True,
            }
        ]
    )

    report = build_phase_d6_parameter_review_pack(evidence_review_bundle=evidence_bundle, guardrail_summary_report=guardrails)

    assert report["status"] == "d6_parameter_review_pack_ready"
    assert report["source_summary"]["review_section_count"] == 10
    by_category = {section["category"]: section for section in report["review_sections"]}
    assert by_category["d4_dynamic_order_management"]["evidence_count"] == 2
    assert by_category["market_data_features"]["evidence_count"] >= 2
    assert by_category["ai_prompt_judge"]["parameter_review_approved"] is False
    assert report["contains_rankings"] is False
    assert "do_not_infer_best_parameter" in report["prohibited_interpretations"]
    _assert_safe(report)


def test_parameter_review_pack_cli_loads_inputs(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    evidence = _write_json(
        tmp_path / "research" / "bundle.json",
        {
            "phase": "D6_combined_evidence_review_bundle_v2",
            "status": "ready",
            "parameter_inventory_summary": {"candidate_count": 66, "category_counts": {}},
            "d5_evidence_summary": {"evidence_row_count": 1, "parameter_category_counts": {"d5_execution_learning": 1}, "evidence_strength_counts": {"weak": 1}},
            "regime_summary": {},
            "fill_realism_summary": {},
            "warning_counts": {},
            "blocker_counts": {},
        },
    )
    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_parameter_review_pack.py", "--evidence-review-bundle", str(evidence), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["source_summary"]["review_section_count"] == 10
    _assert_safe(report)
