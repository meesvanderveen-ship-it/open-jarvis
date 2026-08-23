"""Regime-segmented parameter profiles -- report-only shadow suggestions.

For each canonical market regime (trend_up, trend_down, range_chop,
high_volatility, low_volatility, drawdown_risk_off) this groups the same
evidence used by ``bot.adaptive_learning_intelligence`` by regime tag and
asks: within episodes tagged with *this* regime alone, does the evidence
still point toward loosening or tightening a parameter?

These profiles are never activated and never written into any runtime
config path. They exist purely so an operator can see regime-conditional
pressure (e.g. "MAX_SPREAD_PCT looks too strict in range_chop") before any
such distinction is ever built into a real profile switch -- which would be
a separate, deliberate, governed piece of work.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping

from bot.adaptive_learning_intelligence import (
    PARAMETER_EVIDENCE_SPECS,
    compute_votes_for_parameter,
    load_current_parameter_values,
    load_decision_outcome_records,
    load_execution_outcome_records,
    load_growbot_river_learning_report,
    resolve_current_value,
    river_backend_label,
)
from bot.learnable_parameter_registry import parameter_definitions
from bot.overfit_risk_model import KNOWN_REGIMES, normalize_label

SCHEMA_VERSION = "regime_parameter_profiles_v1"

#: Below this many regime-local evidence records, report the gap rather than
#: a guess -- a single-regime read needs even less volume than the global
#: shadow_candidate floor, but zero is still zero.
MIN_EVIDENCE_PER_REGIME = 3
#: A regime-local narrative sentence is only emitted when the dominant
#: direction holds at least this share of the regime-local directional
#: votes -- keeps the narrative list free of noise.
NARRATIVE_MIN_CONFIDENCE = 0.6


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _pressure_direction(loosen: int, tighten: int) -> str:
    if loosen == 0 and tighten == 0:
        return "no_signal"
    total = loosen + tighten
    if loosen > 0 and tighten > 0:
        if loosen / total >= 0.7:
            return "loosen"
        if tighten / total >= 0.7:
            return "tighten"
        return "mixed"
    return "loosen" if loosen > tighten else "tighten"


def _narrative(regime: str, parameter: str, direction: str) -> str:
    if direction == "loosen":
        return f"In {regime}, {parameter} appears too strict -- evidence suggests loosening."
    if direction == "tighten":
        return f"In {regime}, {parameter} appears too loose -- evidence suggests tightening."
    return ""


def _regime_parameter_entry(regime: str, parameter: str, votes: List[Mapping[str, Any]]) -> Dict[str, Any]:
    regime_votes = [v for v in votes if normalize_label(v.get("regime")) == regime]
    loosen = sum(1 for v in regime_votes if v["vote"] == "loosen")
    tighten = sum(1 for v in regime_votes if v["vote"] == "tighten")
    keep = sum(1 for v in regime_votes if v["vote"] == "keep")
    evidence_count = len(regime_votes)

    if evidence_count < MIN_EVIDENCE_PER_REGIME:
        return {
            "direction": "insufficient_evidence",
            "evidence_count": evidence_count,
            "loosen_signal_count": loosen,
            "tighten_signal_count": tighten,
            "keep_signal_count": keep,
            "confidence": 0.0,
            "narrative": "",
        }

    direction = _pressure_direction(loosen, tighten)
    dominant = max(loosen, tighten)
    confidence = round(dominant / evidence_count, 4) if evidence_count else 0.0
    narrative = _narrative(regime, parameter, direction) if confidence >= NARRATIVE_MIN_CONFIDENCE else ""
    return {
        "direction": direction,
        "evidence_count": evidence_count,
        "loosen_signal_count": loosen,
        "tighten_signal_count": tighten,
        "keep_signal_count": keep,
        "confidence": confidence,
        "narrative": narrative,
    }


def build_regime_parameter_profiles(*, root: str | Path = ".") -> Dict[str, Any]:
    root_path = Path(root)
    decision_records = load_decision_outcome_records(root_path)
    execution_records = load_execution_outcome_records(root_path)
    current_values = load_current_parameter_values(root_path)
    registry = parameter_definitions()

    mapped_parameters = [spec.parameter for spec in PARAMETER_EVIDENCE_SPECS if spec.parameter in registry]

    base_profile = {
        name: resolve_current_value(registry[name], current_values) for name in mapped_parameters
    }

    votes_by_parameter = {
        name: compute_votes_for_parameter(name, decision_records, execution_records, current_values) or []
        for name in mapped_parameters
    }

    profiles: Dict[str, Any] = {
        "base_profile": {
            "parameters": base_profile,
            "note": "Live/registry current values -- not a regime-specific suggestion.",
        }
    }
    narrative_lines: List[str] = []

    for regime in KNOWN_REGIMES:
        regime_parameters: Dict[str, Any] = {}
        for name in mapped_parameters:
            entry = _regime_parameter_entry(regime, name, votes_by_parameter[name])
            regime_parameters[name] = entry
            if entry["narrative"]:
                narrative_lines.append(entry["narrative"])
        profiles[f"{regime}_profile"] = {
            "regime": regime,
            "parameters": regime_parameters,
            "status": "report_only_shadow",
            "activation_status": "never_auto_activated",
        }

    river_backend = river_backend_label(load_growbot_river_learning_report(root_path))

    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _now_iso(),
        "read_only": True,
        "automatic_activation_enabled": False,
        "source": "growbot_river",
        "river_backend": river_backend,
        "canonical_regimes": list(KNOWN_REGIMES),
        "mapped_parameters": mapped_parameters,
        "profiles": profiles,
        "narrative_lines": narrative_lines,
        "activation_policy": (
            "report_only -- no regime profile is ever applied automatically by this module; "
            "promoting a regime-specific value still requires the existing approved-profile/governor path."
        ),
    }


__all__ = [
    "SCHEMA_VERSION",
    "MIN_EVIDENCE_PER_REGIME",
    "NARRATIVE_MIN_CONFIDENCE",
    "build_regime_parameter_profiles",
]
