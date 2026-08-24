from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

import pytest

import bot.growbot_river_governor_bridge as bridge_mod
from bot.adaptive_policy_lab import CANDIDATE_JSON_PATH, GROWBOT_RIVER_REPORT_PATH, stable_payload_hash
from bot.autonomous_parameter_governor import ACTIVATION_LOG_PATH, ROLLBACK_PLAN_PATH
from bot.growbot_river_governor_bridge import (
    build_growbot_river_governor_bridge_status,
    evaluate_fast_start_candidate_eligibility,
    select_top_growbot_river_proposal,
    write_growbot_river_governor_bridge_status,
)
from bot.growbot_river_readiness import LIVE_CYCLE_READINESS_PATH, READINESS_PATH
from bot.learnable_parameter_registry import get_parameter

ROOT = Path(__file__).resolve().parents[1]
PARAMETER = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"


def _run(args: List[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], cwd=cwd, text=True, capture_output=True, check=True)


def _write_base_state(root: Path) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (root / "state/positions.json").write_text("{}\n", encoding="utf-8")
    (root / "state/approved_parameter_profile.json").write_text(
        json.dumps({"parameters": {PARAMETER: "0.0125"}}) + "\n", encoding="utf-8",
    )


def _river_proposal(
    *,
    blockers: Optional[List[str]] = None,
    parameter: str = PARAMETER,
    confidence: float = 0.9,
    suggested_step_pct: float = 1.8,
    evidence_count: int = 200,
    regimes: Optional[List[str]] = None,
    direction_stable_runs: int = 12,
    current_value: float = 0.0125,
    candidate_value: float = 0.0123,
) -> Dict[str, Any]:
    return {
        "parameter": parameter,
        "direction": "loosen",
        "confidence": confidence,
        "suggested_step_pct": suggested_step_pct,
        "phase": "stabilization",
        "current_value": current_value,
        "candidate_value": candidate_value,
        "evidence_count": evidence_count,
        "regimes": regimes if regimes is not None else ["trend_up", "range_chop", "drawdown_risk_off"],
        "direction_stable_runs": direction_stable_runs,
        "reason": "online reward evidence",
        "activation_route": "current_governor_and_approved_profile",
        "rollback": ["retain_previous_approved_profile_hash"],
        "evidence_requirements": ["cost_aware_outcomes"],
        "blockers": list(blockers or []),
    }


def _write_river_report(root: Path, *, proposals: Optional[List[Dict[str, Any]]] = None, blocked_proposals: Optional[List[Dict[str, Any]]] = None) -> None:
    path = root / GROWBOT_RIVER_REPORT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "generated_at": "2026-06-22T00:00:00Z",
        "proposals": proposals or [],
        "blocked_proposals": blocked_proposals or [],
    }), encoding="utf-8")


def _write_candidate_payload(root: Path, *, candidate_row_blockers: Optional[List[str]] = None, parameter: str = PARAMETER) -> None:
    path = root / CANDIDATE_JSON_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "parameter": parameter,
        "current_value": "0.0125",
        "candidate_value": "0.0123",
        "direction": "loosen",
        "source": bridge_mod.GROWBOT_RIVER_SOURCE_TAG,
        "reason": "GrowBot/River online evidence",
        "blockers": list(candidate_row_blockers or []),
    }
    bucket_key = "blocked_parameter_changes" if candidate_row_blockers else "proposed_parameter_changes"
    path.write_text(json.dumps({
        "growbot_river_learning": {"available": True},
        "proposed_parameter_changes": [row] if bucket_key == "proposed_parameter_changes" else [],
        "blocked_parameter_changes": [row] if bucket_key == "blocked_parameter_changes" else [],
    }), encoding="utf-8")


def _write_readiness(
    root: Path,
    *,
    ready: bool,
    blockers: Optional[List[Dict[str, Any]]] = None,
    fast_start_ready: Optional[bool] = None,
) -> None:
    path = root / READINESS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Any] = {
        "stabilization_readiness": {
            "ready": ready,
            "real_blockers": blockers or ([] if ready else [{"blocker": "feature_snapshot_coverage_below_80pct"}]),
        },
    }
    if fast_start_ready is not None:
        payload["fast_start_autotune_readiness"] = {
            "ready": fast_start_ready,
            "real_blockers": [] if fast_start_ready else ["feature_snapshot_coverage_below_50pct"],
        }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_live_cycle_readiness(root: Path) -> None:
    path = root / LIVE_CYCLE_READINESS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"forward_episode_requirements": {"approx_live_decision_cycles_needed": 42}}), encoding="utf-8")


