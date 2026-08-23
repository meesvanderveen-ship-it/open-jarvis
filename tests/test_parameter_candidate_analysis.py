from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.adaptive_policy_lab import build_adaptive_policy_candidate
from bot.autonomous_parameter_governor import validate_governor
from bot.parameter_candidate_analysis import build_parameter_candidate_analysis, render_parameter_candidate_analysis_markdown, write_parameter_candidate_analysis
from bot.reflection_persistence import append_parameter_pressure_events, append_reflection_evaluations, load_reflection_events
from tests.test_adaptive_policy_lab import _report, _rows
from tests.test_adaptive_policy_lab import _stable_history
from tests.test_reflection_persistence import _reflection


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=ROOT, text=True, capture_output=True, check=True)


def _seed_ledgers(root: Path) -> None:
    append_reflection_evaluations(
        {
            "phase": "reflection_learning_context_v1",
            "generated_at": "2026-06-14T01:00:00Z",
            "evaluations": [
                _reflection("missed_opportunity"),
                _reflection("correct_wait", decision_time="2026-06-15T00:00:00Z"),
            ],
        },
        root=root,
    )
    events, _ = load_reflection_events(root)
    append_parameter_pressure_events(events, root=root)


def _seed_many_unknown_regime_ledgers(root: Path) -> dict:
    (root / "state").mkdir(parents=True, exist_ok=True)
    mi = {"summary": {"network_regime": "supportive", "liquidity_regime": "neutral"}}
    (root / "state/market_intelligence_context.json").write_text(json.dumps(mi), encoding="utf-8")
    rows = _rows(300, missed=220, regimes=("unknown",), blocker="expected_net_edge_too_low")
    append_reflection_evaluations(
        {
            "phase": "reflection_learning_context_v1",
            "generated_at": "2026-06-14T01:00:00Z",
            "evaluations": rows,
        },
        root=root,
    )
    events, _ = load_reflection_events(root)
    append_parameter_pressure_events(events, root=root)
    return build_adaptive_policy_candidate(reflection_report=_report(rows), market_intelligence_context=mi, history=[])


def test_candidate_analysis_json_md_and_required_fields(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80, regimes=("neutral",))))
    report = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)
    outputs = write_parameter_candidate_analysis(report, root=tmp_path)
    assert Path(outputs["json"]).exists()
    assert Path(outputs["markdown"]).exists()
    item = report["parameter_analysis"][0]
    assert {"current_value", "candidate_value", "blockers", "evidence", "statistical_gates"} <= set(item)
    assert "supporting_reflection_event_ids" in item
    assert "counterweight_reflection_event_ids" in item
    assert "dominant_tickers" in item["evidence"]
    assert "dominant_setup_types" in item["evidence"]
    assert "dominant_blockers" in item["evidence"]
    assert "history_items_available" in item["statistical_gates"]["direction_stability_gate"]
    assert "last_directions" in item["statistical_gates"]["direction_stability_gate"]
    assert "matched_scope_key" in item["statistical_gates"]["direction_stability_gate"]
    assert "match_strategy" in item["statistical_gates"]["direction_stability_gate"]


