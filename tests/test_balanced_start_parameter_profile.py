from __future__ import annotations

import json
from pathlib import Path

from tools.propose_balanced_start_parameter_profile import build_balanced_start_parameter_profile_candidate


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_balanced_profile_candidate_is_report_only_and_watch_gated(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("ENABLE_APPROVED_PARAMETER_PROFILE", "false")
    _write_json(
        tmp_path / "logs/decision_outcome_report.json",
        {"missed_opportunities": [{"ticker": "BTC-USDC"}] * 4, "false_positive_plans": [], "correct_avoids": []},
    )

    report = build_balanced_start_parameter_profile_candidate(root=tmp_path, generated_at="2026-06-12T00:00:00Z")

    assert report["read_only"] is True
    assert report["approved_parameter_profile_written"] is False
    assert report["allowed_keys_only"] is True
    assert report["safe_to_activate_now"] is False
    assert report["recommended_operator_action"] == "review_candidate_human_only"
    assert report["candidate_profile"]["AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE"] == "1"
    assert sorted(report["profiles"]) == [
        "balanced_candidate_conservative",
        "balanced_candidate_moderate",
        "baseline_current",
    ]
    assert report["profiles"]["balanced_candidate_conservative"]["approved_profile_json"]["parameters"]["AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE"] == "1"
    assert report["hash_to_approve"]