def _governor_status(
    *,
    apply_ready: bool,
    proposed_parameter: str = "",
    why_not_applied: Optional[List[str]] = None,
    apply_blockers: Optional[List[str]] = None,
    candidate_available: bool = False,
    operator_ack_missing: bool = False,
) -> Dict[str, Any]:
    return {
        "apply_ready": apply_ready,
        "candidate_available": candidate_available,
        "proposed_parameter": proposed_parameter,
        "why_not_applied": why_not_applied or [],
        "operator_ack_missing": operator_ack_missing,
        "reason": "activation_allowed" if apply_ready else "blocked",
        "readiness_layers": {"apply_blockers": apply_blockers or []},
    }


def _setup_root(
    tmp_path: Path,
    *,
    ready: bool,
    candidate_row_blockers: Optional[List[str]] = None,
    fast_start_ready: Optional[bool] = None,
    river_proposal: Optional[Dict[str, Any]] = None,
) -> None:
    _write_base_state(tmp_path)
    _write_river_report(tmp_path, proposals=[river_proposal or _river_proposal()])
    _write_candidate_payload(tmp_path, candidate_row_blockers=candidate_row_blockers)
    _write_readiness(tmp_path, ready=ready, fast_start_ready=fast_start_ready)
    _write_live_cycle_readiness(tmp_path)


def test_proposal_present_stabilization_false_blocks_auto_apply(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=False)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False, why_not_applied=["insufficient_market_regimes"]))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["bridge_ready"] is True
    assert status["candidate_ready"] is True
    assert status["auto_apply_eligible"] is False
    assert status["next_required_condition"].startswith("awaiting_live_episode_volume:")
    assert status["top_parameter_candidate"]["parameter"] == PARAMETER


def test_proposal_present_stabilization_true_and_governor_ready_is_auto_apply_eligible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=True, proposed_parameter=PARAMETER))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["auto_apply_eligible"] is True
    assert status["blocked_reason"] == "none_ready_to_apply"
    assert status["governor"]["candidate_is_governor_visible"] is True


