from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_backlearning_label_export_pack import (
    build_d6_backlearning_label_export_pack_report,
    render_d6_backlearning_label_export_pack_markdown,
)


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    d6.mkdir(parents=True)
    (d6 / "multi-ticker-paper-lifecycle-replay-20260609.json").write_text(
        json.dumps(
            {
                "per_ticker_replay_matrix": [
                    {
                        "ticker": "BTC-USDC",
                        "configured": True,
                        "product_rule_evidence_strength": "live_readonly_cached",
                        "paper_replay_usable": True,
                        "paper_c4_entry_replay_status": "paper_replay_ready",
                        "paper_d1_fill_to_position_replay_status": "paper_replay_ready",
                        "paper_d2_plan_replay_status": "paper_replay_ready",
                        "paper_d3_exit_replay_status": "paper_replay_ready",
                        "paper_d4_cancel_replace_replay_status": "paper_replay_ready",
                        "paper_d5_evidence_replay_status": "paper_replay_ready",
                    }
                ],
                "scenario_coverage": [
                    {
                        "ticker": "BTC-USDC",
                        "scenarios": [{"scenario": "full_fill", "status": "represented"}],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    (d6 / "per-ticker-product-rule-evidence-cache-20260609.json").write_text(
        json.dumps(
            {
                "per_ticker_matrix": [
                    {
                        "ticker": "BTC-USDC",
                        "evidence_strength": "live_readonly_cached",
                        "fixture_product_rule_evidence": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (d6 / "d5-d6-evidence-expansion-20260609.json").write_text(
        json.dumps(
            {
                "fee_evidence": {"fee_gap_present": True},
                "no_fill_duration_evidence": {"open_or_no_fill_event_count": 2},
                "cancel_replace_timing_evidence": {"chain_count": 1},
                "partial_fill_evidence": {"partial_fills_present": False},
            }
        ),
        encoding="utf-8",
    )
    (d6 / "state-hygiene-cleanup-preview-20260609.json").write_text('{"status":"WATCH"}', encoding="utf-8")
    (d6 / "d6-human-review-decision-pack-20260609.json").write_text(
        json.dumps(
            {
                "decision_matrix": [
                    {
                        "area": "fee discrepancy evidence",
                        "decision_status": "accepted_for_human_review",
                        "review_severity": "watch",
                        "blocks_parameter_review": True,
                        "blocks_learning_to_execution": True,
                    }
                ],
                "governance_flags": {"parameter_review_candidate": False},
            }
        ),
        encoding="utf-8",
    )
    (d6 / "d6-acceptance-policy-20260609.json").write_text(
        json.dumps({"governance_flags": {"d6_acceptance_policy_ready": True}}),
        encoding="utf-8",
    )


def test_export_includes_label_groups(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_d6_backlearning_label_export_pack_report(root=tmp_path)

    assert report["label_counts"]["ticker_label_count"] == 1
    assert report["label_counts"]["lifecycle_label_count"] == 6
    assert report["label_counts"]["outcome_label_count"] >= 5
    assert report["label_counts"]["review_label_count"] == 1
    assert report["label_counts"]["governance_label_count"] == 4


def test_export_does_not_train_optimize_rank_or_enable_execution(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_d6_backlearning_label_export_pack_report(root=tmp_path)
    meta = report["metadata"]
    flags = report["governance_flags"]

    assert meta["training_performed"] is False
    assert meta["optimization_performed"] is False
    assert meta["ranking_performed"] is False
    assert meta["parameter_values_proposed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert flags["learning_to_execution_ready"] is False


def test_no_external_or_state_side_effect_flags(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_d6_backlearning_label_export_pack_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False


def test_missing_sources_fail_safe(tmp_path: Path) -> None:
    report = build_d6_backlearning_label_export_pack_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["missing_label_sources"]


def test_markdown_contains_counts(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_d6_backlearning_label_export_pack_markdown(
        build_d6_backlearning_label_export_pack_report(root=tmp_path)
    )

    assert "D6 Backlearning Label Export Pack" in markdown
    assert "export_record_count" in markdown
