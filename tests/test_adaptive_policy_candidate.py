from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.adaptive_policy_lab import build_adaptive_policy_candidate, stable_payload_hash
from tests.test_adaptive_policy_lab import _report, _rows


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=cwd, text=True, capture_output=True, check=True)


def test_candidate_safety_review_hash_flags() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80)))
    assert candidate["safe_to_activate_now"] is False
    assert candidate["requires_operator_review"] is True
    assert candidate["requires_hash_ack_activation"] is True
    assert candidate["can_authorize_execution"] is False
    assert candidate["can_block_execution"] is False
    assert candidate["can_mutate_parameters"] is False
    assert candidate["hash"] == stable_payload_hash(candidate)


def test_candidate_hash_is_stable_for_identical_input() -> None:
    c1 = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80)))
    c2 = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80)))
    c2["generated_at"] = c1["generated_at"]
    c2["hash"] = stable_payload_hash(c2)
    assert c1["hash"] == c2["hash"]


def test_candidate_tool_writes_only_adaptive_reports_not_env_or_approved_state(tmp_path: Path) -> None:
    (tmp_path / "reports/reflection").mkdir(parents=True)
    (tmp_path / "reports/reflection/reflection-learning-latest.json").write_text(json.dumps(_report(_rows(300, missed=80))), encoding="utf-8")
    (tmp_path / ".env").write_text("UNCHANGED=true\n", encoding="utf-8")
    state = tmp_path / "state/approved_parameter_profile.json"
    state.parent.mkdir(parents=True)
    state.write_text('{"parameters": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125"}}\n', encoding="utf-8")
    result = _run(["tools/build_adaptive_policy_candidate.py", "--json", "--root", str(tmp_path)])
    payload = json.loads(result.stdout)
    assert payload["safe_to_activate_now"] is False
    assert (tmp_path / "reports/adaptive_policy/adaptive-policy-candidate-latest.json").exists()
    assert (tmp_path / "reports/adaptive_policy/adaptive-policy-candidate-latest.md").exists()
    assert (tmp_path / "reports/adaptive_policy/adaptive-policy-lab-latest.json").exists()
    assert (tmp_path / "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl").exists()
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "UNCHANGED=true\n"
    assert state.read_text(encoding="utf-8") == '{"parameters": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125"}}\n'


def test_status_and_audit_tools_are_context_only(tmp_path: Path) -> None:
    (tmp_path / "reports/reflection").mkdir(parents=True)
    (tmp_path / "reports/reflection/reflection-learning-latest.json").write_text(json.dumps(_report(_rows(20))), encoding="utf-8")
    status = json.loads(_run(["tools/show_adaptive_policy_lab_status.py", "--json", "--root", str(tmp_path)]).stdout)
    assert status["can_authorize_execution"] is False
    assert status["candidate_available"] is False
    audit = json.loads(_run(["tools/write_adaptive_policy_audit.py", "--json", "--root", str(tmp_path)]).stdout)
    assert audit["safety_policy"]["no_coinbase_actions"] is True
    assert audit["safety_policy"]["no_env_mutation"] is True
    assert audit["safety_policy"]["no_production_order_state_mutation"] is True
    assert (tmp_path / "reports/audits/adaptive-policy-lab-latest.json").exists()


def test_no_coinbase_or_order_state_mutation_fields() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80)))
    assert "Coinbase credentials" not in candidate.get("proposed_parameter_changes", [])
    assert candidate["source_policy"] == "adaptive_policy_report_only_no_live_mutation"
