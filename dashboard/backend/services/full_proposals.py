"""Full Parameter Proposals — comprehensive view of every known parameter.

Merges data from all available sources and presents every parameter in the
known universe, even if there is no active proposal.

Sources (all read-only):
- state/approved_parameter_profile.json         active runtime values
- state/approved_parameter_profile.candidate*.json  candidate profiles
- reports/growbot_river/growbot-river-learning-latest.json  proposals + diagnostics
- reports/growbot_river/growbot-river-governor-bridge-status-latest.json  governor state
- reports/parameter_optimization/shadow-outcome-accelerator-latest.json  shadow evidence counts

Output fields per parameter (task spec §5):
  name, current_value, proposed_value, proposed_delta, direction, confidence,
  evidence_count, source, owner, active_in_runtime, consumed_by_runtime,
  visible_in_approved_profile, activation_route, status, blockers,
  regime, ticker_scope, last_updated, safety_note, rollback_note,
  shadow_evidence_count, shadow_sufficient

Never writes. Never calls Coinbase. Never calls run_governor(apply=True).
"""
from __future__ import annotations

from typing import Any

from dashboard.backend import cache
from dashboard.backend.config import PROJECT_ROOT as _ROOT
from dashboard.backend.services.util import read_json_file

# ---------------------------------------------------------------------------
# Comprehensive parameter universe (task spec §6)
# ---------------------------------------------------------------------------

_PARAMETER_META: dict[str, dict] = {
    # Sizing / exposure
    "DEFAULT_QUOTE_SIZE_USDC": {
        "family": "sizing",
        "owner": "bot_config",
        "description": "Default quote size per order (USDC)",
        "safety_class": "sizing",
    },
    "MIN_LIVE_ORDER_QUOTE_USDC": {
        "family": "sizing",
        "owner": "bot_config",
        "description": "Minimum live order quote size (USDC)",
        "safety_class": "sizing",
    },
    "MAX_NOTIONAL_USD": {
        "family": "sizing",
        "owner": "bot_config",
        "description": "Maximum notional exposure per position (USD)",
        "safety_class": "exposure",
    },
    "AUTONOMOUS_MAX_ORDER_QUOTE": {
        "family": "sizing",
        "owner": "governor",
        "description": "Maximum quote size for autonomous orders (USDC)",
        "safety_class": "sizing",
    },
    "PHASE_C_MAX_ORDER_QUOTE": {
        "family": "sizing",
        "owner": "governor",
        "description": "Maximum quote size for C4.3 entry orders (USDC)",
        "safety_class": "sizing",
    },
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE": {
        "family": "sizing",
        "owner": "governor",
        "description": "Maximum quote size for D3 exit orders (USDC)",
        "safety_class": "sizing",
    },
    "AUTONOMOUS_MAX_OPEN_ORDERS": {
        "family": "sizing",
        "owner": "governor",
        "description": "Maximum open autonomous orders",
        "safety_class": "exposure",
    },
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": {
        "family": "sizing",
        "owner": "governor",
        "description": "Maximum new autonomous orders per cycle",
        "safety_class": "exposure",
    },
    "MAX_OPEN_POSITIONS": {
        "family": "sizing",
        "owner": "governor",
        "description": "Maximum simultaneous open positions",
        "safety_class": "exposure",
    },
    # Spread / risk / edge
    "MAX_SPREAD_PCT": {
        "family": "risk",
        "owner": "governor",
        "description": "Maximum allowed spread (%) before skipping entry",
        "safety_class": "liquidity_guard",
    },
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": {
        "family": "risk",
        "owner": "governor",
        "description": "Minimum net edge (%) required to execute the trade plan",
        "safety_class": "edge_filter",
    },
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": {
        "family": "risk",
        "owner": "governor",
        "description": "Minimum reward-to-fee ratio for a trade plan to pass",
        "safety_class": "edge_filter",
    },
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": {
        "family": "risk",
        "owner": "governor",
        "description": "Minimum reward-to-risk ratio for a trade plan to pass",
        "safety_class": "edge_filter",
    },
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": {
        "family": "risk",
        "owner": "governor",
        "description": "Maximum exit target distance (%) from mid-price",
        "safety_class": "exit_economics",
    },
    # Judge / gate
    "JUDGE_MIN_GATE_CONFIDENCE": {
        "family": "judge",
        "owner": "bot_config",
        "description": "Minimum entry-gate confidence to proceed to full analysis",
        "safety_class": "gate_threshold",
    },
    "JUDGE_MIN_SYNTH_CONFIDENCE": {
        "family": "judge",
        "owner": "bot_config",
        "description": "Minimum synthesizer confidence for judge approval",
        "safety_class": "gate_threshold",
    },
    "JUDGE_MIN_BULL_SCORE": {
        "family": "judge",
        "owner": "bot_config",
        "description": "Minimum bull score required for BUY approval",
        "safety_class": "gate_threshold",
    },
    "JUDGE_MAX_BEAR_SCORE": {
        "family": "judge",
        "owner": "bot_config",
        "description": "Maximum allowed bear score for BUY approval",
        "safety_class": "gate_threshold",
    },
    "ENABLE_EXPENSIVE_JUDGE_GATE": {
        "family": "judge",
        "owner": "bot_config",
        "description": "Flag: enables the expensive GPT-5.5 judge gate",
        "safety_class": "cost_gate",
    },
}

