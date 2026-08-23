from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.atomic_io import atomic_write_json
from bot.reflection_learning_context import parse_time


SOURCE_POLICY = "adaptive_policy_report_only_no_live_mutation"
REFLECTION_REPORT_PATH = Path("reports/reflection/reflection-learning-latest.json")
LAB_REPORT_PATH = Path("reports/adaptive_policy/adaptive-policy-lab-latest.json")
CANDIDATE_JSON_PATH = Path("reports/adaptive_policy/adaptive-policy-candidate-latest.json")
CANDIDATE_MD_PATH = Path("reports/adaptive_policy/adaptive-policy-candidate-latest.md")
HISTORY_PATH = Path("reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl")
GROWBOT_RIVER_REPORT_PATH = Path("reports/growbot_river/growbot-river-learning-latest.json")

# fast_start_autotune: a deliberately lower-volume bar for already-bounded,
# low-risk GrowBot/River-sourced proposals whose own per-candidate evidence
# (confidence, evidence_count, distinct regimes) is already strong. It never
# replaces or lowers the strict reflection-based candidate path (the
# SAMPLE_THRESHOLDS gates below remain unchanged for that path); it only
# stops the *orthogonal* reflection-ledger regime/volume gate from blocking a
# GrowBot/River proposal that already carries its own sufficient, independent
# evidence. A parameter must still be governor/approved-profile-routable and
# on the narrower fast_start low-risk allowlist (learnable_parameter_registry)
# for any of this to apply.
FAST_START_MIN_CONFIDENCE = 0.85
FAST_START_MIN_EVIDENCE_COUNT = 75
FAST_START_MIN_DISTINCT_REGIMES = 3
FAST_START_EFFECT_SIZE_DEADBAND_PCT = 1.0

VALIDATED_LABELS = {
    "correct_wait",
    "missed_opportunity",
    "too_strict_wait",
    "correct_avoid",
    "false_signal_avoided",
    "good_trade",
    "bad_trade",
    "early_entry",
    "late_entry",
    "good_exit",
    "bad_exit",
    "missed_exit",
    "overtrading_risk",
}
DIRECTIONAL_ERROR_LABELS = {
    "missed_opportunity",
    "too_strict_wait",
    "bad_trade",
    "early_entry",
    "late_entry",
    "bad_exit",
    "missed_exit",
    "overtrading_risk",
}
DIRECTIONAL_EVENT_LABELS = DIRECTIONAL_ERROR_LABELS | {
    "correct_avoid",
    "false_signal_avoided",
}
LOOSENING_LABELS = {"missed_opportunity", "too_strict_wait"}
COUNTERWEIGHT_LABELS = {"correct_wait", "correct_avoid", "false_signal_avoided"}
OVERTRADING_LABELS = {"overtrading_risk", "bad_trade", "early_entry"}

ALLOWED_PARAMETERS = {
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "MAX_SPREAD_PCT",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    "setup_type_specific_trigger_strictness",
    "starter_probe_eligibility_thresholds",
}
FORBIDDEN_PARAMETERS = {
    "Coinbase credentials",
    "EXECUTION_MODE",
    "ENABLE_FULL_WORKFLOW_LIVE_MODE",
    "REPLICATION_ENABLED",
    "REPLICATION_LIFECYCLE_ENABLED",
    "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED",
    "LEARNING_TO_EXECUTION_ALLOWED",
    "LIVE_LEARNING_ALLOWED",
    "PARAMETER_CHANGE_ALLOWED",
    "MODE_B_CONTROLLED_STOP_EXIT_ACK",
    "MODE_C_MARKET_ORDER_ACK",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
    "ENABLE_LIVE_EXIT_ORDERS",
    "no-naked-sell guards",
    "oversell guards",
    "D2/D3 enablement",
    "lifecycle apply flags",
}

SAMPLE_THRESHOLDS = {
    "min_total_validated_conclusions": 300,
    "min_relevant_conclusions_per_parameter": 150,
    "min_directional_error_labels": 40,
    "min_separate_days": 7,
    "min_market_regimes": 2,
    "min_tickers_per_general_change": 3,
    "min_out_of_sample_conclusions": 75,
    "default_single_step_param_change_pct": 5,
    "max_single_step_param_change_pct": 10,
    "min_effect_size_pct": 5,
    "confidence_buffer_pct": 3,
    "require_direction_stability_runs": 3,
    "require_confidence_interval_excludes_current": True,
    "shrinkage_factor": 0.50,
    "min_regime_enrichment_coverage_pct": 80,
}

CURRENT_PARAMETER_DEFAULTS = {
    "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125",
    "PHASE_D2_MIN_REWARD_TO_FEE_RATIO": "3.0",
    "PHASE_D2_MIN_REWARD_TO_RISK_RATIO": "1.5",
    "MAX_SPREAD_PCT": "0.0060",
    "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT": "0.0350",
    "setup_type_specific_trigger_strictness": "1.0",
    "starter_probe_eligibility_thresholds": "1.0",
}

LABEL_PRESSURE_WEIGHTS = {
    "too_strict_wait": ("loosen", 1.00),
    "missed_opportunity": ("loosen", 0.75),
    "good_trade": ("loosen", 0.10),
    "correct_wait": ("tighten", 0.10),
    "correct_avoid": ("tighten", 0.50),
    "false_signal_avoided": ("tighten", 0.75),
    "bad_trade": ("tighten", 1.00),
    "early_entry": ("tighten", 0.85),
    "overtrading_risk": ("tighten", 1.00),
}

