from __future__ import annotations

import json
from pathlib import Path

from bot.reflection_learning_context import build_reflection_learning_report, write_report_outputs
from bot.reflection_persistence import (
    PARAMETER_PRESSURE_LEDGER_PATH,
    REFLECTION_LEDGER_PATH,
    append_parameter_pressure_events,
    append_reflection_evaluations,
    build_reflection_persistence_status,
    load_reflection_events,
    normalize_reflection_evaluation,
    read_jsonl_ledger,
)


def _reflection(label: str = "missed_opportunity", **overrides) -> dict:
    row = {
        "available": True,
        "ticker": "BTC-USDC",
        "decision_time": "2026-06-14T00:00:00Z",
        "decision_type": "wait",
        "setup_type": "trend_continuation",
        "main_blocker": "expected_net_edge_too_low",
        "future_window_hours": 24,
        "max_favorable_excursion_pct": 0.04,
        "max_adverse_excursion_pct": -0.004,
        "estimated_roundtrip_fee_pct": 0.012,
        "estimated_spread_cost_pct": 0.0005,
        "estimated_slippage_buffer_pct": 0.0025,
        "estimated_net_after_cost_opportunity_pct": 0.02,
        "label": label,
        "confidence": 0.75,
        "reason": "visible_setup_positive_net_path_passed_anti_hindsight_filters",
        "market_regime": "supportive",
    }
    row.update(overrides)
    return row


def _report(rows: list[dict]) -> dict:
    return {"phase": "reflection_learning_context_v1", "generated_at": "2026-06-14T01:00:00Z", "evaluations": rows}


def test_reflection_ledger_created_append_only_and_deduped(tmp_path: Path) -> None:
    report = _report([_reflection()])
    first = append_reflection_evaluations(report, root=tmp_path)
    second = append_reflection_evaluations(report, root=tmp_path)
    path = tmp_path / REFLECTION_LEDGER_PATH
    assert path.exists()
    assert first["appended_events"] == 1
    assert second["appended_events"] == 0
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1


def test_corrupt_jsonl_lines_do_not_crash_and_are_reported(tmp_path: Path) -> None:
    path = tmp_path / REFLECTION_LEDGER_PATH
    path.parent.mkdir(parents=True)
    path.write_text("{bad\n" + json.dumps({"event_id": "ok"}) + "\n", encoding="utf-8")
    rows, corrupt = read_jsonl_ledger(path)
    assert len(rows) == 1
    assert corrupt == 1
    status = build_reflection_persistence_status(root=tmp_path)
    assert status["corrupt_lines"] == 1


def test_latest_report_and_snapshot_are_written_by_reflection_flow(tmp_path: Path) -> None:
    report = build_reflection_learning_report(root=tmp_path, fixture_only=True, no_network=True)
    outputs = write_report_outputs(report, root=tmp_path)
    assert (tmp_path / "reports/reflection/reflection-learning-latest.json").exists()
    assert Path(outputs["snapshot_json"]).exists()
    assert Path(outputs["snapshot_markdown"]).exists()


def test_reflection_event_schema_and_validated_flag() -> None:
    event = normalize_reflection_evaluation(_reflection(), report=_report([]))
    assert event["schema_version"] == "reflection_evaluation_v1"
    assert event["event_id"]
    assert event["validated_conclusion"] is True
    assert event["created_by"] == "reflection_learning_context"


def test_insufficient_evidence_is_not_validated() -> None:
    event = normalize_reflection_evaluation(_reflection("insufficient_evidence", available=False), report=_report([]))
    assert event["validated_conclusion"] is False
    assert "insufficient_evidence_label" in event["validation_blockers"]


def test_parameter_pressure_ledger_created_and_links_reflection_id(tmp_path: Path) -> None:
    append_reflection_evaluations(_report([_reflection()]), root=tmp_path)
    events, _ = load_reflection_events(tmp_path)
    result = append_parameter_pressure_events(events, root=tmp_path, candidate_hash="candidate-a")
    rows, corrupt = read_jsonl_ledger(tmp_path / PARAMETER_PRESSURE_LEDGER_PATH)
    assert corrupt == 0
    assert result["appended_events"] == 1
    assert rows[0]["reflection_event_id"] == events[0]["event_id"]
    assert rows[0]["parameter"] == "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"
    assert rows[0]["adaptive_market_regime"]


def test_unknown_raw_regime_enriched_from_market_intelligence(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state/market_intelligence_context.json").write_text(
        json.dumps({"summary": {"network_regime": "supportive", "liquidity_regime": "neutral"}}),
        encoding="utf-8",
    )
    append_reflection_evaluations(_report([_reflection(market_regime="unknown")]), root=tmp_path)
    events, _ = load_reflection_events(tmp_path)
    assert events[0]["raw_market_regime"] == "unknown"
    assert events[0]["adaptive_market_regime"] == "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown"
    assert events[0]["regime_source"] == "market_intelligence"
    assert events[0]["regime_enriched"] is True
    append_parameter_pressure_events(events, root=tmp_path)
    rows, _ = read_jsonl_ledger(tmp_path / PARAMETER_PRESSURE_LEDGER_PATH)
    assert rows[0]["adaptive_market_regime"] == "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown"


def test_reflection_persistence_preserves_allowlisted_source_time_context() -> None:
    context = {
        "schema_version": "growbot_river_learning_context_v1",
        "captured_at_source_time": True,
        "state": {"confidence": 71.0, "spread_pct": 0.002},
        "regime": "range",
        "regime_context": {"market_regime": "range", "trend_regime": "sideways"},
        "data_policy": {"allowlisted_fields_only": True},
    }
    event = normalize_reflection_evaluation(_reflection(growbot_river_learning_context=context))
    assert event["growbot_river_learning_context"]["state"] == context["state"]
    assert event["growbot_river_learning_context"]["regime"] == "range"
    assert event["adaptive_market_regime"] == "range"


def test_reflection_persistence_does_not_add_empty_context_to_historical_events() -> None:
    event = normalize_reflection_evaluation(_reflection())
    assert "growbot_river_learning_context" not in event


def test_label_pressure_events_map_expected_directions(tmp_path: Path) -> None:
    append_reflection_evaluations(
        _report([
            _reflection("missed_opportunity"),
            _reflection("correct_wait", decision_time="2026-06-14T02:00:00Z"),
            _reflection("bad_trade", decision_time="2026-06-14T03:00:00Z", decision_type="approve_trade"),
        ]),
        root=tmp_path,
    )
    events, _ = load_reflection_events(tmp_path)
    append_parameter_pressure_events(events, root=tmp_path)
    rows, _ = read_jsonl_ledger(tmp_path / PARAMETER_PRESSURE_LEDGER_PATH)
    by_label = {row["label"]: row for row in rows}
    assert by_label["missed_opportunity"]["direction"] == "loosen"
    assert by_label["missed_opportunity"]["loosen_score"] > 0
    assert by_label["correct_wait"]["direction"] == "tighten"
    assert by_label["bad_trade"]["direction"] == "tighten"


def test_status_safety_flags_false(tmp_path: Path) -> None:
    status = build_reflection_persistence_status(root=tmp_path)
    assert status["can_authorize_execution"] is False
    assert status["can_mutate_parameters"] is False
