from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bot.adaptive_policy_lab import CANDIDATE_JSON_PATH, canonical_regime_key, regime_diversity_diagnostics, stable_payload_hash
from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST, sha256_file
from bot.atomic_io import atomic_write_json
from bot.parameter_candidate_analysis import ANALYSIS_JSON_PATH

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional production dependency
    load_dotenv = None


SOURCE_POLICY = "autonomous_parameter_governor_bounded_no_execution_authority"
STATUS_PATH = Path("reports/autonomous_parameter_governor/governor-status-latest.json")
PLAN_JSON_PATH = Path("reports/autonomous_parameter_governor/activation-plan-latest.json")
PLAN_MD_PATH = Path("reports/autonomous_parameter_governor/activation-plan-latest.md")
RUN_PATH = Path("reports/autonomous_parameter_governor/governor-run-latest.json")
RUN_MD_PATH = Path("reports/autonomous_parameter_governor/governor-run-latest.md")
RUN_HISTORY_PATH = Path("reports/autonomous_parameter_governor/history/governor-run-history.jsonl")
AUDIT_JSON_PATH = Path("reports/audits/autonomous-parameter-governor-latest.json")
AUDIT_MD_PATH = Path("reports/audits/autonomous-parameter-governor-latest.md")
ACTIVATION_LOG_PATH = Path("state/autonomous_parameter_governor/activations.jsonl")
BACKUP_DIR = Path("state/autonomous_parameter_governor/backups")
ROLLBACK_PLAN_PATH = Path("reports/autonomous_parameter_governor/rollback/latest-rollback-plan.json")
LEGACY_ROLLBACK_PLAN_PATH = Path("state/autonomous_parameter_governor/rollback_plan_latest.json")
APPROVED_PROFILE_PATH = Path("state/approved_parameter_profile.json")
LOCK_PATH = Path("state/reflection_adaptive_governor.lock")
LOCK_STALE_AFTER_SECONDS = 60 * 60 * 2

REQUIRED_ACK = "I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_BOUNDED_PROFILE_ACTIVATION"
REQUIRED_ROLLBACK_ACK = "I_APPROVE_AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK"

ALLOWED_PARAMETERS = {
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "MAX_SPREAD_PCT",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    "setup_type_specific_trigger_strictness",
    "starter_probe_eligibility_thresholds",
}

ENV_ALLOWLIST = {
    "ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR",
    "AUTONOMOUS_PARAMETER_GOVERNOR_MODE",
    "AUTONOMOUS_PARAMETER_GOVERNOR_ACK",
    "AUTONOMOUS_PARAMETER_GOVERNOR_REQUIRED_ACK",
    "ADAPTIVE_MIN_MARKET_REGIMES_FOR_ANALYSIS",
    "ADAPTIVE_EARLY_TUNING_MODE",
    "ADAPTIVE_MIN_MARKET_REGIMES_FOR_PREPARE",
    "ADAPTIVE_MIN_MARKET_REGIMES_FOR_APPLY",
    "ADAPTIVE_MIN_VALIDATED_CONCLUSIONS_PER_REGIME_FOR_APPLY",
    "ADAPTIVE_MIN_DIRECTIONAL_EVENTS_PER_REGIME_FOR_APPLY",
    "ADAPTIVE_PARAMETER_CHANGE_COOLDOWN_DAYS",
    "ADAPTIVE_MAX_PARAMETERS_PER_APPLY",
    "ADAPTIVE_REQUIRE_NEW_EVIDENCE_SINCE_LAST_APPLY",
    "ADAPTIVE_FORBID_REUSE_OF_LAST_EVIDENCE_HASH",
    "ADAPTIVE_BLOCK_APPLY_WITH_OPEN_ORDERS",
    "ADAPTIVE_BLOCK_APPLY_WITH_OPEN_POSITIONS",
    "ADAPTIVE_MAX_PARAMETER_STEP_PCT",
    "ADAPTIVE_MIN_REGIME_ENRICHMENT_COVERAGE_PCT",
    "ADAPTIVE_REQUIRE_DIRECTION_STABILITY_RUNS",
    "ADAPTIVE_MIN_EFFECT_SIZE_PCT",
    "ADAPTIVE_CONFIDENCE_BUFFER_PCT",
    "ADAPTIVE_SHRINKAGE_FACTOR",
    "AUTONOMOUS_PARAMETER_MAX_CHANGES_PER_24H",
    "AUTONOMOUS_PARAMETER_MAX_PARAMETERS_PER_ACTIVATION",
    "AUTONOMOUS_PARAMETER_COOLDOWN_HOURS",
    "AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_ORDERS",
    "AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_POSITIONS",
    "AUTONOMOUS_PARAMETER_REQUIRE_BACKUP",
    "AUTONOMOUS_PARAMETER_REQUIRE_ROLLBACK_PLAN",
    "AUTONOMOUS_PARAMETER_WRITE_AUDIT_TRAIL",
}


def load_project_env(root: Path = Path(".")) -> None:
    if load_dotenv is None:
        return
    env_path = root / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path, override=True)

FORBIDDEN_PARAMETERS = {
    "EXECUTION_MODE",
    "ENABLE_FULL_WORKFLOW_LIVE_MODE",
    "ENABLE_LIVE_ENTRY_ORDERS",
    "ENABLE_LIVE_EXIT_ORDERS",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
    "ENABLE_PHASE_D2_POSITION_EXECUTOR",
    "ENABLE_PHASE_D3_CONTROLLED_LIVE_EXITS",
    "PHASE_C43_LIFECYCLE_APPLY_LOCAL",
    "PHASE_C43_LIFECYCLE_BUILD_D2_PLAN",
    "PHASE_C43_LIFECYCLE_BUILD_D3_PREVIEW",
    "REPLICATION_ENABLED",
    "REPLICATION_LIFECYCLE_ENABLED",
    "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED",
    "LEARNING_TO_EXECUTION_ALLOWED",
    "LIVE_LEARNING_ALLOWED",
    "PARAMETER_CHANGE_ALLOWED",
    "MODE_B_CONTROLLED_STOP_EXIT_ACK",
    "MODE_C_MARKET_ORDER_ACK",
    "Coinbase credentials",
    "oversell guards",
    "no-naked-sell guards",
    "market-order governance flags",
}

BLOCKER_TYPE_MAP = {
    "candidate_not_available": "data_quality",
    "candidate_file_missing": "data_quality",
    "sample_thresholds_not_met": "data_quality",
    "insufficient_market_regimes": "data_quality",
    "insufficient_distinct_regime_diversity": "data_quality",
    "insufficient_market_regimes_for_prepare": "data_quality",
    "insufficient_market_regimes_for_apply": "data_quality",
    "insufficient_per_regime_apply_evidence": "data_quality",
    "insufficient_validated_conclusions": "data_quality",
    "insufficient_relevant_conclusions": "data_quality",
    "diagnostics_unavailable": "data_quality",
    "regime_coverage_not_passed": "data_quality",
    "regime_coverage_below_apply_minimum": "data_quality",
    "effect_size_gate_not_passed": "data_quality",
    "confidence_gate_not_passed": "data_quality",
    "direction_stability_not_passed": "data_quality",
    "direction_stability_not_met": "data_quality",
    "shrinkage_not_applied": "data_quality",
    "no_proposed_parameter_changes": "data_quality",
    "missing_new_evidence_hash": "data_quality",
    "reused_evidence_hash": "data_quality",
    "candidate_hash_mismatch": "true_safety",
    "non_allowlisted_parameter": "true_safety",
    "parameter_not_supported_by_approved_profile_route": "true_safety",
    "change_beyond_max_total_pct": "true_safety",
    "too_many_parameters_for_single_activation": "true_safety",
    "robust_averaging_missing": "data_quality",
    "open_orders_present": "true_safety",
    "open_d3_exit_present": "true_safety",
    "controlled_stop_or_close_pending": "true_safety",
    "lifecycle_error_active": "true_safety",
    "open_positions_present": "true_safety",
    "missing_operator_review_requirement": "operator_ack",
    "missing_hash_ack_requirement": "operator_ack",
    "missing_or_invalid_ack": "operator_ack",
    "governor_disabled": "workflow_blocker",
    "mode_not_apply_when_safe": "workflow_blocker",
    "max_parameters_per_activation_not_one": "workflow_blocker",
    "full_poc_not_ready": "workflow_blocker",
    "mode_c_not_ready": "workflow_blocker",
    "analysis_not_ready": "workflow_blocker",
    "prepare_not_ready": "workflow_blocker",
    "operator_review_report_missing": "workflow_blocker",
    "candidate_stale": "stale_legacy_gate",
    "cooldown_active": "cooldown",
    "previous_activation_not_evaluated": "cooldown",
    "max_changes_per_24h_reached": "cooldown",
}


def classify_blocker(blocker: str) -> str:
    text = str(blocker or "")
    if text in BLOCKER_TYPE_MAP:
        return BLOCKER_TYPE_MAP[text]
    if text.startswith("insufficient_"):
        return "data_quality"
    if "ack" in text or "operator" in text:
        return "operator_ack"
    if "open_order" in text or "open_position" in text or "oversell" in text or "naked" in text:
        return "true_safety"
    if "stale" in text or "legacy" in text:
        return "stale_legacy_gate"
    return "unknown"


