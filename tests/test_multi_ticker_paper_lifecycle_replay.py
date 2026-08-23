from __future__ import annotations

import json
from pathlib import Path

from bot.phase_multi_ticker_paper_lifecycle_replay import (
    build_multi_ticker_paper_lifecycle_replay_report,
    render_multi_ticker_paper_lifecycle_replay_markdown,
)


def _write_project(root: Path, *, config_text: str | None = None) -> None:
    (root / "bot").mkdir(parents=True)
    (root / "reports" / "d6").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    (root / "state" / "open_orders.json").write_text('{"orders": {}}', encoding="utf-8")
    (root / "bot" / "config.py").write_text(
        config_text
        if config_text is not None
        else "ALLOWED_TICKERS='BTC-USDC,ETH-USDC,SOL-USDC'\n",
        encoding="utf-8",
    )
    parity_rows = [
        {
            "ticker": "BTC-USDC",
            "old_multi_ticker_decision_workflow_status": "seen",
        },
        {
            "ticker": "ETH-USDC",
            "old_multi_ticker_decision_workflow_status": "seen",
        },
        {
            "ticker": "SOL-USDC",
            "old_multi_ticker_decision_workflow_status": "probable",
        },
    ]
    (root / "reports" / "d6" / "main-workflow-parity-report-20260609.json").write_text(
        json.dumps(
            {
                "configured_universe": parity_rows,
                "gate_decision": {
                    "old_multi_ticker_decision_workflow_seen": True,
                    "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
                    "all_ticker_lifecycle_parity_ready": False,
                    "all_ticker_live_allowed_now": False,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "reports" / "d6" / "all-ticker-readiness-gate-20260609.json").write_text(
        json.dumps(
            {
                "readiness_flags": {
                    "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
                    "all_ticker_live_allowed_now": False,
                },
                "per_ticker_readiness_matrix": [
                    {
                        "ticker": "BTC-USDC",
                        "product_rule_status": "ready",
                        "data_coverage_status": "partial",
                        "c4_entry_lifecycle_status": "proven",
                        "d1_fill_to_position_status": "partial",
                        "d2_plan_status": "partial",
                        "d3_exit_status": "proven",
                        "d4_cancel_replace_status": "proven",
                        "d5_d6_evidence_status": "ready",
                    },
                    {
                        "ticker": "ETH-USDC",
                        "product_rule_status": "missing",
                        "data_coverage_status": "partial",
                        "c4_entry_lifecycle_status": "missing",
                        "d1_fill_to_position_status": "missing",
                        "d2_plan_status": "missing",
                        "d3_exit_status": "missing",
                        "d4_cancel_replace_status": "missing",
                        "d5_d6_evidence_status": "partial",
                    },
                    {
                        "ticker": "SOL-USDC",
                        "product_rule_status": "missing",
                        "data_coverage_status": "partial",
                        "c4_entry_lifecycle_status": "missing",
                        "d1_fill_to_position_status": "missing",
                        "d2_plan_status": "missing",
                        "d3_exit_status": "missing",
                        "d4_cancel_replace_status": "missing",
                        "d5_d6_evidence_status": "partial",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    (root / "reports" / "d6" / "product-rule-fixture-evidence-20260609.json").write_text(
        json.dumps(
            {
                "classification": "OK",
                "universe_summary": {
                    "fixture_completion_ready": True,
                    "paper_replay_usable_ticker_count": 3,
                    "fixture_evidence_ticker_count": 2,
                    "live_readonly_cached_ticker_count": 1,
                    "missing_evidence_ticker_count": 0,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "reports" / "d6" / "per-ticker-product-rule-evidence-cache-20260609.json").write_text(
        json.dumps(
            {
                "classification": "WATCH",
                "per_ticker_matrix": [
                    {
                        "ticker": "BTC-USDC",
                        "product_rule_evidence_status": "ready",
                        "evidence_strength": "live_readonly_cached",
                        "paper_replay_usable": True,
                    },
                    {
                        "ticker": "ETH-USDC",
                        "product_rule_evidence_status": "partial",
                        "evidence_strength": "local_fixture",
                        "paper_replay_usable": True,
                    },
                    {
                        "ticker": "SOL-USDC",
                        "product_rule_evidence_status": "partial",
                        "evidence_strength": "local_fixture",
                        "paper_replay_usable": True,
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def test_configured_tickers_are_all_included(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    tickers = [row["ticker"] for row in report["per_ticker_replay_matrix"]]

    assert tickers == ["BTC-USDC", "ETH-USDC", "SOL-USDC"]
    assert report["universe_summary"]["configured_ticker_count"] == 3


def test_old_decision_workflow_is_separate_from_lifecycle_replay(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    eth = {row["ticker"]: row for row in report["per_ticker_replay_matrix"]}["ETH-USDC"]

    assert eth["old_decision_workflow_status"] == "seen"
    assert eth["paper_lifecycle_replay_status"] == "paper_lifecycle_replay_ready"
    assert eth["product_rule_evidence_strength"] == "local_fixture"
    assert "blocked_missing_live_product_rule_evidence" in eth["lifecycle_blockers"]


def test_btc_can_be_candidate_while_all_ticker_live_is_false(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    btc = {row["ticker"]: row for row in report["per_ticker_replay_matrix"]}["BTC-USDC"]

    assert btc["paper_c4_entry_replay_status"] == "paper_replay_ready"
    assert report["gate_decision"]["btc_usdc_tiny_scope_ready_for_operator_preflight"] is True
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False


def test_non_btc_tickers_are_not_nonexistent(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    rows = {row["ticker"]: row for row in report["per_ticker_replay_matrix"]}

    assert rows["ETH-USDC"]["configured"] is True
    assert rows["SOL-USDC"]["old_decision_workflow_status"] in {"seen", "probable"}
    assert rows["ETH-USDC"]["paper_c4_entry_replay_status"] == "paper_replay_ready"


def test_fixture_product_rules_upgrade_paper_not_live_representation(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    eth = {row["ticker"]: row for row in report["per_ticker_replay_matrix"]}["ETH-USDC"]

    assert eth["product_rule_evidence_status"] == "partial"
    assert eth["product_rule_evidence_strength"] == "local_fixture"
    assert eth["paper_replay_usable"] is True
    assert eth["paper_lifecycle_replay_status"] == "paper_lifecycle_replay_ready"
    assert eth["live_ready"] is False
    assert eth["next_step"] == "eligible for paper lifecycle fixture review only"


def test_btc_live_readonly_cached_still_requires_fresh_preflight_and_ack(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    btc = {row["ticker"]: row for row in report["per_ticker_replay_matrix"]}["BTC-USDC"]

    assert btc["product_rule_evidence_strength"] == "live_readonly_cached"
    assert btc["live_ready"] is False
    assert "fresh_operator_preflight_and_live_start_ack_missing" in btc["lifecycle_blockers"]


def test_paper_scenarios_do_not_write_state(tmp_path: Path) -> None:
    _write_project(tmp_path)
    before = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)

    assert report["metadata"]["state_write_performed"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == before
    assert all(row["state_write_performed"] is False for row in report["scenario_coverage"])


def test_replay_includes_c4_d1_d2_d3_d4_d5_stages(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    row = report["per_ticker_replay_matrix"][0]

    for key in (
        "paper_c4_entry_replay_status",
        "paper_d1_fill_to_position_replay_status",
        "paper_d2_plan_replay_status",
        "paper_d3_exit_replay_status",
        "paper_d4_cancel_replace_replay_status",
        "paper_d5_evidence_replay_status",
    ):
        assert key in row


def test_learning_and_live_flags_remain_false(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)

    assert report["learning_backlearning_boundary"]["learning_to_execution_ready"] is False
    assert report["learning_backlearning_boundary"]["parameter_change_allowed"] is False
    assert report["learning_backlearning_boundary"]["parameter_review_approved"] is False
    assert report["learning_backlearning_boundary"]["live_learning_allowed"] is False
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False
    assert report["gate_decision"]["all_ticker_lifecycle_parity_ready"] is False


def test_no_external_or_live_side_effect_flags(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["fixture_evidence_consumed"] is True
    assert meta["parameter_mutation_performed"] is False
    assert meta["learning_to_execution_performed"] is False


def test_malformed_evidence_cache_fails_safe(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "reports" / "d6" / "per-ticker-product-rule-evidence-cache-20260609.json").write_text(
        '{"per_ticker_matrix": "bad"}',
        encoding="utf-8",
    )

    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    rows = {row["ticker"]: row for row in report["per_ticker_replay_matrix"]}

    assert report["classification"] == "WATCH"
    assert rows["ETH-USDC"]["paper_lifecycle_replay_status"] == "blocked_missing_fixture_evidence"
    assert "blocked_missing_fixture_evidence" in rows["ETH-USDC"]["lifecycle_blockers"]
    assert rows["ETH-USDC"]["live_ready"] is False


def test_empty_or_malformed_config_fails_safe(tmp_path: Path) -> None:
    _write_project(tmp_path, config_text="# no ticker config here\n")

    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert "configured_universe_from_config_missing_or_malformed" in report["watch_reasons"]
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False
    assert report["per_ticker_replay_matrix"]


def test_markdown_contains_core_summary(tmp_path: Path) -> None:
    _write_project(tmp_path)
    report = build_multi_ticker_paper_lifecycle_replay_report(root=tmp_path)
    markdown = render_multi_ticker_paper_lifecycle_replay_markdown(report)

    assert "Multi-Ticker Paper Lifecycle Replay" in markdown
    assert "all_ticker_live_allowed_now" in markdown
    assert "ETH-USDC" in markdown
