#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.atomic_io import atomic_write_json
from bot.config import BotConfig
from tools.build_live_learning_sidecar import build_live_learning_sidecar_report

DEFAULT_OUTPUT = Path("reports/live_learning/balanced-start-profile-candidate.json")
ALLOWED_KEYS = {
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "AUTONOMOUS_MAX_OPEN_ORDERS",
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE",
    "MAX_SPREAD_PCT",
    "PHASE_C_MAX_ORDER_QUOTE",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
}
OPTIONAL_REVIEW_KEYS = {
    "NO_FILL_TIMEOUT_MINUTES",
    "CANCEL_REPLACE_MIN_AGE_MINUTES",
    "ENTRY_THRESHOLD_ADJUSTMENT",
    "ALLOWED_TICKERS",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _hash_candidate(candidate: Dict[str, Any]) -> str:
    canonical = json.dumps(candidate, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _profile_payload(
    params: Dict[str, Any],
    *,
    rationale: str,
    strict: list[str],
    loose: list[str],
    benefit: str,
    risk: str,
    review_only: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    approved_json = {"profile_name": "balanced_start_profile", "profile_version": 1, "parameters": params}
    return {
        "candidate_params": params,
        "review_only_parameters": review_only or {},
        "rationale": rationale,
        "too_strict_signals": strict,
        "too_loose_signals": loose,
        "expected_benefit": benefit,
        "risk": risk,
        "activation_requirements": [
            "human review",
            "write state/approved_parameter_profile.json only in separate ACK-gated step",
            "set ENABLE_APPROVED_PARAMETER_PROFILE=true and exact APPROVED_PARAMETER_PROFILE_HASH later",
            "keep learning-to-execution direct bridge disabled",
        ],
        "hash": _hash_candidate(params),
        "approved_profile_json": approved_json,
    }


def _current_baseline(cfg: BotConfig) -> Dict[str, Any]:
    return {
        "AUTONOMOUS_MAX_ORDER_QUOTE": str(cfg.autonomous_max_order_quote),
        "AUTONOMOUS_MAX_OPEN_ORDERS": str(cfg.autonomous_max_open_orders),
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "MAX_SPREAD_PCT": str(cfg.max_spread_pct),
        "PHASE_C_MAX_ORDER_QUOTE": str(cfg.phase_c_max_order_quote),
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": str(cfg.phase_d3_max_exit_order_quote),
        "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": str(cfg.exit_target_max_distance_from_mid_pct),
    }


def build_balanced_start_parameter_profile_candidate(*, root: str | Path = ".", generated_at: Optional[str] = None) -> Dict[str, Any]:
    project_root = Path(root)
    cfg = BotConfig()
    baseline = _current_baseline(cfg)
    sidecar = build_live_learning_sidecar_report(root=project_root, generated_at=generated_at)
    decision_report = _load_json(project_root / "logs/decision_outcome_report.json")
    missed = len(decision_report.get("missed_opportunities") or []) if isinstance(decision_report, dict) else 0
    false_positive = len(decision_report.get("false_positive_plans") or []) if isinstance(decision_report, dict) else 0
    execution_labels = ((sidecar.get("execution_outcomes") or {}).get("label_counts") or {})
    no_fill = int(execution_labels.get("missed_fill_opportunity") or 0)
    strict = []
    loose = []
    if missed >= 3:
        strict.append("multiple_wait_or_skip_missed_opportunities")
    if no_fill:
        strict.append("missed_fill_opportunity_seen")
    if false_positive:
        loose.append("false_positive_plans_seen")
    evidence_missing = []
    if not decision_report:
        evidence_missing.append("decision_outcome_report_missing")
    if not execution_labels:
        evidence_missing.append("execution_outcomes_sparse_or_missing")

    conservative = dict(baseline)
    conservative.update({
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_MAX_OPEN_ORDERS": str(min(int(baseline.get("AUTONOMOUS_MAX_OPEN_ORDERS") or 1), 3)),
        "MAX_SPREAD_PCT": "0.0060",
    })
    conservative_review_only = {
        "NO_FILL_TIMEOUT_MINUTES": "90",
        "CANCEL_REPLACE_MIN_AGE_MINUTES": "120",
        "ENTRY_THRESHOLD_ADJUSTMENT": "0",
    }
    moderate = dict(conservative)
    moderate.update({
        "AUTONOMOUS_MAX_ORDER_QUOTE": str(min(max(float(baseline["AUTONOMOUS_MAX_ORDER_QUOTE"]), 20.0), 25.0)),
        "PHASE_C_MAX_ORDER_QUOTE": str(min(max(float(baseline["PHASE_C_MAX_ORDER_QUOTE"]), 20.0), 25.0)),
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": str(min(max(float(baseline["PHASE_D3_MAX_EXIT_ORDER_QUOTE"]), 20.0), 25.0)),
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "MAX_SPREAD_PCT": "0.0070",
    })
    moderate_review_only = {
        "NO_FILL_TIMEOUT_MINUTES": "60",
        "CANCEL_REPLACE_MIN_AGE_MINUTES": "90",
        "ENTRY_THRESHOLD_ADJUSTMENT": "-small_step_review_only",
    }
    profiles = {
        "baseline_current": _profile_payload(
            baseline,
            rationale="Exact current safe baseline.",
            strict=strict,
            loose=loose,
            benefit="No parameter risk.",
            risk="May preserve missed-fill/no-fill friction.",
        ),
        "balanced_candidate_conservative": _profile_payload(
            conservative,
            rationale="Keeps size/order count stable and only improves no-fill review timing.",
            strict=strict,
            loose=loose,
            benefit="Better long-run observation of order placement without increasing size.",
            risk="Still may be too conservative; optional timing keys require separate whitelist approval before activation.",
            review_only=conservative_review_only,
        ),
        "balanced_candidate_moderate": _profile_payload(
            moderate,
            rationale="Moderate review candidate inside safe bands: max_new_orders_per_cycle remains 1, max_open_orders <= 3, spread <= 0.0080.",
            strict=strict,
            loose=loose,
            benefit="Could reduce missed fills while staying bounded.",
            risk="Requires stronger post-run evidence; not safe to auto-activate from WATCH sidecar.",
            review_only=moderate_review_only,
        ),
    }
    sidecar_watch = sidecar.get("classification") == "WATCH"
    return {
        "phase": "balanced_start_parameter_profile_candidate_v2",
        "generated_at": generated_at or _now_iso(),
        "classification": "WATCH" if sidecar_watch or strict or loose or evidence_missing else "OK",
        "profile_name": "balanced_start_profile_candidate",
        "profile_version": 2,
        "basis": {
            "decision_outcomes_loaded": bool(decision_report),
            "live_learning_sidecar_classification": sidecar.get("classification"),
            "missed_opportunities": missed,
            "false_positive_plans": false_positive,
            "missed_fill_opportunity": no_fill,
            "evidence_missing": evidence_missing,
        },
        "current_baseline": baseline,
        "candidate_profile": conservative,
        "profiles": profiles,
        "allowed_keys_only": set(conservative).issubset(ALLOWED_KEYS),
        "risk_assessment": {
            "no_size_aggression_in_conservative": True,
            "max_new_orders_per_cycle_remains_one": True,
            "universe_expansion": False,
            "report_only": True,
        },
        "too_strict_signals": strict,
        "too_loose_signals": loose,
        "recommended_operator_action": "review_candidate_human_only",
        "safe_to_activate_now": False,
        "required_ack": "CREATE_APPROVED_PARAMETER_PROFILE_WITH_HASH_SEPARATE_PROMPT",
        "hash_to_approve": profiles["balanced_candidate_conservative"]["hash"],
        "read_only": True,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "env_write_performed": False,
        "approved_parameter_profile_written": False,
    }


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    target = path.resolve()
    allowed = (Path.cwd() / "reports/live_learning").resolve()
    if allowed not in [target.parent, *target.parents]:
        raise SystemExit("Refusing to write outside reports/live_learning")
    atomic_write_json(target, payload)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Propose report-only balanced start parameter profile candidates.")
    parser.add_argument("--json-out", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--root", default=".")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_balanced_start_parameter_profile_candidate(root=args.root)
    _write_json(Path(args.json_out), report)
    print(json.dumps({"status": "balanced_start_profile_candidate_written", "json_out": args.json_out, "classification": report["classification"], "safe_to_activate_now": report["safe_to_activate_now"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["DEFAULT_OUTPUT", "build_balanced_start_parameter_profile_candidate", "main", "parse_args"]