def test_candidate_unavailable_insufficient_market_regimes_is_explained(tmp_path: Path) -> None:
    candidate = _seed_many_unknown_regime_ledgers(tmp_path)
    report = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)
    assert report["candidate_available"] is False
    assert report["reason"] == "insufficient_market_regimes"
    assert report["recommendation"] == "collect_more_data"
    assert report["parameter_analysis"][0]["activation_status"] == "blocked"
    assert "insufficient_market_regimes" in report["parameter_analysis"][0]["interpretation"]
    item = report["parameter_analysis"][0]
    assert item["regime"]["ledger_regime_coverage_pct"] == 100.0
    assert item["regime"]["adaptive_gate_regime_coverage_pct"] == 100.0
    assert item["regime"]["adaptive_market_regimes"] == ["network_supportive_liquidity_neutral_trend_unknown_volatility_unknown"]
    assert item["regime"]["unique_enriched_regime_count"] == 1
    assert item["regime"]["required_unique_regime_count"] == 2
    assert item["regime"]["regime_gate_passed"] is False
    assert item["statistical_gates"]["direction_stability_gate"]["current_direction"] == "loosen"
    assert item["statistical_gates"]["direction_stability_gate"]["required_direction"] == "loosen"
    assert item["statistical_gates"]["direction_stability_gate"]["history_items_available"] == 0
    assert item["statistical_gates"]["direction_stability_gate"]["last_directions"] == []
    assert item["statistical_gates"]["direction_stability_gate"]["stability_reason"] == "not_enough_history"
    assert item["statistical_gates"]["effect_size_gate"]["calculated"] is True
    assert item["statistical_gates"]["effect_size_gate"]["used_for_activation"] is False
    assert item["statistical_gates"]["effect_size_gate"]["not_used_reason"] == "candidate_blocked_by_insufficient_market_regimes"
    assert item["statistical_gates"]["confidence_gate"]["calculated"] is True
    assert item["statistical_gates"]["confidence_gate"]["used_for_activation"] is False
    assert item["statistical_gates"]["confidence_gate"]["not_used_reason"] == "candidate_blocked_by_insufficient_market_regimes"
    assert item["pressure_explanation"]["supporting_event_count"] == item["supporting_label_count"]
    assert "counterweight_event_count" in item["pressure_explanation"]
    assert "average_supporting_quality" in item["pressure_explanation"]
    assert "average_counterweight_quality" in item["pressure_explanation"]
    assert item["direction_history"]["candidate_history_path"].endswith("adaptive-policy-candidate-history.jsonl")


