from __future__ import annotations

import importlib.util
import sys
import types
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

def _real_module_available(name: str) -> bool:
    """True als de echte module geinstalleerd is.

    De stubs in dit bestand bestaan zodat de test ook draait zonder de zware
    optionele pakketten. De oude conditie keek naar sys.modules, maar dat is
    bij het eerste gebruik altijd leeg -- ook als de echte module wel
    geinstalleerd is. De stub verdrong dan de echte module voor de rest van
    de sessie, waardoor latere tests over pytest.approx struikelden
    ("module 'numpy' has no attribute 'isscalar'").
    """
    if name in sys.modules:
        return True
    return importlib.util.find_spec(name) is not None


if not _real_module_available("openai"):
    openai_stub = types.ModuleType("openai")

    class OpenAI:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    openai_stub.OpenAI = OpenAI
    sys.modules["openai"] = openai_stub

if not _real_module_available("anthropic"):
    anthropic_stub = types.ModuleType("anthropic")

    class Anthropic:  # pragma: no cover - import shim only
        def __init__(self, *args, **kwargs):
            pass

    anthropic_stub.Anthropic = Anthropic
    sys.modules["anthropic"] = anthropic_stub

if not _real_module_available("pandas"):
    pandas_stub = types.ModuleType("pandas")
    pandas_stub.DataFrame = object
    pandas_stub.Series = object
    pandas_stub.concat = lambda *args, **kwargs: []
    pandas_stub.isna = lambda value: value is None
    sys.modules["pandas"] = pandas_stub

if not _real_module_available("numpy"):
    numpy_stub = types.ModuleType("numpy")
    numpy_stub.nan = float("nan")
    numpy_stub.arange = lambda *args, **kwargs: []
    numpy_stub.polyfit = lambda *args, **kwargs: [0]
    sys.modules["numpy"] = numpy_stub

from bot.config import MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE
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
    def __init__(self, *, ioc_fill_status: str = "FILLED", ioc_filled_size: str = "0.0003083267431275") -> None:
        self.limit_calls: list[dict] = []
        self.market_calls: list[dict] = []
        self.cancel_calls: list[str] = []
        self.ioc_calls: list[dict] = []
        self.ioc_fill_status = ioc_fill_status
        self.ioc_filled_size = ioc_filled_size

    def place_limit_order(self, **kwargs):
        self.limit_calls.append(kwargs)
        return {"success": True, "order_id": "cb-d3-exit-1"}

    def place_market_order(self, **kwargs):  # pragma: no cover - must never run
        self.market_calls.append(kwargs)
        raise AssertionError("market order must not be used")

    def cancel_order(self, order_id: str):
        self.cancel_calls.append(order_id)
        return {"success_results": [order_id]}

    def place_limit_order_ioc(self, **kwargs):
        self.ioc_calls.append(kwargs)
        return {"order_id": "cb-stopexit-ioc-1", "success": True}

    def get_order(self, order_id: str):
        return {"order": {"status": self.ioc_fill_status, "filled_size": self.ioc_filled_size, "average_filled_price": "71000"}}


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


