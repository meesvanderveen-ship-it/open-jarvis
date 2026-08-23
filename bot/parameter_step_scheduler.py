"""Phase-bounded scheduling for report-only parameter proposals."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence, Tuple

from bot.learnable_parameter_registry import LearnableParameter, get_parameter, load_current_values


PHASES: Dict[str, Dict[str, float]] = {
    "coarse_tuning": {"min_step_pct": 5.0, "max_step_pct": 15.0, "max_parameters": 5},
    "stabilization": {"min_step_pct": 2.0, "max_step_pct": 5.0, "max_parameters": 3},
    "fine_tuning": {"min_step_pct": 0.25, "max_step_pct": 2.0, "max_parameters": 1},
}
NON_MARKET_REGIMES = {"", "unknown", "backtest", "historical", "none", "null"}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return default
    return value if value == value and value not in (float("inf"), float("-inf")) else default


def _history_directions(history: Sequence[Mapping[str, Any]], parameter: str) -> List[str]:
    directions: List[str] = []
    for row in history:
        if not isinstance(row, Mapping):
            continue
        # A recalculation or model-state migration is not new evidence. Legacy
        # rows without this marker are deliberately ignored rather than being
        # allowed to promote a phase on repeated identical data.
        if int(_as_float(row.get("new_memory_episodes"))) <= 0:
            continue
        proposals = row.get("proposals")
        if not isinstance(proposals, list):
            continue
        for proposal in proposals:
            if isinstance(proposal, Mapping) and str(proposal.get("parameter") or "") == parameter:
                direction = str(proposal.get("direction") or "")
                if direction in {"loosen", "tighten"}:
                    directions.append(direction)
    return directions


def _stable_direction_count(history: Sequence[Mapping[str, Any]], parameter: str, direction: str) -> int:
    seen = 0
    for value in reversed(_history_directions(history, parameter)):
        if value != direction:
            break
        seen += 1
    return seen


def choose_tuning_phase(
    *,
    episode_count: int,
    distinct_regime_count: int,
    history: Sequence[Mapping[str, Any]],
    signals: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Choose a search phase without interpreting a phase as approval.

    Coarse tuning is the start state.  Stabilization requires repeated
    directional evidence across regimes; fine tuning additionally requires a
    previously stable baseline.
    """
    stable_runs = 0
    for signal in signals:
        parameter = str(signal.get("parameter") or "")
        direction = str(signal.get("direction") or "")
        stable_runs = max(stable_runs, _stable_direction_count(history, parameter, direction))
    if episode_count >= 500 and distinct_regime_count >= 3 and stable_runs >= 5:
        phase = "fine_tuning"
    elif episode_count >= 120 and distinct_regime_count >= 2 and stable_runs >= 3:
        phase = "stabilization"
    else:
        phase = "coarse_tuning"
    return {
        "phase": phase,
        "episode_count": int(episode_count),
        "distinct_regime_count": int(distinct_regime_count),
        "max_observed_prior_stable_direction_runs": stable_runs,
        "phase_rules": {
            "coarse_tuning": "start phase; broad bounded search only",
            "stabilization": "requires >=120 episodes, >=2 regimes and 3 stable proposal runs",
            "fine_tuning": "requires >=500 episodes, >=3 regimes and 5 stable proposal runs",
        },
    }


def _step_pct(confidence: float, phase: str) -> float:
    rules = PHASES[phase]
    confidence = max(0.0, min(1.0, confidence))
    return round(rules["min_step_pct"] + (rules["max_step_pct"] - rules["min_step_pct"]) * confidence, 4)


def _candidate_value(definition: LearnableParameter, current: float, direction: str, step_pct: float) -> float:
    is_loosen = direction == "loosen"
    increase = definition.loosen_change == "increase" if is_loosen else definition.loosen_change != "increase"
    raw = current * (1.0 + step_pct / 100.0) if increase else current * (1.0 - step_pct / 100.0)
    bounded = max(definition.minimum, min(definition.maximum, raw))
    if definition.unit in {"count", "minutes", "hours", "score"}:
        bounded = round(bounded)
    return round(bounded, 8)


