from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_backlearning_parameter_evidence_plan import (
    build_d6_backlearning_parameter_evidence_plan_report,
    render_d6_backlearning_parameter_evidence_plan_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_evidence(root: Path, *, include_all: bool = True) -> None:
    reports = root / "reports" / "d6"
    _write_json(
        reports / "d5-d6-evidence-expansion-20260609.json",
        {
            "phase": "d5_d6_evidence_expansion_v1",
            "classification": "WATCH",
            "fee_evidence": {"fee_gap_present": True},
            "readiness_and_governance_flags": {
                "d5_d6_evidence_expansion_ready": True,
                "human_review_ready": True,
                "learning_to_execution_ready": False,
                "parameter_change_allowed": False,
                "parameter_review_approved": False,
            },
        },
    )
    _write_json(
        reports / "multi-ticker-paper-lifecycle-replay-20260609.json",
        {
            "phase": "multi_ticker_paper_lifecycle_replay_v1",
            "classification": "WATCH",
            "gate_decision": {
                "multi_ticker_paper_lifecycle_replay_ready": True,
                "tickers_replay_ready_count": 0,
                "tickers_replay_partial_count": 18,
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
            },
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
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
            },
        },
    )
    if not include_all:
        return
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
        {
            "phase": "main_workflow_parity_report_v1",
            "gate_decision": {
                "main_workflow_parity_report_ready": True,
                "old_multi_ticker_decision_workflow_seen": True,
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
            },
        },
    )
    _write_json(
        reports / "exit-workflow-readiness-report-20260609.json",
        {
            "phase": "exit_workflow_readiness_report_v1",
            "exit_workflow_readiness_report_ready": True,
            "master_live_exit_ready": False,
            "follower_sell_ready": False,
            "learning_to_execution_ready": False,
        },
    )
    _write_json(
        reports / "safe-regression-harness-20260609.json",
        {
            "phase": "safe_regression_harness_v1",
            "classification": "WATCH",
            "local_safe_regression_passed": True,
            "selected_tests": {"selected_tests_classification": "WATCH", "selected_tests_passed_count": 14},
        },
    )
    _write_json(
        reports / "state-hygiene-cleanup-preview-20260609.json",
        {"phase": "state_hygiene_cleanup_preview_v1", "status": "WATCH", "state_write_performed": False},
    )
    _write_json(
        reports / "coverage-backtest-decision-v1-20260601.json",
        {
            "phase": "coverage_backtest_decision_v1",
            "status": "coverage_backtest_decision_ready",
            "parameter_evidence_created": False,
            "optimization_performed": False,
            "ranking_performed": False,
            "learning_to_execution_enabled": False,
        },
    )


def test_report_builds_with_missing_optional_evidence_sources(tmp_path: Path) -> None:
    _write_evidence(tmp_path, include_all=False)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["governance_flags"]["d6_backlearning_parameter_evidence_plan_ready"] is True
    assert report["governance_flags"]["human_review_ready"] is True
    assert report["evidence_summary"]["evidence_sources_missing"]


def test_evidence_gaps_produce_watch_not_crash(tmp_path: Path) -> None:
    _write_evidence(tmp_path)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)
    gaps = report["evidence_summary"]["evidence_gaps"]

    assert report["classification"] == "WATCH"
    assert "non_btc_product_rule_evidence_missing" in gaps
    assert "tp_close_fee_gap_requires_human_review" in gaps


def test_parameter_categories_are_all_included(tmp_path: Path) -> None:
    _write_evidence(tmp_path)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)
    categories = {row["category"] for row in report["parameter_evidence_matrix"]}

    assert categories == {
        "entry_gating_parameters",
        "sizing_parameters",
        "orderbook_entry_placement_parameters",
        "fill_no_fill_parameters",
        "exit_parameters",
        "ticker_scope_parameters",
        "learning_governance_parameters",
    }


def test_no_parameter_values_are_proposed_for_live_use(tmp_path: Path) -> None:
    _write_evidence(tmp_path)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)
    text = json.dumps(report, sort_keys=True)

    assert "proposed_value" not in text
    assert "recommended_value" not in text
    assert "best_parameter" not in text
    assert all(row["contains_parameter_proposal"] is False for row in report["parameter_evidence_matrix"])
    assert report["parameter_inventory_summary"]["contains_parameter_recommendations"] is False


def test_governance_flags_remain_closed(tmp_path: Path) -> None:
    _write_evidence(tmp_path)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)
    flags = report["governance_flags"]

    assert flags["parameter_change_allowed"] is False
    assert flags["parameter_review_approved"] is False
    assert flags["learning_to_execution_ready"] is False
    assert flags["live_learning_allowed"] is False
    assert flags["parameter_review_candidate"] is False


def test_no_optimization_ranking_external_or_state_actions(tmp_path: Path) -> None:
    _write_evidence(tmp_path)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["optimization_performed"] is False
    assert meta["ranking_performed"] is False
    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False


def test_malformed_evidence_fails_safe(tmp_path: Path) -> None:
    reports = tmp_path / "reports" / "d6"
    reports.mkdir(parents=True)
    (reports / "d5-d6-evidence-expansion-20260609.json").write_text("{not json", encoding="utf-8")

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["governance_flags"]["d6_backlearning_parameter_evidence_plan_ready"] is False
    assert report["governance_flags"]["human_review_ready"] is False
    assert report["evidence_summary"]["evidence_sources_malformed"]


def test_markdown_contains_required_sections(tmp_path: Path) -> None:
    _write_evidence(tmp_path)

    report = build_d6_backlearning_parameter_evidence_plan_report(root=tmp_path)
    markdown = render_d6_backlearning_parameter_evidence_plan_markdown(report)

    assert "D6 Backlearning Parameter Evidence Plan" in markdown
    assert "Governance Flags" in markdown
    assert "Parameter Evidence Matrix" in markdown
