import json
from datetime import datetime, timedelta, timezone

from bot.decision_outcome_tracker import (
    DecisionOutcomeStore,
    build_decision_snapshot_records,
    build_decision_outcome_summary,
    compute_path_metrics,
)


def _feature_pack(price=100.0, candles=None):
    return {
        "current_price": price,
        "candles": {
            "1h": candles or [
                {"time": "2026-05-13T00:00:00+00:00", "open": 100, "high": 101, "low": 99, "close": 100},
            ]
        },
    }


def test_compute_path_metrics_detects_mfe_mae_stop_and_tp():
    candles = [
        {"time": "2026-05-13T01:00:00+00:00", "open": 100, "high": 103, "low": 99, "close": 102},
        {"time": "2026-05-13T02:00:00+00:00", "open": 102, "high": 108, "low": 94, "close": 96},
    ]

    metrics = compute_path_metrics(
        start_price=100,
        start_time="2026-05-13T00:00:00+00:00",
        candles=candles,
        stop_loss=95,
        take_profit_1=106,
        take_profit_2=110,
    )

    assert metrics["available"] is True
    assert metrics["max_favorable_pct"] == 0.08
    assert metrics["max_adverse_pct"] == -0.06
    assert metrics["tp1_touched"] is True
    assert metrics["tp2_touched"] is False
    assert metrics["stop_touched"] is True


def test_build_decision_snapshot_records_for_wait_decision():
    generated = "2026-05-13T00:00:00+00:00"
    analysis = {
        "ticker": "ADA-USDC",
        "generated_at": generated,
        "feature_pack": _feature_pack(0.25),
        "judge": {"decision": "wait", "confidence": 72},
        "entry_gate": {"decision": "watch", "confidence": 66, "setup_type": "breakout_retest"},
        "trade_plan": {"plan_action": "no_plan", "confidence": 0},
        "chart_patterns": {"best_pattern_score": 70, "pattern_bias": "bullish"},
    }

    records = build_decision_snapshot_records(
        ticker="ADA-USDC",
        analysis=analysis,
        feature_pack=analysis["feature_pack"],
        horizons_hours=[4, 12],
    )

    assert len(records) == 2
    assert records[0]["ticker"] == "ADA-USDC"
    assert records[0]["decision_category"] in {"wait", "watch"}
    assert records[0]["status"] == "pending"
    assert records[0]["current_price"] == 0.25
    context = records[0]["growbot_river_learning_context"]
    assert context["captured_at_source_time"] is True
    assert context["data_policy"]["raw_feature_pack_copied"] is False
    assert context["state"]["confidence"] == 72.0


def test_store_resolves_due_wait_as_missed_opportunity(tmp_path):
    path = tmp_path / "decision_outcomes.json"
    log_path = tmp_path / "decision_outcomes.jsonl"
    store = DecisionOutcomeStore(path=path, log_path=log_path, min_move_pct=0.025, adverse_move_pct=0.02)

    generated = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    analysis = {
        "ticker": "SOL-USDC",
        "generated_at": generated,
        "feature_pack": _feature_pack(100),
        "judge": {"decision": "wait", "confidence": 70},
        "entry_gate": {"decision": "watch", "confidence": 60},
        "trade_plan": {"plan_action": "no_plan"},
    }
    added = store.record_analysis_decision(
        ticker="SOL-USDC",
        analysis=analysis,
        feature_pack=analysis["feature_pack"],
        horizons_hours=[4],
    )
    assert len(added) == 1

    future = _feature_pack(
        105,
        candles=[
            {"time": datetime.now(timezone.utc).isoformat(), "open": 100, "high": 106, "low": 99, "close": 105},
        ],
    )
    resolved = store.evaluate_due(feature_packs={"SOL-USDC": future})

    assert len(resolved) == 1
    assert resolved[0]["status"] == "resolved"
    assert resolved[0]["outcome"]["outcome_label"] == "missed_opportunity"
    assert resolved[0]["outcome"]["path_metrics"]["max_favorable_pct"] == 0.06

    summary = store.summary()
    assert summary["count"] == 1
    assert summary["missed_opportunities"][0]["ticker"] == "SOL-USDC"
    log_rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    assert log_rows[0]["records"][0]["growbot_river_learning_context"]["captured_at_source_time"] is True


def test_store_resolves_prepared_plan_as_false_positive(tmp_path):
    path = tmp_path / "decision_outcomes.json"
    log_path = tmp_path / "decision_outcomes.jsonl"
    store = DecisionOutcomeStore(path=path, log_path=log_path, min_move_pct=0.025, adverse_move_pct=0.02)

    generated = (datetime.now(timezone.utc) - timedelta(hours=5)).isoformat()
    analysis = {
        "ticker": "ETH-USDC",
        "generated_at": generated,
        "feature_pack": _feature_pack(100),
        "judge": {"decision": "wait", "confidence": 66},
        "entry_gate": {"decision": "analyze", "confidence": 70},
        "trade_plan": {
            "plan_action": "prepare_breakout",
            "stop_loss": 98,
            "take_profit_1": 104,
            "confidence": 71,
        },
    }
    store.record_analysis_decision(
        ticker="ETH-USDC",
        analysis=analysis,
        feature_pack=analysis["feature_pack"],
        horizons_hours=[4],
    )
    future = _feature_pack(
        97,
        candles=[
            {"time": datetime.now(timezone.utc).isoformat(), "open": 100, "high": 101, "low": 96, "close": 97},
        ],
    )
    resolved = store.evaluate_due(feature_packs={"ETH-USDC": future})

    assert resolved[0]["outcome"]["outcome_label"] == "false_positive_plan"
    summary = build_decision_outcome_summary(resolved)
    assert summary["false_positive_plans"][0]["ticker"] == "ETH-USDC"