PARAMETER_BLOCKER_MAP = {
    "expected_net_edge_too_low": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
    "reward_to_fee_too_low": "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
    "reward_to_risk_too_low": "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
    "spread_too_high": "MAX_SPREAD_PCT",
    "exit_target_too_far": "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    "target_distance": "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
    "trigger_ready_too_strict": "setup_type_specific_trigger_strictness",
    "probe_candidate_rejected_cost": "starter_probe_eligibility_thresholds",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    if out != out or out in (float("inf"), float("-inf")):
        return None
    return out


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _load_market_intelligence_context(root: Path) -> Dict[str, Any]:
    return _load_json(root / "state/market_intelligence_context.json")


def load_reflection_report(root: Path = Path("."), path: Path = REFLECTION_REPORT_PATH) -> Dict[str, Any]:
    return _load_json(root / path)


def load_growbot_river_learning_report(root: Path = Path("."), path: Path = GROWBOT_RIVER_REPORT_PATH) -> Dict[str, Any]:
    """Load the optional sidecar report as untrusted supplemental evidence.

    The sidecar is never an execution authority.  A malformed or unsafe report
    is ignored rather than weakening the reflection-based candidate process.
    """
    payload = _load_json(root / path)
    safety = _as_dict(payload.get("safety_policy"))
    if (
        not payload
        or safety.get("parameter_mutation_allowed") is not False
        or safety.get("execution_authority") is not False
        or safety.get("C43_D3_bypass_allowed") is not False
    ):
        return {}
    return payload


def stable_payload_hash(payload: Dict[str, Any]) -> str:
    clone = deepcopy(payload)
    clone.pop("hash", None)
    clone.pop("generated_at", None)
    clone.pop("outputs", None)
    encoded = json.dumps(clone, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _clean_regime(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    if not text or text in {"none", "null", "unknown"}:
        return ""
    return text


def _regime_key_design() -> str:
    return os.getenv("ADAPTIVE_REGIME_KEY_DESIGN", "network_liquidity_trend_volatility_v2").strip() or "network_liquidity_trend_volatility_v2"


def _infer_candle_regimes(conclusion: Dict[str, Any], candle_context: Optional[Dict[str, Any]]) -> Tuple[str, str]:
    candle = _as_dict(candle_context) or _as_dict(conclusion.get("candle_context"))
    trend = _clean_regime(candle.get("trend_regime") or candle.get("trend") or conclusion.get("trend_regime"))
    volatility = _clean_regime(candle.get("volatility_regime") or candle.get("volatility") or conclusion.get("volatility_regime"))
    recent_trend = _as_float(candle.get("recent_trend_pct") or conclusion.get("recent_trend_pct"))
    if not trend and recent_trend is not None:
        if recent_trend > 0.01:
            trend = "bullish"
        elif recent_trend < -0.01:
            trend = "bearish"
        else:
            trend = "flat"
    atr_pct = _as_float(candle.get("atr_pct") or candle.get("volatility_pct") or conclusion.get("atr_pct"))
    if not volatility and atr_pct is not None:
        volatility = "high" if atr_pct >= 0.03 else ("low" if atr_pct <= 0.005 else "normal")
    return trend, volatility


def _adaptive_regime_key(*, network: str, liquidity: str, trend: str, volatility: str, design: Optional[str] = None) -> str:
    key_design = design or _regime_key_design()
    if key_design in {"legacy", "network_liquidity_v1"}:
        if network != "unknown" or liquidity != "unknown":
            return f"network_{network}_liquidity_{liquidity}"
        if trend != "unknown" or volatility != "unknown":
            return f"trend_{trend}_volatility_{volatility}"
        return "unknown"
    return f"network_{network}_liquidity_{liquidity}_trend_{trend}_volatility_{volatility}"


def canonical_regime_key(regime: Any) -> str:
    text = _clean_regime(regime) or "unknown"
    parts = text.split("_")
    if len(parts) == 4 and parts[0] == "network" and parts[2] == "liquidity":
        return f"network_{parts[1]}_liquidity_{parts[3]}_trend_unknown_volatility_unknown"
    return text


def regime_diversity_diagnostics(regimes: Sequence[Any], *, required: Optional[int] = None) -> Dict[str, Any]:
    raw = sorted({_clean_regime(regime) or "unknown" for regime in regimes if str(regime or "").strip()})
    canonical_by_regime = {regime: canonical_regime_key(regime) for regime in raw}
    distinct = sorted(set(canonical_by_regime.values()))
    deduped_count = max(0, len(raw) - len(distinct))
    reasons: List[str] = []
    if deduped_count:
        reasons.append("legacy_network_liquidity_key_matches_v2_unknown_trend_volatility_key")
    if any(regime.endswith("_trend_unknown_volatility_unknown") for regime in distinct):
        reasons.append("trend_or_volatility_unknown_limits_distinct_regime_diversity")
    if not reasons:
        reasons.append("none")
    min_required = int(required if required is not None else SAMPLE_THRESHOLDS["min_market_regimes"])
    return {
        "raw_regime_count": len(raw),
        "distinct_regime_count": len(distinct),
        "qualifying_regime_count": len(distinct),
        "deduped_regime_count": deduped_count,
        "raw_regimes": raw,
        "distinct_regimes": distinct,
        "canonical_regime_by_raw_regime": canonical_by_regime,
        "regime_dedup_reason": ",".join(reasons),
        "required_distinct_regime_count": min_required,
        "distinct_regime_gate_passed": len(distinct) >= min_required,
        "additional_regime_features_needed": [
            "trend != unknown",
            "volatility != unknown",
            "liquidity shift",
            "risk-on/risk-off",
            "breakout/range/reversal context",
        ],
    }


def build_regime_enrichment_fields(
    conclusion: Dict[str, Any],
    market_intelligence_context: Optional[Dict[str, Any]] = None,
    candle_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    raw_market_regime = _clean_regime(conclusion.get("raw_market_regime") or conclusion.get("market_regime") or conclusion.get("regime")) or "unknown"
    explicit_adaptive = _clean_regime(conclusion.get("adaptive_market_regime"))
    liquidity = _clean_regime(conclusion.get("liquidity_regime")) or "unknown"
    network = _clean_regime(conclusion.get("network_regime")) or "unknown"
    trend = _clean_regime(conclusion.get("trend_regime")) or "unknown"
    volatility = _clean_regime(conclusion.get("volatility_regime")) or "unknown"
    inferred_trend, inferred_volatility = _infer_candle_regimes(conclusion, candle_context)
    if inferred_trend:
        trend = inferred_trend
    if inferred_volatility:
        volatility = inferred_volatility
    key_design = _regime_key_design()

    if explicit_adaptive:
        return {
            "raw_market_regime": raw_market_regime,
            "adaptive_market_regime": explicit_adaptive,
            "market_regime": raw_market_regime,
            "liquidity_regime": liquidity,
            "network_regime": network,
            "trend_regime": trend,
            "volatility_regime": volatility,
            "regime_source": "reflection",
            "regime_key_design": "historical_explicit",
            "regime_enriched": explicit_adaptive != raw_market_regime,
        }

    if raw_market_regime != "unknown":
        if network != "unknown" or liquidity != "unknown" or trend != "unknown" or volatility != "unknown":
            adaptive = _adaptive_regime_key(network=network, liquidity=liquidity, trend=trend, volatility=volatility, design=key_design)
            source = "reflection_plus_enriched_context"
            enriched = adaptive != raw_market_regime
        else:
            adaptive = raw_market_regime
            source = "reflection"
            enriched = False
        return {
            "raw_market_regime": raw_market_regime,
            "adaptive_market_regime": adaptive,
            "market_regime": raw_market_regime,
            "liquidity_regime": liquidity,
            "network_regime": network,
            "trend_regime": trend,
            "volatility_regime": volatility,
            "regime_source": source,
            "regime_key_design": key_design if enriched else "raw_market_regime_v1",
            "regime_enriched": enriched,
        }

    mi_summary = _as_dict(_as_dict(market_intelligence_context).get("summary"))
    network = _clean_regime(mi_summary.get("network_regime") or conclusion.get("network_regime")) or network
    liquidity = _clean_regime(mi_summary.get("liquidity_regime") or conclusion.get("liquidity_regime")) or liquidity
    network = network or "unknown"
    liquidity = liquidity or "unknown"
    if network != "unknown" or liquidity != "unknown" or trend != "unknown" or volatility != "unknown":
        adaptive = _adaptive_regime_key(network=network, liquidity=liquidity, trend=trend, volatility=volatility, design=key_design)
        source_parts = []
        if network != "unknown" or liquidity != "unknown":
            source_parts.append("market_intelligence")
        if trend != "unknown" or volatility != "unknown":
            source_parts.append("candle_context")
        return {
            "raw_market_regime": raw_market_regime,
            "adaptive_market_regime": adaptive,
            "market_regime": raw_market_regime,
            "liquidity_regime": liquidity,
            "network_regime": network,
            "trend_regime": trend,
            "volatility_regime": volatility,
            "regime_source": "+".join(source_parts) or "derived_context",
            "regime_key_design": key_design,
            "regime_enriched": True,
        }

    return {
        "raw_market_regime": raw_market_regime,
        "adaptive_market_regime": "unknown",
        "market_regime": raw_market_regime,
        "liquidity_regime": liquidity,
        "network_regime": network or "unknown",
        "trend_regime": trend or "unknown",
        "volatility_regime": volatility or "unknown",
        "regime_source": "unknown",
        "regime_key_design": key_design,
        "regime_enriched": False,
    }


def enrich_conclusion_market_regime(
    conclusion: Dict[str, Any],
    market_intelligence_context: Optional[Dict[str, Any]] = None,
    candle_context: Optional[Dict[str, Any]] = None,
) -> str:
    return str(build_regime_enrichment_fields(conclusion, market_intelligence_context, candle_context)["adaptive_market_regime"])


def _market_regime(ev: Dict[str, Any]) -> str:
    for key in ("adaptive_market_regime", "market_regime", "liquidity_regime", "network_regime", "crowd_regime"):
        value = _clean_regime(ev.get(key))
        if value:
            return value
    warnings = ev.get("market_intelligence_risk_warnings")
    if isinstance(warnings, list) and warnings:
        return "risk_warning"
    return "unknown"


def _enrich_rows(rows: Sequence[Dict[str, Any]], market_intelligence_context: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched = []
    for row in rows:
        clone = dict(row)
        clone.update(build_regime_enrichment_fields(clone, market_intelligence_context, _as_dict(clone.get("candle_context"))))
        enriched.append(clone)
    return enriched


def regime_enrichment_report(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    regimes = [_market_regime(row) for row in rows]
    known = [regime for regime in regimes if regime != "unknown"]
    coverage = (len(known) / len(regimes) * 100.0) if regimes else 0.0
    return {
        "coverage_pct": round(coverage, 4),
        "min_coverage_pct": SAMPLE_THRESHOLDS["min_regime_enrichment_coverage_pct"],
        "market_regimes": sorted(set(regimes)) if regimes else [],
        "passed": coverage >= SAMPLE_THRESHOLDS["min_regime_enrichment_coverage_pct"],
    }


def is_validated_conclusion(ev: Dict[str, Any]) -> bool:
    if not isinstance(ev, dict):
        return False
    label = str(ev.get("label") or "")
    if label not in VALIDATED_LABELS:
        return False
    if ev.get("available") is False:
        return False
    if not parse_time(ev.get("decision_time")):
        return False
    if not str(ev.get("ticker") or "").strip():
        return False
    if ev.get("setup_type") in (None, "") and ev.get("main_blocker") in (None, ""):
        return False
    required = [
        "future_window_hours",
        "max_favorable_excursion_pct",
        "max_adverse_excursion_pct",
        "estimated_roundtrip_fee_pct",
        "estimated_spread_cost_pct",
        "estimated_slippage_buffer_pct",
        "estimated_net_after_cost_opportunity_pct",
    ]
    if any(_as_float(ev.get(key)) is None for key in required):
        return False
    reason = str(ev.get("reason") or "")
    if not reason:
        return False
    return True


def validated_conclusions(reflection_report: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = reflection_report.get("evaluations") if isinstance(reflection_report.get("evaluations"), list) else []
    return [ev for ev in rows if is_validated_conclusion(ev)]


def _split_oos(rows: Sequence[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    dated = []
    for row in rows:
        dt = parse_time(row.get("decision_time"))
        if dt:
            dated.append((dt, row))
    dated.sort(key=lambda item: item[0])
    if not dated:
        return [], []
    cut = max(0, int(len(dated) * 0.7))
    return [row for _, row in dated[:cut]], [row for _, row in dated[cut:]]


def _evidence_summary(rows: Sequence[Dict[str, Any]], *, relevant_rows: Optional[Sequence[Dict[str, Any]]] = None) -> Dict[str, Any]:
    relevant = list(relevant_rows if relevant_rows is not None else rows)
    days = {
        parse_time(row.get("decision_time")).date().isoformat()
        for row in relevant
        if parse_time(row.get("decision_time"))
    }
    regimes = sorted({_market_regime(row) for row in relevant})
    tickers = sorted({str(row.get("ticker") or "").upper() for row in relevant if row.get("ticker")})
    _ins, oos = _split_oos(relevant)
    labels = Counter(str(row.get("label")) for row in relevant)
    regime_counts: Dict[str, Dict[str, int]] = {}
    for row in relevant:
        regime = _market_regime(row)
        item = regime_counts.setdefault(regime, {"validated_conclusions": 0, "directional_events": 0, "directional_error_labels": 0})
        item["validated_conclusions"] += 1
        label = str(row.get("label") or "")
        if label in DIRECTIONAL_EVENT_LABELS:
            item["directional_events"] += 1
        if label in DIRECTIONAL_ERROR_LABELS:
            item["directional_error_labels"] += 1
    return {
        "total_validated_conclusions": len(rows),
        "relevant_conclusions": len(relevant),
        "directional_error_labels": sum(labels[label] for label in DIRECTIONAL_ERROR_LABELS),
        "total_directional_events": sum(labels[label] for label in DIRECTIONAL_EVENT_LABELS),
        "directional_event_labels": {label: labels[label] for label in sorted(DIRECTIONAL_EVENT_LABELS) if labels[label]},
        "directional_event_count_method": "validated_conclusions_with_directional_or_counter_directional_labels",
        "separate_days": len(days),
        "market_regimes": regimes,
        "regime_counts": dict(sorted(regime_counts.items())),
        "tickers": tickers,
        "out_of_sample_conclusions": len(oos),
        "label_counts": dict(labels),
    }


def _group_key(row: Dict[str, Any]) -> str:
    setup = str(row.get("setup_type") or "unknown").strip() or "unknown"
    blocker = str(row.get("main_blocker") or "").strip().lower()
    if "trigger_ready" in blocker or "threshold" in blocker or "strict" in blocker:
        return "blocker_specific:trigger_ready_or_threshold"
    return f"setup_type_specific:{setup}"


def _trim(values: List[float], pct: float = 0.10) -> List[float]:
    if not values:
        return []
    ordered = sorted(values)
    cut = int(len(ordered) * pct)
    if cut == 0 and len(ordered) >= 5:
        cut = 1
    if cut <= 0 or len(ordered) <= cut * 2:
        return ordered
    return ordered[cut:-cut]


def _winsor(values: List[float], pct: float = 0.10) -> List[float]:
    if not values:
        return []
    ordered = sorted(values)
    cut = int(len(ordered) * pct)
    if cut == 0 and len(ordered) >= 5:
        cut = 1
    if cut <= 0 or len(ordered) <= cut * 2:
        return ordered
    low = ordered[cut]
    high = ordered[-cut - 1]
    return [min(max(v, low), high) for v in ordered]


def robust_stats(values: Sequence[float]) -> Dict[str, Any]:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return {
            "raw_mean": None,
            "median": None,
            "trimmed_mean_10pct": None,
            "winsorized_mean": None,
            "confidence_interval": [None, None],
            "outlier_count": 0,
            "sample_count": 0,
        }
    trimmed = _trim(clean, 0.10)
    winsorized = _winsor(clean, 0.10)
    q1 = clean[len(clean) // 4]
    q3 = clean[(len(clean) * 3) // 4]
    iqr = q3 - q1
    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    outliers = [v for v in clean if v < low or v > high]
    return {
        "raw_mean": mean(clean),
        "median": median(clean),
        "trimmed_mean_10pct": mean(trimmed),
        "winsorized_mean": mean(winsorized),
        "confidence_interval": [clean[max(0, int(len(clean) * 0.025))], clean[min(len(clean) - 1, int(len(clean) * 0.975))]],
        "outlier_count": len(outliers),
        "sample_count": len(clean),
    }


def conservative_step_toward(current: float, target: float, *, default_cap_pct: float = 5.0, hard_cap_pct: float = 10.0) -> tuple[float, float]:
    if current <= 0:
        return target, 0.0
    max_pct = min(abs(float(default_cap_pct)), abs(float(hard_cap_pct)))
    desired_pct = ((target - current) / current) * 100.0
    applied_pct = max(-max_pct, min(max_pct, desired_pct))
    hard_max = abs(float(hard_cap_pct))
    applied_pct = max(-hard_max, min(hard_max, applied_pct))
    return current * (1.0 + applied_pct / 100.0), applied_pct


def passes_effect_size_gate(current_value: float, robust_target_value: Optional[float], *, min_effect_size_pct: float) -> Dict[str, Any]:
    if robust_target_value is None or current_value <= 0:
        return {"min_effect_size_pct": min_effect_size_pct, "actual_effect_size_pct": None, "passed": False}
    effect = abs(float(robust_target_value) - float(current_value)) / float(current_value) * 100.0
    return {
        "min_effect_size_pct": min_effect_size_pct,
        "actual_effect_size_pct": round(effect, 6),
        "passed": effect >= float(min_effect_size_pct),
    }


def confidence_interval_excludes_current(
    current_value: float,
    ci_low: Optional[float],
    ci_high: Optional[float],
    direction: str,
    *,
    require_ci_excludes_current: bool = True,
) -> Dict[str, Any]:
    current_inside = True
    passed = not require_ci_excludes_current
    if ci_low is not None and ci_high is not None:
        low = float(ci_low)
        high = float(ci_high)
        current_inside = low <= float(current_value) <= high
        if direction == "loosen":
            passed = high < float(current_value)
        elif direction == "tighten":
            passed = low > float(current_value)
        else:
            passed = False
    return {
        "require_ci_excludes_current": require_ci_excludes_current,
        "ci_low": ci_low,
        "ci_high": ci_high,
        "current_value_inside_ci": current_inside,
        "passed": bool(passed),
    }


def apply_shrinkage(current_value: float, capped_value: float, *, shrinkage_factor: float) -> float:
    factor = max(0.0, min(1.0, float(shrinkage_factor)))
    return float(current_value) + (float(capped_value) - float(current_value)) * factor


def load_candidate_history(root: Path = Path("."), path: Path = HISTORY_PATH) -> List[Dict[str, Any]]:
    history_path = root / path
    if not history_path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in history_path.read_text(encoding="utf-8").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def normalize_parameter_scope_key(parameter: str, scope: Optional[str]) -> str:
    normalized_scope = str(scope or "").strip()
    if normalized_scope in {"", "none", "global", "candidate", "adaptive_policy_lab"}:
        normalized_scope = "adaptive_policy_lab"
    return f"{str(parameter or '').strip()}|{normalized_scope}"


def _split_parameter_scope_key(scope_key: str) -> Tuple[str, str]:
    parameter, sep, scope = str(scope_key or "").partition("|")
    return parameter.strip(), scope.strip() if sep else ""


def _available_direction_scope_keys(history: Sequence[Dict[str, Any]]) -> List[str]:
    keys = set()
    for item in history:
        directions = _as_dict(item.get("direction_by_parameter_scope"))
        keys.update(str(key) for key in directions if str(key))
    return sorted(keys)


def _direction_scope_match(scope_key: str, available_scope_keys: Sequence[str]) -> Dict[str, Any]:
    parameter, scope = _split_parameter_scope_key(scope_key)
    normalized_scope_key = normalize_parameter_scope_key(parameter, scope)
    available = sorted({str(key) for key in available_scope_keys if str(key)})
    if scope_key in available:
        return {
            "normalized_scope_key": normalized_scope_key,
            "available_scope_keys": available,
            "matched_scope_key": scope_key,
            "matched_scope_keys": [scope_key],
            "match_strategy": "exact",
        }

    canonical_matches = []
    parameter_matches = []
    normalized_scope_by_key: Dict[str, str] = {}
    for key in available:
        item_parameter, item_scope = _split_parameter_scope_key(key)
        if item_parameter != parameter:
            continue
        parameter_matches.append(key)
        item_normalized = normalize_parameter_scope_key(item_parameter, item_scope)
        normalized_scope_by_key[key] = item_normalized
        if item_normalized == normalized_scope_key:
            canonical_matches.append(key)
    if canonical_matches:
        return {
            "normalized_scope_key": normalized_scope_key,
            "available_scope_keys": available,
            "matched_scope_key": canonical_matches[0],
            "matched_scope_keys": canonical_matches,
            "match_strategy": "normalized",
        }
    unique_normalized_scopes = sorted(set(normalized_scope_by_key.values()))
    if len(unique_normalized_scopes) == 1 and parameter_matches:
        return {
            "normalized_scope_key": normalized_scope_key,
            "available_scope_keys": available,
            "matched_scope_key": parameter_matches[0],
            "matched_scope_keys": parameter_matches,
            "match_strategy": "parameter_unique",
        }
    if len(unique_normalized_scopes) > 1:
        return {
            "normalized_scope_key": normalized_scope_key,
            "available_scope_keys": available,
            "matched_scope_key": "",
            "matched_scope_keys": [],
            "match_strategy": "ambiguous",
        }
    return {
        "normalized_scope_key": normalized_scope_key,
        "available_scope_keys": available,
        "matched_scope_key": "",
        "matched_scope_keys": [],
        "match_strategy": "not_found",
    }


def direction_stability_for(scope_key: str, direction: str, history: Sequence[Dict[str, Any]], *, required_runs: int) -> Dict[str, Any]:
    observed = 0
    last_directions: List[str] = []
    reason = "not_enough_history"
    available_scope_keys = _available_direction_scope_keys(history)
    match = _direction_scope_match(scope_key, available_scope_keys)
    matched_scope_keys = set(match["matched_scope_keys"])
    found_scope = False
    if direction:
        for item in reversed(list(history)):
            directions = _as_dict(item.get("direction_by_parameter_scope"))
            matched_key = next((key for key in matched_scope_keys if key in directions), "")
            if not matched_key:
                continue
            found_scope = True
            item_direction = str(directions.get(matched_key) or "")
            last_directions.append(item_direction)
            if item_direction == direction:
                observed += 1
                if observed >= required_runs:
                    break
            else:
                reason = "direction_changed"
                break
    if match["match_strategy"] == "ambiguous":
        reason = "ambiguous_scope_keys"
    elif not found_scope and history:
        reason = "scope_key_not_found"
    passed = observed >= required_runs
    if passed:
        reason = "stable"
    return {
        "scope_key": scope_key,
        "normalized_scope_key": match["normalized_scope_key"],
        "required_runs": required_runs,
        "observed_runs": observed,
        "history_items_available": len(history),
        "available_scope_keys": match["available_scope_keys"],
        "matched_scope_key": match["matched_scope_key"],
        "matched_scope_keys": match["matched_scope_keys"],
        "match_strategy": match["match_strategy"],
        "last_directions": last_directions[:required_runs],
        "required_direction": direction,
        "current_direction": direction,
        "stability_reason": reason,
        "passed": passed,
    }


def direction_by_parameter_scope(changes: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for change in changes:
        parameter = str(change.get("parameter") or "")
        scope = str(change.get("scope") or "")
        if not parameter or not scope:
            continue
        direction = str(change.get("direction") or "")
        if not direction:
            pct = _as_float(change.get("change_pct"))
            if pct is not None:
                direction = "loosen" if pct < 0 else ("tighten" if pct > 0 else "neutral")
            else:
                current = _as_float(change.get("current_value"))
                target = _as_float(change.get("robust_target_value") or change.get("trimmed_mean_suggested_value") or change.get("median_suggested_value"))
                if current is not None and target is not None:
                    direction = "loosen" if target < current else ("tighten" if target > current else "neutral")
        if direction and direction != "neutral":
            out[f"{parameter}|{scope}"] = direction
    return out


def append_candidate_history(candidate: Dict[str, Any], *, root: Path = Path("."), path: Path = HISTORY_PATH) -> None:
    history_path = root / path
    history_path.parent.mkdir(parents=True, exist_ok=True)
    directions = candidate.get("direction_by_parameter_scope") or direction_by_parameter_scope(
        list(candidate.get("proposed_parameter_changes") or []) + list(candidate.get("blocked_parameter_changes") or [])
    )
    item = {
        "generated_at": candidate.get("generated_at"),
        "candidate_available": bool(candidate.get("candidate_available")),
        "recommendation": candidate.get("recommendation"),
        "direction_by_parameter_scope": directions,
        "hash": candidate.get("hash"),
    }
    with history_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item, sort_keys=True, separators=(",", ":")) + "\n")


def _current_parameters(root: Path) -> Dict[str, str]:
    data = _load_json(root / "state/approved_parameter_profile.json")
    params = data.get("parameters") if isinstance(data.get("parameters"), dict) else {}
    out = dict(CURRENT_PARAMETER_DEFAULTS)
    for key in CURRENT_PARAMETER_DEFAULTS:
        if key in params:
            out[key] = str(params[key])
    return out


def map_pressure_to_parameter(row: Dict[str, Any]) -> str:
    text = " ".join(
        str(row.get(key) or "").strip().lower()
        for key in ("main_blocker", "blocker", "reason", "setup_type")
    )
    for marker, parameter in PARAMETER_BLOCKER_MAP.items():
        if marker in text:
            return parameter
    return "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"


def _quality_component(value: Any, default: float = 1.0) -> float:
    parsed = _as_float(value)
    if parsed is None:
        return default
    return max(0.0, min(1.0, parsed))


def _conclusion_quality_score(row: Dict[str, Any]) -> float:
    confidence = _quality_component(row.get("confidence"), 0.75)
    setup_visibility = 1.0 if str(row.get("setup_type") or "").strip() else 0.6
    fillability = 1.0
    if row.get("fillable_entry_estimate") is False or row.get("fillable_exit_estimate") is False:
        fillability = 0.5
    net = _as_float(row.get("estimated_net_after_cost_opportunity_pct")) or 0.0
    cost_score = max(0.0, min(1.0, net / 0.02)) if net > 0 else 0.25
    mae = abs(_as_float(row.get("max_adverse_excursion_pct")) or 0.0)
    drawdown_safety = max(0.25, min(1.0, 1.0 - (mae / 0.05)))
    regime_weight = 0.75 if _market_regime(row) == "unknown" else 1.0
    return confidence * setup_visibility * fillability * cost_score * drawdown_safety * regime_weight


def label_pressure(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    loosen = 0.0
    tighten = 0.0
    labels = Counter(str(row.get("label") or "") for row in rows)
    for row in rows:
        label = str(row.get("label") or "")
        mapped = LABEL_PRESSURE_WEIGHTS.get(label)
        if not mapped:
            continue
        direction, weight = mapped
        score = weight * _conclusion_quality_score(row)
        if direction == "loosen":
            loosen += score
        else:
            tighten += score
    return {
        "loosen_score": round(loosen, 6),
        "tighten_score": round(tighten, 6),
        "net_pressure": round(loosen - tighten, 6),
        "dominant_labels": [label for label, _count in labels.most_common(5) if label],
    }


def _suggested_values_for_edge(rows: Sequence[Dict[str, Any]], current: float) -> List[float]:
    values = []
    for row in rows:
        net = _as_float(row.get("estimated_net_after_cost_opportunity_pct")) or 0.0
        mae = abs(_as_float(row.get("max_adverse_excursion_pct")) or 0.0)
        if net <= 0:
            continue
        # A missed opportunity with positive net edge suggests the threshold may
        # have been above the observable edge. Move only halfway toward observed
        # edge and penalize MAE, leaving final capping to conservative_step_toward.
        implied = max(0.0001, min(current, current - (net * 0.5) + (mae * 0.15)))
        values.append(implied)
    return values


def _candidate_for_group(
    root: Path,
    scope: str,
    rows: Sequence[Dict[str, Any]],
    total_rows: Sequence[Dict[str, Any]],
    *,
    history: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    current_params = _current_parameters(root)
    parameter_votes = Counter(map_pressure_to_parameter(row) for row in rows)
    parameter = parameter_votes.most_common(1)[0][0] if parameter_votes else "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"
    if parameter not in ALLOWED_PARAMETERS:
        parameter = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"
    current_value = float(current_params.get(parameter) or CURRENT_PARAMETER_DEFAULTS.get(parameter) or "1.0")
    labels = Counter(str(row.get("label")) for row in rows)
    summary = _evidence_summary(total_rows, relevant_rows=rows)
    diversity = regime_diversity_diagnostics(summary["market_regimes"])
    blockers: List[str] = []
    if summary["relevant_conclusions"] < SAMPLE_THRESHOLDS["min_relevant_conclusions_per_parameter"]:
        blockers.append("insufficient_relevant_conclusions_per_parameter")
    if summary["directional_error_labels"] < SAMPLE_THRESHOLDS["min_directional_error_labels"]:
        blockers.append("insufficient_directional_error_labels")
    if summary["separate_days"] < SAMPLE_THRESHOLDS["min_separate_days"]:
        blockers.append("insufficient_separate_days")
    if not diversity["distinct_regime_gate_passed"]:
        blockers.append(
            "insufficient_distinct_regime_diversity"
            if diversity["raw_regime_count"] >= SAMPLE_THRESHOLDS["min_market_regimes"]
            else "insufficient_market_regimes"
        )
    if summary["out_of_sample_conclusions"] < SAMPLE_THRESHOLDS["min_out_of_sample_conclusions"]:
        blockers.append("insufficient_out_of_sample_conclusions")
    if labels["overtrading_risk"] or labels["bad_trade"] or labels["early_entry"]:
        blockers.append("overtrading_risk_present")
    if any((_as_float(row.get("estimated_net_after_cost_opportunity_pct")) or 0.0) <= 0 for row in rows if row.get("label") in LOOSENING_LABELS):
        blockers.append("cost_aware_negative_net_opportunity_present")

    suggested_values = _suggested_values_for_edge([r for r in rows if r.get("label") in LOOSENING_LABELS], current_value)
    stats = robust_stats(suggested_values)
    if not suggested_values:
        blockers.append("no_positive_cost_aware_suggestions")

    correct_counterweight = labels["correct_wait"] + labels["correct_avoid"]
    false_signal_counterweight = labels["false_signal_avoided"]
    directional = labels["missed_opportunity"] + labels["too_strict_wait"]
    counterweight_ratio = correct_counterweight / max(1, directional + correct_counterweight)
    if counterweight_ratio > 0.80:
        blockers.append("correct_wait_counterweight_too_high")

    pressure = label_pressure(rows)
    robust_target = stats["trimmed_mean_10pct"] if stats["trimmed_mean_10pct"] is not None else stats["median"]
    direction = ""
    if robust_target is not None:
        direction = "loosen" if robust_target < current_value else ("tighten" if robust_target > current_value else "neutral")
    if direction == "loosen" and pressure["net_pressure"] <= 0:
        blockers.append("label_pressure_does_not_support_loosening")
    if direction == "tighten" and pressure["net_pressure"] >= 0:
        blockers.append("label_pressure_does_not_support_tightening")

    effect_gate = passes_effect_size_gate(
        current_value,
        robust_target,
        min_effect_size_pct=SAMPLE_THRESHOLDS["min_effect_size_pct"],
    )
    if not effect_gate["passed"]:
        blockers.append("effect_size_below_deadband")

    ci_low, ci_high = (stats.get("confidence_interval") or [None, None])
    confidence_gate = confidence_interval_excludes_current(
        current_value,
        ci_low,
        ci_high,
        direction,
        require_ci_excludes_current=bool(SAMPLE_THRESHOLDS["require_confidence_interval_excludes_current"]),
    )
    if not confidence_gate["passed"]:
        blockers.append("confidence_interval_overlaps_current_value")

    scope_key = f"{parameter}|{scope}"
    stability_gate = direction_stability_for(
        scope_key,
        direction,
        history,
        required_runs=int(SAMPLE_THRESHOLDS["require_direction_stability_runs"]),
    )
    if not stability_gate["passed"]:
        blockers.append("direction_stability_not_met")

    if robust_target is None:
        candidate_value = current_value
        change_pct = 0.0
        capped_value = current_value
        capped_change_pct = 0.0
    else:
        damped_target = current_value + (robust_target - current_value) * max(0.25, 1.0 - counterweight_ratio)
        capped_value, capped_change_pct = conservative_step_toward(
            current_value,
            damped_target,
            default_cap_pct=SAMPLE_THRESHOLDS["default_single_step_param_change_pct"],
            hard_cap_pct=SAMPLE_THRESHOLDS["max_single_step_param_change_pct"],
        )
        candidate_value = apply_shrinkage(
            current_value,
            capped_value,
            shrinkage_factor=SAMPLE_THRESHOLDS["shrinkage_factor"],
        )
        change_pct = ((candidate_value - current_value) / current_value * 100.0) if current_value else 0.0

    base = {
        "parameter": parameter,
        "scope": scope,
        "current_value": f"{current_value:.6f}".rstrip("0").rstrip("."),
        "raw_mean_suggested_value": _fmt(stats["raw_mean"]),
        "trimmed_mean_suggested_value": _fmt(stats["trimmed_mean_10pct"]),
        "median_suggested_value": _fmt(stats["median"]),
        "winsorized_mean_suggested_value": _fmt(stats["winsorized_mean"]),
        "robust_target_value": _fmt(robust_target),
        "candidate_value": _fmt(candidate_value),
        "candidate_uncapped_after_step_cap": _fmt(capped_value),
        "candidate_value_after_shrinkage": _fmt(candidate_value),
        "shrinkage_factor": SAMPLE_THRESHOLDS["shrinkage_factor"],
        "change_pct": round(change_pct, 4),
        "change_pct_before_shrinkage": round(capped_change_pct, 4),
        "direction": direction,
        "sample_count": summary["relevant_conclusions"],
        "directional_error_labels": summary["directional_error_labels"],
        "separate_days": summary["separate_days"],
        "market_regimes": summary["market_regimes"],
        "regime_diversity": diversity,
        "tickers": summary["tickers"],
        "out_of_sample_conclusions": summary["out_of_sample_conclusions"],
        "net_after_cost_effect": _distribution([_as_float(r.get("estimated_net_after_cost_opportunity_pct")) for r in rows]),
        "overtrading_risk_effect": labels["overtrading_risk"] + labels["bad_trade"] + labels["early_entry"],
        "correct_wait_counterweight": correct_counterweight,
        "false_signal_counterweight": false_signal_counterweight,
        "robust_stats": stats,
        "label_pressure": pressure,
        "effect_size_gate": effect_gate,
        "confidence_gate": confidence_gate,
        "direction_stability_gate": stability_gate,
        "shrinkage": {
            "factor": SAMPLE_THRESHOLDS["shrinkage_factor"],
            "candidate_uncapped_after_step_cap": _fmt(capped_value),
            "candidate_value_after_shrinkage": _fmt(candidate_value),
        },
        "max_step_change_pct_applied": SAMPLE_THRESHOLDS["default_single_step_param_change_pct"],
        "safe_to_activate_now": False,
        "requires_operator_review": True,
        "blockers": blockers,
        "confidence": "medium" if not blockers and summary["relevant_conclusions"] >= 150 else "low",
    }
    return base


def _growbot_river_supplemental_changes(
    report: Dict[str, Any],
    *,
    history: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Translate bounded sidecar proposals into normal lab candidate rows.

    Only a stabilization/fine-tuning proposal for an already allowlisted
    parameter can become a candidate.  Coarse proposals remain visible as
    blocked research signals.  The normal lab threshold gates still apply in
    ``build_policy_lab_report`` before this function is considered.
    """
    raw = report.get("proposals") if isinstance(report.get("proposals"), list) else []
    eligible: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    for proposal in raw:
        if not isinstance(proposal, dict):
            continue
        parameter = str(proposal.get("parameter") or "")
        phase = str(proposal.get("phase") or "")
        direction = str(proposal.get("direction") or "")
        current = _as_float(proposal.get("current_value"))
        candidate = _as_float(proposal.get("candidate_value"))
        confidence = _as_float(proposal.get("confidence")) or 0.0
        evidence_count = int(_as_float(proposal.get("evidence_count")) or 0)
        stable_runs = int(_as_float(proposal.get("direction_stable_runs")) or 0)
        route = str(proposal.get("activation_route") or "")
        regimes_seen = proposal.get("regimes") or []
        distinct_regimes = len({str(item) for item in regimes_seen if item}) if isinstance(regimes_seen, (list, tuple, set)) else 0

        # Deferred import: bot.learnable_parameter_registry already imports
        # bot.autonomous_parameter_governor, which imports this module, so a
        # module-level import here would create a cycle.
        from bot.learnable_parameter_registry import is_fast_start_autotune_allowed

        fast_start_eligible = bool(
            parameter in ALLOWED_PARAMETERS
            and route == "current_governor_and_approved_profile"
            and phase in {"stabilization", "fine_tuning"}
            and confidence >= FAST_START_MIN_CONFIDENCE
            and evidence_count >= FAST_START_MIN_EVIDENCE_COUNT
            and distinct_regimes >= FAST_START_MIN_DISTINCT_REGIMES
            and is_fast_start_autotune_allowed(parameter)
        )

        blockers: List[str] = list(proposal.get("blockers") or [])
        if parameter not in ALLOWED_PARAMETERS:
            blockers.append("growbot_river_parameter_not_in_current_adaptive_allowlist")
        if route != "current_governor_and_approved_profile":
            blockers.append("growbot_river_parameter_not_routable_through_current_governor")
        if phase not in {"stabilization", "fine_tuning"}:
            blockers.append("growbot_river_coarse_tuning_requires_stabilization_before_candidate")
        if confidence < 0.75:
            blockers.append("growbot_river_confidence_below_bridge_minimum")
        if not fast_start_eligible and evidence_count < SAMPLE_THRESHOLDS["min_relevant_conclusions_per_parameter"]:
            blockers.append("growbot_river_insufficient_parameter_evidence")
        scope = f"growbot_river:{phase or 'unknown'}"
        stability = direction_stability_for(
            f"{parameter}|{scope}", direction, history,
            required_runs=int(SAMPLE_THRESHOLDS["require_direction_stability_runs"]),
        )
        # The sidecar's own run count is diagnostic.  Existing candidate history
        # remains the activation-grade stability source.
        if not stability["passed"]:
            blockers.append("direction_stability_not_met")
        change_pct = ((candidate - current) / current * 100.0) if current not in (None, 0) and candidate is not None else 0.0
        # A fast_start-eligible candidate's own confidence/evidence/regime
        # diversity already justifies a small step; it uses a milder deadband
        # than the strict reflection-based path's 5% so legitimate
        # fine_tuning-sized (0.25-2%) steps are not rejected as "negligible".
        effect_size_floor = FAST_START_EFFECT_SIZE_DEADBAND_PCT if fast_start_eligible else SAMPLE_THRESHOLDS["min_effect_size_pct"]
        effect_gate = passes_effect_size_gate(
            current or 0.0, candidate,
            min_effect_size_pct=effect_size_floor,
        ) if current is not None and candidate is not None else {"passed": False, "reason": "invalid_sidecar_candidate_value"}
        if not effect_gate.get("passed"):
            blockers.append("effect_size_below_deadband")
        row = {
            "parameter": parameter,
            "scope": scope,
            "current_value": _fmt(current),
            "candidate_value": _fmt(candidate),
            "change_pct": round(change_pct, 4),
            "direction": direction,
            "confidence": "high" if confidence >= 0.85 else "medium",
            "online_learning_confidence": round(confidence, 4),
            "sample_count": evidence_count,
            "directional_error_labels": evidence_count,
            "market_regimes": proposal.get("regimes") or [],
            "distinct_regimes_seen": distinct_regimes,
            "tickers": [],
            "source": "growbot_river_sidecar_supplemental",
            "reason": proposal.get("reason") or "GrowBot/River online evidence",
            "requires_operator_review": True,
            "safe_to_activate_now": False,
            "fast_start_autotune_eligible": fast_start_eligible,
            "effect_size_gate": effect_gate,
            "confidence_gate": {
                "passed": confidence >= 0.75,
                "online_learning_confidence": round(confidence, 4),
                "minimum": 0.75,
                "source": "growbot_river_sidecar",
            },
            "direction_stability_gate": stability,
            # A single already-bounded online-learning point estimate, not an
            # aggregate of many noisy human-labeled conclusions: there is
            # nothing to average across samples, so the "robust average" and
            # "shrunk value" are both the sidecar's own candidate value.
            "robust_stats": {
                "sample_count": evidence_count,
                "raw_mean": _fmt(candidate),
                "trimmed_mean_10pct": _fmt(candidate),
                "median": _fmt(candidate),
                "winsorized_mean": _fmt(candidate),
                "confidence_interval": [_fmt(candidate), _fmt(candidate)],
                "source": "growbot_river_sidecar_single_point_estimate",
            },
            "shrinkage": {
                "factor": SAMPLE_THRESHOLDS["shrinkage_factor"],
                "sidecar_direction_stable_runs": stable_runs,
                "candidate_value_after_shrinkage": _fmt(candidate),
            },
            "blockers": sorted(set(blockers)),
        }
        (blocked if row["blockers"] else eligible).append(row)
    return eligible, blocked


def _fmt(value: Any) -> Optional[str]:
    if value is None:
        return None
    return f"{float(value):.8f}".rstrip("0").rstrip(".")


def _distribution(values: Iterable[Optional[float]]) -> Dict[str, Any]:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {"count": len(clean), "min": clean[0], "median": clean[len(clean) // 2], "max": clean[-1]}


def _default_gate_summary() -> Dict[str, Any]:
    return {
        "effect_size_gate": {
            "min_effect_size_pct": SAMPLE_THRESHOLDS["min_effect_size_pct"],
            "actual_effect_size_pct": None,
            "passed": False,
        },
        "confidence_gate": {
            "require_ci_excludes_current": SAMPLE_THRESHOLDS["require_confidence_interval_excludes_current"],
            "ci_low": None,
            "ci_high": None,
            "current_value_inside_ci": True,
            "passed": False,
        },
        "direction_stability_gate": {
            "scope_key": "",
            "normalized_scope_key": "",
            "required_runs": SAMPLE_THRESHOLDS["require_direction_stability_runs"],
            "observed_runs": 0,
            "history_items_available": 0,
            "available_scope_keys": [],
            "matched_scope_key": "",
            "matched_scope_keys": [],
            "match_strategy": "not_found",
            "last_directions": [],
            "required_direction": "",
            "current_direction": "",
            "stability_reason": "not_enough_history",
            "passed": False,
        },
        "shrinkage": {
            "factor": SAMPLE_THRESHOLDS["shrinkage_factor"],
            "candidate_uncapped_after_step_cap": None,
            "candidate_value_after_shrinkage": None,
        },
    }


def _gate_summary_from_changes(changes: Sequence[Dict[str, Any]], regime_report: Dict[str, Any]) -> Dict[str, Any]:
    summary = _default_gate_summary()
    first = next((change for change in changes if isinstance(change, dict)), None)
    if first:
        for key in ("effect_size_gate", "confidence_gate", "direction_stability_gate", "shrinkage"):
            if isinstance(first.get(key), dict):
                summary[key] = first[key]
    summary["regime_enrichment"] = regime_report
    return summary


def build_policy_lab_report(
    *,
    root: Path = Path("."),
    reflection_report: Optional[Dict[str, Any]] = None,
    market_intelligence_context: Optional[Dict[str, Any]] = None,
    history: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    reflection = reflection_report or load_reflection_report(root)
    mi_context = market_intelligence_context if market_intelligence_context is not None else _load_market_intelligence_context(root)
    rows = _enrich_rows(validated_conclusions(reflection), mi_context)
    history_rows = list(history) if history is not None else load_candidate_history(root)
    # An explicitly supplied reflection report is a self-contained analysis
    # input (for example a replay or test fixture). Do not silently blend it
    # with the live sidecar report from `root`.
    growbot_river_report = load_growbot_river_learning_report(root) if reflection_report is None else {}
    evidence = _evidence_summary(rows)
    diversity = regime_diversity_diagnostics(evidence["market_regimes"])
    regime_report = regime_enrichment_report(rows)
    by_setup: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_blocker: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        setup = str(row.get("setup_type") or "unknown")
        blocker = str(row.get("main_blocker") or "unknown")
        by_setup[setup].append(row)
        by_blocker[blocker].append(row)
        groups[_group_key(row)].append(row)

    threshold_blockers: List[str] = []
    if evidence["total_validated_conclusions"] < SAMPLE_THRESHOLDS["min_total_validated_conclusions"]:
        threshold_blockers.append("insufficient_total_validated_conclusions")
    if evidence["separate_days"] < SAMPLE_THRESHOLDS["min_separate_days"]:
        threshold_blockers.append("insufficient_separate_days")
    if not diversity["distinct_regime_gate_passed"]:
        threshold_blockers.append(
            "insufficient_distinct_regime_diversity"
            if diversity["raw_regime_count"] >= SAMPLE_THRESHOLDS["min_market_regimes"]
            else "insufficient_market_regimes"
        )
    if not regime_report["passed"]:
        threshold_blockers.append("insufficient_regime_enrichment_coverage")
    if evidence["out_of_sample_conclusions"] < SAMPLE_THRESHOLDS["min_out_of_sample_conclusions"]:
        threshold_blockers.append("insufficient_out_of_sample_conclusions")

    proposed: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    growbot_river_proposed, growbot_river_blocked = _growbot_river_supplemental_changes(
        growbot_river_report,
        history=history_rows,
    ) if growbot_river_report else ([], [])
    if not threshold_blockers:
        for scope, group_rows in sorted(groups.items()):
            candidate = _candidate_for_group(root, scope, group_rows, rows, history=history_rows)
            if candidate["blockers"]:
                blocked.append(candidate)
            else:
                proposed.append(candidate)
        # Global changes require multi-setup and at least 3 tickers, so keep the
        # global scope blocked unless that stricter evidence is present.
        setup_count = len({str(r.get("setup_type") or "unknown") for r in rows})
        if len(evidence["tickers"]) < SAMPLE_THRESHOLDS["min_tickers_per_general_change"] or setup_count < 2:
            blocked.append(
                {
                    "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                    "scope": "global_only_if_multi_setup_multi_ticker_evidence",
                    "safe_to_activate_now": False,
                    "requires_operator_review": True,
                    "blockers": ["insufficient_tickers_for_global_change" if len(evidence["tickers"]) < 3 else "insufficient_setup_diversity_for_global_change"],
                    "sample_count": evidence["total_validated_conclusions"],
                    "tickers": evidence["tickers"],
                }
            )
        # The sidecar is supplementary: it can only add already allowlisted,
        # stabilized candidates after the normal reflection thresholds pass.
        proposed.extend(growbot_river_proposed)
        blocked.extend(growbot_river_blocked)
    else:
        threshold_scope_key = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
        blocked.append(
            {
                "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                "scope": "adaptive_policy_lab",
                "direction": "loosen",
                "direction_stability_gate": direction_stability_for(
                    threshold_scope_key,
                    "loosen",
                    history_rows,
                    required_runs=int(SAMPLE_THRESHOLDS["require_direction_stability_runs"]),
                ),
                "safe_to_activate_now": False,
                "requires_operator_review": True,
                "blockers": threshold_blockers,
                "sample_count": evidence["total_validated_conclusions"],
            }
        )
        # A fast_start-eligible GrowBot/River row already cleared its own
        # confidence/evidence/regime-diversity bar in
        # _growbot_river_supplemental_changes, using evidence that is
        # independent of (and orthogonal to) the reflection ledger's own
        # regime-tagging/volume thresholds above. Forcing it to also wait on
        # that unrelated reflection-wide gate would block a low-risk,
        # bounded, fine_tuning-sized step on evidence it does not need.
        for row in growbot_river_proposed:
            if row.get("fast_start_autotune_eligible") and not row.get("blockers"):
                proposed.append(row)
            else:
                clone = dict(row)
                clone["blockers"] = sorted(set(list(clone.get("blockers") or []) + ["reflection_thresholds_not_met_for_growbot_river_bridge"]))
                blocked.append(clone)
        for row in growbot_river_blocked:
            clone = dict(row)
            clone["blockers"] = sorted(set(list(clone.get("blockers") or []) + ["reflection_thresholds_not_met_for_growbot_river_bridge"]))
            blocked.append(clone)

    candidate_available = bool(proposed)
    all_changes = proposed or blocked
    gate_summary = _gate_summary_from_changes(all_changes, regime_report)
    directions = direction_by_parameter_scope(list(proposed) + list(blocked))
    recommendation = "propose_candidate_profile" if candidate_available else ("keep_current" if rows and not any(r.get("label") in LOOSENING_LABELS for r in rows) else "collect_more_data")
    reason = "candidate_ready_for_operator_review" if candidate_available else _reason_from_blockers(threshold_blockers, blocked)
    return {
        "phase": "adaptive_policy_lab_v1",
        "generated_at": now_iso(),
        "available": bool(reflection),
        "candidate_available": candidate_available,
        "recommendation": recommendation,
        "reason": reason,
        "safe_to_activate_now": False,
        "requires_operator_review": True,
        "requires_hash_ack_activation": True,
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "sample_thresholds": dict(SAMPLE_THRESHOLDS),
        "thresholds_met": not threshold_blockers,
        "blockers": threshold_blockers,
        "market_regime_coverage_pct": regime_report["coverage_pct"],
        "regime_enrichment": regime_report,
        "effect_size_gate_summary": gate_summary["effect_size_gate"],
        "confidence_gate_summary": gate_summary["confidence_gate"],
        "direction_stability_summary": gate_summary["direction_stability_gate"],
        "shrinkage_enabled": True,
        "shrinkage": gate_summary["shrinkage"],
        "direction_by_parameter_scope": directions,
        "evidence_summary": evidence,
        "regime_diversity": diversity,
        "evidence_by_setup_type": {k: _evidence_summary(v) for k, v in by_setup.items()},
        "evidence_by_blocker": {k: _evidence_summary(v) for k, v in list(by_blocker.items())[:50]},
        "proposed_parameter_changes": proposed,
        "blocked_parameter_changes": blocked,
        "growbot_river_learning": {
            "available": bool(growbot_river_report),
            "path": str(GROWBOT_RIVER_REPORT_PATH),
            "report_generated_at": growbot_river_report.get("generated_at") if growbot_river_report else "",
            "supplemental_candidate_count": len(growbot_river_proposed),
            "supplemental_blocked_count": len(growbot_river_blocked),
            "fast_start_autotune_candidate_count": sum(1 for row in growbot_river_proposed if row.get("fast_start_autotune_eligible")),
            "integration_policy": (
                "supplemental_requires_existing_candidate_gates; a fast_start_autotune-eligible "
                "row (own confidence/evidence/regime bar already met, milder effect-size deadband) "
                "is exempt from the orthogonal reflection-ledger volume/regime-tagging threshold; "
                "all other rows still require it"
            ),
        },
        "allowed_parameters": sorted(ALLOWED_PARAMETERS),
        "forbidden_parameters": sorted(FORBIDDEN_PARAMETERS),
        "overfit_risk": _overfit_risk(evidence, proposed),
        "reflection_summary_used": reflection.get("summary") if isinstance(reflection.get("summary"), dict) else {},
        "basis": _basis(),
    }


def _reason_from_blockers(threshold_blockers: Sequence[str], blocked: Sequence[Dict[str, Any]]) -> str:
    if threshold_blockers:
        if "insufficient_distinct_regime_diversity" in threshold_blockers:
            return "insufficient_distinct_regime_diversity"
        if "insufficient_market_regimes" in threshold_blockers:
            return "insufficient_market_regimes"
        if "insufficient_total_validated_conclusions" in threshold_blockers:
            return "insufficient_evidence_for_parameter_candidate"
        return "insufficient_evidence_for_parameter_candidate"
    blockers = Counter()
    for row in blocked:
        for blocker in row.get("blockers") or []:
            blockers[str(blocker)] += 1
    if blockers:
        return blockers.most_common(1)[0][0]
    return "insufficient_relevant_conclusions_per_parameter_or_scope"


def _overfit_risk(evidence: Dict[str, Any], proposed: Sequence[Dict[str, Any]]) -> str:
    if not evidence.get("total_validated_conclusions"):
        return "unknown"
    if proposed and evidence["total_validated_conclusions"] >= 600 and len(evidence.get("market_regimes") or []) >= 2:
        return "low"
    if evidence["total_validated_conclusions"] >= 300:
        return "medium"
    return "high"


def _basis() -> List[str]:
    return [
        "reflection_learning_labels",
        "missed_opportunity_detection",
        "overtrading_risk_detection",
        "cost_aware_net_opportunity",
        "growbot_inspired_adaptive_policy_lab",
        "growbot_river_supplemental_online_learning",
        "anti_overfitting_sample_thresholds",
        "approved_profile_hash_gate",
    ]


def build_adaptive_policy_candidate(
    *,
    root: Path = Path("."),
    reflection_report: Optional[Dict[str, Any]] = None,
    market_intelligence_context: Optional[Dict[str, Any]] = None,
    history: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    lab = build_policy_lab_report(
        root=root,
        reflection_report=reflection_report,
        market_intelligence_context=market_intelligence_context,
        history=history,
    )
    payload = {
        "profile_name": "adaptive_reflection_candidate_v1",
        "profile_type": "reflection_backlearning_growbot_inspired_candidate",
        "generated_at": lab["generated_at"],
        "available": lab["candidate_available"],
        "candidate_available": lab["candidate_available"],
        "safe_to_activate_now": False,
        "requires_operator_review": True,
        "requires_hash_ack_activation": True,
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "basis": lab["basis"],
        "sample_thresholds": lab["sample_thresholds"],
        "evidence_summary": lab["evidence_summary"],
        "regime_diversity": lab["regime_diversity"],
        "effect_size_gate": lab["effect_size_gate_summary"],
        "confidence_gate": lab["confidence_gate_summary"],
        "direction_stability_gate": lab["direction_stability_summary"],
        "shrinkage": lab["shrinkage"],
        "regime_enrichment": lab["regime_enrichment"],
        "direction_by_parameter_scope": lab["direction_by_parameter_scope"],
        "growbot_river_learning": lab.get("growbot_river_learning") or {},
        "proposed_parameter_changes": lab["proposed_parameter_changes"],
        "blocked_parameter_changes": lab["blocked_parameter_changes"],
        "recommendation": lab["recommendation"],
        "reason": lab["reason"],
        "lab_report": {
            "overfit_risk": lab["overfit_risk"],
            "thresholds_met": lab["thresholds_met"],
            "blockers": lab["blockers"],
            "reflection_summary_used": lab["reflection_summary_used"],
            "market_regime_coverage_pct": lab["market_regime_coverage_pct"],
            "regime_diversity": lab["regime_diversity"],
            "growbot_river_learning": lab.get("growbot_river_learning") or {},
        },
    }
    payload["hash"] = stable_payload_hash(payload)
    return payload


def render_candidate_markdown(candidate: Dict[str, Any]) -> str:
    lines = [
        "# Adaptive Policy Candidate",
        "",
        f"Generated: {candidate.get('generated_at')}",
        f"Available: {candidate.get('available')}",
        f"Recommendation: {candidate.get('recommendation')}",
        f"Reason: {candidate.get('reason')}",
        f"Hash: `{candidate.get('hash')}`",
        "",
        "## Safety",
        "- safe_to_activate_now: false",
        "- requires_operator_review: true",
        "- requires_hash_ack_activation: true",
        "- can_authorize_execution: false",
        "- can_block_execution: false",
        "- can_mutate_parameters: false",
        "",
        "## Proposed Changes",
    ]
    changes = candidate.get("proposed_parameter_changes") or []
    if not changes:
        lines.append("- none")
    for change in changes:
        lines.append(f"- `{change.get('parameter')}` `{change.get('scope')}`: `{change.get('current_value')}` -> `{change.get('candidate_value')}` ({change.get('change_pct')}%)")
    return "\n".join(lines) + "\n"


def write_adaptive_policy_outputs(candidate: Dict[str, Any], *, root: Path = Path(".")) -> Dict[str, str]:
    lab = candidate.get("lab_report_full") if isinstance(candidate.get("lab_report_full"), dict) else build_policy_lab_report(root=root)
    paths = {
        "lab": root / LAB_REPORT_PATH,
        "candidate_json": root / CANDIDATE_JSON_PATH,
        "candidate_markdown": root / CANDIDATE_MD_PATH,
        "history": root / HISTORY_PATH,
    }
    for key, path in paths.items():
        if key == "history":
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(paths["lab"], lab)
    atomic_write_json(paths["candidate_json"], candidate)
    paths["candidate_markdown"].write_text(render_candidate_markdown(candidate), encoding="utf-8")
    append_candidate_history(candidate, root=root)
    return {key: str(path) for key, path in paths.items()}


def feature_pack_adaptive_policy_context(root: Path = Path(".")) -> Dict[str, Any]:
    candidate = _load_json(root / CANDIDATE_JSON_PATH)
    return {
        "available": bool(candidate),
        "candidate_available": bool(candidate.get("candidate_available")),
        "recommendation": candidate.get("recommendation") or "collect_more_data",
        "hash": candidate.get("hash"),
        "safe_to_activate_now": False,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
    }


def inject_adaptive_policy_feature_pack(feature_pack: Dict[str, Any], root: Path = Path("."), *, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    pack = feature_pack if isinstance(feature_pack, dict) else {}
    if (env or os.environ).get("ENABLE_ADAPTIVE_POLICY_CONTEXT", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return pack
    decision_context = pack.setdefault("decision_context", {})
    external = decision_context.setdefault("external_context", {})
    external["adaptive_policy_context"] = feature_pack_adaptive_policy_context(root)
    return pack


__all__ = [
    "SAMPLE_THRESHOLDS",
    "SOURCE_POLICY",
    "build_adaptive_policy_candidate",
    "build_policy_lab_report",
    "append_candidate_history",
    "apply_shrinkage",
    "build_regime_enrichment_fields",
    "confidence_interval_excludes_current",
    "conservative_step_toward",
    "direction_stability_for",
    "enrich_conclusion_market_regime",
    "feature_pack_adaptive_policy_context",
    "inject_adaptive_policy_feature_pack",
    "is_validated_conclusion",
    "label_pressure",
    "load_candidate_history",
    "map_pressure_to_parameter",
    "normalize_parameter_scope_key",
    "passes_effect_size_gate",
    "regime_enrichment_report",
    "robust_stats",
    "stable_payload_hash",
    "validated_conclusions",
    "write_adaptive_policy_outputs",
]
