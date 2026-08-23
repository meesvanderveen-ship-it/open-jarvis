from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.reflection_learning_context import (
    SOURCE_POLICY,
    build_context_state,
    build_reflection_learning_report,
    evaluate_decision_window,
    feature_pack_reflection_learning_context,
    inject_reflection_learning_feature_pack,
)


CFG = {
    "roundtrip_fee_pct": 0.012,
    "slippage_buffer_pct": 0.0025,
    "min_net_opportunity_pct": 0.005,
    "max_acceptable_mae_pct": 0.010,
    "windows_hours": [4],
}


def _candles(prices: list[tuple[float, float]], *, start: str = "2026-06-14T00:00:00Z") -> list[dict]:
    base = datetime.fromisoformat(start.replace("Z", "+00:00")).astimezone(timezone.utc)
    rows = []
    for idx, (high, low) in enumerate(prices):
        ts = base + timedelta(hours=idx)
        close = (high + low) / 2
        rows.append({"timestamp": ts.isoformat().replace("+00:00", "Z"), "start": int(ts.timestamp()), "open": close, "high": high, "low": low, "close": close, "volume": 1})
    return rows


def _wait(**overrides) -> dict:
    base = {
        "ticker": "BTC-USDC",
        "decision_time": "2026-06-14T00:00:00Z",
        "decision": "wait",
        "decision_type": "wait",
        "current_price": 100,
        "setup_visible": True,
        "setup_type": "reclaim_reversal",
        "main_blocker": "normal_wait",
        "feature_pack": {"market": {"spread_pct": 0.0005}},
    }
    base.update(overrides)
    return base


def _label(decision: dict, candles: list[dict]) -> str:
    return evaluate_decision_window(decision, candles, future_window_hours=4, config=CFG)["label"]


def test_pure_mfe_without_visible_setup_is_not_missed_opportunity() -> None:
    assert _label(_wait(setup_visible=False), _candles([(100.2, 99.9), (104, 100)])) == "correct_wait"


def test_mfe_after_costs_insufficient_is_correct_wait() -> None:
    assert _label(_wait(), _candles([(100.4, 99.9), (101.0, 99.8)])) == "correct_wait"


def test_high_mae_before_or_during_mfe_is_not_missed_opportunity() -> None:
    assert _label(_wait(), _candles([(100.2, 98.0), (104.0, 99.0)])) == "correct_wait"


def test_invalidation_first_is_correct_wait() -> None:
    decision = _wait(trade_plan={"stop_loss": 99.0})
    result = evaluate_decision_window(decision, _candles([(100.2, 98.8), (104.0, 100.0)]), future_window_hours=4, config=CFG)
    assert result["label"] == "correct_wait"
    assert result["invalidation_would_have_triggered"] is True


def test_spread_fee_makes_gross_move_net_negative() -> None:
    decision = _wait(feature_pack={"market": {"spread_pct": 0.02}})
    assert _label(decision, _candles([(103.0, 99.8)])) == "correct_wait"


def test_visible_setup_low_mae_positive_net_is_missed_opportunity() -> None:
    assert _label(_wait(), _candles([(100.4, 99.8), (103.0, 100.0)])) == "missed_opportunity"


def test_reflection_evaluation_preserves_source_time_learning_context() -> None:
    decision = _wait(growbot_river_learning_context={
        "schema_version": "growbot_river_learning_context_v1",
        "state": {"confidence": 71.0, "spread_pct": 0.002},
        "regime": "range",
        "regime_context": {"market_regime": "range"},
    })
    result = evaluate_decision_window(decision, _candles([(100.4, 99.8), (103.0, 100.0)]), future_window_hours=4, config=CFG)
    assert result["growbot_river_learning_context"]["regime"] == "range"