# Governor allowlist — parameters the autonomous governor is permitted to tune
_GOVERNOR_ALLOWLIST = {
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "MAX_SPREAD_PCT",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "AUTONOMOUS_MAX_OPEN_ORDERS",
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE",
    "MAX_OPEN_POSITIONS",
    "DEFAULT_QUOTE_SIZE_USDC",
    "PHASE_C_MAX_ORDER_QUOTE",
    "MAX_NOTIONAL_USD",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE",
}

_CATEGORY_PREFIXES = [
    ("PHASE_D2", "D2 planner / exit economics"),
    ("PHASE_D3", "D3 controlled exit"),
    ("PHASE_C", "C4.3 entry"),
    ("JUDGE", "Judge / confidence gate"),
    ("MAX_SPREAD", "Liquidity guard"),
    ("AUTONOMOUS_MAX", "Autonomy caps"),
    ("MAX_OPEN", "Exposure caps"),
    ("MAX_NOTIONAL", "Exposure caps"),
    ("DEFAULT_QUOTE_SIZE", "Sizing"),
    ("EXIT_TARGET", "D3 controlled exit"),
    ("MIN_LIVE_ORDER", "Sizing"),
]


def _category(name: str) -> str:
    for prefix, label in _CATEGORY_PREFIXES:
        if name.startswith(prefix):
            return label
    return "Other"


def _clean_regimes(regimes: list | None) -> list[str]:
    if not regimes:
        return []
    seen: set = set()
    result = []
    for r in (regimes or []):
        if not isinstance(r, str) or "{" in r or len(r) > 60:
            continue
        if r not in seen:
            seen.add(r)
            result.append(r)
    return result[:10]


