from __future__ import annotations

import json
from pathlib import Path

import pytest

from bot.adaptive_learning_intelligence import (
    NO_MAPPING_PARAMETERS,
    build_adaptive_learning_intelligence,
    build_learning_depth_summary,
    build_missed_opportunity_learning,
    build_parameter_evidence,
    build_wait_decision_quality,
    load_decision_outcome_records,
    load_execution_outcome_records,
    load_opportunity_memory,
    load_trade_reflection_records,
)
from bot.learnable_parameter_registry import parameter_definitions


def _decision_record(
    *,
    ticker: str,
    decision_category: str,
    outcome_label: str,
    confidence: float,
    regime: str = "unknown",
    created_at: str = "2026-06-01T00:00:00Z",
    status: str = "resolved",
) -> dict:
    return {
        "ticker": ticker,
        "created_at": created_at,
        "status": status,
        "decision_category": decision_category,
        "growbot_river_learning_context": {
            "regime": regime,
            "state": {"confidence": confidence},
        },
        "outcome": {"outcome_label": outcome_label, "price_change_pct": 0.02},
    }


# --- loaders: missing files must never raise -------------------------------

def test_loaders_return_empty_defaults_when_files_missing(tmp_path: Path):
    assert load_decision_outcome_records(tmp_path) == []
    assert load_execution_outcome_records(tmp_path) == []
    assert load_trade_reflection_records(tmp_path) == []
    assert load_opportunity_memory(tmp_path) == []


# --- per-parameter evidence: directional pressure --------------------------

def test_build_parameter_evidence_detects_loosen_pressure_for_judge_confidence():
    registry = parameter_definitions()
    definition = registry["JUDGE_MIN_GATE_CONFIDENCE"]  # default 62.0, band ~9.3
    decision_records = [
        _decision_record(
            ticker="ADA-USDC", decision_category="wait", outcome_label="missed_opportunity",
            confidence=58.0, regime="range_chop", created_at=f"2026-06-0{i}T00:00:00Z",
        )
        for i in range(1, 9)
    ]
    result = build_parameter_evidence("JUDGE_MIN_GATE_CONFIDENCE", definition, decision_records, [], {})
    assert result["direction"] == "loosen"
    assert result["evidence_count"] == 8
    assert result["loosen_signal_count"] == 8
    assert result["tier"] in ("shadow_candidate", "observed_signal")
    assert result["why_not_apply_ready"]
    assert result["tier"] != "apply_ready_candidate"


def test_build_parameter_evidence_detects_tighten_pressure_for_judge_confidence():
    registry = parameter_definitions()
    definition = registry["JUDGE_MIN_GATE_CONFIDENCE"]
    decision_records = [
        _decision_record(
            ticker="SOL-USDC", decision_category="prepared_plan", outcome_label="false_positive_plan",
            confidence=63.0, regime="trend_down", created_at=f"2026-06-0{i}T00:00:00Z",
        )
        for i in range(1, 9)
    ]
    result = build_parameter_evidence("JUDGE_MIN_GATE_CONFIDENCE", definition, decision_records, [], {})
    assert result["direction"] == "tighten"
    assert result["tighten_signal_count"] == 8


def test_build_parameter_evidence_no_signal_when_nothing_near_band():
    registry = parameter_definitions()
    definition = registry["JUDGE_MIN_GATE_CONFIDENCE"]
    decision_records = [
        _decision_record(ticker="BTC-USDC", decision_category="wait", outcome_label="correct_avoid", confidence=10.0)
    ]
    result = build_parameter_evidence("JUDGE_MIN_GATE_CONFIDENCE", definition, decision_records, [], {})
    assert result["evidence_count"] == 0
    assert result["direction"] == "no_signal"
    assert result["overfit_risk"] == "high"


@pytest.mark.parametrize("name", sorted(NO_MAPPING_PARAMETERS))
def test_no_mapping_parameters_are_honest_about_data_gap(name):
    registry = parameter_definitions()
    definition = registry[name]
    result = build_parameter_evidence(name, definition, [], [], {})
    assert result["tier"] == "observed_signal"
    assert result["evidence_count"] == 0
    assert result["evidence_source"] == "none"
    assert result["direction"] == "keep"
    assert result["why"] == NO_MAPPING_PARAMETERS[name]
    assert result["next_data_needed"] == NO_MAPPING_PARAMETERS[name]


def test_unmapped_registry_parameter_falls_back_to_generic_message():
    registry = parameter_definitions()
    # JUDGE_MIN_SYNTH_CONFIDENCE has no dedicated evidence mapping and is not
    # in NO_MAPPING_PARAMETERS -- it must still resolve safely.
    definition = registry["JUDGE_MIN_SYNTH_CONFIDENCE"]
    result = build_parameter_evidence("JUDGE_MIN_SYNTH_CONFIDENCE", definition, [], [], {})
    assert result["tier"] == "observed_signal"
    assert result["evidence_source"] == "none"
    assert "not yet wired" in result["why"].lower()


# --- wait-decision quality / missed-opportunity learning -------------------

