from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.adaptive_policy_lab import stable_payload_hash
from bot.approved_parameter_profile import sha256_file
from bot.autonomous_parameter_governor import (
    REQUIRED_ACK,
    REQUIRED_ROLLBACK_ACK,
    acquire_governor_lock,
    adaptive_readiness_layers,
    assess_activation_outcome,
    build_activation_plan,
    candidate_hash_valid,
    candidate_stale,
    evaluate_pending_activation,
    governor_settings,
    release_governor_lock,
    rollback_governor_profile,
    run_governor,
    validate_governor,
)


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _candidate(*, available: bool = True, parameter: str = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", change_pct: float = -2.5) -> dict:
    payload = {
        "profile_name": "adaptive_reflection_candidate_v1",
        "generated_at": _now(),
        "candidate_available": available,
        "available": available,
        "safe_to_activate_now": False,
        "requires_operator_review": True,
        "requires_hash_ack_activation": True,
        "source_policy": "adaptive_policy_report_only_no_live_mutation",
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "evidence_hash": "evidence-hash-current",
        "evidence_summary": {
            "market_regimes": ["neutral", "supportive", "risk_off"],
            "total_validated_conclusions": 2100,
            "total_directional_events": 210,
            "regime_counts": {
                "neutral": {"validated_conclusions": 700, "directional_events": 70},
                "supportive": {"validated_conclusions": 700, "directional_events": 70},
                "risk_off": {"validated_conclusions": 700, "directional_events": 70},
            },
        },
        "lab_report": {"thresholds_met": True, "blockers": []},
        "regime_enrichment": {"passed": True, "coverage_pct": 100},
        "effect_size_gate": {"passed": True},
        "confidence_gate": {"passed": True},
        "direction_stability_gate": {"passed": True, "observed_runs": 3, "required_runs": 3},
        "shrinkage": {"factor": 0.5, "candidate_value_after_shrinkage": "0.0121875"},
        "proposed_parameter_changes": [
            {
                "parameter": parameter,
                "scope": "setup_type_specific:support_reclaim",
                "current_value": "0.0125",
                "candidate_value": "0.0121875",
                "change_pct": change_pct,
                "robust_stats": {"median": 0.011, "trimmed_mean_10pct": 0.011},
            }
        ] if available else [],
        "reason": "candidate_ready_for_operator_review" if available else "insufficient_market_regimes",
    }
    payload["hash"] = stable_payload_hash(payload)
    return payload


def _readiness(*, ready: bool = True) -> dict:
    return {
        "recommendation": "ready_for_full_poc_live_run_no_replication" if ready else "blocked",
        "blockers": [] if ready else ["x"],
        "poc_full_workflow_readiness": {"ready": ready},
        "mode_c_market_order_readiness": {"ready": ready},
    }


def _env(**overrides: str) -> dict:
    env = {
        "ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR": "true",
        "AUTONOMOUS_PARAMETER_GOVERNOR_MODE": "apply_when_safe",
        "AUTONOMOUS_PARAMETER_GOVERNOR_ACK": REQUIRED_ACK,
        "AUTONOMOUS_PARAMETER_WRITE_PENDING_ONLY": "false",
    }
    env.update(overrides)
    return env


def _write_base_state(root: Path) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (root / "state/positions.json").write_text("{}\n", encoding="utf-8")
    (root / "state/approved_parameter_profile.json").write_text(
        json.dumps({"parameters": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125"}}) + "\n",
        encoding="utf-8",
    )


def test_current_candidate_available_false_governor_noop(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    status = validate_governor(root=tmp_path, candidate=_candidate(available=False), readiness_report=_readiness())
    assert status["governor_activation_allowed"] is False
    assert status["reason"] == "insufficient_market_regimes"
    assert status["analysis_ready"] is False
    assert status["prepare_ready"] is False
    assert status["apply_ready"] is False


def test_candidate_unavailable_never_analysis_ready_even_with_counts(tmp_path: Path) -> None:
    # Isolate from any real reports/adaptive_policy/analysis report on disk
    # (root defaults to ".") -- this test asserts behaviour for an explicitly
    # unavailable candidate, regardless of what a live analysis run produced.
    _write_base_state(tmp_path)
    status = validate_governor(root=tmp_path, candidate=_candidate(available=False), readiness_report=_readiness())
    assert status["readiness_layers"]["candidate_available"] is False
    assert status["analysis_ready"] is False
    assert "candidate_not_available" in status["readiness_layers"]["analysis_blockers"]


def test_missing_candidate_file_governor_noop(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    status = validate_governor(root=tmp_path, readiness_report=_readiness())
    assert status["reason"] == "candidate_file_missing"


def test_candidate_hash_mismatch_and_stale_block() -> None:
    candidate = _candidate()
    candidate["hash"] = "bad"
    status = validate_governor(candidate=candidate, readiness_report=_readiness())
    assert "candidate_hash_mismatch" in status["blockers"]
    stale = _candidate()
    stale["generated_at"] = (datetime.now(timezone.utc) - timedelta(days=4)).isoformat().replace("+00:00", "Z")
    stale["hash"] = stable_payload_hash(stale)
    assert candidate_stale(stale) is True
    status = validate_governor(candidate=stale, readiness_report=_readiness())
    assert "candidate_stale" in status["blockers"]


def test_candidate_missing_gates_and_insufficient_regimes_block(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    candidate = _candidate()
    candidate.pop("effect_size_gate")
    candidate["evidence_summary"]["market_regimes"] = ["unknown"]
    candidate["hash"] = stable_payload_hash(candidate)
    status = validate_governor(root=tmp_path, candidate=candidate, readiness_report=_readiness())
    assert "effect_size_gate_not_passed" in status["blockers"]
    assert "insufficient_market_regimes" in status["blockers"]


def test_missing_wrong_disabled_and_report_only_modes_do_not_apply(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    candidate = _candidate()
    for env in (
        _env(ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR="false"),
        _env(AUTONOMOUS_PARAMETER_GOVERNOR_ACK="wrong"),
        _env(AUTONOMOUS_PARAMETER_GOVERNOR_MODE="report_only"),
    ):
        result = run_governor(root=tmp_path, env=env, candidate=candidate, readiness_report=_readiness(), apply=True)
        assert result["applied"] is False
        assert result["state_write_performed"] is False


def test_prepare_only_writes_pending_plan_only(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    plan = build_activation_plan(root=tmp_path, env=_env(AUTONOMOUS_PARAMETER_GOVERNOR_MODE="prepare_only"), candidate=_candidate(), readiness_report=_readiness())
    result = run_governor(root=tmp_path, env=_env(AUTONOMOUS_PARAMETER_GOVERNOR_MODE="prepare_only"), candidate=_candidate(), readiness_report=_readiness(), apply=True)
    assert plan["activation_plan_available"] is True
    assert result["applied"] is False
    assert result["reason"] == "mode_not_apply_when_safe"


def test_apply_when_safe_valid_ack_applies_tmp_path_only_and_writes_backup_rollback(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    before = (tmp_path / "state/approved_parameter_profile.json").read_text(encoding="utf-8")
    result = run_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness(), apply=True)
    assert result["applied"] is True
    assert result["apply_ready"] is True
    assert result["state_write_performed"] is True
    assert Path(result["backup_profile_path"]).exists()
    assert (tmp_path / "reports/autonomous_parameter_governor/rollback/latest-rollback-plan.json").exists()
    assert (tmp_path / "state/autonomous_parameter_governor/rollback_plan_latest.json").exists()
    assert (tmp_path / "reports/autonomous_parameter_governor/governor-run-latest.json").exists()
    assert result["parameters_applied"] == ["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]
    assert before != (tmp_path / "state/approved_parameter_profile.json").read_text(encoding="utf-8")


def test_parameter_allowlist_and_size_limits_block() -> None:
    status = validate_governor(candidate=_candidate(parameter="EXECUTION_MODE"), readiness_report=_readiness())
    assert "non_allowlisted_parameter" in status["blockers"]
    candidate = _candidate(change_pct=12.0)
    candidate["hash"] = stable_payload_hash(candidate)
    status = validate_governor(candidate=candidate, readiness_report=_readiness())
    assert "change_beyond_max_total_pct" in status["blockers"]
    candidate = _candidate()
    candidate["proposed_parameter_changes"].append(dict(candidate["proposed_parameter_changes"][0], parameter="MAX_SPREAD_PCT"))
    candidate["hash"] = stable_payload_hash(candidate)
    status = validate_governor(candidate=candidate, readiness_report=_readiness())
    assert "too_many_parameters_for_single_activation" in status["blockers"]


def test_early_tuning_mode_accepts_allowlist_and_caps_single_step() -> None:
    env = _env(ADAPTIVE_EARLY_TUNING_MODE="true", ADAPTIVE_MAX_PARAMETER_STEP_PCT="2", ADAPTIVE_MAX_PARAMETERS_PER_APPLY="1")
    status = validate_governor(env=env, candidate=_candidate(parameter="MAX_SPREAD_PCT", change_pct=1.5), readiness_report=_readiness())
    assert status["early_tuning_mode_available"] is True
    assert status["early_tuning_mode_configured"] is True
    assert "non_allowlisted_parameter" not in status["blockers"]
    assert "change_beyond_max_total_pct" not in status["blockers"]

    too_large = _candidate(parameter="MAX_SPREAD_PCT", change_pct=2.1)
    too_large["hash"] = stable_payload_hash(too_large)
    status = validate_governor(env=env, candidate=too_large, readiness_report=_readiness())
    assert "change_beyond_max_total_pct" in status["blockers"]


def test_early_tuning_mode_blocks_forbidden_safety_live_credential_replication_params() -> None:
    forbidden = [
        "EXECUTION_MODE",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE",
        "REPLICATION_ENABLED",
        "MODE_C_MARKET_ORDER_ACK",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
        "Coinbase credentials",
        "oversell guards",
        "no-naked-sell guards",
    ]
    for parameter in forbidden:
        status = validate_governor(env=_env(ADAPTIVE_EARLY_TUNING_MODE="true"), candidate=_candidate(parameter=parameter), readiness_report=_readiness())
        assert "non_allowlisted_parameter" in status["blockers"]


def test_open_orders_positions_d3_and_readiness_block(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    (tmp_path / "state/open_orders.json").write_text(json.dumps({"orders": {"1": {"status": "open", "phase": "D3_controlled_live_reduce_only_exits", "side": "SELL"}}}), encoding="utf-8")
    status = validate_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness())
    assert "open_orders_present" in status["blockers"]
    assert "open_d3_exit_present" in status["blockers"]
    (tmp_path / "state/open_orders.json").write_text('{"orders": {}}\n', encoding="utf-8")
    (tmp_path / "state/positions.json").write_text(json.dumps({"BTC-USDC": {"status": "open", "position_size_base": "0.01"}}), encoding="utf-8")
    # require_mode_c_ready now defaults to False (market-order readiness is a
    # category mismatch for D2/D3 limit-order parameter tuning and would
    # otherwise permanently block apply in this market-orders-disabled spot
    # POC); request it explicitly here to keep covering the mechanism.
    status = validate_governor(
        root=tmp_path,
        env=_env(AUTONOMOUS_PARAMETER_REQUIRE_MODE_C_READY="true"),
        candidate=_candidate(),
        readiness_report=_readiness(ready=False),
    )
    assert "open_positions_present" in status["blockers"]
    assert "full_poc_not_ready" in status["blockers"]
    assert "mode_c_not_ready" in status["blockers"]


def test_open_orders_block_apply_not_analysis_or_candidate_generation(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    (tmp_path / "state/open_orders.json").write_text(json.dumps({"orders": {"1": {"status": "open"}}}), encoding="utf-8")
    status = validate_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness())
    assert status["analysis_ready"] is True
    assert status["prepare_ready"] is True
    assert status["candidate_generation_ready"] is True
    assert status["apply_ready"] is False
    assert "open_orders_present" in status["true_safety_blockers"]
    assert "open_orders_present" not in status["readiness_layers"]["analysis_blockers"]
    assert "open_orders_present" not in status["readiness_layers"]["prepare_blockers"]


def test_operator_ack_blocks_apply_not_candidate_generation(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    status = validate_governor(root=tmp_path, env=_env(AUTONOMOUS_PARAMETER_GOVERNOR_ACK=""), candidate=_candidate(), readiness_report=_readiness())
    assert status["analysis_ready"] is True
    assert status["prepare_ready"] is True
    assert status["candidate_generation_ready"] is True
    assert status["apply_ready"] is False
    assert status["operator_ack_missing"] is True
    assert status["apply_blockers_by_type"]["operator_ack"] == ["missing_or_invalid_ack"]
    assert status["only_operator_review_or_apply_ack_missing"] is True


def test_blocked_candidate_hash_is_report_hash_not_candidate_hash(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    candidate = _candidate(available=False)
    status = validate_governor(root=tmp_path, candidate=candidate, readiness_report=_readiness())
    assert status["candidate_hash"] == ""
    assert status["blocked_candidate_report_hash"] == candidate["hash"]
    assert status["candidate_available"] is False


def test_governor_status_groups_blockers_by_type(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    (tmp_path / "state/open_orders.json").write_text(json.dumps({"orders": {"1": {"status": "open"}}}), encoding="utf-8")
    status = validate_governor(root=tmp_path, env=_env(AUTONOMOUS_PARAMETER_GOVERNOR_ACK=""), candidate=_candidate(), readiness_report=_readiness())
    assert "open_orders_present" in status["apply_blockers_by_type"]["true_safety"]
    assert "missing_or_invalid_ack" in status["apply_blockers_by_type"]["operator_ack"]
    assert status["next_operator_action"] in {"wait_for_live_safety_clear", "review_status"}


def test_cooldown_rate_limit_and_previous_not_evaluated_block(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"generated_at": _now(), "applied": True, "evaluated": False}) + "\n", encoding="utf-8")
    status = validate_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness())
    assert "max_changes_per_24h_reached" in status["blockers"]
    assert "previous_activation_not_evaluated" in status["blockers"]
    assert "cooldown_active" not in status["blockers"]


def test_cooldown_zero_still_blocks_reused_evidence_hash(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"generated_at": _now(), "applied": True, "evaluated": True, "evidence_hash": "evidence-hash-current"}) + "\n", encoding="utf-8")
    status = validate_governor(root=tmp_path, env=_env(AUTONOMOUS_PARAMETER_MAX_CHANGES_PER_24H="99"), candidate=_candidate(), readiness_report=_readiness())
    assert "cooldown_active" not in status["blockers"]
    assert "reused_evidence_hash" in status["readiness_layers"]["apply_blockers"]


def _old_activation_record(*, profile_hash: str, hours_ago: float = 48.0, **overrides: object) -> dict:
    record = {
        "generated_at": (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "applied": True,
        "evaluated": False,
        "candidate_hash": "candidate-hash-1",
        "evidence_hash": "evidence-hash-1",
        "profile_hash": profile_hash,
        "changed_parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    }
    record.update(overrides)
    return record


def test_evaluate_pending_activation_waits_for_cooldown_not_elapsed(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=1.0)) + "\n", encoding="utf-8")

    result = evaluate_pending_activation(root=tmp_path, settings=governor_settings(_env()))

    assert result["performed"] is False
    assert result["reason"] == "evaluation_cooldown_not_elapsed"
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["evaluated"] is False


def test_evaluate_pending_activation_marks_clean_after_cooldown_elapsed(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=48.0)) + "\n", encoding="utf-8")

    result = evaluate_pending_activation(root=tmp_path, settings=governor_settings(_env()))

    assert result["performed"] is True
    assert result["reason"] == "clean_no_errors_observed"
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["evaluated"] is True
    assert row["evaluation_method"] == "time_and_health_check_auto"
    assert row["evaluation_outcome"] == "clean_no_errors_observed"


def test_evaluate_pending_activation_detects_manual_rollback_via_hash_mismatch(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash="stale-hash-from-before-manual-rollback", hours_ago=48.0)) + "\n", encoding="utf-8")

    result = evaluate_pending_activation(root=tmp_path, settings=governor_settings(_env()))

    assert result["performed"] is True
    assert result["reason"] == "superseded_by_manual_rollback"
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["evaluated"] is True
    assert row["evaluation_outcome"] == "superseded_by_manual_rollback"


def test_evaluate_pending_activation_blocked_by_errors_since_activation(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=48.0)) + "\n", encoding="utf-8")
    errors_log = tmp_path / "logs/errors.jsonl"
    errors_log.parent.mkdir(parents=True)
    recent_error_at = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    errors_log.write_text(json.dumps({"generated_at": recent_error_at, "error": "lifecycle_error"}) + "\n", encoding="utf-8")

    result = evaluate_pending_activation(root=tmp_path, settings=governor_settings(_env()))

    assert result["performed"] is False
    assert result["reason"] == "errors_observed_since_activation"
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["evaluated"] is False


def test_evaluate_pending_activation_idempotent_once_evaluated(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=48.0, evaluated=True, evaluation_outcome="clean_no_errors_observed")) + "\n", encoding="utf-8")

    result = evaluate_pending_activation(root=tmp_path, settings=governor_settings(_env()))

    assert result["performed"] is False
    assert result["reason"] == "already_evaluated"


