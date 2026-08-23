from __future__ import annotations

import json
from pathlib import Path

from tools.build_learning_parameter_dynamic_capability import build_capability_report, main as capability_main


def test_learning_capability_reports_propose_not_direct_mutation(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "bot").mkdir()
    (tmp_path / "reports/live_learning").mkdir(parents=True)
    (tmp_path / "reports/backtests").mkdir(parents=True)
    (tmp_path / ".env").write_text(
        "\n".join([
            "LEARNING_TO_EXECUTION_ALLOWED=false",
            "LIVE_LEARNING_ALLOWED=false",
            "PARAMETER_CHANGE_ALLOWED=false",
            "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED=false",
            "ENABLE_APPROVED_PARAMETER_PROFILE=true",
            "APPROVED_PARAMETER_PROFILE_HASH=abc",
        ]) + "\n",
        encoding="utf-8",
    )
    (tmp_path / "tools/build_live_learning_sidecar.py").write_text("parameter_recommendations = []\n", encoding="utf-8")
    (tmp_path / "tools/run_cost_aware_backlearning.py").write_text("APPROVED_PARAMETER_PROFILE_WHITELIST\n", encoding="utf-8")
    (tmp_path / "bot/approved_parameter_profile.py").write_text("APPROVED_PARAMETER_PROFILE_HASH\nsha256_file\n", encoding="utf-8")
    (tmp_path / "tools/activate_approved_parameter_profile.py").write_text("required_ack\nAPPROVED_PARAMETER_PROFILE_HASH\n", encoding="utf-8")

    report = build_capability_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")

    assert report["learning_can_propose_parameters"] is True
    assert report["learning_can_directly_mutate_live_parameters"] is False
    assert report["approved_profile_exact_hash_required"] is True
    assert report["operator_review_required"] is True
    assert report["safety_blockers"] == []


def test_learning_capability_blocks_enabled_mutation_flag(tmp_path: Path) -> None:
    (tmp_path / "tools").mkdir()
    (tmp_path / "bot").mkdir()
    (tmp_path / ".env").write_text("PARAMETER_CHANGE_ALLOWED=true\n", encoding="utf-8")
    (tmp_path / "bot/approved_parameter_profile.py").write_text("APPROVED_PARAMETER_PROFILE_HASH\nsha256_file\n", encoding="utf-8")

    report = build_capability_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")

    assert report["learning_can_directly_mutate_live_parameters"] is True
    assert "direct_live_parameter_mutation_flag_enabled" in report["safety_blockers"]


def test_learning_capability_tool_writes_reports(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "tools").mkdir()
    (tmp_path / "bot").mkdir()
    (tmp_path / ".env").write_text("PARAMETER_CHANGE_ALLOWED=false\n", encoding="utf-8")
    (tmp_path / "tools/build_live_learning_sidecar.py").write_text("parameter_recommendations\n", encoding="utf-8")
    (tmp_path / "bot/approved_parameter_profile.py").write_text("APPROVED_PARAMETER_PROFILE_HASH\nsha256_file\n", encoding="utf-8")

    assert capability_main([]) == 0
    payload = json.loads((tmp_path / "reports/research/learning-parameter-dynamic-capability-latest.json").read_text())
    assert payload["coinbase_call_attempted"] is False
    assert (tmp_path / "reports/research/learning-parameter-dynamic-capability-latest.md").exists()
