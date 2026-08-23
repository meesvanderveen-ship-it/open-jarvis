from __future__ import annotations

import json
from pathlib import Path

from bot.phase_controlled_learning_governance import (
    build_controlled_learning_governance_report,
    render_controlled_learning_governance_markdown,
)


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    _write_report(d6 / "d6-acceptance-policy-20260609.json", {"phase": "d6_acceptance_policy_v1", "classification": "WATCH"})
    _write_report(
        d6 / "d6-backlearning-label-export-pack-20260609.json",
        {"phase": "d6_backlearning_label_export_pack_v1", "classification": "OK"},
    )
    _write_report(
        d6 / "d6-human-review-decision-pack-20260609.json",
        {"phase": "d6_human_review_decision_pack_v1", "classification": "WATCH"},
    )
    _write_report(
        d6 / "d6-backlearning-parameter-evidence-plan-20260609.json",
        {"phase": "d6_backlearning_parameter_evidence_plan_v1", "classification": "WATCH"},
    )
    _write_report(
        d6 / "roadmap-readiness-decision-map-20260609.json",
        {"phase": "roadmap_readiness_decision_map_v1", "classification": "WATCH"},
    )
    _write_report(
        d6 / "safe-regression-harness-20260609.json",
        {"phase": "safe_regression_harness_v1", "classification": "WATCH"},
    )


def test_all_governance_stages_are_present(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_controlled_learning_governance_report(root=tmp_path)

    names = [row["name"] for row in report["stage_matrix"]]
    assert names == [
        "evidence_collection_only",
        "label_export_ready",
        "human_review_ready",
        "acceptance_policy_ready",
        "parameter_review_candidate",
        "parameter_proposal_candidate",
        "human_parameter_approval_required",
        "dry_run_shadow_learning_allowed",
        "execution_bridge_candidate",
        "live_learning_candidate",
        "live_learning_allowed",
    ]
    assert report["governance_flags"]["controlled_learning_governance_ready"] is True


def test_current_max_allowed_stage_is_report_only_not_execution(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    flags = build_controlled_learning_governance_report(root=tmp_path)["governance_flags"]

    assert flags["current_max_allowed_learning_stage"] == "acceptance_policy_ready"
    assert flags["parameter_proposal_candidate"] is False
    assert flags["parameter_values_proposed"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["learning_to_execution_ready"] is False
    assert flags["live_learning_allowed"] is False


def test_forbidden_transitions_and_ack_requirements_are_explicit(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_controlled_learning_governance_report(root=tmp_path)

    assert report["forbidden_transitions"]
    assert "execution bridge" in " ".join(report["explicit_ACK_requirements"])
    ack_stages = [row for row in report["stage_matrix"] if row["requires_ACK"]]
    assert any(row["name"] == "parameter_proposal_candidate" for row in ack_stages)
    assert any(row["name"] == "live_learning_allowed" for row in ack_stages)


def test_no_external_state_or_parameter_side_effect_flags(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    meta = build_controlled_learning_governance_report(root=tmp_path)["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert meta["optimization_performed"] is False
    assert meta["ranking_performed"] is False


def test_missing_reports_fail_safe_without_crashing(tmp_path: Path) -> None:
    report = build_controlled_learning_governance_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["missing_evidence_sources"]
    assert report["governance_flags"]["parameter_review_candidate"] is False
    assert report["governance_flags"]["learning_to_execution_ready"] is False


def test_markdown_contains_stage_matrix(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_controlled_learning_governance_markdown(
        build_controlled_learning_governance_report(root=tmp_path)
    )

    assert "Controlled Learning Governance" in markdown
    assert "acceptance_policy_ready" in markdown
    assert "live_learning_allowed" in markdown