def _decision_outcome_record(*, created_at: str, decision_category: str, outcome_label: str) -> dict:
    return {
        "created_at": created_at,
        "status": "resolved",
        "decision_category": decision_category,
        "outcome": {"outcome_label": outcome_label},
    }


def _write_decision_outcomes(root: Path, records: list) -> None:
    path = root / "state/decision_outcomes.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"records": records}), encoding="utf-8")


def _wait_records(*, start: datetime, count: int, missed: int) -> list:
    records = []
    for i in range(count):
        label = "missed_opportunity" if i < missed else "correct_avoid"
        ts = (start + timedelta(minutes=i)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        records.append(_decision_outcome_record(created_at=ts, decision_category="wait", outcome_label=label))
    return records


def test_assess_activation_outcome_insufficient_sample_is_not_a_regression(tmp_path: Path) -> None:
    generated_at = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    evaluated_at = datetime.now(timezone.utc).isoformat()
    _write_decision_outcomes(
        tmp_path,
        _wait_records(start=datetime.now(timezone.utc) - timedelta(hours=60), count=5, missed=4)
        + _wait_records(start=datetime.now(timezone.utc) - timedelta(hours=1), count=5, missed=4),
    )
    result = assess_activation_outcome(root=tmp_path, generated_at=generated_at, evaluated_at=evaluated_at, min_sample_size=100, regression_threshold_pct=5.0)
    assert result["available"] is False
    assert result["reason"] == "insufficient_sample"
    assert result["regressed"] is False


def test_assess_activation_outcome_detects_regression(tmp_path: Path) -> None:
    generated_at = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    evaluated_at = datetime.now(timezone.utc).isoformat()
    before = _wait_records(start=datetime.now(timezone.utc) - timedelta(hours=60), count=100, missed=20)
    after = _wait_records(start=datetime.now(timezone.utc) + timedelta(minutes=1), count=100, missed=40)
    _write_decision_outcomes(tmp_path, before + after)
    result = assess_activation_outcome(root=tmp_path, generated_at=generated_at, evaluated_at=evaluated_at, min_sample_size=100, regression_threshold_pct=5.0)
    assert result["available"] is True
    assert result["missed_opportunity_rate_before"] == pytest.approx(0.20)
    assert result["missed_opportunity_rate_after"] == pytest.approx(0.40)
    assert result["deltas_pct"]["missed_opportunity_rate_delta_pct"] == pytest.approx(20.0)
    assert result["regressed"] is True


def test_assess_activation_outcome_small_delta_within_threshold_is_not_regression(tmp_path: Path) -> None:
    generated_at = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    evaluated_at = datetime.now(timezone.utc).isoformat()
    before = _wait_records(start=datetime.now(timezone.utc) - timedelta(hours=60), count=100, missed=20)
    after = _wait_records(start=datetime.now(timezone.utc) + timedelta(minutes=1), count=100, missed=22)
    _write_decision_outcomes(tmp_path, before + after)
    result = assess_activation_outcome(root=tmp_path, generated_at=generated_at, evaluated_at=evaluated_at, min_sample_size=100, regression_threshold_pct=5.0)
    assert result["available"] is True
    assert result["regressed"] is False


def test_evaluate_pending_activation_regression_without_flag_only_reports(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=48.0)) + "\n", encoding="utf-8")
    before = _wait_records(start=datetime.now(timezone.utc) - timedelta(hours=60), count=100, missed=20)
    after = _wait_records(start=datetime.now(timezone.utc) + timedelta(minutes=1), count=100, missed=40)
    _write_decision_outcomes(tmp_path, before + after)

    result = evaluate_pending_activation(root=tmp_path, settings=governor_settings(_env()))

    assert result["performed"] is True
    assert result["reason"] == "regressed_recommend_manual_review"
    assert result["outcome_assessment"]["regressed"] is True
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["evaluation_outcome"] == "regressed_recommend_manual_review"
    # No auto-rollback: the approved profile must be untouched.
    assert sha256_file(tmp_path / "state/approved_parameter_profile.json") == profile_hash


