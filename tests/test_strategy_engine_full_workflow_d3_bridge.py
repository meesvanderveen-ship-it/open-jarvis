from __future__ import annotations

import sys
import types
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

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

if "pandas" not in sys.modules:
    pandas_stub = types.ModuleType("pandas")
    pandas_stub.DataFrame = object
    pandas_stub.Series = object
    pandas_stub.concat = lambda *args, **kwargs: []
    pandas_stub.isna = lambda value: value is None
    sys.modules["pandas"] = pandas_stub

if "numpy" not in sys.modules:
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.nan = float("nan")
    numpy_stub.arange = lambda *args, **kwargs: []
    numpy_stub.polyfit = lambda *args, **kwargs: [0]
    sys.modules["numpy"] = numpy_stub

from bot.order_store import OrderStore
from bot.phase_d3_controlled_live_exits import D3_ACK
from bot.state_store import StateStore
from bot.strategy_engine import StrategyEngine


@pytest.fixture(autouse=True)
def _clear_forbidden_bridge_env(monkeypatch) -> None:
    for name in (
        "REPLICATION_ENABLED",
        "MARKET_ORDER_ENABLED",
        "ENABLE_MARKET_ORDERS",
        "ALLOW_MARKET_ORDERS",
        "LEARNING_TO_EXECUTION_READY",
        "LEARNING_TO_EXECUTION_ALLOWED",
        "LIVE_LEARNING_ALLOWED",
        "PARAMETER_CHANGE_ALLOWED",
    ):
        monkeypatch.setenv(name, "false")


class ExecutorShouldNotBeCalled:
    def execute_close_spot_position(self, **kwargs):
        raise AssertionError("legacy close executor should not be called")


class FakeCoinbaseClient:
    def __init__(self) -> None:
        self.limit_calls: list[dict] = []
        self.market_calls: list[dict] = []

    def place_limit_order(self, **kwargs):
        self.limit_calls.append(kwargs)
        return {"success": True, "order_id": "cb-d3-exit-1"}

    def place_market_order(self, **kwargs):  # pragma: no cover - must never run
        self.market_calls.append(kwargs)
        raise AssertionError("market order must not be used")


def _cfg(**overrides):
    values = {
        "execution_mode": "live",
        "enable_full_workflow_live_mode": True,
        "enable_live_exit_orders": True,
        "autonomous_allow_exits": True,
        "enable_phase_d3_actual_exit_submit": True,
        "enable_phase_d3_controlled_live_exits": True,
        "phase_c_disable_exit_limit_orders": False,
        "autonomous_entry_only_first": False,
        "phase_c_allowed_tickers": ["BTC-USDC"],
        "phase_d3_max_exit_order_quote": Decimal("20.00"),
        "phase_d3_max_open_exit_orders": 3,
        "phase_d3_max_new_exit_orders_per_cycle": 1,
        "phase_d3_exit_order_post_only": True,
        "phase_d3_runtime_submit_ack": D3_ACK,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _position(**overrides):
    values = {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "pos-1",
        "entry_price": "76000",
        "position_size_base": "0.0003083267431275",
        "bot_managed_base": "0.0003083267431275",
        "position_size_quote": "19.03",
        "opened_via_phase_c43_live_order": True,
        "stop_price": "70000",
        "invalidation_price": "69500",
    }
    values.update(overrides)
    return values


def _feature_pack():
    return {
        "market": {"mid_price": "71554.20", "best_bid": "71554.19", "best_ask": "71554.20"},
        "orderbook_context": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "best_bid": "71554.19",
            "best_ask": "71554.20",
        },
        "exchange_rules": {
            "base_increment": "0.00000001",
            "price_increment": "0.01",
            "quote_min_size": "1.00",
        },
    }


def _engine(tmp_path: Path, *, cfg=None, client=None) -> StrategyEngine:
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.cfg = cfg or _cfg()
    engine.client = client if client is not None else FakeCoinbaseClient()
    engine.executor = ExecutorShouldNotBeCalled()
    engine.state = StateStore()
    engine.order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "order_events.jsonl")
    engine.position_epsilon_base = Decimal("0.00000001")
    engine.min_trade_quote_usdc = Decimal("1")
    engine._write_jsonl = StrategyEngine._write_jsonl.__get__(engine, StrategyEngine)
    engine._to_decimal = StrategyEngine._to_decimal
    engine._json_safe = StrategyEngine._json_safe
    engine._now_iso = lambda: "2026-06-10T00:00:00+00:00"
    engine._extract_position_inventory_state = lambda position: {
        "bot_managed_base": Decimal(str(position.get("bot_managed_base", "0"))),
        "legacy_inventory_base": Decimal(str(position.get("legacy_inventory_base", "0"))),
    }
    engine._compute_inventory_sell_plan = lambda **kwargs: {
        "sell_total_base": str(kwargs.get("requested_bot_sell_base", "0")),
        "sell_bot_base": str(kwargs.get("requested_bot_sell_base", "0")),
        "sell_legacy_base": "0",
        "sell_scope": "bot_only",
    }
    engine._get_live_available_base = lambda ticker: Decimal("0.0003083267431275")
    return engine