def _compute_full_proposals() -> dict:
    approved_raw = read_json_file(_ROOT / "state" / "approved_parameter_profile.json", {})
    approved_params: dict = {}
    if isinstance(approved_raw, dict):
        approved_params = approved_raw.get("parameters") or approved_raw.get("parameter_values") or {}

    candidate_raw = read_json_file(
        _ROOT / "state" / "approved_parameter_profile.candidate.start_optimized_v1.json", {}
    )
    candidate_params: dict = {}
    candidate_safe_now: bool = False
    candidate_reason: str = ""
    if isinstance(candidate_raw, dict):
        candidate_params = candidate_raw.get("parameters") or candidate_raw.get("parameter_values") or {}
        candidate_safe_now = bool(candidate_raw.get("safe_to_activate_now"))
        candidate_reason = str(candidate_raw.get("safe_to_activate_now_reason") or "")

    river_raw = read_json_file(
        _ROOT / "reports" / "growbot_river" / "growbot-river-learning-latest.json", {}
    )
    river_proposals: list[dict] = []
    if isinstance(river_raw, dict):
        river_proposals = river_raw.get("proposals") or []

    gov_raw = read_json_file(
        _ROOT / "reports" / "growbot_river" / "growbot-river-governor-bridge-status-latest.json", {}
    )
    gov_candidate: dict = {}
    gov_proposed_param: str = ""
    gov_why_not_applied: list[str] = []
    if isinstance(gov_raw, dict):
        gov_candidate = gov_raw.get("top_parameter_candidate") or {}
        gov_info = gov_raw.get("governor") or {}
        gov_proposed_param = str(gov_info.get("proposed_parameter") or "")
        gov_why_not_applied = gov_info.get("why_not_applied") or []

    shadow_raw = read_json_file(
        _ROOT / "reports" / "parameter_optimization" / "shadow-outcome-accelerator-latest.json", {}
    )
    shadow_total: int = 0
    shadow_usable: int = 0
    shadow_sufficient: bool = False
    if isinstance(shadow_raw, dict):
        shadow_total = int(shadow_raw.get("total_shadow_decisions") or 0)
        shadow_usable = int(shadow_raw.get("usable_evidence_count") or 0)
        shadow_sufficient = bool(shadow_raw.get("sufficient_for_optimization"))

    # Index river proposals and governor candidate
    river_by_param: dict[str, dict] = {
        p.get("parameter"): p for p in river_proposals if isinstance(p, dict) and p.get("parameter")
    }
    gov_param_name: str = gov_candidate.get("parameter") or gov_proposed_param

    # All known parameter names
    all_names: set[str] = (
        set(_PARAMETER_META.keys())
        | set(approved_params.keys())
        | set(candidate_params.keys())
        | set(river_by_param.keys())
        | ({gov_param_name} if gov_param_name else set())
    )

    rows: list[dict] = []
    for name in sorted(all_names):
        meta = _PARAMETER_META.get(name, {})
        current_val = approved_params.get(name)
        candidate_val = candidate_params.get(name)
        river_p: dict = river_by_param.get(name, {})
        is_gov_candidate = name == gov_param_name

        proposed_val: Any = None
        proposed_delta: Any = None
        direction: str = "keep"
        confidence: float | None = None
        evidence_count: int | None = None
        source: str = "no_proposal"
        blockers: list[str] = []
        rollback_note: str = ""
        activation_route: str = ""
        regimes: list[str] = []
        last_updated: str | None = None
        safety_note: str = ""
        status: str = "no_proposal"

        if river_p:
            proposed_val = river_p.get("candidate_value")
            direction = str(river_p.get("direction") or "keep")
            confidence = river_p.get("confidence")
            evidence_count = river_p.get("evidence_count")
            blockers = river_p.get("blockers") or []
            rollback_note = " → ".join(river_p.get("rollback") or [])
            activation_route = str(river_p.get("activation_route") or "")
            regimes = _clean_regimes(river_p.get("regimes") or [])
            source = "growbot_river"
            last_updated = river_raw.get("generated_at") if isinstance(river_raw, dict) else None
            if river_p.get("safe_to_activate_now"):
                status = "safe_to_activate"
            elif blockers:
                status = "blocked"
            else:
                status = "needs_more_evidence"

        if is_gov_candidate and gov_candidate:
            proposed_val = proposed_val or gov_candidate.get("candidate_value")
            direction = direction if direction != "keep" else str(gov_candidate.get("direction") or "keep")
            confidence = confidence or gov_candidate.get("confidence")
            evidence_count = evidence_count or gov_candidate.get("evidence_count")
            regimes = regimes or _clean_regimes(gov_candidate.get("regimes_seen") or [])
            rollback_note = rollback_note or " → ".join(gov_candidate.get("rollback") or [])
            activation_route = activation_route or str(gov_candidate.get("activation_route") or "")
            if gov_why_not_applied:
                blockers = blockers or gov_why_not_applied
            source = "governor" if not river_p else source

        if candidate_val is not None and candidate_val != current_val:
            proposed_val = proposed_val or candidate_val
            if source == "no_proposal":
                source = "candidate_profile"
                status = "safe_to_activate" if candidate_safe_now else "needs_more_evidence"

        if current_val is not None and proposed_val is not None:
            try:
                proposed_delta = round(float(proposed_val) - float(str(current_val).rstrip("%")), 8)
            except (ValueError, TypeError):
                proposed_delta = None

        rows.append({
            "name": name,
            "category": _category(name),
            "family": meta.get("family", "other"),
            "description": meta.get("description", ""),
            "owner": meta.get("owner") or ("governor" if name in _GOVERNOR_ALLOWLIST else "bot_config"),
            "safety_class": meta.get("safety_class", ""),
            # Values
            "current_value": current_val,
            "proposed_value": proposed_val,
            "proposed_delta": proposed_delta,
            "direction": direction,
            "confidence": confidence,
            "evidence_count": evidence_count,
            # Runtime wiring
            "active_in_runtime": current_val is not None,
            "consumed_by_runtime": current_val is not None,
            "visible_in_approved_profile": current_val is not None,
            "in_governor_allowlist": name in _GOVERNOR_ALLOWLIST,
            # Proposal metadata
            "source": source,
            "status": status,
            "activation_route": activation_route or (
                "governor_and_approved_profile" if name in _GOVERNOR_ALLOWLIST else "manual_env_only"
            ),
            "blockers": blockers,
            "regimes_seen": regimes,
            "rollback_note": rollback_note,
            "safety_note": safety_note,
            "last_updated": last_updated,
            # Shadow evidence linkage
            "shadow_evidence_total": shadow_total,
            "shadow_evidence_usable": shadow_usable,
            "shadow_sufficient": shadow_sufficient,
            # Governor visibility
            "governor_is_watching": is_gov_candidate,
            "candidate_profile_value": candidate_val,
        })

    pending_count = sum(1 for r in rows if r["status"] not in ("no_proposal",))
    blocked_count = sum(1 for r in rows if r["status"] == "blocked")

    return {
        "generated_at": (river_raw.get("generated_at") if isinstance(river_raw, dict) else None),
        "parameters": rows,
        "total_parameters": len(rows),
        "parameters_with_proposal": pending_count,
        "parameters_blocked": blocked_count,
        "parameters_no_proposal": sum(1 for r in rows if r["status"] == "no_proposal"),
        "parameters_in_governor_allowlist": sum(1 for r in rows if r["in_governor_allowlist"]),
        "shadow_evidence_total": shadow_total,
        "shadow_evidence_usable": shadow_usable,
        "shadow_sufficient_for_optimization": shadow_sufficient,
    }


def get_full_parameter_proposals() -> dict:
    return cache.get_or_compute("full_parameter_proposals", _compute_full_proposals, ttl_seconds=30)