def test_evaluate_pending_activation_regression_with_flag_executes_auto_rollback(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=48.0)) + "\n", encoding="utf-8")
    before = _wait_records(start=datetime.now(timezone.utc) - timedelta(hours=60), count=100, missed=20)
    after = _wait_records(start=datetime.now(timezone.utc) + timedelta(minutes=1), count=100, missed=40)
    _write_decision_outcomes(tmp_path, before + after)

    # A pre-change backup + rollback plan, exactly what run_governor() writes
    # at apply time.
    backup_dir = tmp_path / "state/autonomous_parameter_governor/backups"
    backup_dir.mkdir(parents=True)
    backup_path = backup_dir / "approved_parameter_profile.before_test.json"
    backup_content = json.dumps({"parameters": {"OLD": "1"}})
    backup_path.write_text(backup_content, encoding="utf-8")
    rollback_plan_path = tmp_path / "reports/autonomous_parameter_governor/rollback/latest-rollback-plan.json"
    rollback_plan_path.parent.mkdir(parents=True)
    rollback_plan_path.write_text(json.dumps({"backup_profile_path": str(backup_path)}), encoding="utf-8")

    result = evaluate_pending_activation(
        root=tmp_path,
        settings=governor_settings(_env(AUTONOMOUS_PARAMETER_AUTO_ROLLBACK_ON_REGRESSION="true")),
    )

    assert result["performed"] is True
    assert result["reason"] == "regressed_auto_rolled_back"
    assert result["outcome_assessment"]["auto_rollback_result"]["applied"] is True
    # The approved profile was actually restored from the backup.
    assert (tmp_path / "state/approved_parameter_profile.json").read_text(encoding="utf-8") == backup_content
    row = json.loads(log.read_text(encoding="utf-8").splitlines()[0])
    assert row["evaluation_outcome"] == "regressed_auto_rolled_back"


