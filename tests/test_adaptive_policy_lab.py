from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from bot.adaptive_policy_lab import (
    SAMPLE_THRESHOLDS,
    append_candidate_history,
    apply_shrinkage,
    build_adaptive_policy_candidate,
    build_policy_lab_report,
    confidence_interval_excludes_current,
    conservative_step_toward,
    direction_stability_for,
    enrich_conclusion_market_regime,
    inject_adaptive_policy_feature_pack,
    is_validated_conclusion,
    label_pressure,
    map_pressure_to_parameter,
    normalize_parameter_scope_key,
    passes_effect_size_gate,
    regime_enrichment_report,
    robust_stats,
)


def _ev(
    idx: int,
    *,
    label: str = "missed_opportunity",
    ticker: str = "BTC-USDC",
    setup_type: str = "support_reclaim",
    blocker: str = "trigger_ready_too_strict_threshold",
    regime: str = "neutral",
    net: float = 0.02,
    day_span: int = 10,
) -> dict:
    start = datetime(2026, 6, 1, tzinfo=timezone.utc)
    ts = start + timedelta(days=idx % day_span, hours=idx // max(1, day_span))
    return {
        "available": True,
        "ticker": ticker,
        "decision_time": ts.isoformat().replace("+00:00", "Z"),
        "setup_type": setup_type,
        "main_blocker": blocker,
        "future_window_hours": 24,
        "max_favorable_excursion_pct": 0.04,
        "max_adverse_excursion_pct": -0.004,
        "estimated_roundtrip_fee_pct": 0.012,
        "estimated_spread_cost_pct": 0.0005,
        "estimated_slippage_buffer_pct": 0.0025,
        "estimated_net_after_cost_opportunity_pct": net,
        "label": label,
        "reason": "visible_setup_positive_net_path_passed_anti_hindsight_filters",
        "market_regime": regime,
    }


def _report(rows: list[dict]) -> dict:
    return {"summary": {"overall_bias": "too_strict"}, "evaluations": rows}


def _stable_history(direction: str = "loosen", parameter: str = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", scope: str = "setup_type_specific:support_reclaim", runs: int = 3) -> list[dict]:
    key = f"{parameter}|{scope}"
    return [{"direction_by_parameter_scope": {key: direction}, "candidate_available": False, "hash": str(i)} for i in range(runs)]


def _rows(
    total: int,
    *,
    missed: int = 50,
    tickers: tuple[str, ...] = ("BTC-USDC", "ETH-USDC", "SOL-USDC"),
    regimes: tuple[str, ...] = ("neutral", "supportive"),
    setup_type: str = "support_reclaim",
    blocker: str = "trigger_ready_too_strict_threshold",
    day_span: int = 10,
    net: float = 0.02,
) -> list[dict]:
    rows = []
    for i in range(total):
        label = "missed_opportunity" if i < missed else "correct_wait"
        rows.append(
            _ev(
                i,
                label=label,
                ticker=tickers[i % len(tickers)],
                regime=regimes[i % len(regimes)],
                setup_type=setup_type,
                blocker=blocker,
                day_span=day_span,
                net=net if label == "missed_opportunity" else 0.001,
            )
        )
    return rows


def test_validated_conclusion_requires_complete_reflection_fields() -> None:
    assert is_validated_conclusion(_ev(0)) is True
    bad = _ev(0)
    bad["label"] = "insufficient_evidence"
    assert is_validated_conclusion(bad) is False
    bad = _ev(0)
    bad.pop("estimated_net_after_cost_opportunity_pct")
    assert is_validated_conclusion(bad) is False


def test_under_300_total_conclusions_no_candidate() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(299, missed=80)))
    assert candidate["candidate_available"] is False
    assert candidate["reason"] == "insufficient_evidence_for_parameter_candidate"


