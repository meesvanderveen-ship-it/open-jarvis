from __future__ import annotations

import json
from pathlib import Path

from tools.build_parameter_proposal_funnel import (
    build_parameter_proposal_funnel,
    render_markdown,
    write_reports,
)
from bot.learnable_parameter_registry import parameter_definitions
from bot.parameter_proposal_scoring import TIERS


def test_funnel_counts_sum_to_total_parameters(tmp_path: Path):
    report = build_parameter_proposal_funnel(root=tmp_path)
    assert report["total_parameters"] == len(parameter_definitions())
    assert sum(report["funnel_counts"].values()) == report["total_parameters"]
    assert set(report["tier_order"]) == set(TIERS)


def test_funnel_never_populates_apply_ready_candidate(tmp_path: Path):
    report = build_parameter_proposal_funnel(root=tmp_path)
    assert report["funnel_counts"]["apply_ready_candidate"] == 0
    assert report["funnel"]["apply_ready_candidate"] == []
    assert "governor" in report["apply_ready_policy"] or "approved_parameter_profile" in report["apply_ready_policy"]


def test_funnel_rows_carry_why_no_proposal_text(tmp_path: Path):
    report = build_parameter_proposal_funnel(root=tmp_path)
    observed = report["funnel"]["observed_signal"]
    assert observed
    assert all(row["why_no_proposal"] for row in observed)


def test_by_category_breakdown_matches_funnel(tmp_path: Path):
    report = build_parameter_proposal_funnel(root=tmp_path)
    total_by_category = sum(
        count for tiers in report["by_category"].values() for count in tiers.values()
    )
    assert total_by_category == report["total_parameters"]


def test_write_reports_produces_valid_json_and_markdown(tmp_path: Path):
    report = build_parameter_proposal_funnel(root=tmp_path)
    write_reports(report, root=tmp_path)

    json_path = tmp_path / "reports" / "learning" / "parameter-proposal-funnel-latest.json"
    md_path = tmp_path / "reports" / "learning" / "parameter-proposal-funnel-latest.md"
    assert json_path.exists()
    assert md_path.exists()

    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["schema_version"] == "parameter_proposal_funnel_v1"

    markdown = md_path.read_text(encoding="utf-8")
    assert "# Parameter Proposal Funnel" in markdown
    assert "observed_signal" in markdown


def test_render_markdown_handles_empty_tier_gracefully(tmp_path: Path):
    report = build_parameter_proposal_funnel(root=tmp_path)
    markdown = render_markdown(report)
    assert "## apply_ready_candidate (0)" in markdown
    assert "- none" in markdown