def test_run_governor_apply_clears_stuck_evaluation_gate_and_applies_next_change(tmp_path: Path) -> None:
    """Regression test for the 2026-06-22..2026-07-05 stuck state: nothing ever
    set `evaluated: true`, so `previous_activation_not_evaluated` blocked every
    activation after the first, forever, regardless of new evidence quality."""
    _write_base_state(tmp_path)
    profile_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    log = tmp_path / "state/autonomous_parameter_governor/activations.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps(_old_activation_record(profile_hash=profile_hash, hours_ago=48.0, evidence_hash="evidence-hash-old")) + "\n", encoding="utf-8")

    result = run_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness(), apply=True)

    assert result["applied"] is True
    assert result["reason"] == "applied"
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["evaluated"] is True
    assert json.loads(lines[1])["applied"] is True


def test_readiness_layers_require_apply_regimes_coverage_and_gates() -> None:
    candidate = _candidate()
    analysis = {
        "candidate_available": True,
        "parameter_analysis": [
            {
                "evidence": {
                    "validated_conclusions": 500,
                    "directional_events": 210,
                    "regime_counts": {
                        "neutral": {"validated_conclusions": 700, "directional_events": 70},
                        "supportive": {"validated_conclusions": 700, "directional_events": 70},
                        "risk_off": {"validated_conclusions": 700, "directional_events": 70},
                    },
                    "relevant_conclusions": 200,
                    "unique_enriched_regime_count": 2,
                    "adaptive_gate_regime_coverage_pct": 90,
                },
                "statistical_gates": {
                    "direction_stability_gate": {"passed": True, "observed_runs": 3, "required_runs": 3},
                    "effect_size_gate": {"would_pass_effect_size_gate": True},
                    "confidence_gate": {"would_pass_confidence_gate": True},
                },
            }
        ],
    }
    layers = adaptive_readiness_layers(candidate=candidate, analysis=analysis, settings={**_env_settings(), "min_market_regimes_for_apply": 3})
    assert layers["analysis_ready"] is True
    assert layers["prepare_ready"] is True
    assert layers["apply_ready"] is False
    assert "insufficient_market_regimes_for_apply" in layers["apply_blockers"]

    analysis["parameter_analysis"][0]["evidence"]["unique_enriched_regime_count"] = 3
    analysis["parameter_analysis"][0]["evidence"]["adaptive_gate_regime_coverage_pct"] = 84
    layers = adaptive_readiness_layers(candidate=candidate, analysis=analysis, settings=_env_settings())
    assert layers["apply_ready"] is False
    assert "regime_coverage_below_apply_minimum" in layers["apply_blockers"]

    analysis["parameter_analysis"][0]["evidence"]["adaptive_gate_regime_coverage_pct"] = 90
    analysis["parameter_analysis"][0]["statistical_gates"]["direction_stability_gate"]["observed_runs"] = 2
    layers = adaptive_readiness_layers(candidate=candidate, analysis=analysis, settings=_env_settings())
    assert layers["apply_ready"] is False
    assert "direction_stability_not_met" in layers["apply_blockers"]