def _full_close_action():
    return {
        "action": "close",
        "side": "SELL",
        "size_base": "0.0003083267431275",
        "reason": "judge_close_position",
    }


def _stop_close_action():
    return {
        "action": "close",
        "side": "SELL",
        "size_base": "0.0003083267431275",
        "reason": "stop_loss_hit",
        "metadata": {"current_price": "71554.20"},
    }


def test_full_workflow_discretionary_close_routes_to_d3_full_close_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_live_exit_submitted"
    assert result["executed"] is True
    assert result["d3_full_workflow_bridge"]["submit_live"] is True
    assert result["d3_controlled_exit_report"]["selected_exit_intent"]["label"] == "FULL_CLOSE"
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"
    assert client.limit_calls[0]["post_only"] is True
    assert client.market_calls == []
    assert engine.order_store.open_exit_orders("BTC-USDC")


def test_stop_close_routes_to_controlled_stop_preview_without_d3_submit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_stop_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "controlled_stop_exit_preview_required"
    assert result["executed"] is False
    assert result["d3_full_workflow_bridge"]["required_route"] == "controlled_stop_exit"
    assert result["controlled_stop_exit_report"]["no_coinbase_submit"] is True
    assert client.limit_calls == []
    assert client.market_calls == []
    assert engine.order_store.open_exit_orders("BTC-USDC") == []


def test_full_close_blocks_stale_ask_that_diverges_from_market_evidence(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)
    position = _position(
        entry_price="0.17000",
        position_size_base="121.58054711",
        bot_managed_base="121.58054711",
        position_size_quote="20.00",
        stop_price="0.16148",
        invalidation_price="0.159565",
    )
    feature_pack = {
        "market": {"mid_price": "0.16200", "best_bid": "0.16199", "best_ask": "0.16200"},
        "orderbook_context": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "best_bid": "0.16999",
            "best_ask": "0.17000",
        },
        "exchange_rules": {"base_increment": "0.00000001", "price_increment": "0.00001", "quote_min_size": "1.00"},
    }
    action = {
        **_full_close_action(),
        "size_base": "121.58054711",
        "metadata": {"current_price": "0.16200"},
    }

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=action,
        feature_pack=feature_pack,
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_readiness"
    intent = result["d3_controlled_exit_report"]["selected_exit_intent"]
    assert intent["limit_price"] == "0.17001"
    assert intent["market_evidence_price"] == "0.16200"
    assert "full_close_limit_price_deviates_from_market_evidence" in intent["blockers"]
    assert client.limit_calls == []


def test_full_workflow_close_blocks_by_readiness_without_orderbook(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)
    feature_pack = {"market": {"mid_price": "71554.20"}, "exchange_rules": _feature_pack()["exchange_rules"]}

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=feature_pack,
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_readiness"
    assert result["executed"] is False
    assert "missing_orderbook_for_full_close" in result["d3_controlled_exit_report"]["selected_exit_intent"]["blockers"]
    assert client.limit_calls == []


def test_full_workflow_d3_bridge_does_not_run_for_unmanaged_position(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(bot_managed_base="0"),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_blocked_no_local_managed_base"
    assert result["blocker"] == "valid_filled_position_evidence_missing_or_zero"
    assert "d3_full_workflow_bridge" not in result
    assert client.limit_calls == []


def test_full_workflow_d3_bridge_does_not_run_with_forbidden_runtime_flags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPLICATION_ENABLED", "true")
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_policy"
    assert "replication_enabled_true" in result["d3_full_workflow_bridge"]["blockers"]
    assert client.limit_calls == []


def test_full_workflow_d3_bridge_requires_external_runtime_authority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client, cfg=_cfg(phase_d3_runtime_submit_ack=""))

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_policy"
    assert "phase_d3_runtime_submit_ack_missing_or_invalid" in result["d3_full_workflow_bridge"]["blockers"]
    assert client.limit_calls == []


