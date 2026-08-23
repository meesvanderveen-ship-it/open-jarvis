from __future__ import annotations

import json
from pathlib import Path

from tools.prepare_approved_parameter_profile_activation import build_activation_plan


def _candidate(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"profile_version": 2, "profiles": {"balanced_candidate_conservative": {"candidate_params": {"MAX_SPREAD_PCT": "0.0060", "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1"}}}}), encoding="utf-8")


def test_activation_without_ack_writes_nothing(tmp_path: Path) -> None:
    c = tmp_path / "candidate.json"
    _candidate(c)
    report = build_activation_plan(candidate_path=c, profile="balanced_candidate_conservative", root=tmp_path)
    assert report["valid"] is True
    assert report["write_performed"] is False
    assert not (tmp_path / "state/approved_parameter_profile.json").exists()


def test_activation_wrong_ack_writes_nothing(tmp_path: Path) -> None:
    c = tmp_path / "candidate.json"
    _candidate(c)
    report = build_activation_plan(candidate_path=c, profile="balanced_candidate_conservative", root=tmp_path, write=True, ack="wrong")
    assert report["write_performed"] is False
    assert "exact_ack_required" in report["blockers"]
    assert not (tmp_path / "state/approved_parameter_profile.json").exists()


def test_activation_correct_ack_writes_expected_file_only(tmp_path: Path) -> None:
    c = tmp_path / "candidate.json"
    _candidate(c)
    dry = build_activation_plan(candidate_path=c, profile="balanced_candidate_conservative", root=tmp_path)
    report = build_activation_plan(
        candidate_path=c,
        profile="balanced_candidate_conservative",
        root=tmp_path,
        write=True,
        ack=dry["required_ack"],
    )
    target = tmp_path / "state/approved_parameter_profile.json"
    assert report["write_performed"] is True
    assert report["ack_valid"] is True
    assert target.exists()
    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload == report["approved_profile_json"]
    assert not (tmp_path / ".env").exists()