def test_readiness_dedupes_legacy_and_v2_unknown_regimes() -> None:
    candidate = _candidate()
    analysis = {
        "candidate_available": False,
        "reason": "insufficient_distinct_regime_diversity",
        "parameter_analysis": [
            {
                "evidence": {
                    "validated_conclusions": 1000,
                    "relevant_conclusions": 1000,
                    "adaptive_market_regimes": [
                        "network_supportive_liquidity_neutral",
                        "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown",
                    ],
                    "regime_counts": {
                        "network_supportive_liquidity_neutral": {"validated_conclusions": 700, "directional_events": 70},
                        "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown": {"validated_conclusions": 700, "directional_events": 70},
                    },
                    "adaptive_gate_regime_coverage_pct": 100,
                },
                "statistical_gates": {
                    "direction_stability_gate": {"passed": True, "observed_runs": 3, "required_runs": 3},
                    "effect_size_gate": {"would_pass_effect_size_gate": True},
                    "confidence_gate": {"would_pass_confidence_gate": True},
                },
            }
        ],
    }
    layers = adaptive_readiness_layers(candidate={**candidate, "candidate_available": False, "proposed_parameter_changes": []}, analysis=analysis, settings=_env_settings())
    assert layers["raw_regime_count"] == 2
    assert layers["distinct_regime_count"] == 1
    assert layers["qualifying_regime_count"] == 1
    assert "insufficient_distinct_regime_diversity" in layers["analysis_blockers"]