def test_build_wait_decision_quality_scores_correct_vs_missed():
    records = (
        [_decision_record(ticker="A", decision_category="wait", outcome_label="correct_avoid", confidence=50) for _ in range(3)]
        + [_decision_record(ticker="B", decision_category="watch", outcome_label="correct_wait_or_neutral", confidence=50) for _ in range(2)]
        + [_decision_record(ticker="C", decision_category="skip", outcome_label="missed_opportunity", confidence=50) for _ in range(5)]
    )
    result = build_wait_decision_quality(records)
    assert result["resolved_wait_like_decisions"] == 10
    assert result["correct_count"] == 5
    assert result["missed_opportunity_count"] == 5
    assert result["wait_decision_quality_pct"] == 0.5


def test_build_wait_decision_quality_handles_no_data():
    result = build_wait_decision_quality([])
    assert result["wait_decision_quality_pct"] is None


def test_build_missed_opportunity_learning_groups_by_ticker_and_setup():
    records = [
        {
            "ticker": "ADA-USDC",
            "status": "resolved",
            "created_at": "2026-06-01T00:00:00Z",
            "decision_category": "wait",
            "trade_plan": {"setup_type": "breakout", "trigger": "trigger near resistance"},
            "outcome": {"outcome_label": "missed_opportunity", "price_change_pct": 0.05},
        },
        {
            "ticker": "ADA-USDC",
            "status": "resolved",
            "created_at": "2026-06-02T00:00:00Z",
            "decision_category": "wait",
            "trade_plan": {"setup_type": "breakout", "trigger": "trigger near resistance"},
            "outcome": {"outcome_label": "missed_opportunity", "price_change_pct": 0.04},
        },
        {
            "ticker": "SOL-USDC",
            "status": "resolved",
            "created_at": "2026-06-03T00:00:00Z",
            "decision_category": "skip",
            "entry_gate": {"setup_type": "reclaim"},
            "outcome": {"outcome_label": "missed_opportunity", "price_change_pct": 0.06},
        },
    ]
    result = build_missed_opportunity_learning(records, top_n=2)
    assert result["missed_opportunity_count"] == 3
    assert result["by_ticker"]["ADA-USDC"] == 2
    assert result["by_setup_type"]["breakout"] == 2
    assert len(result["recent_samples"]) == 2
    # most recent first
    assert result["recent_samples"][0]["created_at"] == "2026-06-03T00:00:00Z"


def test_build_learning_depth_summary_counts_each_source(tmp_path: Path):
    decision_records = [
        _decision_record(ticker="A", decision_category="wait", outcome_label="correct_avoid", confidence=50, status="resolved"),
        _decision_record(ticker="A", decision_category="wait", outcome_label="correct_avoid", confidence=50, status="pending"),
    ]
    execution_records = [{"ticker": "B", "market_regime": "trend_up"}]
    reflection_records = [{"ticker": "C"}]
    result = build_learning_depth_summary(decision_records, execution_records, reflection_records)
    assert result["decision_outcomes_resolved"] == 1
    assert result["decision_outcomes_pending"] == 1
    assert result["execution_outcomes_count"] == 1
    assert result["trade_reflections_count"] == 1
    assert result["total_evidence_records"] == 2


# --- end-to-end orchestrator: no live side effects, no automatic apply -----

def _write_decision_outcomes(root: Path, records: list[dict]) -> None:
    state_dir = root / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "decision_outcomes.json").write_text(json.dumps({"records": records}), encoding="utf-8")


def test_build_adaptive_learning_intelligence_end_to_end(tmp_path: Path):
    records = [
        _decision_record(
            ticker=f"T{i % 4}-USDC", decision_category="wait", outcome_label="missed_opportunity",
            confidence=58.0, regime="range_chop", created_at=f"2026-06-{i:02d}T00:00:00Z",
        )
        for i in range(1, 10)
    ]
    _write_decision_outcomes(tmp_path, records)

    report = build_adaptive_learning_intelligence(root=tmp_path)

    assert report["read_only"] is True
    assert report["llm_call_made"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["automatic_parameter_apply_enabled"] is False

    registry_size = len(parameter_definitions())
    assert sum(report["proposal_maturity_funnel"].values()) == registry_size
    assert len(report["parameter_evidence"]) == registry_size


def test_build_adaptive_learning_intelligence_never_writes_any_file(tmp_path: Path):
    _write_decision_outcomes(tmp_path, [])
    before = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    build_adaptive_learning_intelligence(root=tmp_path)
    after = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert before == after


def test_build_adaptive_learning_intelligence_never_produces_apply_ready_even_with_overwhelming_evidence(tmp_path: Path):
    regimes = ["trend_up", "trend_down", "range_chop", "high_volatility", "low_volatility", "drawdown_risk_off"]
    tickers = [f"T{i}-USDC" for i in range(10)]
    records = [
        _decision_record(
            ticker=tickers[i % len(tickers)],
            decision_category="wait",
            outcome_label="missed_opportunity",
            confidence=58.0,
            regime=regimes[i % len(regimes)],
            created_at=f"2026-{(i % 11) + 1:02d}-01T00:00:00Z",
        )
        for i in range(200)
    ]
    _write_decision_outcomes(tmp_path, records)

    report = build_adaptive_learning_intelligence(root=tmp_path)

    assert report["proposal_maturity_funnel"]["apply_ready_candidate"] == 0
    assert all(item["tier"] != "apply_ready_candidate" for item in report["parameter_evidence"])