def test_reflection_evaluation_derives_state_and_regime_when_context_missing() -> None:
    candles = _candles([(100.4 + i * 0.1, 99.9 + i * 0.1) for i in range(40)])
    decision_time = candles[30]["timestamp"]
    decision = _wait(decision_time=decision_time, current_price=100.0 + 30 * 0.1)
    result = evaluate_decision_window(decision, candles, future_window_hours=4, config=CFG)
    ctx = result["growbot_river_learning_context"]
    assert ctx["state"]
    assert "confidence" in ctx["state"]
    assert ctx["regime"] != "unknown"


def test_strict_main_blocker_becomes_too_strict_wait() -> None:
    decision = _wait(main_blocker="trigger_ready_too_strict_threshold")
    assert _label(decision, _candles([(100.4, 99.8), (103.5, 100.0)])) == "too_strict_wait"


def test_risk_warning_blocks_missed_opportunity() -> None:
    decision = _wait(feature_pack={"market": {"spread_pct": 0.0005}, "decision_context": {"external_context": {"market_intelligence": {"summary": {"risk_warnings": ["risk_off"]}}}}})
    assert _label(decision, _candles([(100.4, 99.8), (104.0, 100.0)])) == "correct_wait"


def test_bad_trade_and_early_entry_labels() -> None:
    bad = _wait(decision="approve_trade", decision_type="approve_trade")
    assert _label(bad, _candles([(100.1, 98.0), (100.2, 98.5)])) == "bad_trade"
    early = _wait(decision="approve_trade", decision_type="approve_trade")
    assert _label(early, _candles([(103.0, 98.0)])) == "early_entry"


def test_false_breakout_candidate_is_overtrading_risk() -> None:
    candidate = _wait(decision="approve_trade_candidate", decision_type="approve_trade_candidate")
    assert _label(candidate, _candles([(102.0, 98.0)])) == "overtrading_risk"


def test_missing_candle_data_gives_insufficient_evidence() -> None:
    assert _label(_wait(), []) == "insufficient_evidence"


def test_context_flags_are_false_and_cannot_authorize_block_or_mutate(tmp_path: Path) -> None:
    report = build_reflection_learning_report(root=tmp_path, fixture_only=True, no_network=True)
    state = build_context_state(report)
    path = tmp_path / "state/reflection_learning_context.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(state), encoding="utf-8")
    ctx = feature_pack_reflection_learning_context(tmp_path)
    assert ctx["can_authorize_execution"] is False
    assert ctx["can_block_execution"] is False
    assert ctx["can_mutate_parameters"] is False
    assert state["source_policy"] == SOURCE_POLICY


def test_feature_pack_injection_is_disabled_by_default_and_context_only(tmp_path: Path) -> None:
    pack = inject_reflection_learning_feature_pack({"decision_context": {}}, tmp_path, env={})
    assert "external_context" not in pack["decision_context"]
    enabled = inject_reflection_learning_feature_pack({"decision_context": {}}, tmp_path, env={"ENABLE_REFLECTION_LEARNING_CONTEXT": "true"})
    ctx = enabled["decision_context"]["external_context"]["reflection_learning"]
    assert ctx["can_authorize_execution"] is False
    assert ctx["can_block_execution"] is False
    assert ctx["can_mutate_parameters"] is False


def test_report_is_read_only_and_does_not_mutate_env_or_order_state(tmp_path: Path) -> None:
    env_path = tmp_path / ".env"
    orders_path = tmp_path / "state/open_orders.json"
    env_path.write_text("UNCHANGED=true\n", encoding="utf-8")
    orders_path.parent.mkdir(parents=True, exist_ok=True)
    orders_path.write_text('{"orders": {}}\n', encoding="utf-8")
    report = build_reflection_learning_report(root=tmp_path, fixture_only=True, no_network=True)
    assert report["coinbase_submit_cancel_replace_calls_attempted"] is False
    assert report["env_mutation_performed"] is False
    assert report["production_order_state_mutation_performed"] is False
    assert env_path.read_text(encoding="utf-8") == "UNCHANGED=true\n"
    assert orders_path.read_text(encoding="utf-8") == '{"orders": {}}\n'