def test_candidate_analysis_traceability_ids(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    report = build_parameter_candidate_analysis(root=tmp_path)
    item = report["parameter_analysis"][0]
    assert item["sample_event_ids"]
    assert len(item["sample_event_ids"]) <= 20
    assert item["supporting_reflection_event_ids"] or item["counterweight_reflection_event_ids"]


def test_candidate_analysis_separates_raw_and_enriched_regimes_in_markdown(tmp_path: Path) -> None:
    (tmp_path / "state").mkdir()
    (tmp_path / "state/market_intelligence_context.json").write_text(
        json.dumps({"summary": {"network_regime": "supportive", "liquidity_regime": "neutral"}}),
        encoding="utf-8",
    )
    append_reflection_evaluations(
        {
            "phase": "reflection_learning_context_v1",
            "generated_at": "2026-06-14T01:00:00Z",
            "evaluations": [_reflection("missed_opportunity", market_regime="unknown")],
        },
        root=tmp_path,
    )
    events, _ = load_reflection_events(tmp_path)
    append_parameter_pressure_events(events, root=tmp_path)
    report = build_parameter_candidate_analysis(root=tmp_path)
    item = report["parameter_analysis"][0]
    assert item["evidence"]["raw_market_regimes"] == ["unknown"]
    assert "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown" in item["evidence"]["adaptive_market_regimes"]
    assert "unknown" not in item["evidence"]["adaptive_market_regimes"]
    markdown = render_parameter_candidate_analysis_markdown(report)
    assert "raw regimes: unknown" in markdown
    assert "adaptive/enriched regimes: network_supportive_liquidity_neutral_trend_unknown_volatility_unknown" in markdown
    assert "ledger regime coverage:" in markdown
    assert "adaptive gate regime coverage:" in markdown
    assert "Waarom is de net pressure positief?" in markdown
    assert "marktregimes: unknown" not in markdown


def test_direction_stability_history_change_and_stable_runs_are_visible(tmp_path: Path) -> None:
    candidate = _seed_many_unknown_regime_ledgers(tmp_path)
    history_path = tmp_path / "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl"
    key = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(
            [
                json.dumps({"direction_by_parameter_scope": {key: "loosen"}}),
                json.dumps({"direction_by_parameter_scope": {key: "tighten"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    changed = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)["parameter_analysis"][0]["statistical_gates"]["direction_stability_gate"]
    assert changed["stability_reason"] == "direction_changed"
    assert changed["last_directions"] == ["tighten"]

    history_path.write_text(
        "\n".join(json.dumps({"direction_by_parameter_scope": {key: "loosen"}}) for _ in range(3)) + "\n",
        encoding="utf-8",
    )
    stable = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)["parameter_analysis"][0]["statistical_gates"]["direction_stability_gate"]
    assert stable["passed"] is True
    assert stable["stability_reason"] == "stable"
    assert stable["observed_runs"] == 3
    assert stable["matched_scope_key"] == key
    assert stable["match_strategy"] == "exact"


def test_direction_stability_scope_key_not_found_is_visible(tmp_path: Path) -> None:
    candidate = _seed_many_unknown_regime_ledgers(tmp_path)
    history_path = tmp_path / "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(json.dumps({"direction_by_parameter_scope": {"OTHER|scope": "loosen"}}) + "\n", encoding="utf-8")
    gate = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)["parameter_analysis"][0]["statistical_gates"]["direction_stability_gate"]
    assert gate["stability_reason"] == "scope_key_not_found"
    assert gate["available_scope_keys"] == ["OTHER|scope"]
    assert gate["match_strategy"] == "not_found"


def test_candidate_analysis_markdown_shows_direction_stability_scope_diagnostics(tmp_path: Path) -> None:
    candidate = _seed_many_unknown_regime_ledgers(tmp_path)
    key = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
    history_path = tmp_path / "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    history_path.write_text(
        "\n".join(json.dumps({"direction_by_parameter_scope": {key: "loosen"}}) for _ in range(3)) + "\n",
        encoding="utf-8",
    )
    markdown = render_parameter_candidate_analysis_markdown(build_parameter_candidate_analysis(root=tmp_path, candidate=candidate))
    assert "Direction stability:" in markdown
    assert f"- expected scope key: {key}" in markdown
    assert f"- matched scope key: {key}" in markdown
    assert "- match strategy: exact" in markdown
    assert "- available scope keys: PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab" in markdown
    assert "- last directions: loosen, loosen, loosen" in markdown
    assert "- observed runs: 3/3" in markdown


def test_confidence_interval_reports_insufficient_numeric_samples(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    candidate = {
        "candidate_available": False,
        "reason": "insufficient_market_regimes",
        "recommendation": "collect_more_data",
        "blocked_parameter_changes": [
            {
                "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                "scope": "adaptive_policy_lab",
                "current_value": "0.0125",
                "direction": "loosen",
                "blockers": ["insufficient_market_regimes"],
            }
        ],
    }
    report = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)
    gate = report["parameter_analysis"][0]["statistical_gates"]["confidence_gate"]
    assert gate["calculated"] is False
    assert gate["reason"] == "insufficient_numeric_samples"


def test_old_pressure_events_without_adaptive_regime_do_not_crash(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    path = tmp_path / "reports/adaptive_policy/history/parameter-pressure-events.jsonl"
    path.write_text(
        json.dumps({
            "event_id": "old",
            "reflection_event_id": "old-ref",
            "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
            "scope": "setup_type_specific:trend_continuation",
            "direction": "loosen",
            "label": "missed_opportunity",
            "loosen_score": 1.0,
            "tighten_score": 0.0,
            "market_regime": "unknown",
        }) + "\n",
        encoding="utf-8",
    )
    report = build_parameter_candidate_analysis(root=tmp_path)
    assert report["parameter_analysis"][0]["evidence"]["adaptive_market_regimes"]


def test_analyze_parameter_candidate_tool_writes_reports(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    result = _run(["tools/analyze_parameter_candidate.py", "--json", "--root", str(tmp_path)])
    payload = json.loads(result.stdout)
    assert payload["parameter_analysis_available"] is True
    assert (tmp_path / "reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.json").exists()
    assert (tmp_path / "reports/adaptive_policy/analysis/parameter-candidate-analysis-latest.md").exists()
    assert payload["can_mutate_parameters"] is False


def test_governor_status_references_candidate_analysis(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    report = build_parameter_candidate_analysis(root=tmp_path)
    write_parameter_candidate_analysis(report, root=tmp_path)
    status = validate_governor(root=tmp_path, candidate={"candidate_available": False, "reason": "insufficient_market_regimes"})
    assert status["candidate_analysis_available"] is True
    assert status["candidate_analysis_path"].endswith("parameter-candidate-analysis-latest.json")
    assert status["candidate_analysis_hash"]
    assert status["analysis_reason"] == report["reason"]
    assert status["can_mutate_allowed_parameters"] is False


def test_analysis_does_not_mutate_env_orders_positions_or_approved_profile(tmp_path: Path) -> None:
    _seed_ledgers(tmp_path)
    env = tmp_path / ".env"
    orders = tmp_path / "state/open_orders.json"
    positions = tmp_path / "state/positions.json"
    profile = tmp_path / "state/approved_parameter_profile.json"
    orders.parent.mkdir(parents=True, exist_ok=True)
    env.write_text("UNCHANGED=true\n", encoding="utf-8")
    orders.write_text('{"orders": {}}\n', encoding="utf-8")
    positions.write_text("{}\n", encoding="utf-8")
    profile.write_text('{"parameters": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125"}}\n', encoding="utf-8")
    _run(["tools/analyze_parameter_candidate.py", "--json", "--root", str(tmp_path)])
    assert env.read_text(encoding="utf-8") == "UNCHANGED=true\n"
    assert orders.read_text(encoding="utf-8") == '{"orders": {}}\n'
    assert positions.read_text(encoding="utf-8") == "{}\n"
    assert profile.read_text(encoding="utf-8") == '{"parameters": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT": "0.0125"}}\n'


def test_directional_error_labels_map_to_directional_events_with_provenance(tmp_path: Path) -> None:
    rows = _rows(300, missed=80, regimes=("supportive", "risk_off"), blocker="expected_net_edge_too_low")
    append_reflection_evaluations(
        {
            "phase": "reflection_learning_context_v1",
            "generated_at": "2026-06-14T01:00:00Z",
            "evaluations": rows,
        },
        root=tmp_path,
    )
    report = build_parameter_candidate_analysis(root=tmp_path, candidate=build_adaptive_policy_candidate(reflection_report=_report(rows)))
    evidence = report["parameter_analysis"][0]["evidence"]
    assert evidence["total_directional_events"] >= evidence["directional_error_labels"]
    assert evidence["directional_event_source"] == "reflection_evaluations.validated_conclusion.label"
    assert evidence["regime_counts"]
    assert any(values["directional_events"] > 0 for values in evidence["regime_counts"].values())


def test_analysis_candidate_available_true_populates_proposal_fields(tmp_path: Path) -> None:
    rows = _rows(300, missed=220, regimes=("supportive", "risk_off"), blocker="expected_net_edge_too_low")
    append_reflection_evaluations(
        {"phase": "reflection_learning_context_v1", "generated_at": "2026-06-14T01:00:00Z", "evaluations": rows},
        root=tmp_path,
    )
    events, _ = load_reflection_events(tmp_path)
    append_parameter_pressure_events(events, root=tmp_path)
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows), history=_stable_history(scope="adaptive_policy_lab"))
    report = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)
    assert report["candidate_available"] is True
    assert report["reason"] == "candidate_ready_for_operator_review"
    assert report["proposed_parameters"]["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]
    assert report["parameter_changes"][0]["direction"] == "loosen"
    assert report["candidate_hash"]
    assert report["evidence_hash"]
    assert report["live_apply_performed"] is False


def test_analysis_duplicate_regimes_exposes_exact_blocker(tmp_path: Path) -> None:
    rows = _rows(
        300,
        missed=220,
        regimes=(
            "network_supportive_liquidity_neutral",
            "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown",
        ),
        blocker="expected_net_edge_too_low",
    )
    append_reflection_evaluations(
        {"phase": "reflection_learning_context_v1", "generated_at": "2026-06-14T01:00:00Z", "evaluations": rows},
        root=tmp_path,
    )
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows), history=_stable_history(scope="adaptive_policy_lab"))
    report = build_parameter_candidate_analysis(root=tmp_path, candidate=candidate)
    assert report["candidate_available"] is False
    assert report["reason"] == "insufficient_distinct_regime_diversity"
    assert report["raw_regime_count"] == 2
    assert report["distinct_regime_count"] == 1
    assert report["candidate_generation_blocker"] == "insufficient_distinct_regime_diversity"
    assert "proposed_parameter_changes" in report["missing_candidate_fields"]
    assert report["candidate_hash"] == ""
    assert report["report_hash"]
    assert report["blocked_candidate_report_hash"]
