from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.adaptive_policy_lab import _growbot_river_supplemental_changes
from bot.growbot_learning_adapter import _parameter_hints, build_episodes, discover_growbot_open_source, normalize_episode, validate_episode_contracts
from bot.growbot_river_readiness import (
    STABILIZATION_GATING_BLOCKERS,
    build_fast_start_autotune_readiness,
    build_growbot_river_readiness,
    build_live_cycle_readiness_report,
    build_river_dependency_status,
    build_stabilization_readiness,
    estimate_forward_episode_requirements,
)
from bot.growbot_river_learning_contract import (
    build_learning_context_snapshot,
    classify_compact_regime_from_metrics,
    derive_regime_metrics_from_candles,
    sanitize_learning_context_snapshot,
)
from bot.learnable_parameter_registry import build_learnable_parameter_registry
from bot.parameter_step_scheduler import schedule_parameter_steps
from bot.river_online_parameter_learner import run_river_online_parameter_learning


ROOT = Path(__file__).resolve().parents[1]


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, *args], cwd=ROOT, text=True, capture_output=True, check=True)


def test_registry_is_broad_and_never_auto_activatable(tmp_path: Path) -> None:
    registry = build_learnable_parameter_registry(tmp_path)
    assert registry["parameter_count"] >= 40
    categories = registry["category_counts"]
    assert {"entry_quality", "orderbook_c43", "sizing", "exit_d3", "regime_market_filters", "workflow_behaviour"} <= set(categories)
    assert all(item["automatic_activation_allowed"] is False for item in registry["parameters"])
    spread = next(item for item in registry["parameters"] if item["parameter"] == "MAX_SPREAD_PCT")
    assert spread["min"] < spread["default_value"] < spread["max"]
    assert spread["activation_route"] == "current_governor_and_approved_profile"


