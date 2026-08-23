from __future__ import annotations

import sys
import types
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")

    class OpenAI:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    openai_stub.OpenAI = OpenAI
    sys.modules["openai"] = openai_stub

if "anthropic" not in sys.modules:
    anthropic_stub = types.ModuleType("anthropic")

    class Anthropic:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    anthropic_stub.Anthropic = Anthropic
    sys.modules["anthropic"] = anthropic_stub

from bot.state_store import StateStore
from bot.strategy_engine import StrategyEngine


def _cfg():
    return SimpleNamespace(
        execution_mode="live",
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
        phase_c_disable_exit_limit_orders=True,
    )


def test_strategy_engine_blocks_exit_before_any_legacy_executor_route(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()

    engine = StrategyEngine.__new__(StrategyEngine)
    engine.cfg = _cfg()
    engine.state = StateStore()
    engine.position_epsilon_base = Decimal("0.00000001")
    engine.min_trade_quote_usdc = Decimal("10")
    engine._write_jsonl = StrategyEngine._write_jsonl.__get__(engine, StrategyEngine)
    engine._to_decimal = StrategyEngine._to_decimal
    engine._json_safe = StrategyEngine._json_safe
    engine._now_iso = lambda: "2026-05-25T21:00:00+00:00"
    engine._extract_position_inventory_state = lambda position: {
        "bot_managed_base": Decimal("0.25"),
        "legacy_inventory_base": Decimal("0"),
    }
    engine._compute_inventory_sell_plan = lambda **kwargs: {
        "sell_total_base": "0.25",
        "sell_bot_base": "0.25",
        "sell_legacy_base": "0",
        "sell_scope": "bot_only",
    }
    engine._get_live_available_base = lambda ticker: Decimal("0.25")

    engine.state.create_position(
        ticker="BTC-USDC",
        side="BUY",
        order_id="pos-1",
        entry_price="100",
        position_size_base="0.25",
        position_size_quote="25",
        entry_reason="unit-test",
        extra={"status": "open", "bot_managed_base": "0.25"},
    )

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=engine.state.get_position("BTC-USDC"),
        action={"action": "close", "side": "SELL", "size_base": "0.25", "reason": "near_stop_with_bearish_confirmation"},
        feature_pack={"market": {"mid_price": "100"}},
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_policy"
    assert result["executed"] is False
    assert engine.state.get_position("BTC-USDC")["status"] == "open"

    assert not (tmp_path / "logs" / "live_exit_orders.jsonl").exists()