def _reason(signal: Mapping[str, Any]) -> str:
    reasons = signal.get("reasons")
    if isinstance(reasons, list) and reasons:
        return "; ".join(str(item) for item in reasons[:3])
    return str(signal.get("reason") or "online reward evidence")


def schedule_parameter_steps(
    signals: Iterable[Mapping[str, Any]],
    *,
    root: Any = ".",
    episode_count: int,
    regimes: Iterable[str],
    history: Sequence[Mapping[str, Any]] = (),
) -> Dict[str, Any]:
    """Turn incremental signals into bounded, report-only proposal rows."""
    cleaned = [dict(signal) for signal in signals if isinstance(signal, Mapping)]
    distinct_regimes = sorted({
        str(regime).strip().lower().replace(" ", "_")
        for regime in regimes
        if str(regime or "").strip().lower().replace(" ", "_") not in NON_MARKET_REGIMES
    })
    decision = choose_tuning_phase(
        episode_count=episode_count,
        distinct_regime_count=len(distinct_regimes),
        history=history,
        signals=cleaned,
    )
    phase = str(decision["phase"])
    current_values = load_current_values(Path(root))
    proposals: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    ordered = sorted(cleaned, key=lambda item: (_as_float(item.get("confidence")), _as_float(item.get("evidence_count"))), reverse=True)
    seen = set()
    for signal in ordered:
        parameter = str(signal.get("parameter") or "")
        direction = str(signal.get("direction") or "")
        definition = get_parameter(parameter)
        if parameter in seen or definition is None or direction not in {"loosen", "tighten"}:
            continue
        seen.add(parameter)
        confidence = max(0.0, min(1.0, _as_float(signal.get("confidence"))))
        evidence_count = int(_as_float(signal.get("evidence_count")))
        stable_runs = _stable_direction_count(history, parameter, direction)
        blockers: List[str] = []
        if evidence_count < 3:
            blockers.append("insufficient_directional_observations")
        if confidence < 0.55:
            blockers.append("low_online_learning_confidence")
        if phase in {"stabilization", "fine_tuning"} and stable_runs < (3 if phase == "stabilization" else 5):
            blockers.append("direction_not_stable_across_prior_learning_cycles")
        if phase == "fine_tuning" and len(distinct_regimes) < 3:
            blockers.append("insufficient_regime_diversity_for_fine_tuning")
        step = _step_pct(confidence, phase)
        current = current_values.get(parameter, definition.default)
        candidate = _candidate_value(definition, current, direction, step)
        row = {
            "parameter": parameter,
            "direction": direction,
            "confidence": round(confidence, 4),
            "suggested_step_pct": step,
            "phase": phase,
            "reason": _reason(signal),
            "current_value": current,
            "candidate_value": candidate,
            "change_pct": round(((candidate - current) / current) * 100.0, 4) if current else 0.0,
            "evidence_count": evidence_count,
            "regimes": distinct_regimes,
            "direction_stable_runs": stable_runs,
            "activation_route": definition.activation_route(),
            "approved_profile_supported": definition.activation_route() in {"current_governor_and_approved_profile", "approved_profile_only_manual_governance"},
            "requires_operator_review": True,
            "safe_to_activate_now": False,
            "parameter_mutation_allowed": False,
            "evidence_requirements": list(definition.evidence_requirements),
            "rollback": list(definition.rollback),
            "blockers": blockers,
        }
        if blockers:
            blocked.append(row)
        else:
            proposals.append(row)
        if len(proposals) >= int(PHASES[phase]["max_parameters"]):
            break
    return {
        "phase_decision": decision,
        "phase": phase,
        "phase_limits": dict(PHASES[phase]),
        "proposals": proposals,
        "blocked_proposals": blocked,
        "proposal_count": len(proposals),
        "blocked_proposal_count": len(blocked),
        "safety_policy": {
            "report_only": True,
            "parameter_mutation_allowed": False,
            "execution_authority": False,
            "approved_profile_route_required": True,
        },
    }


__all__ = ["NON_MARKET_REGIMES", "PHASES", "choose_tuning_phase", "schedule_parameter_steps"]