def test_governor_status_internal_inconsistency_when_candidate_missing_despite_passing_gates(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    analysis_path = tmp_path / "reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.json"
    analysis_path.parent.mkdir(parents=True, exist_ok=True)
    analysis_path.write_text(
        json.dumps(
            {
                "candidate_available": False,
                "reason": "candidate_not_available",
                "recommendation": "collect_more_data",
                "parameter_analysis": [
                    {
                        "evidence": {
                            "validated_conclusions": 1500,
                            "relevant_conclusions": 1000,
                            "adaptive_market_regimes": ["supportive", "risk_off"],
                            "regime_counts": {
                                "supportive": {"validated_conclusions": 800, "directional_events": 80},
                                "risk_off": {"validated_conclusions": 700, "directional_events": 70},
                            },
                            "adaptive_gate_regime_coverage_pct": 100,
                        },
                        "statistical_gates": {
                            "direction_stability_gate": {"passed": True, "observed_runs": 3, "required_runs": 3},
                            "effect_size_gate": {"would_pass_effect_size_gate": True},
                            "confidence_gate": {"would_pass_confidence_gate": True},
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    status = validate_governor(root=tmp_path, env=_env(), candidate={"candidate_available": False, "reason": "candidate_not_available"}, readiness_report=_readiness())
    assert status["internal_inconsistency_detected"] is True
    assert status["recommendation"] == "rerun_candidate_analysis_or_fix_mapping"


def _env_settings() -> dict:
    from bot.autonomous_parameter_governor import governor_settings

    return governor_settings(_env())


def test_validate_requires_exact_ack_open_state_and_rate_limits(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    no_ack = validate_governor(root=tmp_path, env=_env(AUTONOMOUS_PARAMETER_GOVERNOR_ACK=""), candidate=_candidate(), readiness_report=_readiness())
    assert no_ack["apply_ready"] is False
    assert "missing_or_invalid_ack" in no_ack["readiness_layers"]["apply_blockers"]
    (tmp_path / "state/open_orders.json").write_text(json.dumps({"orders": {"1": {"status": "open"}}}), encoding="utf-8")
    open_orders = validate_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness())
    assert "open_orders_present" in open_orders["blockers"]


def test_rollback_dry_run_requires_ack_and_restores_with_ack(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    original_hash = sha256_file(tmp_path / "state/approved_parameter_profile.json")
    applied = run_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness(), apply=True)
    assert applied["applied"] is True
    dry = rollback_governor_profile(root=tmp_path, env={}, apply=False)
    assert dry["rollback_available"] is True
    assert dry["applied"] is False
    no_ack = rollback_governor_profile(root=tmp_path, env={}, apply=True)
    assert no_ack["reason"] == "missing_rollback_ack"
    restored = rollback_governor_profile(root=tmp_path, env={"AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK_ACK": REQUIRED_ROLLBACK_ACK}, apply=True)
    assert restored["applied"] is True
    assert sha256_file(tmp_path / "state/approved_parameter_profile.json") == original_hash


def test_no_env_or_order_state_mutation_in_dry_run(tmp_path: Path) -> None:
    _write_base_state(tmp_path)
    (tmp_path / ".env").write_text("UNCHANGED=true\n", encoding="utf-8")
    before_orders = (tmp_path / "state/open_orders.json").read_text(encoding="utf-8")
    result = run_governor(root=tmp_path, env=_env(), candidate=_candidate(), readiness_report=_readiness(), apply=False)
    assert result["applied"] is False
    assert result["env_mutation_performed"] is False
    assert (tmp_path / ".env").read_text(encoding="utf-8") == "UNCHANGED=true\n"
    assert (tmp_path / "state/open_orders.json").read_text(encoding="utf-8") == before_orders
    assert candidate_hash_valid(_candidate()) is True


def test_governor_lock_blocks_overlap_and_replaces_stale(tmp_path: Path) -> None:
    first = acquire_governor_lock(tmp_path)
    assert first["acquired"] is True
    second = acquire_governor_lock(tmp_path)
    assert second["acquired"] is False
    assert second["reason"] == "skipped_due_to_lock"
    lock_path = tmp_path / "state/reflection_adaptive_governor.lock"
    lock_path.write_text(json.dumps({"created_at": "2020-01-01T00:00:00Z", "pid": 1}), encoding="utf-8")
    stale = acquire_governor_lock(tmp_path)
    assert stale["acquired"] is True
    assert stale["stale_lock_detected"] is True
    release_governor_lock(tmp_path)
