"""Adaptive learning intelligence: per-parameter evidence aggregation.

Reads existing, already-vetted read-only evidence sources --
``state/decision_outcomes.json``, ``logs/execution_outcomes.jsonl``,
``state/trade_reflections.jsonl``, ``state/opportunity_memory.json`` -- and
turns them into:

  * per-parameter evidence: how much, what direction (loosen/tighten/keep),
    which regimes/tickers, an overfit-risk read and a maturity tier.
  * missed-opportunity learning: wait/watch/skip decisions that turned out
    to be wrong.
  * wait-decision quality: how often waiting was actually the right call.
  * learning depth/coverage: how broad the evidence base is overall.

This module makes no LLM calls, no Coinbase calls and writes nothing -- it
is pure read + aggregate. Every proposal it can produce tops out at
"operator_review_candidate"; see ``bot/parameter_proposal_scoring.py`` for
why "apply_ready_candidate" is intentionally unreachable from here. The
existing ``autonomous_parameter_governor`` ACK flow and
``approved_parameter_profile`` gate remain the only route by which any
parameter value can ever actually change.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from bot.learnable_parameter_registry import parameter_definitions
from bot.overfit_risk_model import (
    compute_overfit_risk,
    direction_stability_score,
    parse_timestamp,
    regime_coverage,
    ticker_coverage,
    time_split_halves,
)
from bot.parameter_proposal_scoring import (
    BACKTEST_MIN_REGIMES,
    SHADOW_MIN_EVIDENCE,
    WALK_FORWARD_MIN_TICKERS,
    evaluate_proposal,
    why_not_apply_ready,
)

SCHEMA_VERSION = "adaptive_learning_intelligence_v1"

STATE_DECISION_OUTCOMES = Path("state/decision_outcomes.json")
LOG_EXECUTION_OUTCOMES = Path("logs/execution_outcomes.jsonl")
STATE_TRADE_REFLECTIONS = Path("state/trade_reflections.jsonl")
STATE_OPPORTUNITY_MEMORY = Path("state/opportunity_memory.json")
STATE_APPROVED_PROFILE = Path("state/approved_parameter_profile.json")

# The canonical GrowBot/River learning cycle output (bot/growbot_learning_adapter.py
# + bot/river_online_parameter_learner.py via tools/run_growbot_river_learning_cycle.py).
# This module is an enrichment layer on top of that pipeline, not a second one: every
# parameter this module can map is cross-checked against this report, and that report's
# own confidence/direction/blockers are surfaced verbatim wherever it already has an
# opinion. See bot/growbot_river_readiness.py for the upstream readiness gates.
GROWBOT_RIVER_LEARNING_REPORT_PATH = Path("reports/growbot_river/growbot-river-learning-latest.json")

WAITLIKE_CATEGORIES = {"wait", "watch", "skip"}
ENTRYLIKE_CATEGORIES = {"approved_entry", "prepared_plan"}

LOOSEN_OUTCOME_LABELS = {"missed_opportunity"}
TIGHTEN_OUTCOME_LABELS = {"false_positive_plan"}
KEEP_OUTCOME_LABELS = {"correct_avoid", "correct_wait_or_neutral", "plan_follow_through"}

EXECUTION_LOOSEN_LABELS = {"missed_fill_opportunity", "market_would_have_been_better"}
EXECUTION_TIGHTEN_LABELS = {
    "bad_limit_execution",
    "bad_fill_after_breakdown",
    "bad_cancel",
    "bad_replace",
    "partial_fill_problem",
    "expired_too_late",
}
EXECUTION_KEEP_LABELS = {
    "good_limit_execution",
    "correct_no_fill",
    "avoided_bad_entry",
    "good_cancel",
    "good_replace",
    "partial_fill_good",
    "expired_correctly",
    "limit_better_than_market",
}

RELATIVE_BAND_FRACTION = 0.15
MIN_ABS_BAND = 1e-9
EFFECT_SIZE_FULL_SCALE_PCT = 0.03
LIVE_RELEVANCE_DECAY_DAYS = 90.0
TICKER_COVERAGE_FULL_SCALE = 4.0
PROPOSED_STEP_FRACTION = 0.02


@dataclass(frozen=True)
class ParameterEvidenceSpec:
    parameter: str
    evidence_source: str  # "decision_outcomes" | "execution_outcomes"
    state_field: str  # only used when evidence_source == "decision_outcomes"
    threshold_type: str  # "minimum" | "maximum"


# Deliberately explicit, inspectable mapping: which evidence field backs
# which learnable parameter, and whether the gate is a floor ("minimum") or
# a ceiling ("maximum"). Parameters not listed here either have a documented
# data gap (NO_MAPPING_PARAMETERS) or fall through to a generic
# "not wired up yet" result -- never a silent/fake proposal.
PARAMETER_EVIDENCE_SPECS: Tuple[ParameterEvidenceSpec, ...] = (
    ParameterEvidenceSpec("JUDGE_MIN_GATE_CONFIDENCE", "decision_outcomes", "confidence", "minimum"),
    ParameterEvidenceSpec("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "decision_outcomes", "expected_net_edge_pct", "minimum"),
    ParameterEvidenceSpec("PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "decision_outcomes", "reward_to_fee", "minimum"),
    ParameterEvidenceSpec("PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "decision_outcomes", "reward_to_risk", "minimum"),
    ParameterEvidenceSpec("MAX_SPREAD_PCT", "decision_outcomes", "spread_pct", "maximum"),
    ParameterEvidenceSpec("ORDERBOOK_ENTRY_MAX_DISTANCE_FROM_MID_PCT", "execution_outcomes", "", "maximum"),
    ParameterEvidenceSpec("EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT", "execution_outcomes", "", "maximum"),
)
_SPEC_BY_PARAMETER: Dict[str, ParameterEvidenceSpec] = {spec.parameter: spec for spec in PARAMETER_EVIDENCE_SPECS}

# execution_outcomes has no orderbook-distance value logged per order today,
# so these two parameters are label-only proxies: a buy-side execution_action
# stands in for entry distance, a sell-side one for exit distance. This is
# weaker evidence than a real numeric distance and is reported as such.
_EXECUTION_ONLY_PARAMETER_ACTIONS: Dict[str, frozenset] = {
    "ORDERBOOK_ENTRY_MAX_DISTANCE_FROM_MID_PCT": frozenset({"place_limit_buy"}),
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": frozenset({"place_limit_sell_reduce", "place_limit_sell_close"}),
}

# Parameters explicitly inspected and judged to have no structured
# evidence-to-outcome path yet. This is an honest data-gap statement, not a
# blocker: each entry doubles as the "next_data_needed" text shown in the
# dashboard.
NO_MAPPING_PARAMETERS: Dict[str, str] = {
    "DEFAULT_QUOTE_SIZE_USDC": (
        "No structured evidence source ties decision/execution outcomes to order size yet -- "
        "would need sizing recorded per outcome record to learn anything here."
    ),
    "AUTONOMOUS_MAX_ORDER_QUOTE": (
        "No structured evidence source ties decision/execution outcomes to this autonomy cap yet."
    ),
    "MAX_OPEN_POSITIONS": (
        "No 'blocked by open-position cap' event is logged anywhere yet; this cap's effect on "
        "missed opportunities is invisible to the learning layer until that event exists."
    ),
    "AUTONOMOUS_MAX_OPEN_ORDERS": (
        "No 'blocked by open-order cap' event is logged anywhere yet; this cap's effect is "
        "invisible to the learning layer until that event exists."
    ),
}

_GENERIC_NO_MAPPING_MESSAGE = (
    "Not yet wired into the adaptive learning evidence engine; treated as observed_signal with "
    "zero evidence until a dedicated evidence mapping is added for this parameter."
)


# ---------------------------------------------------------------------------
# Loaders -- all read-only, all defensive against missing/partial files.
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    if limit:
        lines = lines[-limit:]
    records: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            records.append(parsed)
    return records


def load_decision_outcome_records(root: Path) -> List[Dict[str, Any]]:
    data = _read_json(root / STATE_DECISION_OUTCOMES)
    records = data.get("records") if isinstance(data, dict) else None
    return records if isinstance(records, list) else []


def load_execution_outcome_records(root: Path, *, limit: int = 5000) -> List[Dict[str, Any]]:
    return _read_jsonl(root / LOG_EXECUTION_OUTCOMES, limit=limit)


def load_trade_reflection_records(root: Path, *, limit: int = 2000) -> List[Dict[str, Any]]:
    return _read_jsonl(root / STATE_TRADE_REFLECTIONS, limit=limit)


def load_opportunity_memory(root: Path) -> List[Dict[str, Any]]:
    data = _read_json(root / STATE_OPPORTUNITY_MEMORY)
    opportunities = data.get("opportunities") if isinstance(data, dict) else None
    return opportunities if isinstance(opportunities, list) else []


def load_current_parameter_values(root: Path) -> Dict[str, Any]:
    """Best-effort read of the live approved-profile values for display only.

    This intentionally bypasses the strict hash/enable validation in
    ``bot.approved_parameter_profile`` (which raises on a missing hash) --
    this module only ever displays a value, never activates one, so a
    malformed or absent profile should fall back to the registry default
    rather than raise.
    """
    data = _read_json(root / STATE_APPROVED_PROFILE)
    if isinstance(data, dict):
        params = data.get("parameters", data)
        if isinstance(params, dict):
            return params
    return {}


def load_growbot_river_learning_report(root: Path) -> Dict[str, Any]:
    """Best-effort read of the existing GrowBot/River learning-cycle report.

    Produced by ``tools/run_growbot_river_learning_cycle.py`` (which in turn
    calls ``bot/growbot_learning_adapter.py`` and
    ``bot/river_online_parameter_learner.py``). This module never regenerates
    it -- it only reads and cites the already-computed parameter_signals,
    proposals, blocked_proposals and River backend status.
    """
    data = _read_json(root / GROWBOT_RIVER_LEARNING_REPORT_PATH)
    return data if isinstance(data, dict) else {}


def river_backend_label(report: Mapping[str, Any]) -> str:
    """"native_sidecar" when the real River package answered, else "report_only"."""
    backend = report.get("river", {}) if isinstance(report.get("river"), Mapping) else {}
    backend = backend.get("backend") if isinstance(backend.get("backend"), Mapping) else {}
    return "native_sidecar" if backend.get("river_available") is True else "report_only"


def _growbot_river_cross_check_index(report: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Index the existing GrowBot/River report by parameter name for lookup.

    Returns ``{parameter: {"signal": ..., "proposal": ..., "blocked": ...}}``
    using whichever of the three the real pipeline already produced -- this
    module adds depth on top of these, it does not recompute them.
    """
    river = report.get("river") if isinstance(report.get("river"), Mapping) else {}
    signals = river.get("parameter_signals") if isinstance(river.get("parameter_signals"), list) else []
    proposals = report.get("proposals") if isinstance(report.get("proposals"), list) else []
    blocked = report.get("blocked_proposals") if isinstance(report.get("blocked_proposals"), list) else []

    index: Dict[str, Dict[str, Any]] = {}
    for entry in signals:
        if isinstance(entry, Mapping) and entry.get("parameter"):
            index.setdefault(str(entry["parameter"]), {})["signal"] = entry
    for entry in proposals:
        if isinstance(entry, Mapping) and entry.get("parameter"):
            index.setdefault(str(entry["parameter"]), {})["proposal"] = entry
    for entry in blocked:
        if isinstance(entry, Mapping) and entry.get("parameter"):
            index.setdefault(str(entry["parameter"]), {})["blocked"] = entry
    return index


