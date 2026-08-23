from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_shadow_learning_report import (
    build_d6_shadow_learning_report,
    render_d6_shadow_learning_report_markdown,
)


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    _write(
        d6 / "d6-backlearning-label-export-pack-20260609.json",
        {
            "phase": "d6_backlearning_label_export_pack_v1",
            "classification": "OK",
            "label_counts": {
                "ticker_label_count": 18,
                "lifecycle_label_count": 108,
                "outcome_label_count": 185,
                "review_label_count": 12,
                "governance_label_count": 4,
                "export_record_count": 327,
            },
        },
    )
    for name in (
        "d6-acceptance-policy-20260609.json",
        "d6-human-review-decision-pack-20260609.json",
        "controlled-learning-governance-20260609.json",
        "multi-ticker-paper-lifecycle-replay-20260609.json",
        "product-rule-fixture-evidence-20260609.json",
    ):
        _write(d6 / name, {"phase": name, "classification": "WATCH"})


def test_shadow_learning_report_is_dry_run_only(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_d6_shadow_learning_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["report_only"] is True
    assert meta["dry_run_only"] is True
    assert meta["shadow_learning_only"] is True
    assert meta["execution_bridge_created"] is False
    assert meta["runtime_coupling_created"] is False
    assert meta["state_write_performed"] is False


def test_shadow_learning_never_proposes_or_enables_execution(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_d6_shadow_learning_report(root=tmp_path)
    flags = report["governance_flags"]

    assert flags["d6_shadow_learning_report_ready"] is True
    assert flags["report_only_shadow_learning_ready"] is True
    assert flags["execution_bridge_created"] is False
    assert flags["parameter_values_proposed"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["learning_to_execution_ready"] is False
    assert flags["live_learning_allowed"] is False
    assert report["metadata"]["optimization_performed"] is False
    assert report["metadata"]["ranking_performed"] is False


def test_missing_labels_fail_safe_as_watch(tmp_path: Path) -> None:
    report = build_d6_shadow_learning_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["missing_label_sources"]
    assert report["governance_flags"]["learning_to_execution_ready"] is False


def test_shadow_outputs_are_isolated_and_non_executable(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_d6_shadow_learning_report(root=tmp_path)

    assert "parameter values" in report["forbidden_outputs"]
    assert "execution bridge artifacts" in report["forbidden_outputs"]
    assert any("do not write state/" in item for item in report["isolation_boundaries"])
    assert "exact execution-bridge ACK missing" in report["blockers_to_execution_bridge"]


def test_shadow_markdown_renders(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_d6_shadow_learning_report_markdown(build_d6_shadow_learning_report(root=tmp_path))

    assert "D6 Shadow Learning Report" in markdown
    assert "execution_bridge_created" in markdown
