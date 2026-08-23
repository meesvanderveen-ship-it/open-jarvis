from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_human_review_decision_pack import (
    build_d6_human_review_decision_pack_report,
    render_d6_human_review_decision_pack_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_sources(root: Path, *, include_all: bool = True) -> None:
    reports = root / "reports" / "d6"
    _write_json(
        reports / "d6-backlearning-parameter-evidence-plan-20260609.json",
        {
            "phase": "d6_backlearning_parameter_evidence_plan_v1",
            "classification": "WATCH",
            "governance_flags": {
                "d6_backlearning_parameter_evidence_plan_ready": True,
                "human_review_ready": True,
                "parameter_review_candidate": False,
                "parameter_review_approved": False,
                "parameter_change_allowed": False,
                "learning_to_execution_ready": False,
                "live_learning_allowed": False,
            },
            "parameter_evidence_matrix": [
                {
                    "category": "entry_gating_parameters",
                    "evidence_present": ["old multi-ticker decision workflow evidence"],
                    "evidence_missing": ["OOS evidence"],
                },
                {
                    "category": "sizing_parameters",
                    "evidence_present": ["BTC-USDC tiny scope caps documented"],
                    "evidence_missing": ["drawdown evidence"],
                },
                {
                    "category": "orderbook_entry_placement_parameters",
                    "evidence_present": ["paper C4 lifecycle replay labels"],
                    "evidence_missing": ["placement samples"],
                },
                {
                    "category": "fill_no_fill_parameters",
                    "evidence_present": ["five terminal no-fill events"],
                    "evidence_missing": ["larger sample size"],
                },
                {
                    "category": "exit_parameters",
                    "evidence_present": ["exit workflow readiness report"],
                    "evidence_missing": ["master live exit readiness"],
                },
                {
                    "category": "ticker_scope_parameters",
                    "evidence_present": ["configured 18-ticker universe"],
                    "evidence_missing": ["17 non-BTC product-rule evidence rows"],
                },
                {
                    "category": "learning_governance_parameters",
                    "evidence_present": ["D6 parameter inventory and review scaffolds"],
                    "evidence_missing": ["sample-size policy"],
                },
            ],
        },
    )
    _write_json(
        reports / "d5-d6-evidence-expansion-20260609.json",
        {
            "phase": "d5_d6_evidence_expansion_v1",
            "classification": "WATCH",
            "fee_evidence": {"fee_gap_present": True},
            "readiness_and_governance_flags": {"human_review_ready": True, "parameter_change_allowed": False},
        },
    )
    _write_json(
        reports / "per-ticker-product-rule-evidence-cache-20260609.json",
        {
            "phase": "per_ticker_product_rule_evidence_cache_v1",
            "classification": "WATCH",
            "gate_decision": {
                "per_ticker_product_rule_evidence_cache_ready": True,
                "all_ticker_product_rule_evidence_ready": False,
                "tickers_ready_count": 1,
                "tickers_missing_count": 17,
            },
        },
    )
    if not include_all:
        return
    _write_json(
        reports / "multi-ticker-paper-lifecycle-replay-20260609.json",
        {
            "phase": "multi_ticker_paper_lifecycle_replay_v1",
            "classification": "WATCH",
            "gate_decision": {
                "multi_ticker_paper_lifecycle_replay_ready": True,
                "tickers_replay_partial_count": 18,
                "all_ticker_lifecycle_parity_ready": False,
            },
        },
    )
    _write_json(
        reports / "all-ticker-readiness-gate-20260609.json",
        {
            "phase": "all_ticker_readiness_gate_v1",
            "classification": "WATCH",
            "readiness_flags": {
                "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
                "all_ticker_ready": False,
                "all_ticker_live_allowed_now": False,
            },
        },
    )
    _write_json(
        reports / "main-workflow-parity-report-20260609.json",
        {"phase": "main_workflow_parity_report_v1", "gate_decision": {"old_multi_ticker_decision_workflow_seen": True}},
    )
    _write_json(
        reports / "exit-workflow-readiness-report-20260609.json",
        {"phase": "exit_workflow_readiness_report_v1", "master_live_exit_ready": False, "follower_sell_ready": False},
    )
    _write_json(
        reports / "state-hygiene-cleanup-preview-20260609.json",
        {"phase": "state_hygiene_cleanup_preview_v1", "status": "WATCH", "cleanup_preview_count": 1, "apply_now": False},
    )
    _write_json(
        reports / "safe-regression-harness-20260609.json",
        {"phase": "safe_regression_harness_v1", "classification": "WATCH", "local_safe_regression_passed": True},
    )
    _write_json(
        reports / "follower-receiver-api-audit-20260609.json",
        {
            "phase": "follower_receiver_api_audit_v1",
            "classification": "WATCH",
            "readiness_flags": {
                "follower_receiver_code_accessible": False,
                "follower_buy_ready": False,
                "follower_sell_ready": False,
                "follower_ready_for_live": False,
            },
        },
    )


def test_report_builds_with_missing_optional_evidence_sources(tmp_path: Path) -> None:
    _write_sources(tmp_path, include_all=False)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["human_review_decision_pack_ready"] is True
    assert report["evidence_source_summary"]["evidence_sources_missing"]


def test_all_evidence_areas_are_included(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)
    areas = {row["area"] for row in report["decision_matrix"]}

    assert areas == {
        "entry_gating_evidence",
        "sizing_evidence",
        "orderbook_entry_placement_evidence",
        "fill_no_fill_evidence",
        "exit_evidence",
        "ticker_scope_evidence",
        "product_rule_evidence",
        "all_ticker_lifecycle_parity_evidence",
        "fee_discrepancy_evidence",
        "state_hygiene_evidence",
        "replication_follower_evidence",
        "learning_governance_evidence",
    }


def test_incomplete_evidence_produces_watch(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["decision_status_counts"]["blocked"] >= 1
    assert report["parameter_review_readiness"]["parameter_review_candidate"] is False


def test_labels_only_status_is_allowed_without_parameter_approval(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)
    labels = [row for row in report["decision_matrix"] if row["decision_status"] == "labels_only"]

    assert labels
    assert all(row["parameter_review_approved"] is False for row in labels)
    assert all(row["parameter_change_allowed"] is False for row in labels)


def test_governance_and_no_action_flags_remain_closed(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)
    meta = report["metadata"]
    flags = report["governance_flags"]

    assert meta["parameter_values_proposed"] is False
    assert meta["optimization_performed"] is False
    assert meta["ranking_performed"] is False
    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert flags["parameter_values_proposed"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["parameter_review_approved"] is False
    assert flags["learning_to_execution_ready"] is False
    assert flags["live_learning_allowed"] is False


def test_no_parameter_proposal_language_is_emitted(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)
    text = json.dumps(report, sort_keys=True)

    assert "proposed_value" not in text
    assert "recommended_value" not in text
    assert "best_parameter" not in text
    assert report["parameter_review_readiness"]["parameter_values_proposed"] is False


def test_malformed_evidence_fails_safe(tmp_path: Path) -> None:
    reports = tmp_path / "reports" / "d6"
    reports.mkdir(parents=True)
    (reports / "d6-backlearning-parameter-evidence-plan-20260609.json").write_text("{not json", encoding="utf-8")

    report = build_d6_human_review_decision_pack_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["evidence_source_summary"]["evidence_sources_malformed"]
    assert report["governance_flags"]["parameter_change_allowed"] is False


def test_markdown_contains_decision_matrix(tmp_path: Path) -> None:
    _write_sources(tmp_path)

    report = build_d6_human_review_decision_pack_report(root=tmp_path)
    markdown = render_d6_human_review_decision_pack_markdown(report)

    assert "D6 Human-Review Decision Pack" in markdown
    assert "Decision Matrix" in markdown
    assert "parameter_values_proposed" in markdown