def test_governor_apply_ready_but_different_parameter_is_not_auto_apply_eligible(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge must not trust a governor apply_ready signal for an unrelated parameter."""
    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=True, proposed_parameter="MAX_SPREAD_PCT"))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["auto_apply_eligible"] is False
    assert status["governor"]["candidate_is_governor_visible"] is False


def test_cooldown_active_blocks_auto_apply_and_is_surfaced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(
        bridge_mod,
        "validate_governor",
        lambda root, env: _governor_status(apply_ready=False, proposed_parameter=PARAMETER, why_not_applied=["cooldown_active"], apply_blockers=["cooldown_active"]),
    )

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["auto_apply_eligible"] is False
    assert status["blocked_reason"] == ["cooldown_active"]
    assert status["next_required_condition"] == "governor_apply_blockers: cooldown_active"


def test_candidate_blocked_by_effect_size_deadband_surfaces_specific_condition(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True, candidate_row_blockers=["effect_size_below_deadband"])
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False, why_not_applied=["candidate_not_available"]))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["next_required_condition"].startswith("river_suggested_step_below_lab_effect_size_deadband")
    assert "effect_size_below_deadband" in status["top_parameter_candidate"]["candidate_lab_blockers"]


def test_operator_ack_not_yet_set_reports_one_time_not_per_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(
        bridge_mod,
        "validate_governor",
        lambda root, env: _governor_status(apply_ready=False, proposed_parameter=PARAMETER, why_not_applied=["missing_or_invalid_ack"], apply_blockers=["missing_or_invalid_ack"], operator_ack_missing=True),
    )

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["auto_apply_eligible"] is False
    assert "once_in_env" in status["next_required_condition"]
    assert "no_per_change_operator_ack" in status["next_required_condition"] or "no per-change operator ACK" in status["next_required_condition"]


def test_rollback_plan_absent_reports_not_available(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=False)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["rollback"]["rollback_plan_available"] is False
    assert not (tmp_path / ROLLBACK_PLAN_PATH).exists()


def test_rollback_plan_present_is_surfaced_verbatim(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=False)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False))
    plan_path = tmp_path / ROLLBACK_PLAN_PATH
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps({
        "backup_profile_path": "state/backups/x.json",
        "changed_parameter": PARAMETER,
        "activated_profile_hash": "new-hash",
        "previous_profile_hash": "old-hash",
    }), encoding="utf-8")

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["rollback"]["rollback_plan_available"] is True
    assert status["rollback"]["changed_parameter"] == PARAMETER
    assert status["rollback"]["activated_profile_hash"] == "new-hash"
    assert status["rollback"]["previous_profile_hash"] == "old-hash"


@pytest.mark.parametrize(
    "log_lines,expected_status",
    [
        ([], "no_prior_activation"),
        ([json.dumps({"applied": True, "changed_parameter": PARAMETER, "profile_hash": "h1", "evaluated": False})], "applied"),
        ([json.dumps({"applied": False, "changed_parameter": "", "evaluated": False})], "not_applied"),
    ],
)
def test_last_apply_status_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, log_lines: List[str], expected_status: str) -> None:
    _setup_root(tmp_path, ready=False)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False))
    if log_lines:
        log_path = tmp_path / ACTIVATION_LOG_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["last_apply_status"]["status"] == expected_status


def test_select_top_growbot_river_proposal_prefers_unblocked_then_falls_back() -> None:
    blocked_only = {"proposals": [], "blocked_proposals": [_river_proposal(parameter="A"), _river_proposal(parameter="B")]}
    top = select_top_growbot_river_proposal(blocked_only)
    assert top["parameter"] in {"A", "B"}

    with_unblocked = {
        "proposals": [dict(_river_proposal(parameter="C"), confidence=0.5, evidence_count=5)],
        "blocked_proposals": [dict(_river_proposal(parameter="D"), confidence=0.99, evidence_count=999)],
    }
    top = select_top_growbot_river_proposal(with_unblocked)
    assert top["parameter"] == "C"

    assert select_top_growbot_river_proposal({}) == {}


def test_build_status_never_writes_files_and_declares_report_only_safety_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge must remain a read-only aggregator: no new activation route, no mutation."""
    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=True, proposed_parameter=PARAMETER))
    before = sorted(str(p) for p in tmp_path.rglob("*") if p.is_file())

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    after = sorted(str(p) for p in tmp_path.rglob("*") if p.is_file())
    assert before == after, "build_growbot_river_governor_bridge_status must not write any files"
    safety = status["safety_policy"]
    assert safety["report_only"] is True
    assert safety["can_authorize_execution"] is False
    assert safety["can_mutate_parameters"] is False
    assert safety["can_apply_profile"] is False
    assert safety["introduces_new_activation_route"] is False
    assert safety["uses_existing_governor_and_approved_profile_route_only"] is True


