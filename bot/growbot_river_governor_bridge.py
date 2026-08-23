"""Read-only bridge status between GrowBot/River proposals and the existing
autonomous parameter governor / approved-profile route.

The activation route already exists and is not duplicated here:
``growbot_river_learning -> adaptive_policy_lab (_growbot_river_supplemental_changes)
-> parameter_candidate_analysis -> autonomous_parameter_governor ->
approved_parameter_profile -> BotConfig``. This module performs no parameter
mutation, defines no new gate, and writes no state; it only reads the
already-computed reports plus the existing governor's own
:func:`bot.autonomous_parameter_governor.validate_governor` so an
operator/cron can see, in one place, whether a GrowBot/River-sourced
proposal is currently eligible to flow through that unchanged route.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from bot.adaptive_policy_lab import CANDIDATE_JSON_PATH, GROWBOT_RIVER_REPORT_PATH
from bot.atomic_io import atomic_write_json
from bot.autonomous_parameter_governor import (
    ACTIVATION_LOG_PATH,
    ROLLBACK_PLAN_PATH,
    governor_settings,
    load_project_env,
    validate_governor,
)
from bot.growbot_river_readiness import LIVE_CYCLE_READINESS_PATH, READINESS_PATH
from bot.learnable_parameter_registry import LearnableParameter, get_parameter
from bot.parameter_candidate_analysis import ANALYSIS_JSON_PATH


BRIDGE_SCHEMA_VERSION = "growbot_river_governor_bridge_v1"
BRIDGE_STATUS_PATH = Path("reports/growbot_river/growbot-river-governor-bridge-status-latest.json")
BRIDGE_STATUS_MD_PATH = Path("reports/growbot_river/growbot-river-governor-bridge-status-latest.md")
SOURCE_POLICY = "growbot_river_governor_bridge_report_only_no_new_apply_route"
GROWBOT_RIVER_SOURCE_TAG = "growbot_river_sidecar_supplemental"
WORKFLOW_POSITION = (
    "growbot_river_learning -> adaptive_policy_lab(_growbot_river_supplemental_changes) "
    "-> parameter_candidate_analysis -> autonomous_parameter_governor -> "
    "approved_parameter_profile -> BotConfig"
)


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _as_dict(value: Any) -> Dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _ranking_key(row: Mapping[str, Any]) -> Tuple[float, float]:
    return (_as_float(row.get("confidence")), _as_float(row.get("evidence_count")))


# Per-candidate fast_start_autotune eligibility thresholds. Deliberately
# narrower/lower-volume than the strict stabilization/governor gates -- see
# bot.growbot_river_readiness.build_fast_start_autotune_readiness for the
# sidecar-evidence-level (non-candidate-specific) half of this tier.
FAST_START_MIN_CONFIDENCE = 0.85
FAST_START_MIN_EVIDENCE_COUNT = 75
FAST_START_MIN_DISTINCT_REGIMES = 3
FAST_START_MIN_DIRECTION_STABLE_RUNS = 3
FAST_START_MIN_STEP_PCT = 0.25


def evaluate_fast_start_candidate_eligibility(
    *,
    top_proposal: Mapping[str, Any],
    definition: Optional[LearnableParameter],
    sidecar_ready: bool,
) -> Dict[str, Any]:
    """Per-candidate fast_start_autotune eligibility, independent of (and never
    overriding) the real governor/approved-profile route.

    This answers "does this specific candidate's own evidence already clear
    the lower, practical fast_start bar" -- confidence, evidence volume,
    regime diversity, direction stability, a low-risk registry allowlist
    entry, and a fine_tuning-sized step within the parameter's min/max rails.
    It never authorizes an apply: the unchanged autonomous_parameter_governor
    ACK/candidate-hash/cooldown/open-order/regime-enrichment/effect-size gates
    remain the only real authorization path, and `auto_apply_eligible`
    continues to reflect only the real governor's own apply_ready signal.
    """
    parameter = str(top_proposal.get("parameter") or "")
    checks: Dict[str, bool] = {"sidecar_evidence_base_ready": bool(sidecar_ready)}
    reasons: List[str] = []
    if not sidecar_ready:
        reasons.append("sidecar_evidence_base_not_yet_fast_start_ready")

    checks["parameter_in_learnable_registry"] = definition is not None
    if definition is None:
        reasons.append("parameter_not_in_learnable_parameter_registry")

    fast_start_allowed = bool(definition is not None and definition.fast_start_autotune_allowed())
    checks["parameter_fast_start_allowlisted"] = fast_start_allowed
    if definition is not None and not fast_start_allowed:
        reasons.append("parameter_not_on_fast_start_low_risk_allowlist")

    confidence = _as_float(top_proposal.get("confidence"))
    checks["confidence_at_least_threshold"] = confidence >= FAST_START_MIN_CONFIDENCE
    if confidence < FAST_START_MIN_CONFIDENCE:
        reasons.append(f"confidence_below_{FAST_START_MIN_CONFIDENCE}")

    evidence_count = _as_float(top_proposal.get("evidence_count"))
    checks["evidence_count_at_least_threshold"] = evidence_count >= FAST_START_MIN_EVIDENCE_COUNT
    if evidence_count < FAST_START_MIN_EVIDENCE_COUNT:
        reasons.append(f"evidence_count_below_{FAST_START_MIN_EVIDENCE_COUNT}")

    regimes_seen = top_proposal.get("regimes") or top_proposal.get("regimes_seen") or []
    distinct_regimes = len({str(item) for item in regimes_seen if item}) if isinstance(regimes_seen, (list, tuple, set)) else 0
    checks["distinct_regimes_at_least_threshold"] = distinct_regimes >= FAST_START_MIN_DISTINCT_REGIMES
    if distinct_regimes < FAST_START_MIN_DISTINCT_REGIMES:
        reasons.append(f"fewer_than_{FAST_START_MIN_DISTINCT_REGIMES}_distinct_regimes_for_this_candidate")

    stable_runs = _as_float(top_proposal.get("direction_stable_runs"))
    checks["direction_stable_across_runs"] = stable_runs >= FAST_START_MIN_DIRECTION_STABLE_RUNS
    if stable_runs < FAST_START_MIN_DIRECTION_STABLE_RUNS:
        reasons.append("direction_not_stable_across_at_least_3_prior_runs")

    step_pct = abs(_as_float(top_proposal.get("suggested_step_pct")))
    max_step = definition.fast_start_max_step_pct() if fast_start_allowed else None
    step_within_bounds = bool(max_step is not None and FAST_START_MIN_STEP_PCT <= step_pct <= max_step)
    checks["step_within_fine_tuning_bounds"] = step_within_bounds
    if not step_within_bounds:
        reasons.append("suggested_step_pct_outside_fast_start_fine_tuning_bounds")

    candidate_value = top_proposal.get("candidate_value")
    within_rails = False
    if definition is not None and candidate_value is not None:
        try:
            within_rails = definition.minimum <= float(candidate_value) <= definition.maximum
        except (TypeError, ValueError):
            within_rails = False
    checks["candidate_within_registry_min_max_rails"] = within_rails
    if not within_rails:
        reasons.append("candidate_value_outside_registry_min_max_rails")

    eligible = bool(parameter) and all(checks.values())
    return {
        "parameter": parameter or None,
        "eligible": eligible,
        "checks": checks,
        "blocking_reasons": reasons,
        "thresholds": {
            "min_confidence": FAST_START_MIN_CONFIDENCE,
            "min_evidence_count": FAST_START_MIN_EVIDENCE_COUNT,
            "min_distinct_regimes": FAST_START_MIN_DISTINCT_REGIMES,
            "min_direction_stable_runs": FAST_START_MIN_DIRECTION_STABLE_RUNS,
            "max_step_pct": max_step,
        },
        "max_parameters_per_apply": 1,
        "rollback_snapshot_required": True,
        "botconfig_validation_required": True,
        "note": (
            "Evidence-eligibility only. Never authorizes an apply -- the unchanged "
            "autonomous_parameter_governor ACK/candidate-hash/cooldown/open-order/"
            "regime-enrichment/effect-size gates remain the only real authorization "
            "path; see auto_apply_eligible for the real governor's own answer."
        ),
    }


def select_top_growbot_river_proposal(cycle_report: Mapping[str, Any]) -> Dict[str, Any]:
    """Pick the single most-evidenced river proposal, eligible or not.

    Prefers the already-bounded ``proposals`` list (parameter_step_scheduler's
    unblocked rows); falls back to ``blocked_proposals`` so the status always
    surfaces *something* even while nothing has cleared the sidecar's own
    bridge gates yet.
    """
    proposals = [row for row in _as_list(cycle_report.get("proposals")) if isinstance(row, Mapping)]
    if proposals:
        return dict(sorted(proposals, key=_ranking_key, reverse=True)[0])
    blocked = [row for row in _as_list(cycle_report.get("blocked_proposals")) if isinstance(row, Mapping)]
    if blocked:
        return dict(sorted(blocked, key=_ranking_key, reverse=True)[0])
    return {}


def _find_candidate_row(candidate_payload: Mapping[str, Any], parameter: str) -> Dict[str, Any]:
    for key in ("proposed_parameter_changes", "blocked_parameter_changes"):
        for row in _as_list(candidate_payload.get(key)):
            if isinstance(row, Mapping) and row.get("parameter") == parameter and row.get("source") == GROWBOT_RIVER_SOURCE_TAG:
                return dict(row)
    return {}


def _bridge_ready(cycle_report: Mapping[str, Any], candidate_payload: Mapping[str, Any]) -> bool:
    """Whether the structural wiring from sidecar report to candidate file ran.

    A fact about whether ``_growbot_river_supplemental_changes`` executed
    against a real sidecar report, not a verdict on whether any single
    proposal passed every downstream gate.
    """
    growbot_river_learning = _as_dict(candidate_payload.get("growbot_river_learning"))
    if growbot_river_learning.get("available") is True:
        return True
    return bool(cycle_report)


def _rollback_status(root: Path) -> Dict[str, Any]:
    plan = _as_dict(_load_json(root / ROLLBACK_PLAN_PATH))
    if plan:
        return {
            "rollback_plan_available": True,
            "rollback_plan_path": str(root / ROLLBACK_PLAN_PATH),
            "backup_profile_path": plan.get("backup_profile_path"),
            "changed_parameter": plan.get("changed_parameter"),
            "activated_profile_hash": plan.get("activated_profile_hash"),
            "previous_profile_hash": plan.get("previous_profile_hash"),
        }
    return {
        "rollback_plan_available": False,
        "rollback_plan_path": str(root / ROLLBACK_PLAN_PATH),
        "note": "No activation has run yet. The existing governor writes a backup and a rollback plan automatically on every apply (bot.autonomous_parameter_governor.run_governor).",
    }


def _last_apply_status(root: Path) -> Dict[str, Any]:
    path = root / ACTIVATION_LOG_PATH
    try:
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    except Exception:
        lines = []
    if not lines:
        return {"status": "no_prior_activation", "activation_log_path": str(path)}
    try:
        last = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {"status": "no_prior_activation", "activation_log_path": str(path)}
    return {
        "status": "applied" if last.get("applied") else "not_applied",
        "generated_at": last.get("generated_at"),
        "changed_parameter": last.get("changed_parameter"),
        "profile_hash": last.get("profile_hash"),
        "evaluated": last.get("evaluated"),
        "activation_log_path": str(path),
    }


def _next_required_condition(
    *,
    stabilization_readiness: Mapping[str, Any],
    candidate_row: Mapping[str, Any],
    governor_status: Mapping[str, Any],
) -> str:
    if stabilization_readiness and stabilization_readiness.get("ready") is not True:
        blockers = [str(row.get("blocker")) for row in _as_list(stabilization_readiness.get("real_blockers")) if isinstance(row, Mapping) and row.get("blocker")]
        if blockers:
            return "awaiting_live_episode_volume: " + ", ".join(sorted(set(blockers)))
        return "awaiting_live_episode_volume"
    candidate_blockers = [str(b) for b in _as_list(candidate_row.get("blockers"))]
    if "effect_size_below_deadband" in candidate_blockers:
        return (
            "river_suggested_step_below_lab_effect_size_deadband: the sidecar's bounded step is "
            "smaller than adaptive_policy_lab's minimum effect-size deadband; needs a higher-"
            "confidence step or promotion to a phase with a larger step range"
        )
    if "direction_stability_not_met" in candidate_blockers:
        return "awaiting_additional_consistent_direction_learning_cycles"
    if candidate_blockers:
        return "blocked_on: " + ", ".join(sorted(set(candidate_blockers)))
    apply_blockers = [str(b) for b in _as_list(_as_dict(governor_status.get("readiness_layers")).get("apply_blockers"))]
    non_ack_blockers = [b for b in apply_blockers if b != "missing_or_invalid_ack"]
    if non_ack_blockers:
        return "governor_apply_blockers: " + ", ".join(sorted(set(non_ack_blockers)))
    if "missing_or_invalid_ack" in apply_blockers:
        return (
            "operator_must_set_AUTONOMOUS_PARAMETER_GOVERNOR_ACK_once_in_env; no per-change "
            "operator ACK is required afterward"
        )
    return "none_ready_to_auto_apply_once_governor_cycle_runs"


def build_growbot_river_governor_bridge_status(
    *,
    root: Path = Path("."),
    env: Optional[Mapping[str, str]] = None,
) -> Dict[str, Any]:
    """Aggregate, read-only, whether a GrowBot/River proposal can presently flow
    through the existing governor/approved-profile route without a new gate.

    Calls :func:`validate_governor` exactly as
    ``tools/show_autonomous_parameter_governor_status.py`` does. Does not
    duplicate, bypass, or wrap governor logic in a parallel decision path.
    """
    cycle_report = _as_dict(_load_json(root / GROWBOT_RIVER_REPORT_PATH))
    candidate_payload = _as_dict(_load_json(root / CANDIDATE_JSON_PATH))
    readiness_payload = _as_dict(_load_json(root / READINESS_PATH))
    live_cycle_readiness = _as_dict(_load_json(root / LIVE_CYCLE_READINESS_PATH))
    if env is None:
        # Match validate_governor's own behaviour: load .env before reading
        # settings, so the displayed governor.enabled/mode reflect the real
        # configured state instead of an un-dotenv'd os.environ snapshot.
        load_project_env(root)
    settings = governor_settings(env)
    governor_status = validate_governor(root=root, env=env)

    stabilization_readiness = _as_dict(readiness_payload.get("stabilization_readiness"))
    fast_start_autotune_readiness = _as_dict(readiness_payload.get("fast_start_autotune_readiness"))
    strict_stabilization_ready = stabilization_readiness.get("ready") is True
    sidecar_fast_start_ready = fast_start_autotune_readiness.get("ready") is True
    top_proposal = select_top_growbot_river_proposal(cycle_report)
    parameter = str(top_proposal.get("parameter") or "")
    candidate_row = _find_candidate_row(candidate_payload, parameter) if parameter else {}
    definition = get_parameter(parameter) if parameter else None

    bridge_ready = _bridge_ready(cycle_report, candidate_payload)
    candidate_ready = bool(candidate_row or top_proposal)
    governor_visible_parameter = str(governor_status.get("proposed_parameter") or "")
    candidate_is_governor_visible = bool(parameter) and parameter == governor_visible_parameter
    auto_apply_eligible = bool(governor_status.get("apply_ready")) and candidate_is_governor_visible
    blocked_reason: Any = "none_ready_to_apply" if auto_apply_eligible else (
        governor_status.get("why_not_applied") or [str(governor_status.get("reason") or "unknown")]
    )

    fast_start_candidate_eligibility = evaluate_fast_start_candidate_eligibility(
        top_proposal=top_proposal,
        definition=definition,
        sidecar_ready=sidecar_fast_start_ready,
    )
    fast_start_autotune_ready = bool(sidecar_fast_start_ready and fast_start_candidate_eligibility.get("eligible"))

    forward_requirements = _as_dict(live_cycle_readiness.get("forward_episode_requirements"))

    if parameter:
        top_candidate_summary: Dict[str, Any] = {
            "parameter": parameter,
            "direction": top_proposal.get("direction") or candidate_row.get("direction"),
            "current_value": top_proposal.get("current_value", candidate_row.get("current_value")),
            "candidate_value": top_proposal.get("candidate_value", candidate_row.get("candidate_value")),
            "suggested_step_pct": top_proposal.get("suggested_step_pct"),
            "confidence": top_proposal.get("confidence"),
            "evidence_count": top_proposal.get("evidence_count"),
            "regimes_seen": top_proposal.get("regimes") or [],
            "expected_effect": top_proposal.get("reason") or candidate_row.get("reason") or "",
            "activation_route": top_proposal.get("activation_route") or (definition.activation_route() if definition else ""),
            "candidate_lab_blockers": _as_list(candidate_row.get("blockers")),
            "rollback": top_proposal.get("rollback") or (list(definition.rollback) if definition else []),
            "evidence_requirements": top_proposal.get("evidence_requirements") or (list(definition.evidence_requirements) if definition else []),
        }
    else:
        top_candidate_summary = {"parameter": None, "note": "no GrowBot/River proposal present yet"}

    if parameter:
        current_value = top_candidate_summary.get("current_value")
        candidate_value = top_candidate_summary.get("candidate_value")
        change_pct = top_proposal.get("change_pct")
        if change_pct is None:
            try:
                cv, nv = float(current_value), float(candidate_value)
                change_pct = round(((nv - cv) / cv) * 100.0, 4) if cv else 0.0
            except (TypeError, ValueError):
                change_pct = None
        expected_parameter_change = {
            "parameter": parameter,
            "direction": top_candidate_summary.get("direction"),
            "current_value": current_value,
            "candidate_value": candidate_value,
            "change_pct": change_pct,
            "would_be_first_autonomous_change": fast_start_autotune_ready or auto_apply_eligible,
        }
        first_autonomous_candidate_if_fast_start = dict(top_candidate_summary) if fast_start_autotune_ready else None
    else:
        expected_parameter_change = {"parameter": None, "note": "no GrowBot/River proposal present yet"}
        first_autonomous_candidate_if_fast_start = None

    return {
        "schema_version": BRIDGE_SCHEMA_VERSION,
        "generated_at": now_iso(),
        "workflow_position": WORKFLOW_POSITION,
        "bridge_ready": bridge_ready,
        "candidate_ready": candidate_ready,
        "auto_apply_eligible": auto_apply_eligible,
        "strict_stabilization_ready": strict_stabilization_ready,
        "fast_start_autotune_ready": fast_start_autotune_ready,
        "fast_start_candidate_eligibility": fast_start_candidate_eligibility,
        "first_autonomous_candidate_if_fast_start": first_autonomous_candidate_if_fast_start,
        "expected_parameter_change": expected_parameter_change,
        "blocked_reason": blocked_reason,
        "next_required_condition": _next_required_condition(
            stabilization_readiness=stabilization_readiness,
            candidate_row=candidate_row,
            governor_status=governor_status,
        ),
        "top_parameter_candidate": top_candidate_summary,
        "stabilization_readiness": stabilization_readiness,
        "fast_start_autotune_readiness": fast_start_autotune_readiness,
        "forward_episode_requirements": forward_requirements,
        "governor": {
            "enabled": settings.get("enabled"),
            "mode": settings.get("mode"),
            "apply_ready": governor_status.get("apply_ready"),
            "candidate_available": governor_status.get("candidate_available"),
            "proposed_parameter": governor_status.get("proposed_parameter"),
            "why_not_applied": governor_status.get("why_not_applied"),
            "operator_ack_missing": governor_status.get("operator_ack_missing"),
            "candidate_is_governor_visible": candidate_is_governor_visible,
        },
        "cooldown": {
            "cooldown_active": governor_status.get("cooldown_active"),
            "last_activation": governor_status.get("last_activation"),
        },
        "rollback": _rollback_status(root),
        "last_apply_status": _last_apply_status(root),
        "safety_policy": {
            "report_only": True,
            "can_authorize_execution": False,
            "can_mutate_parameters": False,
            "can_apply_profile": False,
            "introduces_new_activation_route": False,
            "uses_existing_governor_and_approved_profile_route_only": True,
        },
        "source_policy": SOURCE_POLICY,
    }


def render_bridge_status_markdown(status: Mapping[str, Any]) -> str:
    top = _as_dict(status.get("top_parameter_candidate"))
    governor = _as_dict(status.get("governor"))
    lines = [
        "# GrowBot/River -> Governor Bridge Status",
        "",
        f"Generated: {status.get('generated_at')}",
        f"Workflow: `{status.get('workflow_position')}`",
        "",
        "## Bridge",
        f"- bridge_ready: {status.get('bridge_ready')}",
        f"- candidate_ready: {status.get('candidate_ready')}",
        f"- strict_stabilization_ready: {status.get('strict_stabilization_ready')}",
        f"- fast_start_autotune_ready: {status.get('fast_start_autotune_ready')}",
        f"- auto_apply_eligible: {status.get('auto_apply_eligible')}",
        f"- blocked_reason: {status.get('blocked_reason')}",
        f"- next_required_condition: {status.get('next_required_condition')}",
        "",
        "## Fast-start candidate eligibility",
    ]
    fast_start = _as_dict(status.get("fast_start_candidate_eligibility"))
    if fast_start.get("parameter"):
        lines.extend(
            [
                f"- parameter: `{fast_start.get('parameter')}`",
                f"- eligible: {fast_start.get('eligible')}",
                f"- blocking_reasons: {', '.join(fast_start.get('blocking_reasons') or []) or 'none'}",
            ]
        )
    else:
        lines.append("- none")
    lines.extend(["", "## Top parameter candidate"])
    if top.get("parameter"):
        lines.extend(
            [
                f"- parameter: `{top.get('parameter')}`",
                f"- direction: {top.get('direction')}",
                f"- current_value -> candidate_value: {top.get('current_value')} -> {top.get('candidate_value')}",
                f"- suggested_step_pct: {top.get('suggested_step_pct')}",
                f"- confidence: {top.get('confidence')}",
                f"- evidence_count: {top.get('evidence_count')}",
                f"- regimes_seen: {', '.join(top.get('regimes_seen') or []) or 'none'}",
                f"- expected_effect: {top.get('expected_effect')}",
                f"- candidate_lab_blockers: {', '.join(top.get('candidate_lab_blockers') or []) or 'none'}",
            ]
        )
    else:
        lines.append("- none")
    lines.extend(
        [
            "",
            "## Governor",
            f"- enabled: {governor.get('enabled')}",
            f"- mode: {governor.get('mode')}",
            f"- apply_ready: {governor.get('apply_ready')}",
            f"- candidate_is_governor_visible: {governor.get('candidate_is_governor_visible')}",
            "",
            "## Cooldown / rollback / last apply",
            f"- cooldown_active: {(status.get('cooldown') or {}).get('cooldown_active')}",
            f"- rollback_plan_available: {(status.get('rollback') or {}).get('rollback_plan_available')}",
            f"- last_apply_status: {(status.get('last_apply_status') or {}).get('status')}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_growbot_river_governor_bridge_status(status: Mapping[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    json_path = root / BRIDGE_STATUS_PATH
    md_path = root / BRIDGE_STATUS_MD_PATH
    atomic_write_json(json_path, dict(status))
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_bridge_status_markdown(status), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


__all__ = [
    "BRIDGE_SCHEMA_VERSION",
    "BRIDGE_STATUS_MD_PATH",
    "BRIDGE_STATUS_PATH",
    "FAST_START_MIN_CONFIDENCE",
    "FAST_START_MIN_DIRECTION_STABLE_RUNS",
    "FAST_START_MIN_DISTINCT_REGIMES",
    "FAST_START_MIN_EVIDENCE_COUNT",
    "FAST_START_MIN_STEP_PCT",
    "WORKFLOW_POSITION",
    "build_growbot_river_governor_bridge_status",
    "evaluate_fast_start_candidate_eligibility",
    "render_bridge_status_markdown",
    "select_top_growbot_river_proposal",
    "write_growbot_river_governor_bridge_status",
]