def test_under_150_relevant_conclusions_blocks_parameter_change() -> None:
    rows = _rows(149, missed=80, setup_type="support_reclaim", blocker="normal_wait") + _rows(151, missed=0, setup_type="other_setup", blocker="normal_wait")
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows))
    assert candidate["candidate_available"] is False
    assert any("insufficient_relevant_conclusions_per_parameter" in b.get("blockers", []) for b in candidate["blocked_parameter_changes"])


def test_under_40_directional_error_labels_blocks_direction() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=39)))
    assert candidate["candidate_available"] is False
    assert any("insufficient_directional_error_labels" in b.get("blockers", []) for b in candidate["blocked_parameter_changes"])


def test_one_day_and_one_market_regime_block_candidate() -> None:
    one_day = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80, day_span=1)))
    same_day_rows = _rows(300, missed=80)
    for row in same_day_rows:
        row["decision_time"] = "2026-06-01T00:00:00Z"
    one_day = build_adaptive_policy_candidate(reflection_report=_report(same_day_rows))
    assert one_day["candidate_available"] is False
    assert "insufficient_separate_days" in one_day["lab_report"]["blockers"]
    one_regime = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80, regimes=("neutral",))))
    assert one_regime["candidate_available"] is False
    assert one_regime["reason"] == "insufficient_market_regimes"
    assert one_regime["direction_by_parameter_scope"] == {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab": "loosen"}
    assert one_regime["blocked_parameter_changes"][0]["direction"] == "loosen"
    assert one_regime["blocked_parameter_changes"][0]["direction_stability_gate"]["scope_key"] == "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"


def test_raw_duplicate_regimes_block_with_distinct_diversity_reason() -> None:
    rows = _rows(
        300,
        missed=220,
        regimes=(
            "network_supportive_liquidity_neutral",
            "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown",
        ),
        blocker="expected_net_edge_too_low",
    )
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows), history=_stable_history(scope="adaptive_policy_lab"))
    assert candidate["candidate_available"] is False
    assert candidate["reason"] == "insufficient_distinct_regime_diversity"
    assert candidate["regime_diversity"]["raw_regime_count"] == 2
    assert candidate["regime_diversity"]["distinct_regime_count"] == 1
    assert candidate["regime_diversity"]["deduped_regime_count"] == 1


def test_two_distinct_regimes_with_stable_direction_build_candidate() -> None:
    rows = _rows(300, missed=220, regimes=("supportive", "risk_off"), blocker="expected_net_edge_too_low")
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows), history=_stable_history(scope="adaptive_policy_lab"))
    assert candidate["candidate_available"] is True
    change = candidate["proposed_parameter_changes"][0]
    assert change["parameter"] == "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"
    assert change["direction"] == "loosen"
    assert change["candidate_value"]
    assert abs(float(change["change_pct_before_shrinkage"])) <= SAMPLE_THRESHOLDS["default_single_step_param_change_pct"]


def test_less_than_75_out_of_sample_blocks_parameter() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(200, missed=80, blocker="normal_wait") + _rows(100, missed=0, setup_type="other_setup", blocker="normal_wait")))
    assert candidate["candidate_available"] is False
    assert any("insufficient_out_of_sample_conclusions" in b.get("blockers", []) for b in candidate["blocked_parameter_changes"])


def test_less_than_three_tickers_blocks_global_change_but_not_setup_specific() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80, tickers=("BTC-USDC", "ETH-USDC"))))
    assert any(b.get("scope") == "global_only_if_multi_setup_multi_ticker_evidence" for b in candidate["blocked_parameter_changes"])


def test_setup_specific_evidence_does_not_make_global_parameter_change() -> None:
    candidate = build_adaptive_policy_candidate(reflection_report=_report(_rows(300, missed=80, setup_type="support_reclaim")))
    assert all(not c["scope"].startswith("global") for c in candidate["proposed_parameter_changes"])


