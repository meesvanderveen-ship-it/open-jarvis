from __future__ import annotations

import json
from pathlib import Path

from bot.phase_shadow_parameter_approximation_pack import (
    PARAMETER_CATEGORIES,
    build_shadow_parameter_approximation_pack,
    render_shadow_parameter_approximation_pack_markdown,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sources(root: Path, *, attempted: bool = False, passed: bool = False) -> Path:
    d6 = root / "reports" / "d6"
    _write(d6 / "d6-backlearning-label-export-pack-20260609.json", {"phase": "labels"})
    _write(d6 / "multi-ticker-paper-lifecycle-replay-20260609.json", {"phase": "replay"})
    _write(d6 / "per-ticker-product-rule-evidence-cache-20260609.json", {"phase": "cache"})
    preflight = d6 / "all-ticker-live-readonly-preflight-20260609.json"
    _write(
        preflight,
        {
            "gate_decision": {
                "all_ticker_live_readonly_preflight_attempted": attempted,
                "all_ticker_live_readonly_preflight_passed": passed,
            }
        },
    )
    return preflight


def test_all_parameter_categories_are_included_and_report_only(tmp_path: Path) -> None:
    preflight = _write_sources(tmp_path)
    report = build_shadow_parameter_approximation_pack(root=tmp_path, preflight_report_path=preflight)

    assert [row["category"] for row in report["parameter_approximation_matrix"]] == PARAMETER_CATEGORIES
    flags = report["governance_flags"]
    assert flags["shadow_parameter_approximation_pack_ready"] is True
    assert flags["parameter_values_approved"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["safe_to_mutate_parameters_now"] is False
    assert report["metadata"]["optimization_performed"] is False
    assert report["metadata"]["ranking_performed"] is False
    assert report["metadata"]["parameter_mutation_performed"] is False


def test_review_only_ranges_are_labelled(tmp_path: Path) -> None:
    preflight = _write_sources(tmp_path)
    report = build_shadow_parameter_approximation_pack(root=tmp_path, preflight_report_path=preflight)

    for row in report["parameter_approximation_matrix"]:
        assert "review-only approximation" in row["review_only_approximate_range"]
        assert row["forbidden_action"]
    assert report["classification"] == "WATCH"


def test_consumes_passed_preflight_without_enabling_mutation(tmp_path: Path) -> None:
    preflight = _write_sources(tmp_path, attempted=True, passed=True)
    report = build_shadow_parameter_approximation_pack(root=tmp_path, preflight_report_path=preflight)

    assert report["preflight_attempted"] is True
    assert report["preflight_passed"] is True
    assert report["governance_flags"]["parameter_change_allowed"] is False
    assert report["governance_flags"]["learning_to_execution_ready"] is False


def test_missing_sources_fail_safe(tmp_path: Path) -> None:
    report = build_shadow_parameter_approximation_pack(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["missing_evidence_sources"]
    assert report["governance_flags"]["safe_to_mutate_parameters_now"] is False


def test_markdown_renders_flags(tmp_path: Path) -> None:
    preflight = _write_sources(tmp_path)
    markdown = render_shadow_parameter_approximation_pack_markdown(
        build_shadow_parameter_approximation_pack(root=tmp_path, preflight_report_path=preflight)
    )

    assert "Shadow Parameter Approximation Pack" in markdown
    assert "parameter_change_allowed" in markdown
