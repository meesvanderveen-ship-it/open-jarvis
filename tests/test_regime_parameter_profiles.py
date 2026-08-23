from __future__ import annotations

import json
from pathlib import Path

from bot.regime_parameter_profiles import (
    MIN_EVIDENCE_PER_REGIME,
    build_regime_parameter_profiles,
)
from bot.overfit_risk_model import KNOWN_REGIMES


def _write_decision_outcomes(root: Path, records: list[dict]) -> None:
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "decision_outcomes.json").write_text(json.dumps({"records": records}), encoding="utf-8")


def _record(*, ticker: str, regime: str, decision_category: str, outcome_label: str, confidence: float = 58.0) -> dict:
    return {
        "ticker": ticker,
        "created_at": "2026-06-01T00:00:00Z",
        "status": "resolved",
        "decision_category": decision_category,
        "growbot_river_learning_context": {"regime": regime, "state": {"confidence": confidence}},
        "outcome": {"outcome_label": outcome_label, "price_change_pct": 0.02},
    }


def test_profiles_cover_all_canonical_regimes_and_never_auto_activate(tmp_path: Path):
    report = build_regime_parameter_profiles(root=tmp_path)
    assert report["automatic_activation_enabled"] is False
    for regime in KNOWN_REGIMES:
        key = f"{regime}_profile"
        assert key in report["profiles"]
        assert report["profiles"][key]["activation_status"] == "never_auto_activated"
        assert report["profiles"][key]["status"] == "report_only_shadow"


def test_base_profile_uses_registry_defaults_when_no_approved_profile(tmp_path: Path):
    report = build_regime_parameter_profiles(root=tmp_path)
    base = report["profiles"]["base_profile"]["parameters"]
    assert base["MAX_SPREAD_PCT"] == 0.006
    assert base["JUDGE_MIN_GATE_CONFIDENCE"] == 62.0


def test_insufficient_evidence_below_floor(tmp_path: Path):
    records = [
        _record(ticker="A", regime="range_chop", decision_category="wait", outcome_label="missed_opportunity")
        for _ in range(MIN_EVIDENCE_PER_REGIME - 1)
    ]
    _write_decision_outcomes(tmp_path, records)
    report = build_regime_parameter_profiles(root=tmp_path)
    entry = report["profiles"]["range_chop_profile"]["parameters"]["JUDGE_MIN_GATE_CONFIDENCE"]
    assert entry["direction"] == "insufficient_evidence"


def test_narrative_emitted_once_evidence_floor_and_confidence_met(tmp_path: Path):
    records = [
        _record(ticker=f"T{i}", regime="range_chop", decision_category="wait", outcome_label="missed_opportunity")
        for i in range(MIN_EVIDENCE_PER_REGIME + 2)
    ]
    _write_decision_outcomes(tmp_path, records)
    report = build_regime_parameter_profiles(root=tmp_path)
    entry = report["profiles"]["range_chop_profile"]["parameters"]["JUDGE_MIN_GATE_CONFIDENCE"]
    assert entry["direction"] == "loosen"
    assert entry["narrative"]
    assert "range_chop" in entry["narrative"]
    assert entry["narrative"] in report["narrative_lines"]


def test_regime_local_pressure_is_isolated_per_regime(tmp_path: Path):
    records = [
        _record(ticker=f"A{i}", regime="range_chop", decision_category="wait", outcome_label="missed_opportunity")
        for i in range(5)
    ] + [
        _record(ticker=f"B{i}", regime="trend_up", decision_category="prepared_plan", outcome_label="false_positive_plan", confidence=63.0)
        for i in range(5)
    ]
    _write_decision_outcomes(tmp_path, records)
    report = build_regime_parameter_profiles(root=tmp_path)
    range_chop = report["profiles"]["range_chop_profile"]["parameters"]["JUDGE_MIN_GATE_CONFIDENCE"]
    trend_up = report["profiles"]["trend_up_profile"]["parameters"]["JUDGE_MIN_GATE_CONFIDENCE"]
    assert range_chop["direction"] == "loosen"
    assert trend_up["direction"] == "tighten"