def test_market_env_flags_do_not_block_safe_d3_limit_bridge_when_config_disables_market(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MARKET_ORDER_ENABLED", "true")
    monkeypatch.setenv("ENABLE_MARKET_ORDERS", "true")
    monkeypatch.setenv("ALLOW_MARKET_ORDERS", "true")
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_live_exit_submitted"
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"
    assert client.market_calls == []


def test_market_config_flags_block_full_workflow_as_unsafe_config(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(
        tmp_path,
        client=client,
        cfg=_cfg(market_order_enabled=True, enable_market_orders=True, allow_market_orders=True),
    )

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_policy"
    assert "market_order_flags_enabled_config_unsafe_for_orderbook_d3" in result["d3_full_workflow_bridge"]["blockers"]
    assert client.limit_calls == []


def test_full_workflow_d3_bridge_blocks_existing_open_exit_reservation(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)
    engine.order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-FULLCLOSE-pos-1-existing",
        "exchange_order_id": "cb-existing-risk-close",
        "order_id": "cb-existing-risk-close",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "0.0003083267431275",
        "remaining_size": "0.0003083267431275",
        "limit_price": "71554.21",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "FULL_CLOSE",
    })

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_readiness"
    assert result["executed"] is False
    blockers = result["d3_controlled_exit_report"]["selected_exit_intent"]["blockers"]
    assert "no_available_base_after_existing_exit_reservations" in blockers
    assert "duplicate_exit_label_already_open_for_position" in blockers
    assert client.limit_calls == []


def test_full_workflow_d3_bridge_spy_receives_submit_live_true(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    import bot.strategy_engine as strategy_module

    captured = {}

    def fake_submit(**kwargs):
        captured.update(kwargs)
        return {
            "status": "d3_controlled_live_exit_submitted",
            "live_order_submitted": True,
            "readiness": {"ready": True, "status": "d3_controlled_exit_ready_for_live_submit"},
            "hard_blocks": [],
        }

    monkeypatch.setattr(strategy_module, "submit_phase_d3_controlled_exit", fake_submit)
    engine = _engine(tmp_path)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_live_exit_submitted"
    assert captured["submit_live"] is True
    assert captured["coinbase_client"] is engine.client
    assert captured["human_ack"] == D3_ACK


def test_live_d3_bridge_never_sells_legacy_inventory_overlay(tmp_path: Path, monkeypatch) -> None:
    """D3 may receive only bot-managed base, never a legacy inventory overlay."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    import bot.strategy_engine as strategy_module

    captured = {}

    def fake_submit(**kwargs):
        captured.update(kwargs)
        return {
            "status": "d3_controlled_live_exit_submitted",
            "live_order_submitted": True,
            "readiness": {"ready": True, "status": "d3_controlled_exit_ready_for_live_submit"},
            "hard_blocks": [],
        }

    monkeypatch.setattr(strategy_module, "submit_phase_d3_controlled_exit", fake_submit)
    bot_base = Decimal("0.0003083267431275")
    legacy_base = Decimal("0.25")
    engine = _engine(
        tmp_path,
        cfg=_cfg(
            inventory_sell_enabled=True,
            inventory_sell_mode="full_inventory_allowed",
            inventory_severe_risk_only=True,
            inventory_min_residual_base=Decimal("0"),
        ),
    )
    engine._compute_inventory_sell_plan = StrategyEngine._compute_inventory_sell_plan.__get__(engine, StrategyEngine)
    engine._extract_position_inventory_state = StrategyEngine._extract_position_inventory_state.__get__(engine, StrategyEngine)
    position = _position(
        bot_managed_base=str(bot_base),
        position_size_base=str(bot_base),
        legacy_inventory_base=str(legacy_base),
        baseline_inventory_base=str(legacy_base),
    )

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    inventory_plan = result["inventory_plan"]
    assert Decimal(str(inventory_plan["sell_legacy_base"])) == legacy_base
    assert Decimal(str(inventory_plan["sell_total_base"])) > bot_base
    assert Decimal(str(captured["exit_intent"]["size_base"])) <= bot_base
    assert result["sell_size_base_for_d3"] == str(bot_base)
    assert captured["submit_live"] is True


def test_inventory_sync_is_disabled_without_explicit_authority(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    engine = _engine(tmp_path, cfg=_cfg(enable_exchange_inventory_sync=False))

    report = engine._sync_exchange_inventory_positions()

    assert report["enabled"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
