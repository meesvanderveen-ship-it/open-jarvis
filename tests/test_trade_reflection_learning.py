import json
from pathlib import Path

from bot.trade_reflection import (
    TradeReflectionStore,
    build_reflection_analytics,
    build_trade_reflection_input,
)


def _record(ticker="ADA-USDC", outcome="loss", setup="breakout_retest", pattern_family="breakout", range_position="near_resistance", volume="weak", pnl=-1.0, pnl_pct=-0.02):
    return {
        "generated_at": "2026-05-13T10:00:00Z",
        "ticker": ticker,
        "setup_type": setup,
        "metrics": {
            "outcome": outcome,
            "realized_pnl": pnl,
            "realized_pnl_pct": pnl_pct,
        },
        "context_buckets": {
            "setup_type": setup,
            "pattern_family": pattern_family,
            "range_position": range_position,
            "volume_confirmation": volume,
            "market_regime": "risk_off",
            "btc_context": "weak",
            "bucket_key": f"setup_type={setup}|pattern_family={pattern_family}|range_position={range_position}|volume_confirmation={volume}|market_regime=risk_off|btc_context=weak",
        },
        "learning_evidence": {
            "surprise_label": "negative_surprise" if outcome == "loss" else "positive_confirmation",
            "surprise_ratio": 2.5,
            "warning": "unit test",
        },
        "lesson": {
            "summary": "unit lesson",
            "avoid_conditions": ["avoid_unit"] if outcome == "loss" else [],
            "prefer_conditions": ["prefer_unit"] if outcome == "win" else [],
        },
    }


def test_build_trade_reflection_input_adds_learning_evidence():
    reflection = build_trade_reflection_input(
        ticker="ADA-USDC",
        position_before={
            "entry_price": "0.30",
            "position_size_base": "100",
            "opened_at": "2026-05-13T08:00:00+00:00",
        },
        closed_position={
            "close_price": "0.28",
            "close_time": "2026-05-13T12:00:00+00:00",
            "close_reason": "stop_loss",
            "realized_pnl": "-2.0",
        },
        chart_patterns={
            "patterns": [{"type": "breakout_retest", "family": "breakout", "quality": 75}],
            "market_structure": {"range_position": "near_resistance", "volume_confirmation": "weak"},
        },
        trade_plan={"plan_action": "prepare_breakout", "confidence": 78, "setup_type": "breakout_retest"},
        judge={"decision": "approve_trade", "confidence": 76, "setup_type": "breakout_retest"},
        feature_pack={"market_regime": "trend", "orderbook_context": {"best_bid": "0.279", "best_ask": "0.280"}},
    )

    assert "learning_evidence" in reflection
    assert reflection["learning_evidence"]["surprise_label"] in {"negative_surprise", "weak_setup_loss"}
    assert "context_buckets" in reflection
    assert reflection["lesson"]["anti_overfit_note"]
    assert reflection["growbot_river_learning_context"]["regime"] == "trend"
    assert reflection["growbot_river_learning_context"]["data_policy"]["raw_feature_pack_copied"] is False


def test_reflection_analytics_groups_repeated_losses():
    records = [
        _record("ADA-USDC", "loss", pnl=-1, pnl_pct=-0.02),
        _record("SOL-USDC", "loss", pnl=-2, pnl_pct=-0.03),
        _record("XRP-USDC", "loss", pnl=-1.5, pnl_pct=-0.01),
        _record("ETH-USDC", "win", setup="support_sweep_reclaim", pattern_family="reclaim", range_position="near_support", volume="strong", pnl=3, pnl_pct=0.04),
    ]

    analytics = build_reflection_analytics(records, min_samples_for_signal=3)

    assert analytics["count"] == 4
    assert analytics["overall"]["losses"] == 3
    assert analytics["candidate_avoid_contexts"]
    assert any(item["dimension"] == "setup_type" and item["value"] == "breakout_retest" for item in analytics["candidate_avoid_contexts"])
    assert analytics["surprise_flags"]
    assert "do not change live thresholds" in analytics["learning_policy"]


def test_reflection_store_writes_learning_report(tmp_path):
    path = tmp_path / "trade_reflections.jsonl"
    report_path = tmp_path / "trade_learning_report.json"
    store = TradeReflectionStore(path=path, max_records=50)
    for record in [_record("ADA-USDC", "loss"), _record("SOL-USDC", "loss"), _record("XRP-USDC", "loss")]:
        store.append(record)

    report = store.write_learning_report(output_path=report_path, limit=50, min_samples_for_signal=3)

    assert report_path.exists()
    payload = json.loads(report_path.read_text())
    assert payload["report_type"] == "trade_reflection_learning_report"
    assert payload["count"] == 3
    assert report["candidate_avoid_contexts"]
