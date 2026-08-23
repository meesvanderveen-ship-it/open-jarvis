from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from bot.adaptive_policy_lab import (
    CANDIDATE_JSON_PATH,
    CURRENT_PARAMETER_DEFAULTS,
    DIRECTIONAL_ERROR_LABELS,
    DIRECTIONAL_EVENT_LABELS,
    HISTORY_PATH,
    SAMPLE_THRESHOLDS,
    _evidence_summary,
    _load_json,
    _load_market_intelligence_context,
    _market_regime,
    _suggested_values_for_edge,
    build_regime_enrichment_fields,
    build_adaptive_policy_candidate,
    build_policy_lab_report,
    confidence_interval_excludes_current,
    direction_stability_for,
    label_pressure,
    load_candidate_history,
    passes_effect_size_gate,
    regime_diversity_diagnostics,
    robust_stats,
    stable_payload_hash,
)
from bot.atomic_io import atomic_write_json
from bot.reflection_persistence import (
    PARAMETER_PRESSURE_LEDGER_PATH,
    load_reflection_events,
    read_jsonl_ledger,
)


ANALYSIS_JSON_PATH = Path("reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.json")
ANALYSIS_MD_PATH = Path("reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.md")
SOURCE_POLICY = "parameter_candidate_analysis_report_only_no_live_mutation"

LABELS = [
    "missed_opportunity",
    "too_strict_wait",
    "correct_wait",
    "correct_avoid",
    "bad_trade",
    "overtrading_risk",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, list) else []