def _growbot_river_cross_check(name: str, index: Mapping[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Surface the existing GrowBot/River pipeline's own opinion for `name`, if any."""
    entry = index.get(name) or {}
    signal = entry.get("signal") if isinstance(entry.get("signal"), Mapping) else None
    proposal = entry.get("proposal") if isinstance(entry.get("proposal"), Mapping) else None
    blocked = entry.get("blocked") if isinstance(entry.get("blocked"), Mapping) else None
    return {
        "river_signal_available": signal is not None,
        "river_confidence": signal.get("confidence") if signal else None,
        "river_evidence_count": signal.get("evidence_count") if signal else None,
        "river_direction": signal.get("direction") if signal else None,
        "river_candidate_ranking_score": signal.get("candidate_ranking_score") if signal else None,
        "river_dominant_regime": signal.get("dominant_regime") if signal else None,
        "river_already_proposed": proposal is not None,
        "river_blocked": blocked is not None,
        "river_blockers": list(blocked.get("blockers") or []) if blocked else [],
        "river_blocked_reason": blocked.get("reason") if blocked else None,
    }


# ---------------------------------------------------------------------------
# Small numeric helpers
# ---------------------------------------------------------------------------

def _as_float(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result or result in (float("inf"), float("-inf")):
        return None
    return result


def _band(threshold: float) -> float:
    return max(abs(threshold) * RELATIVE_BAND_FRACTION, MIN_ABS_BAND)


def _passes(value: float, threshold: float, threshold_type: str) -> bool:
    return value >= threshold if threshold_type == "minimum" else value <= threshold


def _pressure_direction(loosen_count: int, tighten_count: int) -> str:
    if loosen_count == 0 and tighten_count == 0:
        return "no_signal"
    total = loosen_count + tighten_count
    if loosen_count > 0 and tighten_count > 0:
        if loosen_count / total >= 0.7:
            return "loosen"
        if tighten_count / total >= 0.7:
            return "tighten"
        return "mixed"
    return "loosen" if loosen_count > tighten_count else "tighten"


def _most_recent_age_days(votes: Sequence[Mapping[str, Any]]) -> Optional[float]:
    timestamps = [parse_timestamp(v.get("created_at")) for v in votes]
    timestamps = [t for t in timestamps if t is not None]
    if not timestamps:
        return None
    most_recent = max(timestamps)
    now = datetime.now(timezone.utc)
    return max(0.0, (now - most_recent).total_seconds() / 86400.0)


# ---------------------------------------------------------------------------
# Evidence extraction per source
# ---------------------------------------------------------------------------

def _decision_outcome_votes(
    records: Sequence[Mapping[str, Any]], spec: ParameterEvidenceSpec, threshold: float
) -> List[Dict[str, Any]]:
    band = _band(threshold)
    votes: List[Dict[str, Any]] = []
    for record in records:
        if str(record.get("status")) != "resolved":
            continue
        ctx = record.get("growbot_river_learning_context")
        state = ctx.get("state") if isinstance(ctx, Mapping) else None
        value = _as_float(state.get(spec.state_field)) if isinstance(state, Mapping) else None
        if value is None:
            continue
        category = str(record.get("decision_category") or "")
        outcome = record.get("outcome") if isinstance(record.get("outcome"), Mapping) else {}
        outcome_label = str(outcome.get("outcome_label") or "")
        near_band = abs(value - threshold) <= band
        passed = _passes(value, threshold, spec.threshold_type)
        relevant = near_band and (
            (category in WAITLIKE_CATEGORIES and not passed)
            or (category in ENTRYLIKE_CATEGORIES and passed)
        )
        if not relevant:
            continue
        vote = "none"
        if category in WAITLIKE_CATEGORIES and outcome_label in LOOSEN_OUTCOME_LABELS:
            vote = "loosen"
        elif category in ENTRYLIKE_CATEGORIES and outcome_label in TIGHTEN_OUTCOME_LABELS:
            vote = "tighten"
        elif outcome_label in KEEP_OUTCOME_LABELS:
            vote = "keep"
        votes.append(
            {
                "ticker": record.get("ticker"),
                "regime": ctx.get("regime") if isinstance(ctx, Mapping) else None,
                "created_at": record.get("created_at"),
                "value": value,
                "decision_category": category,
                "outcome_label": outcome_label,
                "vote": vote,
                "effect_pct": _as_float(outcome.get("price_change_pct")),
            }
        )
    return votes


def _execution_outcome_votes(
    records: Sequence[Mapping[str, Any]], spec: ParameterEvidenceSpec
) -> List[Dict[str, Any]]:
    allowed_actions = _EXECUTION_ONLY_PARAMETER_ACTIONS.get(spec.parameter)
    votes: List[Dict[str, Any]] = []
    for record in records:
        action = str(record.get("execution_action") or "")
        if allowed_actions and action not in allowed_actions:
            continue
        primary_label = str(record.get("primary_label") or "")
        if not primary_label:
            continue
        ctx = record.get("growbot_river_learning_context")
        regime = ctx.get("regime") if isinstance(ctx, Mapping) else None
        if not regime:
            regime = record.get("market_regime")
        vote = "none"
        if primary_label in EXECUTION_LOOSEN_LABELS:
            vote = "loosen"
        elif primary_label in EXECUTION_TIGHTEN_LABELS:
            vote = "tighten"
        elif primary_label in EXECUTION_KEEP_LABELS:
            vote = "keep"
        votes.append(
            {
                "ticker": record.get("ticker"),
                "regime": regime,
                "created_at": record.get("generated_at"),
                "value": None,
                "decision_category": action,
                "outcome_label": primary_label,
                "vote": vote,
                "effect_pct": _as_float(record.get("post_move_pct_vs_limit")),
            }
        )
    return votes


# ---------------------------------------------------------------------------
# Per-parameter evidence assembly
# ---------------------------------------------------------------------------

def resolve_current_value(definition: Any, current_values: Mapping[str, Any]) -> float:
    value = _as_float(current_values.get(definition.name))
    return value if value is not None else float(definition.default)


def compute_votes_for_parameter(
    name: str,
    decision_records: Sequence[Mapping[str, Any]],
    execution_records: Sequence[Mapping[str, Any]],
    current_values: Mapping[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """Return the raw evidence votes backing `name`, or None if unmapped.

    Shared by the per-parameter evidence builder and the regime-segmented
    profile builder so both look at exactly the same evidence.
    """
    spec = _SPEC_BY_PARAMETER.get(name)
    if spec is None:
        return None
    definition = parameter_definitions().get(name)
    if definition is None:
        return None
    threshold = resolve_current_value(definition, current_values)
    if spec.evidence_source == "decision_outcomes":
        return _decision_outcome_votes(decision_records, spec, threshold)
    return _execution_outcome_votes(execution_records, spec)


def _risk_impact_text(reg_dict: Mapping[str, Any]) -> str:
    safety = reg_dict.get("safety_class")
    category = reg_dict.get("category")
    if safety == "high_risk_manual_only":
        return f"{category}: high_risk_manual_only -- never auto-changeable, requires explicit manual governance."
    if safety == "never_auto_change":
        return f"{category}: never_auto_change."
    return f"{category}: human_review_required before any activation route."


def _expected_effect_text(direction: str, loosen_count: int, tighten_count: int, evidence_count: int) -> str:
    if direction == "loosen":
        return (
            f"Loosening would have let an estimated {loosen_count} of {evidence_count} near-threshold "
            "case(s) in this evidence window pass instead of being blocked."
        )
    if direction == "tighten":
        return (
            f"Tightening would have blocked an estimated {tighten_count} of {evidence_count} "
            "near-threshold case(s) that passed but turned out to be a false-positive plan."
        )
    if direction == "mixed":
        return "Evidence is split between loosen- and tighten-favouring cases; no net expected effect can be estimated yet."
    return "No evidence currently indicates this threshold should move."


def _why_text(
    direction: str, loosen_count: int, tighten_count: int, keep_count: int, regimes: Mapping[str, Any], tickers: Mapping[str, Any]
) -> str:
    base = (
        f"{loosen_count} loosen-favouring, {tighten_count} tighten-favouring and {keep_count} "
        f"keep-favouring near-threshold case(s) across {regimes['distinct_known']} known regime(s) and "
        f"{tickers['distinct_known']} ticker(s)."
    )
    if direction in ("loosen", "tighten"):
        return f"Pressure direction: {direction}. {base}"
    if direction == "mixed":
        return f"Mixed pressure -- no dominant direction. {base}"
    return f"No directional pressure detected yet. {base}"


def _next_data_needed_text(tier: str, regimes: Mapping[str, Any], tickers: Mapping[str, Any]) -> str:
    if tier == "operator_review_candidate":
        return "Evidence base is broad and stable; no additional data required before a human review."
    missing = []
    if regimes["distinct_known"] < BACKTEST_MIN_REGIMES:
        missing.append("more market regimes")
    if tickers["distinct_known"] < WALK_FORWARD_MIN_TICKERS:
        missing.append("more tickers")
    if not missing:
        missing.append("more time/evidence volume")
    return "Needs: " + ", ".join(missing) + "."


def _proposed_value(direction: str, reg_dict: Mapping[str, Any]) -> float:
    current = float(reg_dict["current_value"])
    if direction not in ("loosen", "tighten"):
        return current
    span = float(reg_dict["max"]) - float(reg_dict["min"])
    step = max(span * PROPOSED_STEP_FRACTION, 1e-9)
    loosen_change = reg_dict.get("loosen_change") or "decrease"
    sign = 1.0 if loosen_change == "increase" else -1.0
    if direction == "tighten":
        sign = -sign
    proposed = current + sign * step
    proposed = max(float(reg_dict["min"]), min(float(reg_dict["max"]), proposed))
    return round(proposed, 8)


def _no_mapping_result(
    name: str, reg_dict: Mapping[str, Any], message: str, *, river_backend: str, cross_check: Mapping[str, Any]
) -> Dict[str, Any]:
    empty_regimes = regime_coverage([])
    empty_tickers = ticker_coverage([])
    return {
        "parameter": name,
        "category": reg_dict.get("category"),
        "unit": reg_dict.get("unit"),
        "loosen_change": reg_dict.get("loosen_change"),
        "safety_class": reg_dict.get("safety_class"),
        "source": "growbot_river",
        "river_backend": river_backend,
        "evidence_source": "none",
        "current_value": reg_dict.get("current_value"),
        "proposed_value": reg_dict.get("current_value"),
        "direction": "keep",
        "tier": "observed_signal",
        "proposal_tier": "observed_signal",
        "confidence": 0.0,
        "proposal_score": 0.0,
        "evidence_count": 0,
        "loosen_signal_count": 0,
        "tighten_signal_count": 0,
        "keep_signal_count": 0,
        "effect_size": None,
        "regimes_seen": [],
        "tickers_seen": [],
        "regime_coverage_pct": 0.0,
        "regime_coverage": empty_regimes,
        "ticker_coverage": empty_tickers,
        "direction_stability": 0.0,
        "direction_stability_reason": "no_evidence_source_mapped",
        "overfit_risk": "high",
        "overfit_reasons": ["no_evidence_at_all"],
        "risk_impact": _risk_impact_text(reg_dict),
        "expected_effect": "no_data",
        "why": message,
        "why_not_apply_ready": why_not_apply_ready("observed_signal"),
        "why_no_proposal": message,
        "next_data_needed": message,
        "growbot_river_cross_check": cross_check,
    }


def build_parameter_evidence(
    name: str,
    definition: Any,
    decision_records: Sequence[Mapping[str, Any]],
    execution_records: Sequence[Mapping[str, Any]],
    current_values: Mapping[str, Any],
    *,
    river_backend: str = "report_only",
    growbot_river_index: Optional[Mapping[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    cross_check = _growbot_river_cross_check(name, growbot_river_index or {})
    reg_dict = definition.to_dict(current_value=resolve_current_value(definition, current_values))
    spec = _SPEC_BY_PARAMETER.get(name)
    if spec is None:
        message = NO_MAPPING_PARAMETERS.get(name, _GENERIC_NO_MAPPING_MESSAGE)
        return _no_mapping_result(name, reg_dict, message, river_backend=river_backend, cross_check=cross_check)

    votes = compute_votes_for_parameter(name, decision_records, execution_records, current_values) or []

    evidence_count = len(votes)
    loosen_count = sum(1 for v in votes if v["vote"] == "loosen")
    tighten_count = sum(1 for v in votes if v["vote"] == "tighten")
    keep_count = sum(1 for v in votes if v["vote"] == "keep")
    direction = _pressure_direction(loosen_count, tighten_count)

    regimes = regime_coverage(votes)
    tickers = ticker_coverage(votes)

    first_half, second_half = time_split_halves(votes)
    dir_first = _pressure_direction(
        sum(1 for v in first_half if v["vote"] == "loosen"), sum(1 for v in first_half if v["vote"] == "tighten")
    )
    dir_second = _pressure_direction(
        sum(1 for v in second_half if v["vote"] == "loosen"), sum(1 for v in second_half if v["vote"] == "tighten")
    )
    stability, stability_reason = direction_stability_score(
        dir_first, dir_second, evidence_first=len(first_half), evidence_second=len(second_half)
    )

    overfit = compute_overfit_risk(votes, direction_stability=stability)

    dominant_count = max(loosen_count, tighten_count)
    consistency = (dominant_count / evidence_count) if evidence_count else 0.0
    volume_factor = min(1.0, evidence_count / SHADOW_MIN_EVIDENCE) if evidence_count else 0.0
    confidence = round(consistency * (0.5 + 0.5 * volume_factor), 4)

    effect_values = [abs(v["effect_pct"]) for v in votes if isinstance(v.get("effect_pct"), (int, float))]
    mean_abs_effect = round(sum(effect_values) / len(effect_values), 6) if effect_values else None
    effect_size_quality = min(1.0, mean_abs_effect / EFFECT_SIZE_FULL_SCALE_PCT) if mean_abs_effect else 0.3

    recent_age_days = _most_recent_age_days(votes)
    live_relevance = (
        max(0.0, 1.0 - recent_age_days / LIVE_RELEVANCE_DECAY_DAYS) if recent_age_days is not None else 0.5
    )

    ticker_coverage_score = min(1.0, tickers["distinct_known"] / TICKER_COVERAGE_FULL_SCALE)

    drawdown_penalty = 0.0
    if direction == "loosen" and tighten_count and evidence_count:
        drawdown_penalty = round(0.05 * (tighten_count / evidence_count), 4)
    overfit_penalty = round(overfit.score * 0.5, 4)

    evaluation = evaluate_proposal(
        evidence_count=evidence_count,
        pressure_direction=direction,
        regimes_seen_count=regimes["distinct_known"],
        tickers_seen_count=tickers["distinct_known"],
        direction_stability=stability,
        overfit_risk=overfit.risk,
        confidence=confidence,
        regime_coverage_pct=regimes["coverage_pct"],
        ticker_coverage_score=ticker_coverage_score,
        effect_size_quality=effect_size_quality,
        live_relevance=live_relevance,
        overfit_penalty=overfit_penalty,
        drawdown_penalty=drawdown_penalty,
    )

    why_no_proposal_text = evaluation.why_no_proposal
    if cross_check["river_blocked"]:
        blocker_text = ", ".join(cross_check["river_blockers"]) or cross_check["river_blocked_reason"] or "blocked"
        why_no_proposal_text = f"GrowBot/River pipeline already blocked this candidate: {blocker_text}."

    return {
        "parameter": name,
        "category": reg_dict["category"],
        "unit": reg_dict["unit"],
        "loosen_change": reg_dict["loosen_change"],
        "safety_class": reg_dict["safety_class"],
        "source": "growbot_river",
        "river_backend": river_backend,
        "evidence_source": spec.evidence_source,
        "current_value": reg_dict["current_value"],
        "proposed_value": _proposed_value(direction, reg_dict),
        "direction": direction,
        "tier": evaluation.tier,
        "proposal_tier": evaluation.tier,
        "confidence": confidence,
        "proposal_score": evaluation.score,
        "evidence_count": evidence_count,
        "loosen_signal_count": loosen_count,
        "tighten_signal_count": tighten_count,
        "keep_signal_count": keep_count,
        "effect_size": mean_abs_effect,
        "regimes_seen": regimes["known_regimes_seen"],
        "tickers_seen": tickers["tickers_seen"],
        "regime_coverage_pct": regimes["coverage_pct"],
        "regime_coverage": regimes,
        "ticker_coverage": tickers,
        "direction_stability": stability,
        "direction_stability_reason": stability_reason,
        "overfit_risk": overfit.risk,
        "overfit_reasons": list(overfit.reasons),
        "risk_impact": _risk_impact_text(reg_dict),
        "expected_effect": _expected_effect_text(direction, loosen_count, tighten_count, evidence_count),
        "why": _why_text(direction, loosen_count, tighten_count, keep_count, regimes, tickers),
        "why_not_apply_ready": evaluation.why_not_apply_ready,
        "why_no_proposal": why_no_proposal_text,
        "next_data_needed": evaluation.why_no_proposal or _next_data_needed_text(evaluation.tier, regimes, tickers),
        "growbot_river_cross_check": cross_check,
    }


# ---------------------------------------------------------------------------
# Missed-opportunity learning / wait-decision quality / learning depth
# ---------------------------------------------------------------------------

def build_wait_decision_quality(decision_records: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    resolved = [
        r
        for r in decision_records
        if str(r.get("status")) == "resolved" and str(r.get("decision_category")) in WAITLIKE_CATEGORIES
    ]
    counts = Counter(str((r.get("outcome") or {}).get("outcome_label") or "unresolved") for r in resolved)
    correct = counts.get("correct_avoid", 0) + counts.get("correct_wait_or_neutral", 0)
    missed = counts.get("missed_opportunity", 0)
    classified = correct + missed
    quality_pct = round(correct / classified, 4) if classified else None
    return {
        "resolved_wait_like_decisions": len(resolved),
        "outcome_breakdown": dict(counts),
        "correct_count": correct,
        "missed_opportunity_count": missed,
        "wait_decision_quality_pct": quality_pct,
        "interpretation": (
            "Share of resolved wait/watch/skip decisions that were the right call "
            "(correct_avoid or correct_wait_or_neutral) versus missed_opportunity."
            if classified
            else "Not enough resolved wait-like decisions with a clear outcome label yet."
        ),
    }


def build_missed_opportunity_learning(
    decision_records: Sequence[Mapping[str, Any]], *, top_n: int = 10
) -> Dict[str, Any]:
    missed = [
        r
        for r in decision_records
        if str(r.get("status")) == "resolved" and (r.get("outcome") or {}).get("outcome_label") == "missed_opportunity"
    ]
    by_ticker = Counter(str(r.get("ticker") or "unknown") for r in missed)
    by_setup = Counter(
        str((r.get("trade_plan") or {}).get("setup_type") or (r.get("entry_gate") or {}).get("setup_type") or "unknown")
        for r in missed
    )
    samples = []
    for record in sorted(missed, key=lambda r: r.get("created_at") or "", reverse=True)[:top_n]:
        trade_plan = record.get("trade_plan") or {}
        entry_gate = record.get("entry_gate") or {}
        samples.append(
            {
                "ticker": record.get("ticker"),
                "created_at": record.get("created_at"),
                "decision_category": record.get("decision_category"),
                "price_change_pct": (record.get("outcome") or {}).get("price_change_pct"),
                "setup_type": trade_plan.get("setup_type") or entry_gate.get("setup_type"),
                "reason_recorded": trade_plan.get("trigger") or entry_gate.get("decision") or "no reason recorded",
            }
        )
    return {
        "missed_opportunity_count": len(missed),
        "by_ticker": dict(by_ticker.most_common(10)),
        "by_setup_type": dict(by_setup.most_common(10)),
        "recent_samples": samples,
    }


def build_learning_depth_summary(
    decision_records: Sequence[Mapping[str, Any]],
    execution_records: Sequence[Mapping[str, Any]],
    reflection_records: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    resolved = [r for r in decision_records if str(r.get("status")) == "resolved"]
    pending = [r for r in decision_records if str(r.get("status")) == "pending"]

    all_evidence: List[Dict[str, Any]] = []
    for record in resolved:
        ctx = record.get("growbot_river_learning_context")
        all_evidence.append(
            {
                "ticker": record.get("ticker"),
                "regime": ctx.get("regime") if isinstance(ctx, Mapping) else None,
            }
        )
    for record in execution_records:
        ctx = record.get("growbot_river_learning_context")
        regime = ctx.get("regime") if isinstance(ctx, Mapping) else None
        all_evidence.append({"ticker": record.get("ticker"), "regime": regime or record.get("market_regime")})

    regimes = regime_coverage(all_evidence)
    tickers = ticker_coverage(all_evidence)

    return {
        "decision_outcomes_resolved": len(resolved),
        "decision_outcomes_pending": len(pending),
        "execution_outcomes_count": len(execution_records),
        "trade_reflections_count": len(reflection_records),
        "total_evidence_records": len(all_evidence),
        "regime_coverage": regimes,
        "ticker_coverage": tickers,
    }


# ---------------------------------------------------------------------------
# Top-level orchestrator
# ---------------------------------------------------------------------------

def build_adaptive_learning_intelligence(*, root: str | Path = ".") -> Dict[str, Any]:
    root_path = Path(root)

    decision_records = load_decision_outcome_records(root_path)
    execution_records = load_execution_outcome_records(root_path)
    reflection_records = load_trade_reflection_records(root_path)
    opportunities = load_opportunity_memory(root_path)
    current_values = load_current_parameter_values(root_path)
    growbot_river_report = load_growbot_river_learning_report(root_path)
    river_backend = river_backend_label(growbot_river_report)
    growbot_river_index = _growbot_river_cross_check_index(growbot_river_report)

    registry = parameter_definitions()
    parameter_evidence = [
        build_parameter_evidence(
            name,
            definition,
            decision_records,
            execution_records,
            current_values,
            river_backend=river_backend,
            growbot_river_index=growbot_river_index,
        )
        for name, definition in sorted(registry.items())
    ]

    tier_counts = Counter(item["tier"] for item in parameter_evidence)
    overfit_counts = Counter(item["overfit_risk"] for item in parameter_evidence)

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "read_only": True,
        "llm_call_made": False,
        "coinbase_call_attempted": False,
        "state_write_performed": False,
        "automatic_parameter_apply_enabled": False,
        "source": "growbot_river",
        "river_backend": river_backend,
        "integrates_existing_growbot_river_layer": True,
        "replaces_growbot_river": False,
        "growbot_river_learning_report_generated_at": growbot_river_report.get("generated_at"),
        "parameter_evidence": parameter_evidence,
        "proposal_maturity_funnel": {tier: tier_counts.get(tier, 0) for tier in (
            "observed_signal",
            "shadow_candidate",
            "backtest_candidate",
            "walk_forward_candidate",
            "operator_review_candidate",
            "apply_ready_candidate",
        )},
        "overfit_risk_monitor": {
            "low": overfit_counts.get("low", 0),
            "medium": overfit_counts.get("medium", 0),
            "high": overfit_counts.get("high", 0),
            "high_risk_parameters": sorted(
                item["parameter"] for item in parameter_evidence if item["overfit_risk"] == "high"
            ),
        },
        "wait_decision_quality": build_wait_decision_quality(decision_records),
        "missed_opportunity_learning": build_missed_opportunity_learning(decision_records),
        "learning_depth": build_learning_depth_summary(decision_records, execution_records, reflection_records),
        "opportunity_memory_count": len(opportunities),
        "source_evidence": {
            "decision_outcomes_path": str(STATE_DECISION_OUTCOMES),
            "execution_outcomes_path": str(LOG_EXECUTION_OUTCOMES),
            "trade_reflections_path": str(STATE_TRADE_REFLECTIONS),
            "opportunity_memory_path": str(STATE_OPPORTUNITY_MEMORY),
            "growbot_river_learning_report_path": str(GROWBOT_RIVER_LEARNING_REPORT_PATH),
        },
    }


__all__ = [
    "SCHEMA_VERSION",
    "PARAMETER_EVIDENCE_SPECS",
    "NO_MAPPING_PARAMETERS",
    "load_decision_outcome_records",
    "load_execution_outcome_records",
    "load_trade_reflection_records",
    "load_opportunity_memory",
    "load_current_parameter_values",
    "load_growbot_river_learning_report",
    "river_backend_label",
    "GROWBOT_RIVER_LEARNING_REPORT_PATH",
    "resolve_current_value",
    "compute_votes_for_parameter",
    "build_parameter_evidence",
    "build_wait_decision_quality",
    "build_missed_opportunity_learning",
    "build_learning_depth_summary",
    "build_adaptive_learning_intelligence",
]