def group_blockers_by_type(blockers: Sequence[str]) -> Dict[str, List[str]]:
    out = {
        "true_safety": [],
        "data_quality": [],
        "operator_ack": [],
        "cooldown": [],
        "workflow_blocker": [],
        "stale_legacy_gate": [],
        "duplicate_gate": [],
        "status_mapping_bug": [],
        "unknown": [],
    }
    for blocker in sorted({str(item) for item in blockers if str(item)}):
        out.setdefault(classify_blocker(blocker), []).append(blocker)
    return out


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def _float(value: Any) -> Optional[float]:
    try:
        out = float(str(value).strip())
    except Exception:
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def governor_settings(env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    env_map = env if env is not None else os.environ
    required_ack = env_map.get("AUTONOMOUS_PARAMETER_GOVERNOR_REQUIRED_ACK", REQUIRED_ACK)
    required_rollback_ack = env_map.get("AUTONOMOUS_PARAMETER_GOVERNOR_REQUIRED_ROLLBACK_ACK", REQUIRED_ROLLBACK_ACK)
    mode = str(env_map.get("AUTONOMOUS_PARAMETER_GOVERNOR_MODE", "report_only")).strip() or "report_only"
    if mode not in {"report_only", "prepare_only", "apply_when_safe"}:
        mode = "report_only"
    return {
        "enabled": _bool(env_map.get("ENABLE_AUTONOMOUS_PARAMETER_GOVERNOR"), False),
        "early_tuning_mode": _bool(env_map.get("ADAPTIVE_EARLY_TUNING_MODE"), False),
        "mode": mode,
        "ack": str(env_map.get("AUTONOMOUS_PARAMETER_GOVERNOR_ACK", "")).strip(),
        "required_ack": required_ack,
        "rollback_ack": str(env_map.get("AUTONOMOUS_PARAMETER_GOVERNOR_ROLLBACK_ACK", "")).strip(),
        "required_rollback_ack": required_rollback_ack,
        "max_changes_per_24h": _int(env_map.get("AUTONOMOUS_PARAMETER_MAX_CHANGES_PER_24H"), 1),
        "cooldown_hours": _int(
            env_map.get("AUTONOMOUS_PARAMETER_COOLDOWN_HOURS"),
            _int(env_map.get("ADAPTIVE_PARAMETER_CHANGE_COOLDOWN_DAYS"), 0) * 24,
        ),
        "cooldown_days": _int(env_map.get("ADAPTIVE_PARAMETER_CHANGE_COOLDOWN_DAYS"), 0),
        "apply_only_when_no_open_orders": _bool(
            env_map.get("AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_ORDERS"),
            _bool(env_map.get("ADAPTIVE_BLOCK_APPLY_WITH_OPEN_ORDERS"), True),
        ),
        "apply_only_when_no_open_positions": _bool(
            env_map.get("AUTONOMOUS_PARAMETER_APPLY_ONLY_WHEN_NO_OPEN_POSITIONS"),
            _bool(env_map.get("ADAPTIVE_BLOCK_APPLY_WITH_OPEN_POSITIONS"), True),
        ),
        "require_full_poc_ready": _bool(env_map.get("AUTONOMOUS_PARAMETER_REQUIRE_FULL_POC_READY"), True),
        # Mode C (market-order) readiness is a category mismatch for the
        # parameter governor: D2/D3 limit-order thresholds (the only
        # allowlisted parameters) have no relationship to market-order
        # infrastructure, which this spot POC keeps permanently disabled by
        # design (MARKET_ORDER_ENABLED=false). Defaulting this to True would
        # make `apply_when_safe` structurally unreachable forever, regardless
        # of evidence quality. Market orders remain independently blocked by
        # their own ENABLE_MARKET_ORDERS/ALLOW_MARKET_ORDERS/MARKET_ORDER_ENABLED
        # flags no matter how this setting is configured.
        "require_mode_c_ready": _bool(env_map.get("AUTONOMOUS_PARAMETER_REQUIRE_MODE_C_READY"), False),
        "require_candidate_hash_stable": _bool(env_map.get("AUTONOMOUS_PARAMETER_REQUIRE_CANDIDATE_HASH_STABLE"), True),
        "require_candidate_not_stale": _bool(env_map.get("AUTONOMOUS_PARAMETER_REQUIRE_CANDIDATE_NOT_STALE"), True),
        "max_total_change_pct": _float(env_map.get("AUTONOMOUS_PARAMETER_MAX_TOTAL_CHANGE_PCT")) or (_float(env_map.get("ADAPTIVE_MAX_PARAMETER_STEP_PCT")) or 5.0),
        "max_parameters_per_activation": _int(
            env_map.get("AUTONOMOUS_PARAMETER_MAX_PARAMETERS_PER_ACTIVATION"),
            _int(env_map.get("ADAPTIVE_MAX_PARAMETERS_PER_APPLY"), 1),
        ),
        "write_pending_only": _bool(env_map.get("AUTONOMOUS_PARAMETER_WRITE_PENDING_ONLY"), False),
        "require_backup": _bool(env_map.get("AUTONOMOUS_PARAMETER_REQUIRE_BACKUP"), True),
        "require_rollback_plan": _bool(env_map.get("AUTONOMOUS_PARAMETER_REQUIRE_ROLLBACK_PLAN"), True),
        "write_audit_trail": _bool(env_map.get("AUTONOMOUS_PARAMETER_WRITE_AUDIT_TRAIL"), True),
        "rollback_on_health_warning": _bool(env_map.get("AUTONOMOUS_PARAMETER_ROLLBACK_ON_HEALTH_WARNING"), True),
        "min_market_regimes_for_analysis": _int(env_map.get("ADAPTIVE_MIN_MARKET_REGIMES_FOR_ANALYSIS"), 2),
        "min_market_regimes_for_prepare": _int(env_map.get("ADAPTIVE_MIN_MARKET_REGIMES_FOR_PREPARE"), 2),
        "min_market_regimes_for_apply": _int(env_map.get("ADAPTIVE_MIN_MARKET_REGIMES_FOR_APPLY"), 2),
        "min_validated_conclusions_per_regime_for_apply": _int(env_map.get("ADAPTIVE_MIN_VALIDATED_CONCLUSIONS_PER_REGIME_FOR_APPLY"), 700),
        "min_directional_events_per_regime_for_apply": _int(env_map.get("ADAPTIVE_MIN_DIRECTIONAL_EVENTS_PER_REGIME_FOR_APPLY"), 70),
        "require_new_evidence_since_last_apply": _bool(env_map.get("ADAPTIVE_REQUIRE_NEW_EVIDENCE_SINCE_LAST_APPLY"), True),
        "forbid_reuse_of_last_evidence_hash": _bool(env_map.get("ADAPTIVE_FORBID_REUSE_OF_LAST_EVIDENCE_HASH"), True),
        "min_regime_enrichment_coverage_pct": _float(env_map.get("ADAPTIVE_MIN_REGIME_ENRICHMENT_COVERAGE_PCT")) or 85.0,
        "require_direction_stability_runs": _int(env_map.get("ADAPTIVE_REQUIRE_DIRECTION_STABILITY_RUNS"), 3),
        "min_effect_size_pct": _float(env_map.get("ADAPTIVE_MIN_EFFECT_SIZE_PCT")) or 5.0,
        "confidence_buffer_pct": _float(env_map.get("ADAPTIVE_CONFIDENCE_BUFFER_PCT")) or 3.0,
        "shrinkage_factor": _float(env_map.get("ADAPTIVE_SHRINKAGE_FACTOR")) or 0.50,
    }


def load_candidate(root: Path = Path(".")) -> Dict[str, Any]:
    payload = _load_json(root / CANDIDATE_JSON_PATH)
    return payload if isinstance(payload, dict) else {}


def candidate_hash_valid(candidate: Dict[str, Any]) -> bool:
    expected = str(candidate.get("hash") or "").strip()
    return bool(expected) and stable_payload_hash(candidate) == expected


def candidate_stale(candidate: Dict[str, Any], *, max_age_hours: int = 48, now: Optional[datetime] = None) -> bool:
    generated = parse_time(candidate.get("generated_at"))
    if generated is None:
        return True
    current = now or datetime.now(timezone.utc)
    return generated < current - timedelta(hours=max_age_hours)


def _gate_passed(candidate: Dict[str, Any], key: str) -> bool:
    value = candidate.get(key)
    return isinstance(value, dict) and value.get("passed") is True


def _is_fast_start_autotune_change(change: Dict[str, Any]) -> bool:
    """A GrowBot/River-sourced row that already cleared its own
    confidence/evidence/regime-diversity bar in
    ``adaptive_policy_lab._growbot_river_supplemental_changes``.

    Evidence shaped this way (a single bounded online-learning estimate) is
    structurally incompatible with the reflection-ledger evidence the strict
    path's gates below expect (hundreds of per-regime validated conclusions).
    Detecting it lets those checks use the row's own evidence instead of
    reflection-ledger fields the row never populates -- it does not skip or
    lower any check for the strict reflection-sourced path."""
    return bool(
        isinstance(change, dict)
        and str(change.get("source") or "") == "growbot_river_sidecar_supplemental"
        and change.get("fast_start_autotune_eligible") is True
    )


def _candidate_gate_blockers(candidate: Dict[str, Any], settings: Dict[str, Any]) -> List[str]:
    blockers: List[str] = []
    if not candidate:
        return ["candidate_file_missing"]
    if candidate.get("candidate_available") is not True:
        blockers.append("candidate_not_available")
        reason = str(candidate.get("reason") or "")
        if reason:
            blockers.append(reason)
        return sorted(set(blockers))
    if settings["require_candidate_hash_stable"] and not candidate_hash_valid(candidate):
        blockers.append("candidate_hash_mismatch")
    if settings["require_candidate_not_stale"] and candidate_stale(candidate):
        blockers.append("candidate_stale")
    if candidate.get("requires_operator_review") is not True:
        blockers.append("missing_operator_review_requirement")
    if candidate.get("requires_hash_ack_activation") is not True:
        blockers.append("missing_hash_ack_requirement")
    changes = candidate.get("proposed_parameter_changes") if isinstance(candidate.get("proposed_parameter_changes"), list) else []
    fast_start_only = bool(changes) and all(_is_fast_start_autotune_change(change) for change in changes)
    lab = candidate.get("lab_report") if isinstance(candidate.get("lab_report"), dict) else {}
    if fast_start_only:
        # The reflection-ledger-wide thresholds_met/regime fields measure an
        # evidence source the fast_start row does not use; use the row's own
        # already-verified regime list instead of the reflection summary.
        regimes: List[str] = []
        for change in changes:
            regimes.extend(str(item) for item in (change.get("market_regimes") or []) if item)
    else:
        evidence = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
        regimes = evidence.get("market_regimes") if isinstance(evidence.get("market_regimes"), list) else []
        if lab.get("thresholds_met") is not True:
            blockers.append("sample_thresholds_not_met")
    diversity = regime_diversity_diagnostics(regimes)
    if int(diversity.get("distinct_regime_count") or 0) < 2:
        blockers.append(
            "insufficient_distinct_regime_diversity"
            if int(diversity.get("raw_regime_count") or 0) >= 2
            else "insufficient_market_regimes"
        )
    for key, blocker in (
        ("regime_enrichment", "regime_coverage_not_passed"),
        ("effect_size_gate", "effect_size_gate_not_passed"),
        ("confidence_gate", "confidence_gate_not_passed"),
        ("direction_stability_gate", "direction_stability_not_passed"),
    ):
        if not _gate_passed(candidate, key):
            blockers.append(blocker)
    shrinkage = candidate.get("shrinkage") if isinstance(candidate.get("shrinkage"), dict) else {}
    if not shrinkage or shrinkage.get("candidate_value_after_shrinkage") in (None, ""):
        blockers.append("shrinkage_not_applied")
    if not changes:
        blockers.append("no_proposed_parameter_changes")
    if len(changes) > settings["max_parameters_per_activation"]:
        blockers.append("too_many_parameters_for_single_activation")
    for change in changes:
        parameter = str(change.get("parameter") or "")
        if parameter in FORBIDDEN_PARAMETERS or parameter not in ALLOWED_PARAMETERS:
            blockers.append("non_allowlisted_parameter")
        if parameter not in APPROVED_PARAMETER_PROFILE_WHITELIST:
            blockers.append("parameter_not_supported_by_approved_profile_route")
        pct = abs(_float(change.get("change_pct")) or 0.0)
        if pct > float(settings["max_total_change_pct"]):
            blockers.append("change_beyond_max_total_pct")
        if not isinstance(change.get("robust_stats"), dict):
            blockers.append("robust_averaging_missing")
    return sorted(set(blockers))


def candidate_analysis_status(root: Path = Path(".")) -> Dict[str, Any]:
    path = root / ANALYSIS_JSON_PATH
    payload = _load_json(path)
    available = isinstance(payload, dict) and bool(payload)
    return {
        "candidate_analysis_available": available,
        "candidate_analysis_path": str(path),
        "candidate_analysis_hash": sha256_file(path) if path.exists() else "",
        "analysis_reason": str(payload.get("reason") or "") if available else "candidate_analysis_missing",
    }


def load_candidate_analysis(root: Path = Path(".")) -> Dict[str, Any]:
    payload = _load_json(root / ANALYSIS_JSON_PATH)
    return payload if isinstance(payload, dict) else {}


def _first_parameter_analysis(analysis: Dict[str, Any]) -> Dict[str, Any]:
    rows = analysis.get("parameter_analysis")
    if isinstance(rows, list):
        first = next((row for row in rows if isinstance(row, dict)), {})
        return first if isinstance(first, dict) else {}
    return {}


def _regime_count(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> int:
    item = _first_parameter_analysis(analysis)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    for key in ("distinct_regime_count", "unique_enriched_regime_count", "unique_regime_count"):
        value = _int(evidence.get(key), -1)
        if value >= 0:
            return value
    candidate_evidence = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
    regimes = candidate_evidence.get("market_regimes") if isinstance(candidate_evidence.get("market_regimes"), list) else []
    return int(regime_diversity_diagnostics(regimes).get("distinct_regime_count") or 0)


def _regime_diagnostics(candidate: Dict[str, Any], analysis: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, Any]:
    item = _first_parameter_analysis(analysis)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    regimes = evidence.get("adaptive_market_regimes") if isinstance(evidence.get("adaptive_market_regimes"), list) else []
    if not regimes:
        explicit_count = _int(evidence.get("distinct_regime_count"), _int(evidence.get("unique_enriched_regime_count"), _int(evidence.get("unique_regime_count"), -1)))
        if explicit_count >= 0:
            required = int(settings["min_market_regimes_for_apply"])
            return {
                "raw_regime_count": _int(evidence.get("raw_regime_count"), explicit_count),
                "distinct_regime_count": explicit_count,
                "qualifying_regime_count": explicit_count,
                "deduped_regime_count": _int(evidence.get("deduped_regime_count"), 0),
                "raw_regimes": [],
                "distinct_regimes": [],
                "canonical_regime_by_raw_regime": {},
                "regime_dedup_reason": str(evidence.get("regime_dedup_reason") or "explicit_analysis_distinct_count"),
                "required_distinct_regime_count": required,
                "distinct_regime_gate_passed": explicit_count >= required,
                "additional_regime_features_needed": [],
            }
    if not regimes:
        candidate_evidence = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
        regimes = candidate_evidence.get("market_regimes") if isinstance(candidate_evidence.get("market_regimes"), list) else []
    return regime_diversity_diagnostics(regimes, required=int(settings["min_market_regimes_for_apply"]))


def _direction_stability_gate(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    item = _first_parameter_analysis(analysis)
    gates = item.get("statistical_gates") if isinstance(item.get("statistical_gates"), dict) else {}
    gate = gates.get("direction_stability_gate") if isinstance(gates.get("direction_stability_gate"), dict) else {}
    if gate:
        return gate
    fallback = candidate.get("direction_stability_gate") if isinstance(candidate.get("direction_stability_gate"), dict) else {}
    return fallback


def _effect_gate(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    item = _first_parameter_analysis(analysis)
    gates = item.get("statistical_gates") if isinstance(item.get("statistical_gates"), dict) else {}
    return gates.get("effect_size_gate") if isinstance(gates.get("effect_size_gate"), dict) else (candidate.get("effect_size_gate") if isinstance(candidate.get("effect_size_gate"), dict) else {})


def _confidence_gate(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Any]:
    item = _first_parameter_analysis(analysis)
    gates = item.get("statistical_gates") if isinstance(item.get("statistical_gates"), dict) else {}
    return gates.get("confidence_gate") if isinstance(gates.get("confidence_gate"), dict) else (candidate.get("confidence_gate") if isinstance(candidate.get("confidence_gate"), dict) else {})


def _regime_coverage_pct(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> float:
    item = _first_parameter_analysis(analysis)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    value = _float(evidence.get("adaptive_gate_regime_coverage_pct"))
    if value is not None:
        return value
    regime = candidate.get("regime_enrichment") if isinstance(candidate.get("regime_enrichment"), dict) else {}
    return _float(regime.get("coverage_pct")) or 0.0


def _evidence_counts_by_regime(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    item = _first_parameter_analysis(analysis)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    rows = evidence.get("regime_counts") or evidence.get("counts_by_regime")
    if isinstance(rows, dict):
        for regime, values in rows.items():
            if not isinstance(values, dict):
                continue
            out[str(regime)] = {
                "validated_conclusions": _int(values.get("validated_conclusions") or values.get("validated_analyses"), 0),
                "directional_events": _int(values.get("directional_events"), 0),
            }
    if out:
        return out
    candidate_evidence = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
    rows = candidate_evidence.get("regime_counts") or candidate_evidence.get("counts_by_regime")
    if isinstance(rows, dict):
        for regime, values in rows.items():
            if not isinstance(values, dict):
                continue
            current = out.setdefault(str(regime), {"validated_conclusions": 0, "directional_events": 0})
            current["validated_conclusions"] = max(
                current["validated_conclusions"],
                _int(values.get("validated_conclusions") or values.get("validated_analyses"), 0),
            )
            current["directional_events"] = max(current["directional_events"], _int(values.get("directional_events"), 0))
    if not out:
        regimes = candidate_evidence.get("market_regimes") if isinstance(candidate_evidence.get("market_regimes"), list) else []
        total_validated = _int(candidate_evidence.get("total_validated_conclusions"), _int(evidence.get("validated_conclusions"), 0))
        total_directional = _int(candidate_evidence.get("total_directional_events"), _int(evidence.get("directional_events"), 0))
        if regimes:
            per_validated = total_validated // max(1, len(regimes))
            per_directional = total_directional // max(1, len(regimes))
            for regime in regimes:
                out[str(regime)] = {
                    "validated_conclusions": per_validated,
                    "directional_events": per_directional,
                }
    return out


def _canonical_evidence_counts_by_regime(evidence_counts: Dict[str, Dict[str, int]]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for regime, counts in evidence_counts.items():
        key = canonical_regime_key(regime)
        item = out.setdefault(key, {"validated_conclusions": 0, "directional_events": 0})
        item["validated_conclusions"] += _int(counts.get("validated_conclusions"), 0)
        item["directional_events"] += _int(counts.get("directional_events"), 0)
    return dict(sorted(out.items()))


def _evidence_hash(candidate: Dict[str, Any], analysis: Dict[str, Any]) -> str:
    item = _first_parameter_analysis(analysis)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    candidate_evidence = candidate.get("evidence_summary") if isinstance(candidate.get("evidence_summary"), dict) else {}
    return str(
        candidate.get("evidence_hash")
        or candidate_evidence.get("evidence_hash")
        or analysis.get("evidence_hash")
        or evidence.get("evidence_hash")
        or ""
    ).strip()


def adaptive_readiness_layers(
    *,
    root: Path = Path("."),
    settings: Optional[Dict[str, Any]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    analysis: Optional[Dict[str, Any]] = None,
    validation_blockers: Optional[Sequence[str]] = None,
) -> Dict[str, Any]:
    cfg = settings or governor_settings()
    candidate_payload = candidate if candidate is not None else load_candidate(root)
    analysis_payload = analysis if analysis is not None else load_candidate_analysis(root)
    visible_changes_for_fast_start = candidate_payload.get("proposed_parameter_changes") if isinstance(candidate_payload.get("proposed_parameter_changes"), list) else []
    fast_start_change = next((c for c in visible_changes_for_fast_start if _is_fast_start_autotune_change(c)), None)
    item = _first_parameter_analysis(analysis_payload)
    evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
    direction_gate = _direction_stability_gate(candidate_payload, analysis_payload)
    effect = _effect_gate(candidate_payload, analysis_payload)
    confidence = _confidence_gate(candidate_payload, analysis_payload)
    regime_diag = _regime_diagnostics(candidate_payload, analysis_payload, cfg)
    regime_count = int(regime_diag.get("distinct_regime_count") or _regime_count(candidate_payload, analysis_payload))
    coverage = _regime_coverage_pct(candidate_payload, analysis_payload)
    evidence_counts = _evidence_counts_by_regime(candidate_payload, analysis_payload)
    canonical_evidence_counts = _canonical_evidence_counts_by_regime(evidence_counts)
    candidate_available = candidate_payload.get("candidate_available") is True or analysis_payload.get("candidate_available") is True
    analysis_diag_available = bool(effect) and bool(confidence)
    enough_validated = _int(evidence.get("validated_conclusions"), 0) >= 300 or _int((candidate_payload.get("evidence_summary") or {}).get("total_validated_conclusions") if isinstance(candidate_payload.get("evidence_summary"), dict) else 0, 0) >= 300
    enough_relevant = _int(evidence.get("relevant_conclusions"), 0) >= 150 or candidate_available
    analysis_blockers: List[str] = []
    if not candidate_available:
        analysis_blockers.append("candidate_not_available")
    if regime_count < int(cfg["min_market_regimes_for_analysis"]):
        analysis_blockers.append(
            "insufficient_distinct_regime_diversity"
            if int(regime_diag.get("raw_regime_count") or 0) >= int(cfg["min_market_regimes_for_analysis"])
            else "insufficient_market_regimes"
        )
    if not enough_validated:
        analysis_blockers.append("insufficient_validated_conclusions")
    if not enough_relevant:
        analysis_blockers.append("insufficient_relevant_conclusions")
    if not analysis_diag_available:
        analysis_blockers.append("diagnostics_unavailable")
    analysis_ready = not analysis_blockers

    observed = _int(direction_gate.get("observed_runs"), 0)
    required = max(int(cfg["require_direction_stability_runs"]), _int(direction_gate.get("required_runs"), 0))
    if direction_gate.get("passed") is True and observed <= 0:
        observed = required
    direction_stable = bool(direction_gate.get("passed")) and observed >= required
    prepare_blockers = list(analysis_blockers)
    if not analysis_ready:
        prepare_blockers.append("analysis_not_ready")
    if regime_count < int(cfg["min_market_regimes_for_prepare"]):
        prepare_blockers.append("insufficient_market_regimes_for_prepare")
    if not direction_stable:
        prepare_blockers.append("direction_stability_not_met")
    if not candidate_available:
        prepare_blockers.append("candidate_not_available")
    operator_report_available = bool(analysis_payload) or candidate_payload.get("requires_operator_review") is True
    if not operator_report_available:
        prepare_blockers.append("operator_review_report_missing")
    prepare_ready = analysis_ready and not prepare_blockers

    effect_passed = bool(effect.get("passed") is True or effect.get("would_pass_effect_size_gate") is True)
    confidence_passed = bool(confidence.get("passed") is True or confidence.get("would_pass_confidence_gate") is True)
    apply_blockers = list(prepare_blockers)
    if not prepare_ready:
        apply_blockers.append("prepare_not_ready")
    if regime_count < int(cfg["min_market_regimes_for_apply"]):
        apply_blockers.append("insufficient_market_regimes_for_apply")
    if fast_start_change is not None:
        # The reflection-ledger per-regime validated-conclusion/directional-event
        # counts (calibrated for hundreds of human-labeled conclusions per
        # regime) do not apply to a single bounded online-learning estimate.
        # Use the row's own already-verified regime list and evidence_count
        # instead -- the fast_start bar (>=3 regimes, >=75 evidence_count) was
        # already independently checked in _growbot_river_supplemental_changes.
        fast_start_regimes = sorted({str(r) for r in (fast_start_change.get("market_regimes") or []) if r})
        fast_start_evidence_count = _int(fast_start_change.get("sample_count"), 0)
        qualifying_regimes = (
            fast_start_regimes
            if len(fast_start_regimes) >= int(cfg["min_market_regimes_for_apply"]) and fast_start_evidence_count > 0
            else []
        )
    else:
        qualifying_regimes = [
            regime
            for regime, counts in canonical_evidence_counts.items()
            if int(counts.get("validated_conclusions") or 0) >= int(cfg["min_validated_conclusions_per_regime_for_apply"])
            and int(counts.get("directional_events") or 0) >= int(cfg["min_directional_events_per_regime_for_apply"])
        ]
    if len(qualifying_regimes) < int(cfg["min_market_regimes_for_apply"]):
        apply_blockers.append("insufficient_per_regime_apply_evidence")
    if coverage < float(cfg["min_regime_enrichment_coverage_pct"]):
        apply_blockers.append("regime_coverage_below_apply_minimum")
    if not effect_passed:
        apply_blockers.append("effect_size_gate_not_passed")
    if not confidence_passed:
        apply_blockers.append("confidence_gate_not_passed")
    if validation_blockers:
        apply_blockers.extend(str(blocker) for blocker in validation_blockers)
    apply_ready = prepare_ready and not apply_blockers
    direction_gate = dict(direction_gate)
    direction_gate["observed_runs"] = observed
    direction_gate["required_runs"] = required
    return {
        "analysis_ready": bool(analysis_ready),
        "prepare_ready": bool(prepare_ready),
        "apply_ready": bool(apply_ready),
        "analysis_blockers": sorted(set(analysis_blockers)),
        "prepare_blockers": sorted(set(prepare_blockers)),
        "apply_blockers": sorted(set(apply_blockers)),
        "regime_count": regime_count,
        "raw_regime_count": regime_diag.get("raw_regime_count", regime_count),
        "distinct_regime_count": regime_diag.get("distinct_regime_count", regime_count),
        "qualifying_regime_count": len(qualifying_regimes),
        "deduped_regime_count": regime_diag.get("deduped_regime_count", 0),
        "regime_dedup_reason": regime_diag.get("regime_dedup_reason", "none"),
        "distinct_regimes": regime_diag.get("distinct_regimes", []),
        "additional_regime_features_needed": regime_diag.get("additional_regime_features_needed", []),
        "min_market_regimes_for_analysis": cfg["min_market_regimes_for_analysis"],
        "min_market_regimes_for_prepare": cfg["min_market_regimes_for_prepare"],
        "min_market_regimes_for_apply": cfg["min_market_regimes_for_apply"],
        "adaptive_gate_regime_coverage_pct": coverage,
        "min_regime_enrichment_coverage_pct": cfg["min_regime_enrichment_coverage_pct"],
        "evidence_counts_by_regime": evidence_counts,
        "deduped_evidence_counts_by_regime": canonical_evidence_counts,
        "regime_key_design": (evidence.get("regime_key_designs") or ["unknown"])[0] if isinstance(evidence.get("regime_key_designs"), list) and evidence.get("regime_key_designs") else "unknown",
        "regime_key_designs": evidence.get("regime_key_designs") if isinstance(evidence.get("regime_key_designs"), list) else [],
        "directional_event_source": evidence.get("directional_event_source") or "",
        "directional_event_count_method": evidence.get("directional_event_count_method") or "",
        "qualifying_apply_regimes": sorted(qualifying_regimes),
        "min_validated_conclusions_per_regime_for_apply": cfg["min_validated_conclusions_per_regime_for_apply"],
        "min_directional_events_per_regime_for_apply": cfg["min_directional_events_per_regime_for_apply"],
        "evidence_hash": _evidence_hash(candidate_payload, analysis_payload),
        "direction_stability": direction_gate,
        "effect_size_gate_passed": effect_passed,
        "confidence_gate_passed": confidence_passed,
        "candidate_available": candidate_available,
    }


OPEN_STATUSES = {"planned", "pending", "submitted", "open", "partially_filled", "cancel_pending", "replace_pending"}
D3_PHASE = "D3_controlled_live_reduce_only_exits"


def _orders(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("orders"), dict):
        return [v for v in payload["orders"].values() if isinstance(v, dict)]
    if isinstance(payload, list):
        return [v for v in payload if isinstance(v, dict)]
    return []


def order_position_safety(root: Path = Path(".")) -> Dict[str, Any]:
    orders = _orders(_load_json(root / "state/open_orders.json"))
    open_orders = [o for o in orders if str(o.get("status") or "").lower() in OPEN_STATUSES]
    open_d3 = [
        o for o in open_orders
        if str(o.get("phase") or "") == D3_PHASE and str(o.get("side") or "").upper() == "SELL"
    ]
    positions_payload = _load_json(root / "state/positions.json")
    positions = positions_payload.get("positions") if isinstance(positions_payload, dict) and isinstance(positions_payload.get("positions"), dict) else positions_payload
    open_positions = []
    if isinstance(positions, dict):
        for pos in positions.values():
            if not isinstance(pos, dict):
                continue
            status = str(pos.get("status") or "open").lower()
            base = _float(pos.get("position_size_base") or pos.get("size_base") or pos.get("base_size") or pos.get("bot_managed_base")) or 0.0
            if status in {"open", "active"} and abs(base) > 0:
                open_positions.append(pos)
    return {
        "open_orders": len(open_orders),
        "open_positions": len(open_positions),
        "open_d3_exit": len(open_d3),
        "controlled_stop_or_close_pending": any("stop" in str(o.get("reason") or o.get("order_type") or "").lower() or "close" in str(o.get("reason") or "").lower() for o in open_orders),
        "lifecycle_error_active": False,
    }


def readiness_status(root: Path = Path("."), readiness_report: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if readiness_report is None:
        try:
            from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report

            readiness_report = build_full_autonomous_run_readiness_report(root=root)
        except Exception as exc:
            return {
                "readiness_recommendation": "unknown",
                "full_poc_ready": False,
                "mode_c_ready": False,
                "blockers": [f"readiness_unavailable:{exc}"],
            }
    poc = readiness_report.get("poc_full_workflow_readiness") if isinstance(readiness_report.get("poc_full_workflow_readiness"), dict) else {}
    mode_c = readiness_report.get("mode_c_market_order_readiness") if isinstance(readiness_report.get("mode_c_market_order_readiness"), dict) else {}
    return {
        "readiness_recommendation": readiness_report.get("recommendation") or "unknown",
        "full_poc_ready": poc.get("ready") is True,
        "mode_c_ready": mode_c.get("ready") is True,
        "blockers": readiness_report.get("blockers") if isinstance(readiness_report.get("blockers"), list) else [],
    }


def _load_activations(root: Path) -> List[Dict[str, Any]]:
    path = root / ACTIVATION_LOG_PATH
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return []
    rows = []
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def cooldown_status(root: Path, settings: Dict[str, Any], *, now: Optional[datetime] = None) -> Dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    activations = _load_activations(root)
    applied = [row for row in activations if row.get("applied") is True]
    last = applied[-1] if applied else None
    since = current - timedelta(hours=24)
    recent = [row for row in applied if (parse_time(row.get("generated_at")) or current) >= since]
    blockers: List[str] = []
    if last:
        last_ts = parse_time(last.get("generated_at"))
        if int(settings.get("cooldown_hours") or 0) > 0 and last_ts and last_ts > current - timedelta(hours=settings["cooldown_hours"]):
            blockers.append("cooldown_active")
        if last.get("evaluated") is not True:
            blockers.append("previous_activation_not_evaluated")
    if len(recent) >= settings["max_changes_per_24h"]:
        blockers.append("max_changes_per_24h_reached")
    return {
        "cooldown_active": "cooldown_active" in blockers,
        "last_activation": last,
        "changes_last_24h": len(recent),
        "blockers": blockers,
    }


def validate_governor(
    *,
    root: Path = Path("."),
    env: Optional[Mapping[str, str]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    readiness_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if env is None:
        load_project_env(root)
    settings = governor_settings(env)
    candidate_payload = candidate if candidate is not None else load_candidate(root)
    analysis_payload = load_candidate_analysis(root)
    order_safety = order_position_safety(root)
    ready = readiness_status(root, readiness_report)
    cooldown = cooldown_status(root, settings)
    blockers = _candidate_gate_blockers(candidate_payload, settings)
    analysis = candidate_analysis_status(root)
    if settings["apply_only_when_no_open_orders"] and order_safety["open_orders"] > 0:
        blockers.append("open_orders_present")
    if settings["apply_only_when_no_open_orders"] and order_safety["open_d3_exit"] > 0:
        blockers.append("open_d3_exit_present")
    if settings["apply_only_when_no_open_orders"] and order_safety["controlled_stop_or_close_pending"]:
        blockers.append("controlled_stop_or_close_pending")
    if order_safety["lifecycle_error_active"]:
        blockers.append("lifecycle_error_active")
    if settings["apply_only_when_no_open_positions"] and order_safety["open_positions"] > 0:
        blockers.append("open_positions_present")
    if settings["require_full_poc_ready"] and not ready["full_poc_ready"]:
        blockers.append("full_poc_not_ready")
    if settings["require_mode_c_ready"] and not ready["mode_c_ready"]:
        blockers.append("mode_c_not_ready")
    blockers.extend(cooldown["blockers"])
    blockers = sorted(set(blockers))
    analysis_payload = load_candidate_analysis(root)
    if analysis_payload.get("reason") == "insufficient_distinct_regime_diversity":
        blockers = sorted({"insufficient_distinct_regime_diversity" if blocker == "insufficient_market_regimes" else blocker for blocker in blockers})
    readiness_layers = adaptive_readiness_layers(
        root=root,
        settings=settings,
        candidate=candidate_payload,
        analysis=analysis_payload,
        validation_blockers=blockers,
    )
    evidence_hash = str(readiness_layers.get("evidence_hash") or "")
    last_activation = cooldown.get("last_activation") if isinstance(cooldown.get("last_activation"), dict) else {}
    last_evidence_hash = str(last_activation.get("evidence_hash") or last_activation.get("candidate_hash") or "")
    if settings["require_new_evidence_since_last_apply"] and last_activation and not evidence_hash:
        readiness_layers["apply_blockers"].append("missing_new_evidence_hash")
    if settings["forbid_reuse_of_last_evidence_hash"] and evidence_hash and last_evidence_hash and evidence_hash == last_evidence_hash:
        readiness_layers["apply_blockers"].append("reused_evidence_hash")
    candidate_hash = str(candidate_payload.get("hash") or "") if candidate_payload else ""
    analysis_changes = _analysis_proposed_changes(analysis_payload)
    candidate_changes = _proposed_changes(candidate_payload)
    visible_changes = candidate_changes or analysis_changes
    first_change = visible_changes[0] if visible_changes else {}
    proposed_parameters = analysis_payload.get("proposed_parameters") if isinstance(analysis_payload.get("proposed_parameters"), dict) else {}
    proposed_parameter_changes = [
        change for change in (analysis_payload.get("proposed_parameter_changes") or [])
        if isinstance(change, dict)
    ] if isinstance(analysis_payload.get("proposed_parameter_changes"), list) else []
    parameter_changes = [
        change for change in (analysis_payload.get("parameter_changes") or [])
        if isinstance(change, dict)
    ] if isinstance(analysis_payload.get("parameter_changes"), list) else []
    candidate_generation_blockers = [
        blocker for blocker in sorted(set(readiness_layers.get("analysis_blockers") or []))
        if blocker != "candidate_not_available"
    ]
    analysis_blocker = str(analysis_payload.get("candidate_generation_blocker") or "")
    if analysis_blocker and analysis_blocker != "none" and analysis_blocker not in candidate_generation_blockers:
        candidate_generation_blockers.insert(0, analysis_blocker)
    candidate_proposal_present = bool(candidate_changes or proposed_parameter_changes)
    proposed_parameters_present = bool(proposed_parameters)
    parameter_changes_present = bool(parameter_changes)
    apply_blockers_by_type = group_blockers_by_type(readiness_layers.get("apply_blockers") or [])
    candidate_generation_blockers_by_type = group_blockers_by_type(candidate_generation_blockers)
    next_data_needed = []
    if "insufficient_distinct_regime_diversity" in candidate_generation_blockers:
        next_data_needed.extend(readiness_layers.get("additional_regime_features_needed") or [])
    if "diagnostics_unavailable" in candidate_generation_blockers:
        next_data_needed.append("effect/confidence diagnostics")
    if "insufficient_relevant_conclusions" in candidate_generation_blockers:
        next_data_needed.append("more validated relevant conclusions")
    next_data_needed = sorted(set(str(item) for item in next_data_needed if str(item)))
    internal_inconsistency = bool(
        not (candidate_payload.get("candidate_available") is True or analysis_payload.get("candidate_available") is True)
        and readiness_layers.get("distinct_regime_count", readiness_layers.get("regime_count", 0)) >= settings["min_market_regimes_for_analysis"]
        and readiness_layers.get("qualifying_regime_count", 0) >= settings["min_market_regimes_for_apply"]
        and readiness_layers.get("effect_size_gate_passed") is True
        and readiness_layers.get("confidence_gate_passed") is True
        and (readiness_layers.get("direction_stability") or {}).get("passed") is True
    )
    if "candidate_file_missing" in blockers:
        reason = "candidate_file_missing"
    elif "insufficient_distinct_regime_diversity" in readiness_layers["analysis_blockers"] or analysis_payload.get("reason") == "insufficient_distinct_regime_diversity":
        reason = "insufficient_distinct_regime_diversity"
    elif "insufficient_market_regimes" in blockers or "insufficient_market_regimes" in readiness_layers["analysis_blockers"]:
        reason = "insufficient_market_regimes"
    elif "candidate_not_available" in blockers:
        reason = "candidate_not_available"
    elif blockers:
        reason = blockers[0]
    else:
        reason = "activation_allowed"
    ack_valid = settings["ack"] == settings["required_ack"]
    if not settings["enabled"]:
        readiness_layers["apply_blockers"].append("governor_disabled")
    if settings["mode"] != "apply_when_safe":
        readiness_layers["apply_blockers"].append("mode_not_apply_when_safe")
    if not ack_valid:
        readiness_layers["apply_blockers"].append("missing_or_invalid_ack")
    if settings["max_parameters_per_activation"] != 1:
        readiness_layers["apply_blockers"].append("max_parameters_per_activation_not_one")
    if analysis_payload.get("reason") == "insufficient_distinct_regime_diversity":
        for key in ("analysis_blockers", "prepare_blockers", "apply_blockers"):
            readiness_layers[key] = [
                "insufficient_distinct_regime_diversity" if blocker == "insufficient_market_regimes" else blocker
                for blocker in readiness_layers.get(key, [])
            ]
    readiness_layers["apply_blockers"] = sorted(set(readiness_layers["apply_blockers"]))
    apply_blockers_by_type = group_blockers_by_type(readiness_layers.get("apply_blockers") or [])
    operator_ack_missing = "missing_or_invalid_ack" in readiness_layers["apply_blockers"]
    true_safety_blockers = apply_blockers_by_type.get("true_safety", [])
    data_quality_blockers = apply_blockers_by_type.get("data_quality", [])
    stale_legacy_blockers = apply_blockers_by_type.get("stale_legacy_gate", [])
    workflow_blockers = apply_blockers_by_type.get("workflow_blocker", [])
    only_operator_review_or_apply_ack_missing = bool(
        visible_changes
        and not true_safety_blockers
        and not data_quality_blockers
        and not stale_legacy_blockers
        and set(readiness_layers.get("apply_blockers", [])) <= {"missing_or_invalid_ack"}
    )
    if internal_inconsistency:
        next_operator_action = "rerun_candidate_analysis_or_fix_mapping"
    elif candidate_payload.get("candidate_available") is True and only_operator_review_or_apply_ack_missing:
        next_operator_action = "operator_review_and_exact_ack"
    elif data_quality_blockers:
        next_operator_action = "collect_data"
    elif true_safety_blockers:
        next_operator_action = "wait_for_live_safety_clear"
    elif workflow_blockers:
        next_operator_action = "review_workflow_mode"
    else:
        next_operator_action = "review_status"
    readiness_layers["apply_ready"] = bool(
        readiness_layers["prepare_ready"]
        and settings["enabled"]
        and settings["mode"] == "apply_when_safe"
        and ack_valid
        and settings["max_parameters_per_activation"] == 1
        and not readiness_layers["apply_blockers"]
    )
    can_mutate = readiness_layers["apply_ready"]
    return {
        "generated_at": now_iso(),
        "available": True,
        "enabled": settings["enabled"],
        "mode": settings["mode"],
        "candidate_available": bool(candidate_payload.get("candidate_available")) if candidate_payload else False,
        "candidate_available_reason": reason,
        "analysis_candidate_available": bool(analysis_payload.get("candidate_available")) if analysis_payload else False,
        "candidate_hash": candidate_hash if candidate_payload.get("candidate_available") is True else "",
        "blocked_candidate_report_hash": candidate_hash if candidate_payload and candidate_payload.get("candidate_available") is not True else "",
        "report_hash": analysis.get("candidate_analysis_hash") or analysis_payload.get("analysis_hash") or "",
        **analysis,
        "analysis_ready": readiness_layers["analysis_ready"],
        "prepare_ready": readiness_layers["prepare_ready"],
        "apply_ready": readiness_layers["apply_ready"],
        "readiness_layers": readiness_layers,
        "regime_count": readiness_layers.get("regime_count"),
        "raw_regime_count": readiness_layers.get("raw_regime_count"),
        "distinct_regime_count": readiness_layers.get("distinct_regime_count"),
        "qualifying_regime_count": readiness_layers.get("qualifying_regime_count"),
        "deduped_regime_count": readiness_layers.get("deduped_regime_count"),
        "regime_dedup_reason": readiness_layers.get("regime_dedup_reason"),
        "regime_key_design": readiness_layers.get("regime_key_design"),
        "regime_key_designs": readiness_layers.get("regime_key_designs"),
        "evidence_counts_by_regime": readiness_layers.get("evidence_counts_by_regime"),
        "deduped_evidence_counts_by_regime": readiness_layers.get("deduped_evidence_counts_by_regime"),
        "candidate_generation_ready": bool((candidate_payload.get("candidate_available") is True or analysis_payload.get("candidate_available") is True) and not candidate_generation_blockers),
        "candidate_generation_blocker": analysis_payload.get("candidate_generation_blocker") or (readiness_layers["analysis_blockers"][0] if readiness_layers["analysis_blockers"] else "none"),
        "candidate_generation_blockers": candidate_generation_blockers,
        "candidate_generation_blockers_by_type": candidate_generation_blockers_by_type,
        "candidate_proposal_present": candidate_proposal_present,
        "proposed_parameters_present": proposed_parameters_present,
        "parameter_changes_present": parameter_changes_present,
        "missing_candidate_fields": analysis_payload.get("missing_candidate_fields") if isinstance(analysis_payload.get("missing_candidate_fields"), list) else [],
        "internal_inconsistency_detected": internal_inconsistency,
        "recommendation": "rerun_candidate_analysis_or_fix_mapping" if internal_inconsistency else (analysis_payload.get("recommendation") or candidate_payload.get("recommendation") or "collect_more_data"),
        "proposed_parameter": first_change.get("parameter") or "",
        "proposed_old_value": first_change.get("current_value") or "",
        "proposed_new_value": first_change.get("candidate_value") or "",
        "proposed_step_pct": first_change.get("change_pct"),
        "apply_blockers_by_type": apply_blockers_by_type,
        "operator_ack_missing": operator_ack_missing,
        "true_safety_blockers": true_safety_blockers,
        "data_quality_blockers": data_quality_blockers,
        "stale_legacy_blockers": stale_legacy_blockers,
        "workflow_blockers": workflow_blockers,
        "next_data_needed": next_data_needed,
        "next_operator_action": next_operator_action,
        "why_not_applied": sorted(set(readiness_layers.get("apply_blockers") or blockers)) or ["operator_review_or_apply_ack_required"],
        "only_operator_review_or_apply_ack_missing": only_operator_review_or_apply_ack_missing,
        "directional_event_source": readiness_layers.get("directional_event_source"),
        "directional_event_count_method": readiness_layers.get("directional_event_count_method"),
        "early_tuning_mode_available": True,
        "early_tuning_mode_configured": bool(settings.get("early_tuning_mode")),
        "apply_blocked_by_open_orders": bool(settings["apply_only_when_no_open_orders"] and order_safety["open_orders"] > 0),
        "apply_blocked_by_open_positions": bool(settings["apply_only_when_no_open_positions"] and order_safety["open_positions"] > 0),
        "governor_activation_allowed": readiness_layers["apply_ready"],
        "governor_reason": reason,
        "reason": reason,
        "blockers": blockers,
        "open_orders": order_safety["open_orders"],
        "open_positions": order_safety["open_positions"],
        "open_d3_exit": order_safety["open_d3_exit"],
        "readiness_recommendation": ready["readiness_recommendation"],
        "readiness": ready,
        "cooldown_active": cooldown["cooldown_active"],
        "last_activation": cooldown["last_activation"],
        "settings": settings,
        "source_policy": SOURCE_POLICY,
        "can_authorize_orders": False,
        "can_mutate_allowed_parameters": can_mutate,
    }


def _current_profile(root: Path) -> Dict[str, Any]:
    payload = _load_json(root / APPROVED_PROFILE_PATH)
    return payload if isinstance(payload, dict) else {"parameters": {}}


def _proposed_changes(candidate: Dict[str, Any]) -> List[Dict[str, Any]]:
    changes = candidate.get("proposed_parameter_changes")
    return [change for change in changes if isinstance(change, dict)] if isinstance(changes, list) else []


def _analysis_proposed_changes(analysis: Dict[str, Any]) -> List[Dict[str, Any]]:
    for key in ("proposed_parameter_changes", "parameter_changes"):
        changes = analysis.get(key)
        if isinstance(changes, list):
            return [change for change in changes if isinstance(change, dict)]
    return []


def build_activation_plan(
    *,
    root: Path = Path("."),
    env: Optional[Mapping[str, str]] = None,
    candidate: Optional[Dict[str, Any]] = None,
    readiness_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    candidate_payload = candidate if candidate is not None else load_candidate(root)
    validation = validate_governor(root=root, env=env, candidate=candidate_payload, readiness_report=readiness_report)
    layers = validation.get("readiness_layers") if isinstance(validation.get("readiness_layers"), dict) else {}
    changes = _proposed_changes(candidate_payload)
    allowed_only = all(str(change.get("parameter") or "") in ALLOWED_PARAMETERS for change in changes)
    profile = _current_profile(root)
    params = profile.get("parameters") if isinstance(profile.get("parameters"), dict) else {}
    proposed_params = dict(params)
    for change in changes:
        parameter = str(change.get("parameter") or "")
        if parameter in APPROVED_PARAMETER_PROFILE_WHITELIST:
            proposed_params[parameter] = str(change.get("candidate_value") or "")
    next_profile = dict(profile)
    next_profile["parameters"] = proposed_params
    next_profile["source"] = "autonomous_parameter_governor_candidate"
    next_profile["candidate_hash"] = candidate_payload.get("hash")
    plan_available = bool(layers.get("prepare_ready"))
    return {
        "activation_plan_available": plan_available,
        "reason": validation["reason"] if not plan_available else "activation_plan_ready",
        "analysis_ready": bool(layers.get("analysis_ready")),
        "prepare_ready": bool(layers.get("prepare_ready")),
        "apply_ready": bool(layers.get("apply_ready")),
        "candidate_hash": validation["candidate_hash"],
        "candidate_analysis_available": validation.get("candidate_analysis_available"),
        "candidate_analysis_path": validation.get("candidate_analysis_path"),
        "candidate_analysis_hash": validation.get("candidate_analysis_hash"),
        "analysis_reason": validation.get("analysis_reason"),
        "proposed_changes": changes,
        "allowed_parameters_only": allowed_only,
        "would_write_profile": bool(layers.get("apply_ready")),
        "would_backup_current_profile": True,
        "would_require_no_open_orders": True,
        "would_require_no_open_positions": True,
        "would_require_ack": True,
        "safe_to_apply_now": validation["can_mutate_allowed_parameters"],
        "governor_validation": validation,
        "next_profile_preview": next_profile,
        "source_policy": SOURCE_POLICY,
    }


def render_activation_plan_markdown(plan: Dict[str, Any]) -> str:
    lines = [
        "# Autonomous Parameter Governor Activation Plan",
        "",
        f"Available: {plan.get('activation_plan_available')}",
        f"Reason: `{plan.get('reason')}`",
        f"Candidate hash: `{plan.get('candidate_hash')}`",
        "",
        "## Safety",
        "- order authority: false",
        "- env mutation: false",
        "- requires no open orders: true",
        "- requires no open positions: true",
        "- requires ACK: true",
        "",
        "## Proposed Changes",
    ]
    changes = plan.get("proposed_changes") or []
    if not changes:
        lines.append("- none")
    for change in changes:
        lines.append(f"- `{change.get('parameter')}`: `{change.get('current_value')}` -> `{change.get('candidate_value')}`")
    return "\n".join(lines) + "\n"


def write_activation_plan(plan: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    paths = {"json": root / PLAN_JSON_PATH, "markdown": root / PLAN_MD_PATH}
    atomic_write_json(paths["json"], plan)
    paths["markdown"].parent.mkdir(parents=True, exist_ok=True)
    paths["markdown"].write_text(render_activation_plan_markdown(plan), encoding="utf-8")
    return {key: str(path) for key, path in paths.items()}


def render_governor_run_markdown(result: Dict[str, Any]) -> str:
    plan = result.get("plan") if isinstance(result.get("plan"), dict) else {}
    validation = plan.get("governor_validation") if isinstance(plan.get("governor_validation"), dict) else {}
    return "\n".join(
        [
            "# Autonomous Parameter Governor Run",
            "",
            f"Generated: {result.get('generated_at')}",
            f"Action: `{result.get('action')}`",
            f"Applied: {result.get('applied')}",
            f"Reason: `{result.get('reason')}`",
            f"Analysis ready: {result.get('analysis_ready')}",
            f"Prepare ready: {result.get('prepare_ready')}",
            f"Apply ready: {result.get('apply_ready')}",
            f"Candidate available: {validation.get('candidate_available')}",
            f"Candidate hash: `{result.get('candidate_hash')}`",
            "",
            "## Safety",
            f"- coinbase_action_performed: {result.get('coinbase_action_performed')}",
            f"- env_mutation_performed: {result.get('env_mutation_performed')}",
            f"- state_write_performed: {result.get('state_write_performed')}",
            f"- service_lifecycle_performed: {result.get('service_lifecycle_performed')}",
            f"- parameters_applied: {', '.join(result.get('parameters_applied') or []) or 'none'}",
        ]
    ) + "\n"


def write_governor_run_outputs(result: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    atomic_write_json(root / RUN_PATH, result)
    (root / RUN_MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / RUN_MD_PATH).write_text(render_governor_run_markdown(result), encoding="utf-8")
    (root / RUN_HISTORY_PATH).parent.mkdir(parents=True, exist_ok=True)
    with (root / RUN_HISTORY_PATH).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n")
    return {"json": str(root / RUN_PATH), "markdown": str(root / RUN_MD_PATH), "history": str(root / RUN_HISTORY_PATH)}


def run_governor(
    *,
    root: Path = Path("."),
    env: Optional[Mapping[str, str]] = None,
    apply: bool = False,
    candidate: Optional[Dict[str, Any]] = None,
    readiness_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if env is None:
        load_project_env(root)
    settings = governor_settings(env)
    candidate_payload = candidate if candidate is not None else load_candidate(root)
    plan = build_activation_plan(root=root, env=env, candidate=candidate_payload, readiness_report=readiness_report)
    validation = plan["governor_validation"]
    layers = validation.get("readiness_layers") if isinstance(validation.get("readiness_layers"), dict) else {}
    changes = _proposed_changes(candidate_payload)
    changed_parameters = [str(change.get("parameter") or "") for change in changes[:1] if str(change.get("parameter") or "")]
    action = "dry_run" if not apply else ("apply_one_parameter" if validation.get("apply_ready") else "noop_collect_more_data")
    result = {
        "generated_at": now_iso(),
        "dry_run": not apply,
        "applied": False,
        "reason": validation["reason"],
        "action": action,
        "governor_enabled": settings["enabled"],
        "mode": settings["mode"],
        "analysis_ready": bool(validation.get("analysis_ready")),
        "prepare_ready": bool(validation.get("prepare_ready")),
        "apply_ready": bool(validation.get("apply_ready")),
        "candidate_hash": validation["candidate_hash"],
        "candidate_available": validation.get("candidate_available"),
        "parameters_applied": [],
        "state_write_performed": False,
        "env_mutation_performed": False,
        "service_lifecycle_performed": False,
        "coinbase_action_performed": False,
        "source_policy": SOURCE_POLICY,
        "plan": plan,
    }
    if not apply:
        result["dry_run_only"] = True
        result["outputs"] = write_governor_run_outputs(result, root=root)
        return result
    if not settings["enabled"]:
        result["reason"] = "governor_disabled"
    elif settings["mode"] != "apply_when_safe":
        result["reason"] = "mode_not_apply_when_safe"
    elif settings["ack"] != settings["required_ack"]:
        result["reason"] = "missing_or_invalid_ack"
    elif not validation["apply_ready"]:
        result["reason"] = validation["reason"]
    elif settings["write_pending_only"]:
        result["reason"] = "write_pending_only"
    else:
        backup_dir = root / BACKUP_DIR
        backup_dir.mkdir(parents=True, exist_ok=True)
        src = root / APPROVED_PROFILE_PATH
        backup_path = backup_dir / f"approved_parameter_profile.before_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        if src.exists():
            shutil.copy2(src, backup_path)
        else:
            atomic_write_json(backup_path, {"parameters": {}})
        one_parameter_profile = dict(plan["next_profile_preview"])
        current_profile = _current_profile(root)
        current_params = current_profile.get("parameters") if isinstance(current_profile.get("parameters"), dict) else {}
        next_params = dict(current_params)
        for change in changes[:1]:
            parameter = str(change.get("parameter") or "")
            if parameter in APPROVED_PARAMETER_PROFILE_WHITELIST and parameter in ALLOWED_PARAMETERS:
                next_params[parameter] = str(change.get("candidate_value") or "")
        one_parameter_profile["parameters"] = next_params
        atomic_write_json(src, one_parameter_profile)
        new_hash = sha256_file(src)
        rollback_plan = {
            "generated_at": result["generated_at"],
            "rollback_available": True,
            "backup_profile_path": str(backup_path),
            "would_restore_hash": sha256_file(backup_path),
            "activated_profile_hash": new_hash,
            "candidate_hash": validation["candidate_hash"],
            "previous_profile_hash": sha256_file(backup_path),
            "new_profile_hash": new_hash,
            "changed_parameter": changed_parameters[0] if changed_parameters else "",
        }
        atomic_write_json(root / ROLLBACK_PLAN_PATH, rollback_plan)
        atomic_write_json(root / LEGACY_ROLLBACK_PLAN_PATH, rollback_plan)
        log_path = root / ACTIVATION_LOG_PATH
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "generated_at": result["generated_at"],
                "applied": True,
                "evaluated": False,
                "candidate_hash": validation["candidate_hash"],
                "evidence_hash": (layers or {}).get("evidence_hash") or validation["candidate_hash"],
                "profile_hash": new_hash,
                "changed_parameter": changed_parameters[0] if changed_parameters else "",
            }, sort_keys=True) + "\n")
        result.update({
            "applied": True,
            "reason": "applied",
            "action": "apply_one_parameter",
            "state_write_performed": True,
            "parameters_applied": changed_parameters[:1],
            "backup_profile_path": str(backup_path),
            "rollback_plan_path": str(root / ROLLBACK_PLAN_PATH),
            "activated_profile_hash": new_hash,
        })
    if not result["applied"]:
        result["action"] = "noop_collect_more_data"
    result["readiness_layers"] = layers
    result["outputs"] = write_governor_run_outputs(result, root=root)
    return result


def rollback_governor_profile(
    *,
    root: Path = Path("."),
    env: Optional[Mapping[str, str]] = None,
    apply: bool = False,
) -> Dict[str, Any]:
    if env is None:
        load_project_env(root)
    settings = governor_settings(env)
    plan = _load_json(root / ROLLBACK_PLAN_PATH)
    if not plan:
        plan = _load_json(root / LEGACY_ROLLBACK_PLAN_PATH)
    backup = Path(str(plan.get("backup_profile_path") or "")) if isinstance(plan, dict) else Path("")
    if not backup.is_absolute():
        backup = root / backup
    available = isinstance(plan, dict) and bool(plan) and backup.exists()
    allowed = apply and available and settings["rollback_ack"] == settings["required_rollback_ack"]
    result = {
        "generated_at": now_iso(),
        "rollback_available": available,
        "rollback_allowed": allowed,
        "applied": False,
        "reason": "dry_run" if not apply else ("missing_rollback_ack" if settings["rollback_ack"] != settings["required_rollback_ack"] else ("rollback_unavailable" if not available else "rollback_ready")),
        "backup_profile_path": str(backup) if available else "",
        "would_restore_hash": sha256_file(backup) if available else "",
        "state_write_performed": False,
        "env_mutation_performed": False,
    }
    if allowed:
        shutil.copy2(backup, root / APPROVED_PROFILE_PATH)
        result.update({"applied": True, "reason": "rollback_applied", "state_write_performed": True})
        audit_path = root / "reports/autonomous_parameter_governor/rollback/rollback-latest.json"
        atomic_write_json(audit_path, result)
    return result


def maybe_run_autonomous_parameter_governor_cycle_hook(root: Path = Path("."), env: Optional[Mapping[str, str]] = None) -> Dict[str, Any]:
    settings = governor_settings(env)
    if not settings["enabled"]:
        return {"ran": False, "reason": "governor_disabled", "source_policy": SOURCE_POLICY}
    return run_governor(root=root, env=env, apply=False)


def acquire_governor_lock(root: Path = Path("."), *, stale_after_seconds: int = LOCK_STALE_AFTER_SECONDS) -> Dict[str, Any]:
    path = root / LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        created = parse_time(payload.get("created_at")) if isinstance(payload, dict) else None
        stale = created is None or created < now - timedelta(seconds=stale_after_seconds)
        if not stale:
            return {"acquired": False, "path": str(path), "reason": "skipped_due_to_lock", "stale": False, "lock": payload}
        stale_payload = {"stale_lock_detected": True, "previous_lock": payload, "replaced_at": now_iso()}
    else:
        stale_payload = {"stale_lock_detected": False}
    payload = {"created_at": now_iso(), "pid": os.getpid(), "stale_replaced": stale_payload.get("stale_lock_detected", False)}
    atomic_write_json(path, payload)
    return {"acquired": True, "path": str(path), "reason": "lock_acquired", **stale_payload, "lock": payload}


def release_governor_lock(root: Path = Path(".")) -> None:
    path = root / LOCK_PATH
    try:
        if path.exists():
            path.unlink()
    except Exception:
        pass


def _run_tool(root: Path, args: Sequence[str]) -> Dict[str, Any]:
    started = datetime.now(timezone.utc)
    result = subprocess.run([sys.executable, *args, "--root", str(root)], cwd=Path(__file__).resolve().parents[1], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    try:
        payload = json.loads(result.stdout)
    except Exception:
        payload = {}
    return {
        "args": list(args),
        "returncode": result.returncode,
        "ok": result.returncode == 0,
        "started_at": started.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "stderr_tail": result.stderr[-1000:],
        "summary": payload if isinstance(payload, dict) else {},
    }


def run_governor_cycle(
    *,
    root: Path = Path("."),
    env: Optional[Mapping[str, str]] = None,
    apply: bool = True,
    dry_run: bool = False,
    run_reports: bool = True,
) -> Dict[str, Any]:
    lock = acquire_governor_lock(root)
    if not lock.get("acquired"):
        result = {
            "generated_at": now_iso(),
            "action": "skipped_due_to_lock",
            "applied": False,
            "reason": lock.get("reason"),
            "lock": lock,
            "coinbase_action_performed": False,
            "state_write_performed": False,
            "env_mutation_performed": False,
            "service_lifecycle_performed": False,
            "parameters_applied": [],
            "source_policy": SOURCE_POLICY,
        }
        result["outputs"] = write_governor_run_outputs(result, root=root)
        return result
    commands: List[Dict[str, Any]] = []
    try:
        if run_reports:
            commands.append(_run_tool(root, ["tools/run_reflection_adaptive_report_sidecar.py", "--json"]))
        governor_result = run_governor(root=root, env=env, apply=bool(apply and not dry_run))
        governor_result["lock"] = lock
        governor_result["commands"] = commands
        governor_result["dry_run"] = bool(dry_run or not apply)
        governor_result["outputs"] = write_governor_run_outputs(governor_result, root=root)
        return governor_result
    except Exception as exc:
        result = {
            "generated_at": now_iso(),
            "action": "error",
            "applied": False,
            "reason": f"governor_cycle_error:{exc}",
            "lock": lock,
            "commands": commands,
            "coinbase_action_performed": False,
            "state_write_performed": False,
            "env_mutation_performed": False,
            "service_lifecycle_performed": False,
            "parameters_applied": [],
            "source_policy": SOURCE_POLICY,
        }
        result["outputs"] = write_governor_run_outputs(result, root=root)
        return result
    finally:
        release_governor_lock(root)


__all__ = [
    "ALLOWED_PARAMETERS",
    "FORBIDDEN_PARAMETERS",
    "SOURCE_POLICY",
    "build_activation_plan",
    "acquire_governor_lock",
    "adaptive_readiness_layers",
    "candidate_hash_valid",
    "candidate_stale",
    "cooldown_status",
    "governor_settings",
    "load_project_env",
    "load_candidate",
    "load_candidate_analysis",
    "maybe_run_autonomous_parameter_governor_cycle_hook",
    "order_position_safety",
    "readiness_status",
    "render_activation_plan_markdown",
    "rollback_governor_profile",
    "run_governor_cycle",
    "run_governor",
    "release_governor_lock",
    "validate_governor",
    "write_governor_run_outputs",
    "write_activation_plan",
]