def _partial_reduce_action():
    return {
        "action": "reduce",
        "side": "SELL",
        "size_base": "0.0001541633715638",
        "reason": "judge_reduce_size",
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


def test_full_workflow_reduce_size_routes_to_d3_partial_reduce_submit(tmp_path: Path, monkeypatch) -> None:
    # Regression test for a live incident: a judge reduce_size for a
    # weakening thesis returned d3_no_ready_position_executor_plan because
    # it was routed through the D.2 take-profit-bracket fee-edge gate, which
    # answers an unrelated question ("is a fresh TP from here still
    # profitable after fees") and has nothing to do with a risk-driven
    # partial exit the judge already decided on. reduce_size must use the
    # same direct discretionary-exit intent path as close, sized to the
    # requested partial amount, not the D.2 report.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, cfg=_cfg(min_live_order_quote_usdc=Decimal("5.00")), client=client)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_partial_reduce_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_live_exit_submitted"
    assert result["executed"] is True
    intent = result["d3_controlled_exit_report"]["selected_exit_intent"]
    assert intent["label"] == "PARTIAL_REDUCE"
    assert intent["size_base"] == "0.00015416"
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"
    assert client.market_calls == []


def test_reduce_size_below_min_quote_is_blocked_not_full_close_exempt(tmp_path: Path, monkeypatch) -> None:
    # A partial reduce must not silently inherit the full-close exemption
    # that lets a full close dump a below-minimum residual: with nothing
    # forcing an immediate exit, an under-minimum partial should be blocked
    # so the bot can wait instead of forcing a too-small live order.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)  # default cfg: $50 min live order quote

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=_position(),
        action=_partial_reduce_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_readiness"
    intent = result["d3_controlled_exit_report"]["selected_exit_intent"]
    assert "exit_quote_below_min_live_order_quote" in intent["blockers"]
    assert client.limit_calls == []


def test_position_action_uses_freshest_persisted_stop_not_stale_in_memory_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    # Regression test for a live incident: a judge reduce/close decision
    # carries the position snapshot fetched at the top of the cycle, minutes
    # before this point (analyze_ticker's judge call is slow). A concurrent
    # hourly heartbeat can trail the stop below entry and persist it to disk
    # in that window, but the in-memory snapshot never sees it -- so the exit
    # route was failing protective-risk-completeness on a stale
    # stop_price == entry_price artifact even though the live position was
    # actually risk-complete (stop already trailed below entry on disk).
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)
    stale_position = _position(stop_price="76000")  # == entry_price, as if never trailed
    engine.state.upsert_position("BTC-USDC", _position(stop_price="70000"))  # trailed below entry on disk

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=stale_position,
        action=_full_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_live_exit_submitted"
    assert result["executed"] is True
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"


def test_blocked_partial_reduce_falls_back_to_resting_tp1_order(tmp_path: Path, monkeypatch) -> None:
    # Regression test for a live incident: a judge reduce_size for SOL-USDC
    # kept returning d3_controlled_exit_blocked_by_readiness because the
    # sliced amount fell under min_live_order_quote_usdc on a small position,
    # and -- since the cycle's action was "reduce", not "hold" -- the
    # proactive TP1 resting logic never ran either. Net effect: nothing ever
    # rested on the book despite a live take-profit target above price. A
    # blocked partial reduce must fall back to resting the position's own
    # take-profit order.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)  # default cfg: $50 min live order quote
    position = _position(take_profit_price="75000")

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=_partial_reduce_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "d3_controlled_exit_blocked_by_readiness"
    intent = result["d3_controlled_exit_report"]["selected_exit_intent"]
    assert "exit_quote_below_min_live_order_quote" in intent["blockers"]
    proactive = result["proactive_take_profit_exit_fallback"]
    assert proactive["submitted"] is True
    assert proactive["exit_intent"]["label"] == "TP1"
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"
    assert engine.order_store.open_exit_orders("BTC-USDC")


def test_blocked_partial_reduce_escalates_to_full_close_when_price_past_take_profit(
    tmp_path: Path, monkeypatch
) -> None:
    # If price has already run through take_profit_price, resting a maker
    # TP1 order there would cross the book, so the TP1 fallback itself gets
    # blocked (take_profit_price_at_or_below_current_bid...). Combined with
    # a too-small partial reduce, neither a partial sell nor a fresh TP
    # order can legally go out -- a full close is the only reduce-only
    # action left, so the blocked reduce must escalate to one.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)  # default cfg: $50 min live order quote
    position = _position(take_profit_price="71000")  # below current best_bid 71554.19

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=_partial_reduce_action(),
        feature_pack=_feature_pack(),
    )

    assert result["escalated_from_blocked_partial_reduce"] is True
    assert result["status"] == "d3_controlled_live_exit_submitted"
    assert result["executed"] is True
    intent = result["d3_controlled_exit_report"]["selected_exit_intent"]
    assert intent["label"] == "FULL_CLOSE"
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"


def _hold_action(position):
    return {
        "action": "hold",
        "side": "NONE",
        "size_base": "0",
        "reason": "position_valid",
        "metadata": {"updated_position": position},
    }


