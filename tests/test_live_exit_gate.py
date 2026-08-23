from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from bot.live_exit_gate import append_live_exit_event, build_blocked_live_exit_event, evaluate_live_exit_allowed


def _cfg(**overrides):
    base = dict(
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
        phase_c_disable_exit_limit_orders=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_sell_blocked_by_default_flags() -> None:
    evaluation = evaluate_live_exit_allowed(
        cfg=_cfg(),
        side="SELL",
        source_module="test",
        source_function="unit",
        source_tag="strategy_engine_live_position_exit",
        intended_exit_type="market_close",
        ticker="BTC-USDC",
    )
    assert evaluation["allowed"] is False
    assert "enable_live_exit_orders_false" in evaluation["block_reasons"]
    assert "source_not_explicitly_allowed_for_live_sell" in evaluation["block_reasons"]


def test_buy_not_gated() -> None:
    evaluation = evaluate_live_exit_allowed(cfg=_cfg(), side="BUY", ticker="BTC-USDC")
    assert evaluation["allowed"] is True
    assert evaluation["gate_applicable"] is False


def test_blocked_event_can_be_logged(tmp_path: Path) -> None:
    evaluation = evaluate_live_exit_allowed(
        cfg=_cfg(),
        side="SELL",
        source_module="test_module",
        source_function="test_function",
        source_tag="legacy_exit",
        intended_exit_type="market_close",
        ticker="BTC-USDC",
        execution_status="live_exit_blocked_by_policy",
    )
    event = build_blocked_live_exit_event(evaluation)
    path = tmp_path / "live_exit_orders.jsonl"
    append_live_exit_event(event, path)
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["blocked"] is True
    assert row["source_module"] == "test_module"
    assert row["execution_status"] == "live_exit_blocked_by_policy"