def test_robust_stats_use_median_and_trimmed_mean_not_only_raw_mean() -> None:
    stats = robust_stats([1, 1, 1, 1, 100])
    assert stats["raw_mean"] != stats["median"]
    assert stats["trimmed_mean_10pct"] != stats["raw_mean"]


def test_candidate_change_default_and_hard_caps() -> None:
    value, pct = conservative_step_toward(100, 50, default_cap_pct=5, hard_cap_pct=10)
    assert value == 95
    assert pct == -5
    value, pct = conservative_step_toward(100, 1, default_cap_pct=20, hard_cap_pct=10)
    assert value == 90
    assert pct == -10


def test_effect_size_gate_deadband_blocks_small_changes() -> None:
    gate = passes_effect_size_gate(100.0, 96.0, min_effect_size_pct=5)
    assert gate["passed"] is False
    assert gate["actual_effect_size_pct"] == 4.0
    gate = passes_effect_size_gate(100.0, 94.0, min_effect_size_pct=5)
    assert gate["passed"] is True


def test_confidence_interval_gate_for_loosen_and_tighten() -> None:
    overlap = confidence_interval_excludes_current(100.0, 95.0, 105.0, "loosen")
    assert overlap["passed"] is False
    assert overlap["current_value_inside_ci"] is True
    loosen = confidence_interval_excludes_current(100.0, 90.0, 95.0, "loosen")
    assert loosen["passed"] is True
    tighten = confidence_interval_excludes_current(100.0, 105.0, 110.0, "tighten")
    assert tighten["passed"] is True


def test_direction_stability_requires_three_consecutive_runs() -> None:
    key = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|setup_type_specific:support_reclaim"
    unstable = direction_stability_for(key, "loosen", _stable_history(runs=2), required_runs=3)
    assert unstable["passed"] is False
    assert unstable["history_items_available"] == 2
    assert unstable["last_directions"] == ["loosen", "loosen"]
    assert unstable["stability_reason"] == "not_enough_history"
    assert unstable["match_strategy"] == "exact"
    assert unstable["matched_scope_key"] == key
    stable = direction_stability_for(key, "loosen", _stable_history(runs=3), required_runs=3)
    assert stable["passed"] is True
    assert stable["stability_reason"] == "stable"
    assert stable["observed_runs"] == 3