def test_build_status_calls_validate_governor_without_bypassing_real_gates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The bridge must defer entirely to the existing governor's own validate_governor
    (no candidate/readiness override), so it can never see a friendlier answer than the
    real governor route (including its BotConfig-backed readiness chain) would give."""
    _setup_root(tmp_path, ready=True)
    calls: List[Mapping[str, Any]] = []

    def _spy(*, root: Path, env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
        calls.append({"root": root, "env": env})
        return _governor_status(apply_ready=False)

    monkeypatch.setattr(bridge_mod, "validate_governor", _spy)
    build_growbot_river_governor_bridge_status(root=tmp_path)

    assert len(calls) == 1
    assert calls[0]["root"] == tmp_path


def test_top_parameter_candidate_includes_required_status_fields(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=True, proposed_parameter=PARAMETER))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)
    top = status["top_parameter_candidate"]

    for field in (
        "parameter", "direction", "current_value", "candidate_value", "suggested_step_pct",
        "confidence", "evidence_count", "regimes_seen", "expected_effect", "rollback",
    ):
        assert field in top
    assert "auto_apply_eligible" in status
    assert "blocked_reason" in status
    assert "next_required_condition" in status
    assert "last_apply_status" in status


def test_write_outputs_then_status_files_exist_with_consistent_content(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=False)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)
    outputs = write_growbot_river_governor_bridge_status(status, root=tmp_path)

    json_path = Path(outputs["json"])
    md_path = Path(outputs["markdown"])
    assert json_path.exists() and md_path.exists()
    on_disk = json.loads(json_path.read_text(encoding="utf-8"))
    assert on_disk["bridge_ready"] == status["bridge_ready"]
    assert "GrowBot/River" in md_path.read_text(encoding="utf-8")


def test_no_growbot_river_proposal_present_yet(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write_base_state(tmp_path)
    _write_readiness(tmp_path, ready=False)
    _write_live_cycle_readiness(tmp_path)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["top_parameter_candidate"]["parameter"] is None
    assert status["auto_apply_eligible"] is False


def test_cli_tool_show_bridge_status_runs_against_minimal_fixture(tmp_path: Path) -> None:
    """tools/show_growbot_river_governor_bridge_status.py is the operator-facing
    surface for this bridge; it must run cleanly with no fixtures at all and report
    an explicit not-ready state rather than crashing."""
    (tmp_path / "state").mkdir(parents=True)
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text("{}\n", encoding="utf-8")
    result = json.loads(_run(["tools/show_growbot_river_governor_bridge_status.py", "--json", "--root", str(tmp_path)]).stdout)
    assert result["bridge_ready"] is False
    assert result["auto_apply_eligible"] is False
    assert result["safety_policy"]["can_mutate_parameters"] is False


def test_prepare_tool_apply_delegates_to_existing_run_governor_not_a_parallel_route(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`tools/prepare_growbot_river_governor_candidate.py --apply` must call the
    existing `bot.autonomous_parameter_governor.run_governor` and nothing else -- it
    must not implement its own apply/mutation logic."""
    import tools.prepare_growbot_river_governor_candidate as prepare_tool

    _setup_root(tmp_path, ready=True)
    calls: List[Dict[str, Any]] = []

    def _fake_run_governor(*, root: Path, apply: bool) -> Dict[str, Any]:
        calls.append({"root": root, "apply": apply})
        return {"applied": False, "reason": "stubbed_for_test"}

    monkeypatch.setattr(prepare_tool, "run_governor", _fake_run_governor)
    monkeypatch.setattr(
        prepare_tool,
        "build_growbot_river_governor_bridge_status",
        lambda root: {"bridge_ready": True, "candidate_ready": True, "auto_apply_eligible": False},
    )
    monkeypatch.setattr(
        prepare_tool,
        "write_growbot_river_governor_bridge_status",
        lambda status, root: {"json": str(root / "status.json"), "markdown": str(root / "status.md")},
    )

    exit_code = prepare_tool.main(["--root", str(tmp_path), "--skip-refresh", "--apply", "--json"])

    assert exit_code == 0
    assert len(calls) == 1
    assert calls[0] == {"root": tmp_path, "apply": True}