def _change_rows(candidate: Dict[str, Any], lab: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = [row for row in _as_list(candidate.get("proposed_parameter_changes")) if isinstance(row, dict)]
    rows.extend(row for row in _as_list(candidate.get("blocked_parameter_changes")) if isinstance(row, dict))
    if rows:
        return rows
    lab_rows = [row for row in _as_list(lab.get("proposed_parameter_changes")) if isinstance(row, dict)]
    lab_rows.extend(row for row in _as_list(lab.get("blocked_parameter_changes")) if isinstance(row, dict))
    if lab_rows:
        return lab_rows
    return [
        {
            "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
            "scope": "adaptive_policy_lab",
            "current_value": CURRENT_PARAMETER_DEFAULTS["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"],
            "candidate_value": None,
            "direction": "loosen",
            "blockers": ["insufficient_market_regimes"],
        }
    ]


def _direction(row: Dict[str, Any], pressure: Dict[str, Any]) -> str:
    explicit = str(row.get("direction") or "").strip()
    if explicit in {"loosen", "tighten"}:
        return explicit
    net = float(pressure.get("net_pressure") or 0.0)
    if net > 0:
        return "loosen"
    if net < 0:
        return "tighten"
    return "neutral"


def _event_ids(rows: Sequence[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for row in rows:
        event_id = str(row.get("event_id") or row.get("reflection_event_id") or "").strip()
        if event_id and event_id not in out:
            out.append(event_id)
        if len(out) >= 20:
            break
    return out


def _top_values(rows: Sequence[Dict[str, Any]], key: str, *, limit: int = 5) -> List[str]:
    counts = Counter(str(row.get(key) or "").strip() for row in rows)
    return [value for value, _count in counts.most_common(limit) if value]


def _matching_reflections(reflections: Sequence[Dict[str, Any]], change: Dict[str, Any]) -> List[Dict[str, Any]]:
    scope = str(change.get("scope") or "")
    if scope.startswith("setup_type_specific:"):
        setup = scope.split(":", 1)[1]
        return [row for row in reflections if str(row.get("setup_type") or "unknown") == setup]
    return list(reflections)


def _matching_pressure(pressure_events: Sequence[Dict[str, Any]], change: Dict[str, Any]) -> List[Dict[str, Any]]:
    parameter = str(change.get("parameter") or "")
    scope = str(change.get("scope") or "")
    return [
        row
        for row in pressure_events
        if str(row.get("parameter") or "") == parameter
        and (not scope or scope == "adaptive_policy_lab" or str(row.get("scope") or "") == scope)
    ]


def _label_breakdown(rows: Sequence[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(str(row.get("label") or "") for row in rows)
    return {label: counts[label] for label in LABELS}


def _directional_regime_counts(rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    out: Dict[str, Dict[str, int]] = {}
    for row in rows:
        regime = str(row.get("adaptive_market_regime") or row.get("market_regime") or "unknown").strip() or "unknown"
        item = out.setdefault(regime, {"validated_conclusions": 0, "directional_events": 0, "directional_error_labels": 0})
        item["validated_conclusions"] += 1
        label = str(row.get("label") or "")
        if label in DIRECTIONAL_EVENT_LABELS:
            item["directional_events"] += 1
        if label in DIRECTIONAL_ERROR_LABELS:
            item["directional_error_labels"] += 1
    return dict(sorted(out.items()))


def _enrich_loaded_rows(rows: Sequence[Dict[str, Any]], market_intelligence_context: Dict[str, Any]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for row in rows:
        clone = dict(row)
        clone.update(build_regime_enrichment_fields(clone, market_intelligence_context, clone.get("candle_context") if isinstance(clone.get("candle_context"), dict) else {}))
        enriched.append(clone)
    return enriched


def _regime_summary(
    rows: Sequence[Dict[str, Any]],
    pressure_rows: Sequence[Dict[str, Any]],
    adaptive_gate: Dict[str, Any],
    blockers: Sequence[str],
) -> Dict[str, Any]:
    combined = list(rows) + list(pressure_rows)
    raw = sorted({str((row.get("raw_market_regime") or row.get("market_regime") or "unknown")).strip() or "unknown" for row in combined}) if combined else []
    adaptive_all = sorted({str((row.get("adaptive_market_regime") or _market_regime(row) or "unknown")).strip() or "unknown" for row in combined}) if combined else []
    adaptive_known = [regime for regime in adaptive_all if regime != "unknown"]
    adaptive = adaptive_known or adaptive_all
    sources = sorted({str(row.get("regime_source") or "unknown").strip() or "unknown" for row in combined}) if combined else []
    key_designs = sorted({str(row.get("regime_key_design") or "unknown").strip() or "unknown" for row in combined}) if combined else []
    coverage = 0.0
    if combined:
        covered = sum(1 for row in combined if str(row.get("adaptive_market_regime") or _market_regime(row) or "unknown") != "unknown")
        coverage = covered / len(combined) * 100.0
    diversity = regime_diversity_diagnostics(adaptive_known or adaptive_all, required=int(SAMPLE_THRESHOLDS["min_market_regimes"]))
    unique_enriched = int(diversity["distinct_regime_count"])
    required = SAMPLE_THRESHOLDS["min_market_regimes"]
    gate_passed = unique_enriched >= int(required) and "insufficient_market_regimes" not in set(blockers)
    gate_reason = "passed" if gate_passed else (
        "insufficient_distinct_regime_diversity"
        if diversity["raw_regime_count"] >= int(required) and unique_enriched < int(required)
        else ("insufficient_market_regimes" if unique_enriched < int(required) or "insufficient_market_regimes" in set(blockers) else "blocked")
    )
    adaptive_gate_coverage = adaptive_gate.get("coverage_pct") if isinstance(adaptive_gate, dict) else None
    if adaptive_gate_coverage is None:
        adaptive_gate_coverage = coverage
    return {
        "raw_market_regimes": raw,
        "adaptive_market_regimes": adaptive,
        "regime_sources": sources,
        "regime_key_designs": key_designs,
        "ledger_regime_coverage_pct": round(coverage, 4),
        "adaptive_gate_regime_coverage_pct": round(float(adaptive_gate_coverage), 4),
        "unique_enriched_regime_count": unique_enriched,
        "raw_regime_count": diversity["raw_regime_count"],
        "distinct_regime_count": diversity["distinct_regime_count"],
        "qualifying_regime_count": diversity["qualifying_regime_count"],
        "deduped_regime_count": diversity["deduped_regime_count"],
        "regime_dedup_reason": diversity["regime_dedup_reason"],
        "distinct_regimes": diversity["distinct_regimes"],
        "canonical_regime_by_raw_regime": diversity["canonical_regime_by_raw_regime"],
        "additional_regime_features_needed": diversity["additional_regime_features_needed"],
        "required_unique_regime_count": required,
        "regime_gate_passed": bool(gate_passed),
        "regime_gate_reason": gate_reason,
        "regime_coverage_pct": round(coverage, 4),
        "unique_regime_count": unique_enriched,
        "required_unique_regimes": required,
        "regime_enriched": any(bool(row.get("regime_enriched")) for row in combined),
    }


def _pressure_summary(rows: Sequence[Dict[str, Any]], reflections: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    if rows:
        loosen = sum(float(row.get("loosen_score") or 0.0) for row in rows)
        tighten = sum(float(row.get("tighten_score") or 0.0) for row in rows)
        if loosen == 0.0 and tighten == 0.0:
            return label_pressure(reflections)
        return {
            "loosen_score": round(loosen, 6),
            "tighten_score": round(tighten, 6),
            "net_pressure": round(loosen - tighten, 6),
        }
    return label_pressure(reflections)


def _direction_from_labels(rows: Sequence[Dict[str, Any]]) -> str:
    labels = Counter(str(row.get("label") or "") for row in rows)
    loosen_count = labels["missed_opportunity"] + labels["too_strict_wait"]
    tighten_count = labels["bad_trade"] + labels["overtrading_risk"]
    if loosen_count > tighten_count:
        return "loosen"
    if tighten_count > loosen_count:
        return "tighten"
    return "neutral"


def _pressure_explanation(
    *,
    direction: str,
    pressure: Dict[str, Any],
    supporting: Sequence[Dict[str, Any]],
    counter: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    supporting_raw = pressure.get("loosen_score") if direction == "loosen" else pressure.get("tighten_score")
    counter_raw = pressure.get("tighten_score") if direction == "loosen" else pressure.get("loosen_score")
    supporting_score = float(supporting_raw or 0.0)
    counter_score = float(counter_raw or 0.0)
    supporting_count = len(supporting)
    counter_count = len(counter)
    return {
        "supporting_event_count": supporting_count,
        "counterweight_event_count": counter_count,
        "supporting_weighted_score": round(supporting_score, 6),
        "counterweight_weighted_score": round(counter_score, 6),
        "net_weighted_pressure": round(float(pressure.get("net_pressure") or 0.0), 6),
        "average_supporting_quality": round(supporting_score / supporting_count, 6) if supporting_count else 0.0,
        "average_counterweight_quality": round(counter_score / counter_count, 6) if counter_count else 0.0,
        "why_net_positive": (
            "Fewer high-quality missed/too_strict events outweigh many low-weight correct_wait/counterweight events "
            "after confidence, net-after-cost, drawdown-safety and label-weight adjustments."
        ),
    }


def _activation_status(candidate: Dict[str, Any], change: Dict[str, Any]) -> str:
    if candidate.get("candidate_available") is True and not change.get("blockers"):
        return "candidate"
    if change.get("applied") is True:
        return "applied"
    return "blocked"


def _missing_candidate_fields(candidate: Dict[str, Any]) -> List[str]:
    missing: List[str] = []
    if candidate.get("candidate_available") is not True:
        for key in ("proposed_parameter_changes", "proposed_parameters", "parameter_changes"):
            value = candidate.get(key)
            if not value:
                missing.append(key)
    return sorted(set(missing))


def _analysis_blocker(reason: str, parameter_analysis: Sequence[Dict[str, Any]]) -> str:
    blockers: List[str] = []
    for item in parameter_analysis:
        blockers.extend(str(blocker) for blocker in item.get("blockers") or [])
    if blockers:
        return blockers[0]
    return reason or "none"


def _statistical_gates(candidate: Dict[str, Any], change: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "effect_size_gate": change.get("effect_size_gate") if isinstance(change.get("effect_size_gate"), dict) else candidate.get("effect_size_gate") or {},
        "confidence_gate": change.get("confidence_gate") if isinstance(change.get("confidence_gate"), dict) else candidate.get("confidence_gate") or {},
        "direction_stability_gate": change.get("direction_stability_gate") if isinstance(change.get("direction_stability_gate"), dict) else candidate.get("direction_stability_gate") or {},
        "regime_enrichment": candidate.get("regime_enrichment") or {},
        "shrinkage": change.get("shrinkage") if isinstance(change.get("shrinkage"), dict) else candidate.get("shrinkage") or {},
    }


def _as_float(value: Any) -> Optional[float]:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _not_used_reason(blockers: Sequence[str]) -> Optional[str]:
    if not blockers:
        return None
    return f"candidate_blocked_by_{str(list(blockers)[0])}"


def _diagnostic_gates(
    *,
    change: Dict[str, Any],
    rows: Sequence[Dict[str, Any]],
    direction: str,
    blockers: Sequence[str],
    history: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    parameter = str(change.get("parameter") or "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT")
    scope = str(change.get("scope") or "adaptive_policy_lab")
    current = _as_float(change.get("current_value")) or _as_float(CURRENT_PARAMETER_DEFAULTS.get(parameter)) or 0.0
    robust_target = _as_float(change.get("robust_target_value") or change.get("trimmed_mean_suggested_value") or change.get("median_suggested_value"))
    stats = change.get("robust_stats") if isinstance(change.get("robust_stats"), dict) else {}
    if robust_target is None:
        suggested = _suggested_values_for_edge([r for r in rows if r.get("label") in {"missed_opportunity", "too_strict_wait"}], current)
        stats = robust_stats(suggested)
        robust_target = stats["trimmed_mean_10pct"] if stats.get("trimmed_mean_10pct") is not None else stats.get("median")
    sample_count = int((stats or {}).get("sample_count") or 0)
    effect = passes_effect_size_gate(current, robust_target, min_effect_size_pct=SAMPLE_THRESHOLDS["min_effect_size_pct"])
    effect_diag = {
        "calculated": effect.get("actual_effect_size_pct") is not None,
        "actual_effect_size_pct": effect.get("actual_effect_size_pct"),
        "min_required_pct": effect.get("min_effect_size_pct"),
        "direction": direction,
        "would_pass_effect_size_gate": bool(effect.get("passed")),
        "activation_eligible": not blockers and bool(effect.get("passed")),
        "used_for_activation": not blockers and bool(effect.get("passed")),
        "not_used_reason": _not_used_reason(blockers),
    }
    if not effect_diag["calculated"]:
        effect_diag["reason"] = "insufficient_numeric_samples"

    ci_low, ci_high = ((stats or {}).get("confidence_interval") or [None, None])
    enough_ci_samples = sample_count >= 2 and ci_low is not None and ci_high is not None
    confidence = confidence_interval_excludes_current(
        current,
        ci_low if enough_ci_samples else None,
        ci_high if enough_ci_samples else None,
        direction,
        require_ci_excludes_current=bool(SAMPLE_THRESHOLDS["require_confidence_interval_excludes_current"]),
    )
    ci_diag = {
        "calculated": bool(enough_ci_samples),
        "ci_low": confidence.get("ci_low"),
        "ci_high": confidence.get("ci_high"),
        "current_value_inside_ci": confidence.get("current_value_inside_ci"),
        "direction": direction,
        "would_pass_confidence_gate": bool(confidence.get("passed")),
        "activation_eligible": not blockers and bool(confidence.get("passed")),
        "used_for_activation": not blockers and bool(confidence.get("passed")),
        "not_used_reason": _not_used_reason(blockers),
    }
    if not ci_diag["calculated"]:
        ci_diag["reason"] = "insufficient_numeric_samples"

    scope_key = f"{parameter}|{scope}"
    stability = direction_stability_for(
        scope_key,
        direction,
        history,
        required_runs=int(SAMPLE_THRESHOLDS["require_direction_stability_runs"]),
    )
    stability["scope_key"] = scope_key
    stability["candidate_history_path"] = str(HISTORY_PATH)
    return {
        "effect_size_gate": effect_diag,
        "confidence_gate": ci_diag,
        "direction_stability_gate": stability,
    }


def _missing_gate_reason(blockers: Sequence[str]) -> str:
    primary = str((list(blockers) or ["candidate_not_available"])[0])
    return f"not_calculated_because_candidate_blocked_by_{primary}"


def _gate_statuses(gates: Dict[str, Any], blockers: Sequence[str]) -> Dict[str, Any]:
    effect = gates.get("effect_size_gate") or {}
    confidence = gates.get("confidence_gate") or {}
    reason = _missing_gate_reason(blockers)
    effect_value = effect.get("actual_effect_size_pct")
    ci_low = confidence.get("ci_low")
    ci_high = confidence.get("ci_high")
    return {
        "effect_size_status": effect_value if effect.get("calculated") or effect_value is not None else reason,
        "confidence_interval_status": f"{ci_low}..{ci_high}" if confidence.get("calculated") and ci_low is not None and ci_high is not None else reason,
        "direction_stability_status": gates.get("direction_stability_gate") or {},
        "shrinkage_status": gates.get("shrinkage") or {},
        "regime_enrichment_status": gates.get("regime_enrichment") or {},
    }


def _interpretation(change: Dict[str, Any], evidence: Dict[str, Any], pressure: Dict[str, Any], blockers: Sequence[str]) -> str:
    parameter = change.get("parameter")
    if blockers:
        primary = blockers[0]
        if primary == "insufficient_market_regimes":
            return f"{parameter} remains blocked because insufficient_market_regimes: validated reflection evidence does not cover enough distinct market regimes."
        return f"{parameter} remains blocked because {primary} is not satisfied."
    net = float(pressure.get("net_pressure") or 0.0)
    if net > 0:
        return f"{parameter} has loosening pressure, but activation remains gated by the governor and operator review."
    if net < 0:
        return f"{parameter} has tightening pressure, but activation remains gated by the governor and operator review."
    return f"{parameter} has neutral pressure; collect more validated reflection evidence."


def build_parameter_candidate_analysis(
    *,
    root: Path = Path("."),
    candidate: Optional[Dict[str, Any]] = None,
    lab_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if candidate is not None:
        candidate_payload = candidate
    else:
        built_candidate = build_adaptive_policy_candidate(root=root)
        candidate_payload = built_candidate if built_candidate else _load_json(root / CANDIDATE_JSON_PATH)
    lab = lab_report if lab_report is not None else build_policy_lab_report(root=root)
    reflections_raw, reflection_corrupt = load_reflection_events(root)
    mi_context = _load_market_intelligence_context(root)
    reflections = _enrich_loaded_rows(reflections_raw, mi_context)
    pressure_events, pressure_corrupt = read_jsonl_ledger(root / PARAMETER_PRESSURE_LEDGER_PATH)
    history_rows = load_candidate_history(root)
    validated = [row for row in reflections if row.get("validated_conclusion") is True]
    changes = _change_rows(candidate_payload, lab)
    parameter_analysis: List[Dict[str, Any]] = []
    for change in changes:
        relevant_reflections = _matching_reflections(validated, change)
        relevant_pressure = _matching_pressure(pressure_events, change)
        pressure = _pressure_summary(relevant_pressure, relevant_reflections)
        direction = _direction(change, pressure)
        if direction == "neutral":
            direction = _direction_from_labels(relevant_reflections)
        supporting = [
            row for row in relevant_pressure
            if (direction == "loosen" and float(row.get("loosen_score") or 0.0) > 0)
            or (direction == "tighten" and float(row.get("tighten_score") or 0.0) > 0)
        ]
        counter = [
            row for row in relevant_pressure
            if (direction == "loosen" and float(row.get("tighten_score") or 0.0) > 0)
            or (direction == "tighten" and float(row.get("loosen_score") or 0.0) > 0)
        ]
        if not supporting and not counter:
            if direction == "loosen":
                supporting = [row for row in relevant_reflections if row.get("label") in {"missed_opportunity", "too_strict_wait"}]
                counter = [row for row in relevant_reflections if row.get("label") in {"correct_wait", "correct_avoid", "false_signal_avoided", "bad_trade", "overtrading_risk"}]
            elif direction == "tighten":
                supporting = [row for row in relevant_reflections if row.get("label") in {"bad_trade", "overtrading_risk"}]
                counter = [row for row in relevant_reflections if row.get("label") in {"missed_opportunity", "too_strict_wait", "correct_wait", "correct_avoid"}]
        evidence_summary = _evidence_summary(validated, relevant_rows=relevant_reflections)
        regime_counts = _directional_regime_counts(relevant_reflections)
        blockers = list(change.get("blockers") or [])
        if not blockers and candidate_payload.get("candidate_available") is not True:
            reason = str(candidate_payload.get("reason") or lab.get("reason") or "candidate_not_available")
            blockers = [reason]
        gates = _statistical_gates(candidate_payload, change)
        diagnostic_gates = _diagnostic_gates(
            change=change,
            rows=relevant_reflections,
            direction=direction,
            blockers=blockers,
            history=history_rows,
        )
        gates["effect_size_gate"] = diagnostic_gates["effect_size_gate"]
        gates["confidence_gate"] = diagnostic_gates["confidence_gate"]
        gates["direction_stability_gate"] = diagnostic_gates["direction_stability_gate"]
        regime_summary = _regime_summary(relevant_reflections, relevant_pressure, gates.get("regime_enrichment") or {}, blockers)
        if (
            candidate_payload.get("candidate_available") is not True
            and "insufficient_market_regimes" in blockers
            and regime_summary["regime_gate_reason"] == "insufficient_distinct_regime_diversity"
        ):
            blockers = ["insufficient_distinct_regime_diversity" if blocker == "insufficient_market_regimes" else blocker for blocker in blockers]
            for gate_key in ("effect_size_gate", "confidence_gate"):
                gate = gates.get(gate_key)
                if isinstance(gate, dict) and gate.get("not_used_reason") == "candidate_blocked_by_insufficient_market_regimes":
                    gate["not_used_reason"] = "candidate_blocked_by_insufficient_distinct_regime_diversity"
        evidence = {
            "total_reflections": len(reflections),
            "validated_conclusions": len(validated),
            "relevant_conclusions": evidence_summary["relevant_conclusions"],
            "directional_error_labels": evidence_summary["directional_error_labels"],
            "directional_events": evidence_summary.get("total_directional_events", 0),
            "total_directional_events": evidence_summary.get("total_directional_events", 0),
            "directional_event_labels": evidence_summary.get("directional_event_labels", {}),
            "directional_event_source": "reflection_evaluations.validated_conclusion.label",
            "directional_event_count_method": evidence_summary.get("directional_event_count_method", "validated_conclusions_with_directional_or_counter_directional_labels"),
            "separate_days": evidence_summary["separate_days"],
            "market_regimes": evidence_summary["market_regimes"],
            "regime_counts": regime_counts,
            "counts_by_regime": regime_counts,
            "raw_market_regimes": regime_summary["raw_market_regimes"],
            "adaptive_market_regimes": regime_summary["adaptive_market_regimes"],
            "regime_sources": regime_summary["regime_sources"],
            "regime_key_designs": regime_summary["regime_key_designs"],
            "regime_coverage_pct": regime_summary["regime_coverage_pct"],
            "ledger_regime_coverage_pct": regime_summary["ledger_regime_coverage_pct"],
            "adaptive_gate_regime_coverage_pct": regime_summary["adaptive_gate_regime_coverage_pct"],
            "unique_regime_count": regime_summary["unique_regime_count"],
            "unique_enriched_regime_count": regime_summary["unique_enriched_regime_count"],
            "raw_regime_count": regime_summary["raw_regime_count"],
            "distinct_regime_count": regime_summary["distinct_regime_count"],
            "qualifying_regime_count": regime_summary["qualifying_regime_count"],
            "deduped_regime_count": regime_summary["deduped_regime_count"],
            "regime_dedup_reason": regime_summary["regime_dedup_reason"],
            "distinct_regimes": regime_summary["distinct_regimes"],
            "canonical_regime_by_raw_regime": regime_summary["canonical_regime_by_raw_regime"],
            "additional_regime_features_needed": regime_summary["additional_regime_features_needed"],
            "required_unique_regimes": regime_summary["required_unique_regimes"],
            "required_unique_regime_count": regime_summary["required_unique_regime_count"],
            "regime_gate_passed": regime_summary["regime_gate_passed"],
            "regime_gate_reason": regime_summary["regime_gate_reason"],
            "out_of_sample_conclusions": evidence_summary["out_of_sample_conclusions"],
            "dominant_blockers": _top_values(relevant_reflections, "main_blocker"),
            "dominant_tickers": _top_values(relevant_reflections, "ticker"),
            "dominant_setup_types": _top_values(relevant_reflections, "setup_type"),
        }
        direction_history = {
            "history_items_available": len(history_rows),
            "last_3_direction_entries": (gates.get("direction_stability_gate") or {}).get("last_directions") or [],
            "sidecar_runs_seen": len(history_rows),
            "candidate_history_path": str(root / HISTORY_PATH),
            "available_scope_keys": (gates.get("direction_stability_gate") or {}).get("available_scope_keys") or [],
            "matched_scope_key": (gates.get("direction_stability_gate") or {}).get("matched_scope_key") or "",
            "match_strategy": (gates.get("direction_stability_gate") or {}).get("match_strategy") or "not_found",
            "observed_runs": (gates.get("direction_stability_gate") or {}).get("observed_runs", 0),
            "required_runs": (gates.get("direction_stability_gate") or {}).get("required_runs", 0),
            "stability_reason": (gates.get("direction_stability_gate") or {}).get("stability_reason") or "",
        }
        parameter_analysis.append(
            {
                "parameter": change.get("parameter"),
                "scope": change.get("scope"),
                "current_value": change.get("current_value") or CURRENT_PARAMETER_DEFAULTS.get(str(change.get("parameter") or ""), ""),
                "candidate_value": change.get("candidate_value") if candidate_payload.get("candidate_available") is True else None,
                "direction": direction,
                "activation_status": _activation_status(candidate_payload, {**change, "blockers": blockers}),
                "blockers": blockers,
                "regime": regime_summary,
                "evidence": evidence,
                "label_breakdown": _label_breakdown(relevant_reflections),
                "pressure_summary": pressure,
                "pressure_explanation": _pressure_explanation(direction=direction, pressure=pressure, supporting=supporting, counter=counter),
                "supporting_label_count": len(supporting),
                "counterweight_label_count": len(counter),
                "statistical_gates": gates,
                "statistical_gate_statuses": _gate_statuses(gates, blockers),
                "direction_history": direction_history,
                "supporting_reflection_event_ids": _event_ids(supporting),
                "counterweight_reflection_event_ids": _event_ids(counter),
                "sample_event_ids": _event_ids(relevant_reflections),
                "interpretation": _interpretation(change, evidence, pressure, blockers),
            }
        )
    reason = str(candidate_payload.get("reason") or lab.get("reason") or "insufficient_market_regimes")
    if parameter_analysis:
        first_evidence = parameter_analysis[0].get("evidence") if isinstance(parameter_analysis[0].get("evidence"), dict) else {}
        if (
            reason == "insufficient_market_regimes"
            and int(first_evidence.get("raw_regime_count") or 0) >= int(SAMPLE_THRESHOLDS["min_market_regimes"])
            and int(first_evidence.get("distinct_regime_count") or 0) < int(SAMPLE_THRESHOLDS["min_market_regimes"])
        ):
            reason = "insufficient_distinct_regime_diversity"
    recommendation = str(candidate_payload.get("recommendation") or lab.get("recommendation") or "collect_more_data")
    proposed_changes = [row for row in _as_list(candidate_payload.get("proposed_parameter_changes")) if isinstance(row, dict)]
    proposed_parameters = {
        str(row.get("parameter")): row.get("candidate_value")
        for row in proposed_changes
        if str(row.get("parameter") or "")
    }
    candidate_generation_blocker = "none" if candidate_payload.get("candidate_available") is True else _analysis_blocker(reason, parameter_analysis)
    missing_candidate_fields = _missing_candidate_fields(candidate_payload)
    first_item = parameter_analysis[0] if parameter_analysis else {}
    first_evidence = first_item.get("evidence") if isinstance(first_item.get("evidence"), dict) else {}
    candidate_available = bool(candidate_payload.get("candidate_available"))
    raw_candidate_hash = str(candidate_payload.get("hash") or stable_payload_hash(candidate_payload))
    payload = {
        "schema_version": "parameter_candidate_analysis_v1",
        "generated_at": now_iso(),
        "candidate_hash": raw_candidate_hash if candidate_available else "",
        "blocked_candidate_report_hash": "" if candidate_available else raw_candidate_hash,
        "candidate_available": candidate_available,
        "recommendation": recommendation,
        "reason": reason,
        "candidate_generation_blocker": candidate_generation_blocker,
        "missing_candidate_fields": missing_candidate_fields,
        "raw_regime_count": first_evidence.get("raw_regime_count", 0),
        "distinct_regime_count": first_evidence.get("distinct_regime_count", 0),
        "qualifying_regime_count": first_evidence.get("qualifying_regime_count", 0),
        "deduped_regime_count": first_evidence.get("deduped_regime_count", 0),
        "regime_dedup_reason": first_evidence.get("regime_dedup_reason", "none"),
        "stale_analysis_detected": False,
        "proposed_parameters": proposed_parameters,
        "parameter_changes": proposed_changes,
        "proposed_parameter_changes": proposed_changes,
        "evidence_hash": stable_payload_hash({"parameter_analysis_evidence": [item.get("evidence") for item in parameter_analysis]}),
        "safe_to_apply_now": False,
        "requires_operator_review": True,
        "live_apply_performed": False,
        "parameter_analysis_available": True,
        "parameter_analysis": parameter_analysis,
        "reflection_ledger": {
            "path": str(root / "reports/reflection/history/reflection-evaluations.jsonl"),
            "corrupt_lines": reflection_corrupt,
        },
        "parameter_pressure_ledger": {
            "path": str(root / PARAMETER_PRESSURE_LEDGER_PATH),
            "corrupt_lines": pressure_corrupt,
        },
        "growbot_river_learning": candidate_payload.get("growbot_river_learning") or (lab.get("growbot_river_learning") if isinstance(lab, dict) else {}) or {},
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_mutate_parameters": False,
    }
    payload["analysis_hash"] = stable_payload_hash(payload)
    payload["report_hash"] = payload["analysis_hash"]
    return payload


def render_parameter_candidate_analysis_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Parameter Candidate Analysis",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Candidate available: {report.get('candidate_available')}",
        f"Recommendation: {report.get('recommendation')}",
        f"Reason: {report.get('reason')}",
        f"Candidate hash: `{report.get('candidate_hash')}`",
        f"Blocked candidate report hash: `{report.get('blocked_candidate_report_hash')}`",
        "",
    ]
    for item in report.get("parameter_analysis") or []:
        evidence = item.get("evidence") or {}
        labels = item.get("label_breakdown") or {}
        pressure = item.get("pressure_summary") or {}
        explanation = item.get("pressure_explanation") or {}
        gates = item.get("statistical_gates") or {}
        gate_statuses = item.get("statistical_gate_statuses") or {}
        effect_gate = gates.get("effect_size_gate") or {}
        confidence_gate = gates.get("confidence_gate") or {}
        direction_gate = gates.get("direction_stability_gate") or {}
        regime_gate_status = "passed" if evidence.get("regime_gate_passed") else "blocked"
        lines.extend(
            [
                f"## Parameter: {item.get('parameter')}",
                f"Status: {item.get('activation_status')}",
                f"Richting: {item.get('direction')}",
                "",
                "Waarom:",
                f"- {item.get('interpretation')}",
                "",
                "Regime:",
                f"- raw regimes: {', '.join(evidence.get('raw_market_regimes') or []) or 'none'}",
                f"- adaptive/enriched regimes: {', '.join(evidence.get('adaptive_market_regimes') or []) or 'none'}",
                f"- regime sources: {', '.join(evidence.get('regime_sources') or []) or 'none'}",
                f"- ledger regime coverage: {evidence.get('ledger_regime_coverage_pct')}%",
                f"- adaptive gate regime coverage: {evidence.get('adaptive_gate_regime_coverage_pct')}%",
                f"- unique enriched regime count: {evidence.get('unique_enriched_regime_count')}",
                f"- required unique regimes: {evidence.get('required_unique_regimes')}",
                f"- regime gate: {regime_gate_status}, {evidence.get('regime_gate_reason')}",
                "",
                "Bewijs:",
                f"- total reflections: {evidence.get('total_reflections')}",
                f"- validated conclusions: {evidence.get('validated_conclusions')}",
                f"- relevante conclusies: {evidence.get('relevant_conclusions')}",
                f"- directional error labels: {evidence.get('directional_error_labels')}",
                f"- separate days: {evidence.get('separate_days')}",
                f"- out-of-sample conclusions: {evidence.get('out_of_sample_conclusions')}",
                f"- dominante labels: {', '.join(k for k, v in labels.items() if v) or 'none'}",
                f"- dominant blockers: {', '.join(evidence.get('dominant_blockers') or []) or 'none'}",
                f"- dominant tickers: {', '.join(evidence.get('dominant_tickers') or []) or 'none'}",
                f"- dominant setup_types: {', '.join(evidence.get('dominant_setup_types') or []) or 'none'}",
                "",
                "Parameterdruk:",
                f"- loosen_score: {pressure.get('loosen_score')}",
                f"- tighten_score: {pressure.get('tighten_score')}",
                f"- net pressure: {pressure.get('net_pressure')}",
                f"- supporting label count: {item.get('supporting_label_count')}",
                f"- counterweight label count: {item.get('counterweight_label_count')}",
                "",
                "Waarom is de net pressure positief?",
                f"- supporting events: {explanation.get('supporting_event_count')}",
                f"- counterweight events: {explanation.get('counterweight_event_count')}",
                f"- supporting weighted score: {explanation.get('supporting_weighted_score')}",
                f"- counterweight weighted score: {explanation.get('counterweight_weighted_score')}",
                f"- average supporting quality: {explanation.get('average_supporting_quality')}",
                f"- average counterweight quality: {explanation.get('average_counterweight_quality')}",
                f"- uitleg: {explanation.get('why_net_positive')}",
                "",
                "Effect-size:",
                f"- calculated: {effect_gate.get('calculated')}",
                f"- actual effect-size: {effect_gate.get('actual_effect_size_pct')}%",
                f"- min required: {effect_gate.get('min_required_pct')}%",
                f"- would pass: {effect_gate.get('would_pass_effect_size_gate')}",
                f"- used for activation: {effect_gate.get('used_for_activation')}",
                f"- not used because: {str(effect_gate.get('not_used_reason') or '').replace('candidate_blocked_by_', '') or 'none'}",
                "",
                "Confidence interval:",
                f"- calculated: {confidence_gate.get('calculated')}",
                f"- ci_low: {confidence_gate.get('ci_low')}",
                f"- ci_high: {confidence_gate.get('ci_high')}",
                f"- current inside CI: {confidence_gate.get('current_value_inside_ci')}",
                f"- would pass: {confidence_gate.get('would_pass_confidence_gate')}",
                f"- used for activation: {confidence_gate.get('used_for_activation')}",
                f"- not used because: {str(confidence_gate.get('not_used_reason') or '').replace('candidate_blocked_by_', '') or 'none'}",
                "",
                "Statistische gates:",
                f"- effect-size status: {gate_statuses.get('effect_size_status')}",
                f"- confidence interval status: {gate_statuses.get('confidence_interval_status')}",
                "Direction stability:",
                f"- expected scope key: {direction_gate.get('scope_key')}",
                f"- normalized scope key: {direction_gate.get('normalized_scope_key')}",
                f"- matched scope key: {direction_gate.get('matched_scope_key') or 'none'}",
                f"- match strategy: {direction_gate.get('match_strategy')}",
                f"- history items available: {direction_gate.get('history_items_available')}",
                f"- candidate history path: {direction_gate.get('candidate_history_path')}",
                f"- available scope keys: {', '.join(direction_gate.get('available_scope_keys') or []) or 'none'}",
                f"- last directions: {', '.join(direction_gate.get('last_directions') or []) or 'none'}",
                f"- observed runs: {direction_gate.get('observed_runs')}/{direction_gate.get('required_runs')}",
                f"- reason: {direction_gate.get('stability_reason')}",
                f"- shrinkage status: {json.dumps(gate_statuses.get('shrinkage_status') or {}, sort_keys=True)}",
                f"- regime enrichment status: {json.dumps(gate_statuses.get('regime_enrichment_status') or {}, sort_keys=True)}",
                "",
                "Top supporting reflection event IDs:",
                *[f"- {event_id}" for event_id in (item.get('supporting_reflection_event_ids') or ["none"])],
                "",
                "Top counterweight reflection event IDs:",
                *[f"- {event_id}" for event_id in (item.get('counterweight_reflection_event_ids') or ["none"])],
                "",
                "Besluit:",
                f"- {report.get('recommendation') if item.get('activation_status') != 'candidate' else 'candidate ready'}",
                "",
            ]
        )
    lines.extend(
        [
            "## Safety",
            "- can_authorize_execution: false",
            "- can_mutate_parameters: false",
            "- report-only analysis",
        ]
    )
    return "\n".join(lines) + "\n"


def write_parameter_candidate_analysis(report: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    json_path = root / ANALYSIS_JSON_PATH
    md_path = root / ANALYSIS_MD_PATH
    atomic_write_json(json_path, report)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(render_parameter_candidate_analysis_markdown(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path)}


__all__ = [
    "ANALYSIS_JSON_PATH",
    "ANALYSIS_MD_PATH",
    "build_parameter_candidate_analysis",
    "render_parameter_candidate_analysis_markdown",
    "write_parameter_candidate_analysis",
]