def test_direction_stability_normalizes_global_candidate_and_empty_scopes() -> None:
    expected = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
    assert normalize_parameter_scope_key("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "global") == expected
    for scope in ("", "global", "candidate"):
        history_key = f"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|{scope}"
        history = [{"direction_by_parameter_scope": {history_key: "loosen"}} for _ in range(3)]
        gate = direction_stability_for(expected, "loosen", history, required_runs=3)
        assert gate["passed"] is True
        assert gate["match_strategy"] == "normalized"
        assert gate["matched_scope_key"] == history_key


def test_direction_stability_parameter_unique_fallback_and_ambiguity() -> None:
    expected = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
    unique_key = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|setup_type_specific:trend_continuation"
    unique = direction_stability_for(expected, "loosen", [{"direction_by_parameter_scope": {unique_key: "loosen"}} for _ in range(3)], required_runs=3)
    assert unique["passed"] is True
    assert unique["match_strategy"] == "parameter_unique"
    assert unique["matched_scope_key"] == unique_key

    ambiguous = direction_stability_for(
        expected,
        "loosen",
        [
            {"direction_by_parameter_scope": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|setup_type_specific:trend_continuation": "loosen"}},
            {"direction_by_parameter_scope": {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|setup_type_specific:mean_reversion": "loosen"}},
        ],
        required_runs=3,
    )
    assert ambiguous["passed"] is False
    assert ambiguous["match_strategy"] == "ambiguous"
    assert ambiguous["stability_reason"] == "ambiguous_scope_keys"
    assert ambiguous["matched_scope_key"] == ""


def test_direction_stability_not_found_lists_available_scope_keys_and_direction_changes() -> None:
    expected = "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab"
    missing = direction_stability_for(expected, "loosen", [{"direction_by_parameter_scope": {"OTHER|scope": "loosen"}}], required_runs=3)
    assert missing["stability_reason"] == "scope_key_not_found"
    assert missing["match_strategy"] == "not_found"
    assert missing["available_scope_keys"] == ["OTHER|scope"]

    changed = direction_stability_for(
        expected,
        "loosen",
        [{"direction_by_parameter_scope": {expected: "loosen"}}, {"direction_by_parameter_scope": {expected: "tighten"}}],
        required_runs=3,
    )
    assert changed["stability_reason"] == "direction_changed"
    assert changed["last_directions"] == ["tighten"]


def test_candidate_history_writes_direction_by_parameter_scope_for_blocked_candidates(tmp_path) -> None:
    append_candidate_history(
        {
            "generated_at": "2026-06-14T00:00:00Z",
            "candidate_available": False,
            "recommendation": "collect_more_data",
            "hash": "abc",
            "blocked_parameter_changes": [
                {
                    "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                    "scope": "adaptive_policy_lab",
                    "direction": "loosen",
                    "blockers": ["insufficient_market_regimes"],
                }
            ],
        },
        root=tmp_path,
    )
    row = json.loads((tmp_path / "reports/adaptive_policy/history/adaptive-policy-candidate-history.jsonl").read_text(encoding="utf-8"))
    assert row["direction_by_parameter_scope"] == {"PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT|adaptive_policy_lab": "loosen"}


def test_shrinkage_halves_capped_step_and_caps_still_apply() -> None:
    capped, pct = conservative_step_toward(0.0125, 0.0108, default_cap_pct=5, hard_cap_pct=10)
    assert round(pct, 6) == -5
    assert round(apply_shrinkage(0.0125, capped, shrinkage_factor=0.5), 8) == 0.0121875
    capped, pct = conservative_step_toward(100, 1, default_cap_pct=20, hard_cap_pct=10)
    assert capped == 90
    assert pct == -10


def test_regime_enrichment_coverage_and_sources() -> None:
    rows = [_ev(i, regime="unknown") for i in range(10)]
    enriched_unknown = [{"adaptive_market_regime": "unknown"} for _ in rows]
    assert regime_enrichment_report(enriched_unknown)["passed"] is False
    mi = {"summary": {"network_regime": "supportive", "liquidity_regime": "neutral"}}
    assert enrich_conclusion_market_regime({"market_regime": "unknown"}, mi, {}) == "network_supportive_liquidity_neutral_trend_unknown_volatility_unknown"
    candle = {"recent_trend_pct": 0.02, "atr_pct": 0.01}
    assert enrich_conclusion_market_regime({"market_regime": "unknown"}, {}, candle) == "network_unknown_liquidity_unknown_trend_bullish_volatility_normal"


def test_regime_key_uses_market_intelligence_and_candle_context_together() -> None:
    from bot.adaptive_policy_lab import build_regime_enrichment_fields

    mi = {"summary": {"network_regime": "supportive", "liquidity_regime": "neutral"}}
    candle = {"trend_regime": "bearish", "volatility_regime": "high"}
    fields = build_regime_enrichment_fields({"market_regime": "unknown"}, mi, candle)
    assert fields["adaptive_market_regime"] == "network_supportive_liquidity_neutral_trend_bearish_volatility_high"
    assert fields["trend_regime"] == "bearish"
    assert fields["volatility_regime"] == "high"
    assert fields["regime_source"] == "market_intelligence+candle_context"
    bullish = build_regime_enrichment_fields({"market_regime": "unknown"}, mi, {"trend_regime": "bullish", "volatility_regime": "high"})
    assert bullish["adaptive_market_regime"] != fields["adaptive_market_regime"]


def test_label_pressure_maps_loosen_tighten_and_counterweights() -> None:
    pressure = label_pressure([_ev(0, label="too_strict_wait"), _ev(1, label="missed_opportunity")])
    assert pressure["loosen_score"] > 0
    assert pressure["net_pressure"] > 0
    pressure = label_pressure([_ev(0, label="bad_trade"), _ev(1, label="overtrading_risk")])
    assert pressure["tighten_score"] > 0
    assert pressure["net_pressure"] < 0
    damped = label_pressure([_ev(0, label="missed_opportunity"), _ev(1, label="correct_wait"), _ev(2, label="false_signal_avoided")])
    assert damped["tighten_score"] > 0


def test_parameter_mapping_stays_inside_allowed_parameter_surface() -> None:
    assert map_pressure_to_parameter({"main_blocker": "expected_net_edge_too_low"}) == "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"
    assert map_pressure_to_parameter({"main_blocker": "reward_to_fee_too_low"}) == "PHASE_D2_MIN_REWARD_TO_FEE_RATIO"
    forbidden = {"main_blocker": "EXECUTION_MODE REPLICATION_ENABLED MODE_C_MARKET_ORDER_ACK"}
    assert map_pressure_to_parameter(forbidden) == "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"


def test_candidate_new_gates_block_until_stable_history_and_enriched_regime() -> None:
    rows = _rows(300, missed=80, blocker="expected_net_edge_too_low", regimes=("neutral", "supportive"))
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows), history=[])
    assert candidate["candidate_available"] is False
    assert any("direction_stability_not_met" in b.get("blockers", []) for b in candidate["blocked_parameter_changes"])
    candidate = build_adaptive_policy_candidate(reflection_report=_report(rows), history=_stable_history())
    assert candidate["effect_size_gate"]["passed"] is True
    assert candidate["confidence_gate"]["passed"] is True
    assert candidate["direction_stability_gate"]["passed"] is True


def test_counterweights_and_overtrading_and_negative_net_block_or_dampen() -> None:
    high_correct = _rows(300, missed=45)
    candidate = build_adaptive_policy_candidate(reflection_report=_report(high_correct))
    assert candidate["candidate_available"] is False
    assert any("correct_wait_counterweight_too_high" in b.get("blockers", []) for b in candidate["blocked_parameter_changes"])
    over = _rows(300, missed=80)
    over[10]["label"] = "overtrading_risk"
    candidate = build_adaptive_policy_candidate(reflection_report=_report(over))
    assert any("overtrading_risk_present" in b.get("blockers", []) for b in candidate["blocked_parameter_changes"])
    negative = _rows(300, missed=80, net=-0.001)
    candidate = build_adaptive_policy_candidate(reflection_report=_report(negative))
    assert candidate["candidate_available"] is False


def test_adaptive_policy_feature_pack_disabled_by_default_and_context_only(tmp_path) -> None:
    pack = inject_adaptive_policy_feature_pack({"decision_context": {}}, tmp_path, env={})
    assert "external_context" not in pack["decision_context"]
    pack = inject_adaptive_policy_feature_pack({"decision_context": {}}, tmp_path, env={"ENABLE_ADAPTIVE_POLICY_CONTEXT": "true"})
    ctx = pack["decision_context"]["external_context"]["adaptive_policy_context"]
    assert ctx["can_authorize_execution"] is False
    assert ctx["can_block_execution"] is False
    assert ctx["can_mutate_parameters"] is False
    assert ctx["safe_to_activate_now"] is False


def test_lab_report_safety_flags_are_false() -> None:
    report = build_policy_lab_report(reflection_report=_report(_rows(10)))
    assert report["can_authorize_execution"] is False
    assert report["can_block_execution"] is False
    assert report["can_mutate_parameters"] is False
    assert report["source_policy"] == "adaptive_policy_report_only_no_live_mutation"
    assert SAMPLE_THRESHOLDS["min_total_validated_conclusions"] == 300