def test_prepare_tool_apply_holds_the_existing_governor_lock_so_it_cannot_race_the_governor_cycle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A scheduled `--apply` run must not be able to race a concurrent
    tools/run_autonomous_parameter_governor.py cycle over the same
    approved_parameter_profile.json / activation log: both must go through
    the same existing acquire_governor_lock/release_governor_lock pair."""
    import tools.prepare_growbot_river_governor_candidate as prepare_tool
    from bot.autonomous_parameter_governor import acquire_governor_lock

    _setup_root(tmp_path, ready=True)
    monkeypatch.setattr(
        prepare_tool,
        "build_growbot_river_governor_bridge_status",
        lambda root: {"bridge_ready": True, "candidate_ready": True, "auto_apply_eligible": False},
    )
    monkeypatch.setattr(
        prepare_tool,
        "write_growbot_river_governor_bridge_status",
        lambda status, root: {"json": str(root / "status.json"), "markdown": str(root / "status.md")},
    )
    calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(prepare_tool, "run_governor", lambda **kwargs: calls.append(kwargs) or {"applied": False})

    held = acquire_governor_lock(tmp_path)
    assert held["acquired"] is True

    exit_code = prepare_tool.main(["--root", str(tmp_path), "--skip-refresh", "--apply", "--json"])

    assert exit_code == 0
    assert calls == [], "run_governor must not run while another governor cycle holds the lock"


def test_growbot_river_governor_timer_templates_exist_and_use_locking_runner() -> None:
    service = ROOT / "deploy_templates/coinbase-growbot-river-governor.service"
    timer = ROOT / "deploy_templates/coinbase-growbot-river-governor.timer"
    assert service.exists()
    assert timer.exists()
    service_text = service.read_text(encoding="utf-8")
    assert "tools/prepare_growbot_river_governor_candidate.py --apply --json" in service_text
    assert "No Coinbase order submit/cancel/apply authority" in service_text
    assert "governor lock" in service_text
    assert "OnUnitActiveSec=1h" in timer.read_text(encoding="utf-8")


# --- fast_start_autotune tier -------------------------------------------------


def test_evaluate_fast_start_candidate_eligibility_matches_real_world_top_candidate() -> None:
    """Mirrors the actual live top-ranked GrowBot/River proposal observed on
    2026-06-22 (PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT, confidence~0.8998,
    evidence_count~207, 5 regimes, suggested_step_pct~1.8247, 12 stable runs).
    Every per-candidate criterion already passes; only the broader sidecar
    evidence base (passed in here as True) gates the final answer."""
    proposal = _river_proposal(
        confidence=0.8998,
        suggested_step_pct=1.8247,
        evidence_count=207,
        regimes=["drawdown_risk_off", "high_volatility", "range_chop", "trend_down", "trend_up"],
        direction_stable_runs=12,
        current_value=0.0125,
        candidate_value=0.01227191,
    )
    definition = get_parameter(PARAMETER)

    result = evaluate_fast_start_candidate_eligibility(top_proposal=proposal, definition=definition, sidecar_ready=True)

    assert result["eligible"] is True
    assert result["blocking_reasons"] == []
    assert all(result["checks"].values())


def test_evaluate_fast_start_candidate_eligibility_blocked_when_sidecar_evidence_not_ready() -> None:
    """The same strong candidate is not eligible while the broader sidecar
    evidence base (coverage/regimes/river/walk-forward) has not cleared the
    fast_start bar yet -- this is the real current state as of 2026-06-22
    (46.1% feature coverage vs the 50% fast_start floor)."""
    proposal = _river_proposal(
        confidence=0.8998,
        suggested_step_pct=1.8247,
        evidence_count=207,
        regimes=["drawdown_risk_off", "high_volatility", "range_chop", "trend_down", "trend_up"],
        direction_stable_runs=12,
    )
    definition = get_parameter(PARAMETER)

    result = evaluate_fast_start_candidate_eligibility(top_proposal=proposal, definition=definition, sidecar_ready=False)

    assert result["eligible"] is False
    assert result["blocking_reasons"] == ["sidecar_evidence_base_not_yet_fast_start_ready"]


def test_evaluate_fast_start_candidate_eligibility_blocked_by_parameter_not_on_allowlist() -> None:
    # DEFAULT_QUOTE_SIZE_USDC is sizing/exposure, deliberately high_risk_manual_only
    # and never fast_start-eligible -- unlike EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT,
    # which was extended onto fast_start (2026-07 gap fix, see
    # test_growbot_river_learning.py::test_fast_start_autotune_allowlist_is_narrower_than_full_governor_allowlist).
    proposal = _river_proposal(parameter="DEFAULT_QUOTE_SIZE_USDC")
    definition = get_parameter("DEFAULT_QUOTE_SIZE_USDC")

    result = evaluate_fast_start_candidate_eligibility(top_proposal=proposal, definition=definition, sidecar_ready=True)

    assert result["eligible"] is False
    assert "parameter_not_on_fast_start_low_risk_allowlist" in result["blocking_reasons"]


def test_evaluate_fast_start_candidate_eligibility_blocked_by_oversized_step() -> None:
    proposal = _river_proposal(suggested_step_pct=8.0)
    definition = get_parameter(PARAMETER)

    result = evaluate_fast_start_candidate_eligibility(top_proposal=proposal, definition=definition, sidecar_ready=True)

    assert result["eligible"] is False
    assert "suggested_step_pct_outside_fast_start_fine_tuning_bounds" in result["blocking_reasons"]


def test_evaluate_fast_start_candidate_eligibility_blocked_by_low_confidence_or_evidence() -> None:
    low_confidence = evaluate_fast_start_candidate_eligibility(
        top_proposal=_river_proposal(confidence=0.6), definition=get_parameter(PARAMETER), sidecar_ready=True,
    )
    assert low_confidence["eligible"] is False
    assert "confidence_below_0.85" in low_confidence["blocking_reasons"]

    low_evidence = evaluate_fast_start_candidate_eligibility(
        top_proposal=_river_proposal(evidence_count=10), definition=get_parameter(PARAMETER), sidecar_ready=True,
    )
    assert low_evidence["eligible"] is False
    assert "evidence_count_below_75" in low_evidence["blocking_reasons"]


def test_evaluate_fast_start_candidate_eligibility_no_candidate_is_not_eligible() -> None:
    result = evaluate_fast_start_candidate_eligibility(top_proposal={}, definition=None, sidecar_ready=True)
    assert result["eligible"] is False
    assert result["parameter"] is None


def test_bridge_surfaces_fast_start_tier_distinct_from_strict_stabilization_and_real_governor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new fast_start tier must be visibly distinct from the strict
    stabilization tier, and must never make auto_apply_eligible (the real
    governor authority) any friendlier than the unchanged governor itself
    reports."""
    proposal = _river_proposal(
        confidence=0.8998,
        suggested_step_pct=1.8247,
        evidence_count=207,
        regimes=["drawdown_risk_off", "high_volatility", "range_chop", "trend_down", "trend_up"],
        direction_stable_runs=12,
        candidate_value=0.01227191,
    )
    _setup_root(tmp_path, ready=False, fast_start_ready=True, river_proposal=proposal)
    monkeypatch.setattr(
        bridge_mod, "validate_governor",
        lambda root, env: _governor_status(apply_ready=False, why_not_applied=["effect_size_below_deadband"]),
    )

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["strict_stabilization_ready"] is False
    assert status["fast_start_autotune_ready"] is True
    assert status["fast_start_candidate_eligibility"]["eligible"] is True
    assert status["first_autonomous_candidate_if_fast_start"]["parameter"] == PARAMETER
    # The real governor authority is untouched: still not auto_apply_eligible.
    assert status["auto_apply_eligible"] is False


