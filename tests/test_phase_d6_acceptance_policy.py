from __future__ import annotations

from pathlib import Path

from bot.phase_d6_acceptance_policy import (
    POLICY_SECTIONS,
    build_d6_acceptance_policy_report,
    render_d6_acceptance_policy_markdown,
)


def test_all_policy_sections_exist(tmp_path: Path) -> None:
    report = build_d6_acceptance_policy_report(root=tmp_path)

    for section in POLICY_SECTIONS:
        assert section in report
        assert report[section]["policy_passed"] is False


def test_parameter_and_learning_gates_remain_false(tmp_path: Path) -> None:
    report = build_d6_acceptance_policy_report(root=tmp_path)
    flags = report["governance_flags"]

    assert flags["d6_acceptance_policy_ready"] is True
    assert flags["parameter_review_candidate"] is False
    assert flags["parameter_review_approved"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["learning_to_execution_ready"] is False
    assert flags["live_learning_allowed"] is False


def test_no_parameter_values_optimization_or_ranking(tmp_path: Path) -> None:
    report = build_d6_acceptance_policy_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["parameter_values_proposed"] is False
    assert meta["optimization_performed"] is False
    assert meta["ranking_performed"] is False
    assert meta["parameter_mutation_performed"] is False


def test_no_external_or_state_side_effect_flags(tmp_path: Path) -> None:
    report = build_d6_acceptance_policy_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False


def test_markdown_contains_policy_summary(tmp_path: Path) -> None:
    report = build_d6_acceptance_policy_report(root=tmp_path)
    markdown = render_d6_acceptance_policy_markdown(report)

    assert "D6 Acceptance Policy" in markdown
    assert "sample_size_policy" in markdown
    assert "parameter_review_candidate" in markdown
