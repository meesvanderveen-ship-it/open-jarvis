from __future__ import annotations

import json
from pathlib import Path

from tools import run_reflection_adaptive_report_sidecar as sidecar


def test_sidecar_runs_report_only_commands_in_order_and_writes_outputs(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run(name, args, *, root):
        calls.append(name)
        return {"name": name, "ok": True, "returncode": 0, "duration_sec": 0, "summary": {}}

    monkeypatch.setattr(sidecar, "_run_command", fake_run)
    (tmp_path / "reports/reflection").mkdir(parents=True)
    (tmp_path / "reports/reflection/reflection-learning-latest.json").write_text(
        json.dumps({"summary": {"total_events": 2, "validated_conclusions": 2}, "evaluations": [{}, {}]}),
        encoding="utf-8",
    )
    (tmp_path / "reports/adaptive_policy").mkdir(parents=True)
    (tmp_path / "reports/adaptive_policy/adaptive-policy-candidate-latest.json").write_text(
        json.dumps({
            "candidate_available": False,
            "reason": "insufficient_market_regimes",
            "recommendation": "collect_more_data",
            "evidence_summary": {"market_regimes": ["network_supportive_liquidity_neutral"]},
        }),
        encoding="utf-8",
    )
    history = tmp_path / "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl"
    history.parent.mkdir(parents=True, exist_ok=True)
    history.write_text(json.dumps({"direction_by_parameter_scope": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab": "loosen"}}) + "\n", encoding="utf-8")
    analysis_dir = tmp_path / "reports/adaptive_policy/analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    (analysis_dir / "parameter-candidate-analysis-latest.json").write_text(
        json.dumps({
            "candidate_available": False,
            "reason": "insufficient_market_regimes",
            "recommendation": "collect_more_data",
            "parameter_analysis": [
                {
                    "direction_history": {
                        "history_items_available": 1,
                        "last_3_direction_entries": ["loosen"],
                        "sidecar_runs_seen": 1,
                        "candidate_history_path": str(history),
                    },
                    "statistical_gates": {
                        "direction_stability_gate": {
                            "history_items_available": 1,
                            "matched_scope_key": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab",
                            "match_strategy": "exact",
                            "observed_runs": 1,
                            "required_runs": 3,
                            "stability_reason": "not_enough_history",
                        }
                    },
                }
            ],
        }),
        encoding="utf-8",
    )
    (tmp_path / "reports/autonomous_parameter_governor").mkdir(parents=True)
    (tmp_path / "reports/autonomous_parameter_governor/governor-status-latest.json").write_text(
        json.dumps({"enabled": False, "mode": "report_only", "governor_activation_allowed": False, "reason": "candidate_not_available"}),
        encoding="utf-8",
    )

    env = tmp_path / ".env"
    orders = tmp_path / "state/open_orders.json"
    positions = tmp_path / "state/positions.json"
    profile = tmp_path / "state/approved_parameter_profile.json"
    orders.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("UNCHANGED=true\n", encoding="utf-8")
    orders.write_text('{"orders": {}}\n', encoding="utf-8")
    positions.write_text("{}\n", encoding="utf-8")
    profile.write_text('{"parameters": {}}\n', encoding="utf-8")

    summary = sidecar.build_sidecar_summary(root=tmp_path)
    outputs = sidecar.write_sidecar_outputs(summary, root=tmp_path)

    assert calls == [name for name, _args in sidecar.COMMANDS]
    assert summary["status"] == "completed"
    assert summary["adaptive"]["candidate_history_path"].endswith("adaptive-policy-candidate-history.jsonl")
    assert summary["adaptive"]["sidecar_runs_seen"] == 1
    assert summary["adaptive"]["direction_history"]["candidate_history_path"].endswith("adaptive-policy-candidate-history.jsonl")
    assert summary["adaptive"]["direction_stability"]["matched_scope_key"] == "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
    assert summary["adaptive"]["direction_stability"]["match_strategy"] == "exact"
    assert summary["adaptive"]["direction_stability"]["observed_runs"] == 1
    assert summary["safety"]["coinbase_action_performed"] is False
    assert Path(outputs["json"]).exists()
    assert Path(outputs["markdown"]).exists()
    assert Path(outputs["jsonl_log"]).exists()
    assert "direction_stability" in Path(outputs["markdown"]).read_text(encoding="utf-8")
    assert env.read_text(encoding="utf-8") == "UNCHANGED=true\n"
    assert orders.read_text(encoding="utf-8") == '{"orders": {}}\n'
    assert positions.read_text(encoding="utf-8") == "{}\n"
    assert profile.read_text(encoding="utf-8") == '{"parameters": {}}\n'


def test_sidecar_fails_safely_when_subcommand_fails(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []

    def fake_run(name, args, *, root):
        calls.append(name)
        return {"name": name, "ok": name != "analyze_parameter_candidate", "returncode": 1, "duration_sec": 0, "summary": {}}

    monkeypatch.setattr(sidecar, "_run_command", fake_run)
    summary = sidecar.build_sidecar_summary(root=tmp_path)

    assert summary["status"] == "failed"
    assert calls == [
        "build_reflection_learning_report",
        "show_reflection_persistence_status",
        "build_adaptive_policy_candidate",
        "analyze_parameter_candidate",
    ]
    assert summary["safety"]["service_lifecycle_performed"] is False
    assert summary["safety"]["approved_profile_live_mutation_performed"] is False


def test_timer_templates_exist_but_are_not_installed() -> None:
    root = Path(__file__).resolve().parents[1]
    service = root / "deploy_templates/reflection-adaptive-sidecar.service"
    timer = root / "deploy_templates/reflection-adaptive-sidecar.timer"
    assert service.exists()
    assert timer.exists()
    assert "Do not enable without operator approval" in service.read_text(encoding="utf-8")
    assert "Do not enable without operator approval" in timer.read_text(encoding="utf-8")
