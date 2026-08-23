from __future__ import annotations

import json
from pathlib import Path

from tools.summarize_autonomous_run_next_steps import build_next_steps_summary


def _write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_next_steps_keep_baseline_with_little_evidence(tmp_path: Path) -> None:
    run = tmp_path / "run.json"
    prof = tmp_path / "profile.json"
    _write(run, {"summary": {}, "open_orders_summary": {}})
    _write(prof, {"basis": {"missed_fill_opportunity": 0}, "profiles": {}})
    report = build_next_steps_summary(run_report=run, balanced_profile=prof)
    assert report["recommendation"] == "continue_mode_a"
    assert report["profile_action"] == "keep_baseline"


def test_next_steps_conservative_on_missed_fill_without_risk_issues(tmp_path: Path) -> None:
    run = tmp_path / "run.json"
    prof = tmp_path / "profile.json"
    _write(run, {"summary": {"blocked_actions": 0, "errors": 0}, "open_orders_summary": {}})
    _write(prof, {"basis": {"missed_fill_opportunity": 3}, "profiles": {"balanced_candidate_conservative": {"hash": "abc"}}})
    report = build_next_steps_summary(run_report=run, balanced_profile=prof)
    assert report["recommendation"] == "continue_mode_a"
    assert report["profile_action"] == "review_conservative_candidate"


def test_next_steps_stop_and_fix_on_runtime_issues(tmp_path: Path) -> None:
    run = tmp_path / "run.json"
    prof = tmp_path / "profile.json"
    _write(run, {"summary": {"atomic_write_errors": 1}, "open_orders_summary": {}})
    _write(prof, {"basis": {"missed_fill_opportunity": 3}, "profiles": {}})
    report = build_next_steps_summary(run_report=run, balanced_profile=prof)
    assert report["recommendation"] == "stop_and_fix"
    assert report["profile_action"] == "no_profile_activation"