def test_bridge_fast_start_not_ready_when_sidecar_evidence_not_ready_even_for_a_strong_candidate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    proposal = _river_proposal(
        confidence=0.95, suggested_step_pct=1.5, evidence_count=300,
        regimes=["trend_up", "trend_down", "range_chop"], direction_stable_runs=10,
    )
    _setup_root(tmp_path, ready=False, fast_start_ready=False, river_proposal=proposal)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=False))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["fast_start_autotune_ready"] is False
    assert status["fast_start_candidate_eligibility"]["eligible"] is False
    assert status["first_autonomous_candidate_if_fast_start"] is None


def test_expected_parameter_change_reports_direction_current_and_candidate_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True, fast_start_ready=True)
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: _governor_status(apply_ready=True, proposed_parameter=PARAMETER))

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    change = status["expected_parameter_change"]
    assert change["parameter"] == PARAMETER
    assert change["direction"] == "loosen"
    assert change["current_value"] == 0.0125
    assert change["candidate_value"] == 0.0123
    assert change["change_pct"] is not None


def test_cooldown_status_surfaced_from_governor_validate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_root(tmp_path, ready=True)
    governor_status = _governor_status(apply_ready=False, proposed_parameter=PARAMETER, why_not_applied=["cooldown_active"])
    governor_status["cooldown_active"] = True
    governor_status["last_activation"] = {"changed_parameter": PARAMETER, "applied": True}
    monkeypatch.setattr(bridge_mod, "validate_governor", lambda root, env: governor_status)

    status = build_growbot_river_governor_bridge_status(root=tmp_path)

    assert status["cooldown"]["cooldown_active"] is True
    assert status["cooldown"]["last_activation"]["changed_parameter"] == PARAMETER


def test_prepare_tool_without_apply_never_calls_run_governor(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import tools.prepare_growbot_river_governor_candidate as prepare_tool

    _setup_root(tmp_path, ready=True)
    calls: List[Dict[str, Any]] = []
    monkeypatch.setattr(prepare_tool, "run_governor", lambda **kwargs: calls.append(kwargs) or {"applied": False})
    monkeypatch.setattr(
        prepare_tool,
        "build_growbot_river_governor_bridge_status",
        lambda root: {"bridge_ready": True, "candidate_ready": True, "auto_apply_eligible": False},
    )
    monkeypatch.setattr(
        prepare_tool,
        "write_growbot_river_governor_bridge_status",
        lambda status, root: {"json": str(root / "status.json"), "markdown": str(root / "status.md")},
    )

    exit_code = prepare_tool.main(["--root", str(tmp_path), "--skip-refresh", "--json"])

    assert exit_code == 0
    assert calls == []