def test_fast_start_autotune_allowlist_is_narrower_than_full_governor_allowlist(tmp_path: Path) -> None:
    """fast_start is a deliberately smaller, lower-risk subset of the parameters
    the governor/approved-profile route already supports -- not a new route."""
    registry = build_learnable_parameter_registry(tmp_path)
    by_name = {item["parameter"]: item for item in registry["parameters"]}

    for name in ("PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "PHASE_D2_MIN_REWARD_TO_RISK_RATIO"):
        assert by_name[name]["fast_start_autotune_allowed"] is True
        assert by_name[name]["fast_start_max_step_pct"] == 2.0

    # MAX_SPREAD_PCT is allowlisted but capped at half the normal fine_tuning
    # ceiling per the explicit "extra caution" requirement.
    assert by_name["MAX_SPREAD_PCT"]["fast_start_autotune_allowed"] is True
    assert by_name["MAX_SPREAD_PCT"]["fast_start_max_step_pct"] == 1.0

    # Governor-supported but not on the narrower fast_start allowlist.
    assert by_name["EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT"]["fast_start_autotune_allowed"] is False
    assert by_name["EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT"]["fast_start_max_step_pct"] is None

    # High-risk / not governor-supported parameters are never fast_start-eligible.
    assert by_name["JUDGE_MIN_GATE_CONFIDENCE"]["fast_start_autotune_allowed"] is False
    assert by_name["DEFAULT_QUOTE_SIZE_USDC"]["fast_start_autotune_allowed"] is False


def test_verified_growbot_upstream_is_provenance_only_without_local_runtime(tmp_path: Path) -> None:
    source = discover_growbot_open_source(tmp_path)
    assert source["local_source_found"] is False
    assert source["source_code_executed"] is False
    assert source["upstream"]["repository_url"] == "https://github.com/britcruise9/GrowBot"
    assert source["upstream"]["license"] == "CC-BY-NC-4.0"
    assert source["upstream"]["upstream_learning_runtime_available"] is False


def test_local_growbot_source_is_manifested_but_never_imported(tmp_path: Path) -> None:
    source_dir = tmp_path / "vendor/GrowBot"
    source_dir.mkdir(parents=True)
    (source_dir / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (source_dir / "train_policy.py").write_text("raise RuntimeError('must never execute')\n", encoding="utf-8")
    source = discover_growbot_open_source(tmp_path)
    assert source["local_source_found"] is True
    assert source["source_code_executed"] is False
    assert source["local_inventory"]["learning_runtime_detected"] is True
    assert source["status"] == "local_source_detected_but_not_executed"


def test_episode_contract_reports_missing_regime_as_a_promotion_blocker() -> None:
    episode = {
        "episode_id": "contract-1",
        "source": "reflection",
        "episode_type": "decision_cycle",
        "state": {"spread_pct": 0.002},
        "regime": "unknown",
        "decision_context": {},
        "action": "parameter_setting_or_threshold_selection",
        "reward": -0.5,
        "reward_reasons": ["missed"],
        "raw_evidence_ref": {"source": "reflection"},
        "parameter_hints": [],
    }
    contract = validate_episode_contracts([episode])
    assert contract["syntactic_contract_passed"] is True
    assert contract["parameter_promotion_evidence_ready"] is False
    assert "insufficient_regime_enrichment_coverage" in contract["promotion_blockers"]


def test_learning_context_is_allowlisted_and_adapter_uses_its_regime() -> None:
    context = build_learning_context_snapshot(
        {
            "orderbook_context": {"best_bid": "99", "best_ask": "100"},
            "secret": "must_not_be_copied",
        },
        {"confidence": 71, "market_regime": "range", "api_key": "must_not_be_copied"},
    )
    assert context["state"] == {"confidence": 71.0, "spread_pct": pytest.approx(2 / 199)}
    assert context["regime"] == "range"
    assert "secret" not in context and "api_key" not in context
    episode = normalize_episode("trade_reflection", {"metrics": {"outcome": "loss", "realized_pnl_pct": -0.02}, "growbot_river_learning_context": context})
    assert episode["episode_type"] == "closed_trade"
    assert episode["label"] == "bad_trade"
    assert episode["state"]["confidence"] == 71.0
    assert episode["regime"] == "range"


def test_learning_context_sanitizer_drops_unallowlisted_fields_before_ledger_use() -> None:
    context = sanitize_learning_context_snapshot({
        "captured_at_source_time": True,
        "state": {"confidence": 70, "spread_pct": 0.002, "api_key": 123},
        "regime": "range",
        "regime_context": {"market_regime": "range", "secret": "must_not_persist"},
        "raw_feature_pack": {"secret": "must_not_persist"},
    })
    assert context["state"] == {"confidence": 70.0, "spread_pct": 0.002}
    assert context["regime_context"]["market_regime"] == "range"
    assert "api_key" not in context["state"]
    assert "secret" not in context


def test_readiness_never_marks_profile_or_live_ready(tmp_path: Path) -> None:
    episode_report = {
        "learning_data_contract": {
            "syntactic_contract_passed": True,
            "coverage": {
                "nonempty_feature_state_pct": 100,
                "known_market_regime_pct": 100,
                "observed_nonzero_reward_pct": 100,
                "parameter_hint_count": 100,
            },
        },
        "summary": {"distinct_known_regime_count": 3, "regime_evidence": {"known_market_regime_coverage_pct": 100}},
        "growbot_open_source": {},
    }
    river_report = {"backend": {"river_available": True}, "walk_forward_validation": {"passed": True}}
    readiness = build_growbot_river_readiness(root=tmp_path, episode_report=episode_report, river_report=river_report)
    assert readiness["readiness"]["report_only_ready"] is True
    assert readiness["readiness"]["stabilization_ready"] is True
    assert readiness["readiness"]["fast_start_autotune_ready"] is True
    assert readiness["readiness"]["parameter_profile_activation_ready"] is False
    assert readiness["readiness"]["mode_a_live_ready"] is False


def test_growbot_upstream_label_is_demoted_to_historical_once_river_available(tmp_path: Path) -> None:
    episode_report = {
        "learning_data_contract": {
            "syntactic_contract_passed": True,
            "coverage": {"nonempty_feature_state_pct": 51.0, "known_market_regime_pct": 50.6},
        },
        "summary": {"distinct_known_regime_count": 47},
        "growbot_open_source": {
            "status": "blocked_no_local_learning_runtime_and_upstream_has_no_published_learning_runtime",
        },
    }
    river_report = {"backend": {"river_available": True}, "walk_forward_validation": {"passed": True}}
    readiness = build_growbot_river_readiness(root=tmp_path, episode_report=episode_report, river_report=river_report)

    # The upstream-license label never gates anything once River already
    # supplies the live learning runtime: it must not appear as an active
    # blocker, only as a historical/stale readiness label.
    assert "growbot_upstream_learning_runtime_unavailable" not in readiness["blockers"]
    gating_blockers = set(readiness["blockers"]) & STABILIZATION_GATING_BLOCKERS
    assert gating_blockers == {"feature_snapshot_coverage_below_80pct", "market_regime_coverage_below_80pct"}
    historical_labels = {row["label"] for row in readiness["historical_readiness_labels"]}
    assert historical_labels == {"growbot_upstream_learning_runtime_unavailable"}
    assert readiness["historical_readiness_labels"][0]["status"] == "historical_stale_label_not_an_active_blocker"

    # Only the two coverage blockers are real, and the summary says so
    # without hard-coding the count (it must hold for one, two or three).
    summary = readiness["real_blockers_summary"]
    assert "feature_snapshot_coverage_below_80pct" in summary
    assert "market_regime_coverage_below_80pct" in summary
    assert "self-resolves with more live episodes" in summary


def test_growbot_upstream_label_still_blocks_when_river_unavailable(tmp_path: Path) -> None:
    episode_report = {
        "learning_data_contract": {
            "syntactic_contract_passed": True,
            "coverage": {"nonempty_feature_state_pct": 100, "known_market_regime_pct": 100},
        },
        "summary": {"distinct_known_regime_count": 5},
        "growbot_open_source": {
            "status": "blocked_no_local_learning_runtime_and_upstream_has_no_published_learning_runtime",
        },
    }
    river_report = {"backend": {"river_available": False}, "walk_forward_validation": {"passed": False}}
    readiness = build_growbot_river_readiness(root=tmp_path, episode_report=episode_report, river_report=river_report)

    assert "growbot_upstream_learning_runtime_unavailable" in readiness["blockers"]
    assert readiness["historical_readiness_labels"] == []


def test_fine_tuning_ready_requires_stabilization_and_fine_tuning_phase(tmp_path: Path) -> None:
    episode_report = {
        "learning_data_contract": {
            "syntactic_contract_passed": True,
            "coverage": {"nonempty_feature_state_pct": 100, "known_market_regime_pct": 100},
        },
        "summary": {"distinct_known_regime_count": 5},
        "growbot_open_source": {},
    }
    river_report = {"backend": {"river_available": True}, "walk_forward_validation": {"passed": True}}

    not_fine_tuning = build_growbot_river_readiness(
        root=tmp_path, episode_report=episode_report, river_report=river_report, cycle_report={"phase_decision": {"phase": "stabilization"}},
    )
    assert not_fine_tuning["readiness"]["stabilization_ready"] is True
    assert not_fine_tuning["readiness"]["fine_tuning_ready"] is False

    is_fine_tuning = build_growbot_river_readiness(
        root=tmp_path, episode_report=episode_report, river_report=river_report, cycle_report={"phase_decision": {"phase": "fine_tuning"}},
    )
    assert is_fine_tuning["readiness"]["fine_tuning_ready"] is True


def test_fast_start_autotune_readiness_uses_lower_bar_than_stabilization() -> None:
    """46.1%/45.75% coverage fails the strict 80%/80% stabilization bar but
    already clears the lower 50%/45% fast_start bar except for the feature-state
    shortfall -- this is the exact real-world numbers this tier was built for."""
    readiness = build_fast_start_autotune_readiness(
        coverage={"nonempty_feature_state_pct": 46.1, "known_market_regime_pct": 45.75},
        distinct_regime_count=5,
        river_available=True,
        walk_forward_passed=True,
    )
    assert readiness["ready"] is False
    assert readiness["real_blockers"] == ["feature_snapshot_coverage_below_50pct"]

    ready = build_fast_start_autotune_readiness(
        coverage={"nonempty_feature_state_pct": 51.0, "known_market_regime_pct": 46.0},
        distinct_regime_count=3,
        river_available=True,
        walk_forward_passed=True,
    )
    assert ready["ready"] is True
    assert ready["real_blockers"] == []


def test_fast_start_autotune_readiness_blocks_on_river_dependency_and_regime_diversity() -> None:
    readiness = build_fast_start_autotune_readiness(
        coverage={"nonempty_feature_state_pct": 90.0, "known_market_regime_pct": 90.0},
        distinct_regime_count=2,
        river_available=False,
        walk_forward_passed=False,
    )
    assert readiness["ready"] is False
    assert set(readiness["real_blockers"]) == {
        "river_native_sidecar_unavailable",
        "river_walk_forward_not_passed",
        "fewer_than_three_observed_market_regimes",
    }


def test_scheduler_keeps_coarse_proposals_bounded_and_report_only(tmp_path: Path) -> None:
    signals = [
        {
            "parameter": parameter,
            "direction": "loosen",
            "confidence": 0.9,
            "evidence_count": 12,
            "reasons": ["synthetic_missed_opportunity_cluster"],
        }
        for parameter in (
            "MAX_SPREAD_PCT",
            "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
            "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
            "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
            "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT",
            "COOLDOWN_MINUTES",
        )
    ]
    report = schedule_parameter_steps(signals, root=tmp_path, episode_count=20, regimes=["range"], history=[])
    assert report["phase"] == "coarse_tuning"
    assert len(report["proposals"]) == 5
    assert all(5.0 <= row["suggested_step_pct"] <= 15.0 for row in report["proposals"])
    assert all(row["parameter_mutation_allowed"] is False for row in report["proposals"])
    assert report["safety_policy"]["execution_authority"] is False


def test_scheduler_does_not_treat_backtest_as_a_market_regime(tmp_path: Path) -> None:
    report = schedule_parameter_steps(
        [{"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "confidence": 0.9, "evidence_count": 10}],
        root=tmp_path,
        episode_count=500,
        regimes=["unknown", "backtest", "historical"],
        history=[],
    )
    assert report["phase"] == "coarse_tuning"
    assert report["phase_decision"]["distinct_regime_count"] == 0


def test_scheduler_requires_fresh_memory_for_direction_stability(tmp_path: Path) -> None:
    signal = {"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "confidence": 0.9, "evidence_count": 10}
    stale_history = [{"proposals": [signal]} for _ in range(5)]
    stale = schedule_parameter_steps([signal], root=tmp_path, episode_count=500, regimes=["range", "trend", "volatile"], history=stale_history)
    assert stale["phase"] == "coarse_tuning"

    fresh_history = [{"new_memory_episodes": 1, "proposals": [signal]} for _ in range(3)]
    fresh = schedule_parameter_steps([signal], root=tmp_path, episode_count=500, regimes=["range", "trend", "volatile"], history=fresh_history)
    assert fresh["phase"] == "stabilization"


def test_episode_ids_preserve_distinct_horizons_and_river_deduplicates_input(tmp_path: Path) -> None:
    decision_log = tmp_path / "logs/decision_outcomes.jsonl"
    decision_log.parent.mkdir(parents=True)
    decision_log.write_text(
        json.dumps({
            "event": "decision_outcome_snapshots_stored",
            "records": [
                {
                    "ticker": "BTC-USDC",
                    "created_at": "2026-06-21T00:00:00Z",
                    "horizon_hours": horizon,
                    "decision": "wait",
                    "outcome_label": "missed_opportunity",
                }
                for horizon in (4, 12, 24)
            ],
        }) + "\n",
        encoding="utf-8",
    )
    built = build_episodes(tmp_path, max_per_source=10)
    episodes = built["episodes"]
    assert len(episodes) == 3
    assert len({row["episode_id"] for row in episodes}) == 3
    assert built["episode_identity"]["compact_identity_collisions_resolved"] == 2

    duplicate_batch = [episodes[0], dict(episodes[0])]
    first = run_river_online_parameter_learning(duplicate_batch, root=tmp_path)
    assert first["processing"]["newly_processed"] == 1
    assert first["processing"]["duplicate_episode_ids_in_input"] == 1
    second = run_river_online_parameter_learning(duplicate_batch, root=tmp_path)
    assert second["processing"]["newly_processed"] == 0


def test_real_river_models_are_persistent_when_dependency_is_available(tmp_path: Path) -> None:
    pytest.importorskip("river")
    episode = {
        "episode_id": "river-native-1",
        "label": "missed_opportunity",
        "reward": -0.5,
        "state": {"spread_pct": 0.007, "expected_net_edge_pct": 0.011},
        "regime": "range",
        "parameter_hints": [{"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "reason": "spread_too_high"}],
    }
    first = run_river_online_parameter_learning([episode], root=tmp_path)
    assert first["backend"]["backend"] == "river_native_streaming_models"
    assert (tmp_path / "reports/growbot_river/river-native-models.pkl").exists()
    assert (tmp_path / "reports/growbot_river/river-native-models-manifest.json").exists()
    second = run_river_online_parameter_learning([dict(episode, episode_id="river-native-2")], root=tmp_path)
    assert second["backend"]["model_persistence"]["loaded"] is True
    signal = next(item for item in second["parameter_signals"] if item["parameter"] == "MAX_SPREAD_PCT")
    assert signal["river_prediction_count"] == 1
    assert signal["river_expected_reward"] is not None


def test_native_river_bootstraps_after_fallback_without_replaying_fallback_stats(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import bot.river_online_parameter_learner as learner

    api = learner._import_river()
    if api is None:
        pytest.skip("real River optional dependency unavailable")
    episode = {
        "episode_id": "fallback-then-native-1",
        "label": "missed_opportunity",
        "reward": -0.5,
        "state": {"spread_pct": 0.007},
        "regime": "range",
        "parameter_hints": [{"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "reason": "spread_too_high"}],
    }
    monkeypatch.setattr(learner, "_import_river", lambda: None)
    fallback = learner.run_river_online_parameter_learning([episode], root=tmp_path)
    assert fallback["processing"]["newly_processed"] == 1

    monkeypatch.setattr(learner, "_import_river", lambda: api)
    native = learner.run_river_online_parameter_learning([episode], root=tmp_path)
    assert native["processing"]["newly_processed"] == 0
    assert native["processing"]["native_newly_processed"] == 1
    assert native["processing"]["native_input_dedup_contract_rebuilt"] is True
    assert native["backend"]["diagnostic_samples"] == 1


def test_coarse_and_nonroutable_sidecar_rows_cannot_enter_adaptive_candidates() -> None:
    report = {
        "proposals": [
            {
                "parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
                "phase": "coarse_tuning",
                "direction": "loosen",
                "confidence": 0.95,
                "evidence_count": 500,
                "current_value": 0.0125,
                "candidate_value": 0.011,
                "activation_route": "current_governor_and_approved_profile",
            },
            {
                "parameter": "TP1_ALLOCATION_PCT",
                "phase": "fine_tuning",
                "direction": "loosen",
                "confidence": 0.95,
                "evidence_count": 500,
                "current_value": 0.50,
                "candidate_value": 0.55,
                "activation_route": "research_only_profile_extension_required",
            },
        ]
    }
    eligible, blocked = _growbot_river_supplemental_changes(report, history=[])
    assert eligible == []
    blocked_by_parameter = {row["parameter"]: row["blockers"] for row in blocked}
    assert "growbot_river_coarse_tuning_requires_stabilization_before_candidate" in blocked_by_parameter["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"]
    assert "growbot_river_parameter_not_in_current_adaptive_allowlist" in blocked_by_parameter["TP1_ALLOCATION_PCT"]
    assert "growbot_river_parameter_not_routable_through_current_governor" in blocked_by_parameter["TP1_ALLOCATION_PCT"]


def test_cycle_uses_existing_logs_without_execution_or_profile_mutation(tmp_path: Path) -> None:
    reflection = {
        "evaluations": [
            {
                "decision_time": f"2026-06-2{i}T00:00:00Z",
                "ticker": f"ASSET{i}-USDC",
                "label": "missed_opportunity",
                "main_blocker": "spread_too_high",
                "market_regime": "range" if i % 2 else "trend",
                "confidence": 0.8,
                "estimated_net_after_cost_opportunity_pct": 0.02,
            }
            for i in range(1, 5)
        ]
    }
    reflection_path = tmp_path / "reports/reflection/reflection-learning-latest.json"
    reflection_path.parent.mkdir(parents=True)
    reflection_path.write_text(json.dumps(reflection), encoding="utf-8")
    profile = tmp_path / "state/approved_parameter_profile.json"
    profile.parent.mkdir(parents=True)
    profile.write_text(json.dumps({"parameters": {"MAX_SPREAD_PCT": "0.006"}}), encoding="utf-8")
    before_profile = profile.read_text(encoding="utf-8")
    orders = tmp_path / "state/open_orders.json"
    orders.write_text('{"orders": {}}\n', encoding="utf-8")
    before_orders = orders.read_text(encoding="utf-8")

    result = _run(["tools/run_growbot_river_learning_cycle.py", "--root", str(tmp_path), "--max-per-source", "10"])
    assert "growbot_river episodes=4" in result.stdout
    report_path = tmp_path / "reports/growbot_river/growbot-river-learning-latest.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["safety_policy"]["execution_authority"] is False
    assert report["safety_policy"]["parameter_mutation_allowed"] is False
    assert report["safety_policy"]["C43_D3_bypass_allowed"] is False
    assert report["downstream"]["autonomous_parameter_governor"].startswith("not_invoked")
    assert profile.read_text(encoding="utf-8") == before_profile
    assert orders.read_text(encoding="utf-8") == before_orders
    ledger = tmp_path / "reports/growbot_river/history/episodes.jsonl"
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 4
    proposal_history = tmp_path / "reports/growbot_river/history/proposal-history.jsonl"
    assert len(proposal_history.read_text(encoding="utf-8").splitlines()) == 1

    _run(["tools/run_growbot_river_learning_cycle.py", "--root", str(tmp_path), "--max-per-source", "10"])
    assert len(ledger.read_text(encoding="utf-8").splitlines()) == 4
    assert len(proposal_history.read_text(encoding="utf-8").splitlines()) == 1
    status = _run(["tools/show_growbot_river_learning_status.py", "--root", str(tmp_path), "--json"])
    payload = json.loads(status.stdout)
    assert payload["river_newly_processed"] == 0
    assert payload["governor_invoked"] is False
    assert payload["approved_profile_mutated"] is False


def test_classify_compact_regime_priority_order() -> None:
    assert classify_compact_regime_from_metrics(drawdown_pct=-0.08, volatility_pct=0.05, trend_strength=0.05) == "drawdown_risk_off"
    assert classify_compact_regime_from_metrics(volatility_pct=0.05, trend_strength=0.05) == "high_volatility"
    assert classify_compact_regime_from_metrics(trend_strength=0.05) == "trend_up"
    assert classify_compact_regime_from_metrics(trend_strength=-0.05) == "trend_down"
    assert classify_compact_regime_from_metrics(volatility_pct=0.002) == "low_volatility"
    assert classify_compact_regime_from_metrics(trend_strength=0.0, volatility_pct=0.01) == "range_chop"
    assert classify_compact_regime_from_metrics() == "unknown"


def test_derive_regime_metrics_from_candles_trend_and_drawdown() -> None:
    rising = [{"high": 101 + i, "low": 99 + i, "close": 100 + i} for i in range(10)]
    metrics = derive_regime_metrics_from_candles(rising)
    assert metrics["trend_strength"] > 0
    assert metrics["drawdown_pct"] == 0.0

    pulled_back = [{"high": 110, "low": 108, "close": 109}, {"high": 100, "low": 95, "close": 98}]
    metrics2 = derive_regime_metrics_from_candles(pulled_back)
    assert metrics2["drawdown_pct"] < 0
    assert derive_regime_metrics_from_candles([{"close": 1}]) == {}


def test_build_learning_context_snapshot_falls_back_to_candle_regime_when_unknown() -> None:
    candles = [{"high": 100.3 + i * 0.2, "low": 99.8 + i * 0.2, "close": 100.0 + i * 0.2} for i in range(8)]
    context = build_learning_context_snapshot({}, {"confidence": 0.6}, candles=candles)
    assert context["regime"] == "trend_up"
    assert context["state"]["trend_strength"] > 0

    explicit = build_learning_context_snapshot({}, {"confidence": 0.6, "market_regime": "supportive"}, candles=candles)
    assert explicit["regime"] == "supportive"


def test_trade_reflection_heartbeat_rows_are_not_counted_as_episodes(tmp_path: Path) -> None:
    log = tmp_path / "logs/trade_reflections.jsonl"
    log.parent.mkdir(parents=True)
    rows = [
        {"generated_at": "2026-06-21T00:00:00Z", "event": "trade_learning_cycle_summary", "summary": {"count": 1}},
        {
            "generated_at": "2026-06-21T00:00:00Z",
            "ticker": "BTC-USDC",
            "status": "stored",
            "reflection": {"metrics": {"outcome": "win", "realized_pnl_pct": 0.02}, "ticker": "BTC-USDC"},
        },
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    built = build_episodes(tmp_path, max_per_source=10)
    trade_reflection_episodes = [e for e in built["episodes"] if e["source"] == "trade_reflection"]
    assert len(trade_reflection_episodes) == 1
    assert trade_reflection_episodes[0]["label"] == "good_trade"


def test_decision_outcome_engine_summary_rows_are_not_counted_as_episodes(tmp_path: Path) -> None:
    log = tmp_path / "logs/decision_outcomes.jsonl"
    log.parent.mkdir(parents=True)
    rows = [
        {"generated_at": "2026-06-21T00:00:00Z", "event": "decision_outcome_snapshots_stored_by_engine", "ticker": "BTC-USDC", "count": 1},
        {
            "generated_at": "2026-06-21T00:00:00Z",
            "event": "decision_outcome_snapshots_stored",
            "records": [{"ticker": "BTC-USDC", "created_at": "2026-06-21T00:00:00Z", "horizon_hours": 4, "decision": "wait", "outcome_label": "missed_opportunity"}],
        },
    ]
    log.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    built = build_episodes(tmp_path, max_per_source=10)
    decision_outcome_episodes = [e for e in built["episodes"] if e["source"] == "decision_outcome"]
    assert len(decision_outcome_episodes) == 1


def test_river_signals_expose_regime_evidence_breakdown(tmp_path: Path) -> None:
    episodes = [
        {
            "episode_id": f"regime-episode-{i}",
            "label": "missed_opportunity",
            "reward": -0.5,
            "regime": "trend_up" if i % 2 == 0 else "range_chop",
            "parameter_hints": [{"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "reason": "spread_too_high"}],
        }
        for i in range(6)
    ]
    report = run_river_online_parameter_learning(episodes, root=tmp_path)
    signal = next(item for item in report["parameter_signals"] if item["parameter"] == "MAX_SPREAD_PCT")
    assert signal["regime_evidence_counts"] == {"trend_up": 3, "range_chop": 3}
    assert signal["dominant_regime"] in {"trend_up", "range_chop"}
    by_regime = report["regime_drift"]["deterministic_summary"]["by_regime"]
    assert by_regime["trend_up"]["count"] == 3
    assert by_regime["trend_up"]["average_reward"] == -0.5


def test_parameter_hints_widen_with_numeric_state_evidence() -> None:
    missed_state = {
        "spread_pct": 0.008,
        "expected_net_edge_pct": 0.005,
        "reward_to_fee": 2.0,
        "reward_to_risk": 1.0,
        "liquidity_score": 0.3,
        "orderbook_imbalance": 0.05,
        "volume_ratio": 0.5,
        "ticker_score": 30.0,
        "confidence": 0.5,
    }
    hints = _parameter_hints("missed_opportunity", {}, missed_state)
    parameters = {hint["parameter"] for hint in hints}
    assert parameters == {
        "MAX_SPREAD_PCT",
        "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT",
        "PHASE_D2_MIN_REWARD_TO_FEE_RATIO",
        "PHASE_D2_MIN_REWARD_TO_RISK_RATIO",
        "ORDERBOOK_LIQUIDITY_MIN_SCORE",
        "ORDERBOOK_IMBALANCE_MIN_ABS",
        "VOLUME_CONFIRMATION_MIN",
        "TICKER_SCORE_MIN",
        "JUDGE_MIN_GATE_CONFIDENCE",
    }
    assert all(hint["direction"] == "loosen" for hint in hints)
    # Evidence that does not cross any threshold yields no state-based hints.
    assert _parameter_hints("missed_opportunity", {}, {"spread_pct": 0.001, "confidence": 0.9}) == []


def test_parameter_hints_dedupe_per_parameter_direction() -> None:
    # main_blocker text and numeric state both point at MAX_SPREAD_PCT/loosen;
    # one episode must not double-count evidence for the same parameter.
    row = {"main_blocker": "spread too wide for entry"}
    state = {"spread_pct": 0.02}
    hints = _parameter_hints("missed_opportunity", row, state)
    spread_hints = [hint for hint in hints if hint["parameter"] == "MAX_SPREAD_PCT"]
    assert len(spread_hints) == 1


def test_bad_outcome_state_hints_cover_volatility_and_drawdown() -> None:
    bad_state = {
        "spread_pct": 0.008,
        "expected_net_edge_pct": 0.005,
        "reward_to_risk": 1.0,
        "confidence": 0.7,
        "volatility_pct": 0.05,
        "drawdown_pct": -0.08,
        "liquidity_score": 0.3,
    }
    hints = _parameter_hints("bad_trade", {}, bad_state)
    parameters = {hint["parameter"] for hint in hints}
    assert {"VOLATILITY_MAX_PCT", "STOP_DISTANCE_PCT", "JUDGE_MIN_GATE_CONFIDENCE", "ORDERBOOK_LIQUIDITY_MIN_SCORE"} <= parameters
    assert all(hint["direction"] == "tighten" for hint in hints)


def test_river_signals_expose_good_bad_missed_probabilities_and_regime_effect_direction(tmp_path: Path) -> None:
    episodes = []
    for i in range(10):
        regime = "trend_up" if i < 6 else "range_chop"
        # trend_up evidence is all loosen-direction missed opportunities;
        # range_chop evidence is all tighten-direction bad trades, so the same
        # parameter must show a different effect direction per regime.
        if regime == "trend_up":
            episodes.append({
                "episode_id": f"ep-tu-{i}",
                "label": "missed_opportunity",
                "reward": -0.5,
                "regime": regime,
                "parameter_hints": [{"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "reason": "spread_too_high"}],
            })
        else:
            episodes.append({
                "episode_id": f"ep-rc-{i}",
                "label": "bad_trade",
                "reward": -0.5,
                "regime": regime,
                "parameter_hints": [{"parameter": "MAX_SPREAD_PCT", "direction": "tighten", "reason": "adverse_or_bad_entry"}],
            })
    report = run_river_online_parameter_learning(episodes, root=tmp_path)
    signal = next(item for item in report["parameter_signals"] if item["parameter"] == "MAX_SPREAD_PCT")
    assert signal["missed_opportunity_probability"] == pytest.approx(0.6)
    assert signal["bad_trade_probability"] == 1.0
    assert signal["good_trade_probability"] == 0.0
    assert signal["regime_effect_direction"] == {"trend_up": "loosen", "range_chop": "tighten"}
    assert signal["dominant_regime"] in {"trend_up", "range_chop"}
    drift_hint = signal["regime_drift_hint"]
    assert drift_hint["available"] is True
    assert drift_hint["regime"] == signal["dominant_regime"]
    assert drift_hint["observations"] > 0


def test_stabilization_readiness_distinguishes_historical_forward_and_real_blockers() -> None:
    episodes = [
        {"source": "reflection", "state": {"confidence": 0.5}, "regime": "trend_up"},
        {"source": "reflection", "state": {"confidence": 0.5}, "regime": "range_chop"},
        {"source": "decision_outcome", "state": {}, "regime": "unknown"},
        {"source": "decision_outcome", "state": {}, "regime": "unknown"},
        {"source": "trade_reflection", "state": {}, "regime": "unknown"},
    ]
    blockers = [
        "feature_snapshot_coverage_below_80pct",
        "market_regime_coverage_below_80pct",
        "river_native_sidecar_unavailable",
        "river_walk_forward_not_passed",
        "adaptive_candidate_not_available",
        "growbot_upstream_learning_runtime_unavailable",
    ]
    readiness = build_stabilization_readiness(blockers=blockers, episodes=episodes)
    assert readiness["ready"] is False
    # Only the exact gating set appears as a "real" stabilization blocker;
    # downstream/permanent blockers are not stabilization blockers.
    real_blocker_names = {row["blocker"] for row in readiness["real_blockers"]}
    assert real_blocker_names == {
        "feature_snapshot_coverage_below_80pct",
        "market_regime_coverage_below_80pct",
        "river_native_sidecar_unavailable",
        "river_walk_forward_not_passed",
    }
    assert "adaptive_candidate_not_available" not in real_blocker_names
    assert "growbot_upstream_learning_runtime_unavailable" not in real_blocker_names
    assert readiness["historical_coverage_gap"]["by_source"]["decision_outcome"]["nonempty_feature_state_pct"] == 0.0
    assert readiness["historical_coverage_gap"]["is_blocking"] is False
    assert readiness["forward_ready_coverage"]["by_source"]["reflection"]["known_market_regime_pct"] == 100.0


def test_stabilization_readiness_is_ready_when_no_gating_blockers_present() -> None:
    readiness = build_stabilization_readiness(blockers=["adaptive_candidate_not_available"], episodes=[])
    assert readiness["ready"] is True
    assert readiness["real_blockers"] == []


def test_river_report_remains_report_only_with_new_diagnostic_fields(tmp_path: Path) -> None:
    episode = {
        "episode_id": "safety-1",
        "label": "missed_opportunity",
        "reward": -0.5,
        "regime": "trend_up",
        "parameter_hints": [{"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "reason": "spread_too_high"}],
    }
    report = run_river_online_parameter_learning([episode], root=tmp_path)
    assert report["safety_policy"]["execution_authority"] is False
    assert report["safety_policy"]["parameter_mutation_allowed"] is False
    assert report["safety_policy"]["report_only"] is True
    signal = report["parameter_signals"][0]
    assert signal["safe_to_activate_now"] is False


def test_estimate_forward_episode_requirements_rollover_vs_additive() -> None:
    estimate = estimate_forward_episode_requirements(
        coverage={"nonempty_feature_state_pct": 47.5672, "known_market_regime_pct": 47.2269},
        episode_count=2939,
    )
    # Rollover (capped-window) model must always be far cheaper than the
    # additive worst case for the same coverage gap.
    assert 0 < estimate["episodes_needed_rollover_model"] < estimate["episodes_needed_additive_worst_case"]
    assert estimate["episodes_needed_rollover_model"] == pytest.approx(964, abs=5)
    assert estimate["target_pct"] == 80.0


def test_estimate_forward_episode_requirements_zero_when_already_at_target() -> None:
    estimate = estimate_forward_episode_requirements(
        coverage={"nonempty_feature_state_pct": 100.0, "known_market_regime_pct": 100.0},
        episode_count=500,
    )
    assert estimate["episodes_needed_rollover_model"] == 0
    assert estimate["episodes_needed_additive_worst_case"] == 0


def test_river_dependency_status_reports_real_import_error_when_unavailable() -> None:
    status = build_river_dependency_status({"backend": {"river_available": False, "backend": "deterministic_incremental_stats_river_compatible"}})
    assert status["available"] is False
    assert "river" in status["import_error_detail"].lower() or status["import_error_detail"] == ""
    assert status["fallback_backend_sufficient_for_report_only_use"] is True
    assert any("requirements-river-sidecar.txt" in step for step in status["safe_install_route"])


def test_river_dependency_status_reflects_available_backend() -> None:
    status = build_river_dependency_status({
        "backend": {
            "river_available": True,
            "backend": "river_native_streaming_models",
            "model_persistence": {"loaded": True},
        }
    })
    assert status["available"] is True
    assert status["model_persistence"]["loaded"] is True


def test_live_cycle_readiness_report_has_all_required_sections(tmp_path: Path) -> None:
    episode_report = {
        "learning_data_contract": {
            "coverage": {"nonempty_feature_state_pct": 47.5, "known_market_regime_pct": 47.2},
            "episode_count": 2939,
        },
    }
    river_report = {
        "backend": {"river_available": False, "backend": "deterministic_incremental_stats_river_compatible"},
        "parameter_signals": [
            {
                "parameter": "MAX_SPREAD_PCT",
                "direction": "loosen",
                "confidence": 0.8,
                "evidence_count": 50,
                "expected_reward": -0.4,
                "missed_opportunity_probability": 0.6,
                "good_trade_probability": 0.1,
                "bad_trade_probability": 0.9,
                "dominant_regime": "trend_up",
                "regime_effect_direction": {"trend_up": "loosen"},
                "candidate_ranking_score": 0.6,
                "activation_route": "current_governor_and_approved_profile",
                "safe_to_activate_now": False,
            }
        ],
    }
    report = build_live_cycle_readiness_report(root=tmp_path, episode_report=episode_report, river_report=river_report, cycle_report={})
    for key in (
        "current_phase",
        "ranked_parameter_candidates",
        "stabilization_readiness",
        "forward_episode_requirements",
        "river_dependency_status",
        "top_learning_signals",
        "remaining_real_limitations",
        "recommended_next_live_cycle_observations",
    ):
        assert key in report, f"missing required section: {key}"
    assert report["ranked_parameter_candidates"][0]["parameter"] == "MAX_SPREAD_PCT"
    assert report["safety_policy"]["can_mutate_parameters"] is False
    assert report["safety_policy"]["can_authorize_execution"] is False
    assert len(report["top_learning_signals"]) == 14
    signals_by_name = {row["signal"] for row in report["top_learning_signals"]}
    assert {"liquidity", "orderbook_imbalance", "volume_ratio", "ticker_score", "setup_type", "confidence", "spread", "volatility", "reward/fee", "reward/risk", "fill/no-fill", "slippage", "MFE/MAE", "exit result"} == signals_by_name
    # volume_ratio/ticker_score are honestly flagged as having no live
    # producer yet; every other signal must already have a confirmed one.
    by_signal = {row["signal"]: row for row in report["top_learning_signals"]}
    assert by_signal["volume_ratio"]["live_producer_exists"] is False
    assert by_signal["ticker_score"]["live_producer_exists"] is False
    assert all(row["live_producer_exists"] for name, row in by_signal.items() if name not in {"volume_ratio", "ticker_score"})


def test_forward_episode_requirements_include_automatic_pass_condition() -> None:
    estimate = estimate_forward_episode_requirements(
        coverage={"nonempty_feature_state_pct": 47.5672, "known_market_regime_pct": 47.2269},
        episode_count=2939,
    )
    assert estimate["approx_live_decision_cycles_needed"] > 0
    assert "no further code change" in estimate["automatic_pass_condition"].lower()
    assert str(estimate["episodes_needed_rollover_model"]) in estimate["automatic_pass_condition"]

    already_met = estimate_forward_episode_requirements(
        coverage={"nonempty_feature_state_pct": 100.0, "known_market_regime_pct": 100.0},
        episode_count=500,
    )
    assert already_met["approx_live_decision_cycles_needed"] == 0
    assert "already met" in already_met["automatic_pass_condition"].lower()


def test_execution_outcome_paths_derive_regime_from_feature_pack_candles() -> None:
    from bot.execution_outcome_tracker import build_paper_execution_outcome, build_paper_no_fill_followup_outcome

    candles = [{"high": 100.3 + i * 0.2, "low": 99.8 + i * 0.2, "close": 100.0 + i * 0.2} for i in range(8)]
    feature_pack = {
        "raw_context": {
            "1h": {
                "starts": list(range(8)),
                "highs": [c["high"] for c in candles],
                "lows": [c["low"] for c in candles],
                "closes": [c["close"] for c in candles],
                "volumes": [1] * 8,
            }
        }
    }
    order = {"side": "BUY", "ticker": "BTC-USDC", "limit_price": "100", "status": "filled", "feature_pack": feature_pack}
    evaluation = {"action": "fill", "status": "filled", "fill_price": "100", "market_snapshot": {"best_bid": "99.9", "best_ask": "100.1"}}
    fill_context = build_paper_execution_outcome(order, evaluation)["growbot_river_learning_context"]
    assert fill_context["regime"] != "unknown"
    assert fill_context["context"]["fill_status"] == "filled"

    followup_order = {"side": "BUY", "ticker": "BTC-USDC", "limit_price": "100", "status": "expired"}
    followup_context = build_paper_no_fill_followup_outcome(followup_order, feature_pack)["growbot_river_learning_context"]
    assert followup_context["regime"] != "unknown"
    assert followup_context["context"]["fill_status"] == "expired"