def test_hold_cycle_proactively_places_tp1_resting_sell_order(tmp_path: Path, monkeypatch) -> None:
    # Without this, the position only reacts to a level crossing on the next
    # cycle/heartbeat -- a fast move through take-profit between cycles would
    # be missed entirely since nothing was ever resting on the book. A hold
    # cycle (no close/reduce already happening) should rest a maker SELL at
    # the position's own take_profit_price.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)
    position = _position(take_profit_price="75000")

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=_hold_action(position),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "hold_position"
    proactive = result["proactive_take_profit_exit"]
    assert proactive["submitted"] is True
    assert proactive["exit_intent"]["label"] == "TP1"
    assert Decimal(proactive["exit_intent"]["limit_price"]) == Decimal("75000")
    assert client.limit_calls and client.limit_calls[0]["side"] == "SELL"
    assert client.market_calls == []
    assert engine.order_store.open_exit_orders("BTC-USDC")


def test_hold_cycle_does_not_duplicate_existing_resting_exit_order(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(tmp_path, client=client)
    position = _position(take_profit_price="75000")

    engine.order_store.upsert_order({
        "client_order_id": "phased3-BTCUSDC-TP1-pos-1-existing",
        "exchange_order_id": "exchange-phased3-BTCUSDC-TP1-pos-1-existing",
        "ticker": "BTC-USDC",
        "side": "SELL",
        "status": "submitted",
        "phase": "D3_controlled_live_reduce_only_exits",
        "linked_position_id": "pos-1",
        "size_base": "0.0003083267431275",
        "remaining_size": "0.0003083267431275",
        "limit_price": "75000.00",
        "execution_action": "place_limit_sell",
        "d3_exit_label": "TP1",
    })

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=_hold_action(position),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "hold_position"
    assert "proactive_take_profit_exit" not in result
    assert client.limit_calls == []


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


def test_stop_close_executes_via_mode_b_when_fully_armed(tmp_path: Path, monkeypatch) -> None:
    # Mode A (default everywhere else) stays preview-only, per the test
    # above. Mode B is this codebase's own documented graduated activation
    # (docs/MODE_B_CONTROLLED_STOP_EXIT_ACTIVATION_PLAN.md): only when every
    # flag plus the exact ACK are armed does a stop breach actually cancel
    # (none open here), submit a near-market IOC SELL, verify the fill, and
    # close the local position.
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir()
    client = FakeCoinbaseClient()
    engine = _engine(
        tmp_path,
        client=client,
        cfg=_cfg(
            enable_controlled_stop_market_exits=True,
            enable_autonomous_stop_exit_cancel=True,
            enable_autonomous_stop_exit_submit=True,
            enable_autonomous_stop_exit_apply=True,
            mode_b_controlled_stop_exit_ack=MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE,
            controlled_stop_exit_max_quote_usd=Decimal("25.00"),
            controlled_stop_exit_require_open_tp_cancel_first=True,
            controlled_stop_exit_order_type="near_market_limit_ioc",
            controlled_stop_exit_max_slippage_pct=Decimal("0.0100"),
            market_order_enabled=False,
            enable_market_orders=False,
            allow_market_orders=False,
            mode_c_market_order_ack="",
            enable_trade_reflection_memory=False,
        ),
    )
    # stop_price above the feature_pack's current price (71554.20) so
    # controlled_stop_market_exit_plan._stop_breached's numeric fallback
    # (current <= stop) fires -- distinct from _requires_controlled_stop_exit_route's
    # own reason-text check, which already routes "stop_loss_hit" here regardless.
    position = _position(stop_price="72000")
    engine.state.upsert_position("BTC-USDC", position)

    result = engine._handle_position_action(
        ticker="BTC-USDC",
        position=position,
        action=_stop_close_action(),
        feature_pack=_feature_pack(),
    )

    assert result["status"] == "controlled_stop_market_exit_applied"
    assert result["executed"] is True
    assert client.cancel_calls == []  # nothing open to cancel in this fixture
    assert len(client.ioc_calls) == 1
    assert client.ioc_calls[0]["side"] == "SELL"
    assert client.limit_calls == []
    assert client.market_calls == []
    closed = engine.state.get_position("BTC-USDC")
    assert closed["status"] == "closed"


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
