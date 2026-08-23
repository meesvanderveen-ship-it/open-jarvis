from __future__ import annotations

import importlib.util
import sys
import types
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

# The sandbox used for patch validation does not install paid-provider SDKs.
# StrategyEngine imports bot.llm_clients at module import time, so provide tiny
# inert stubs. The production server .venv can still use the real packages.
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

from bot.order_store import OrderStore
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.strategy_engine import StrategyEngine


def cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote="25.00",
        phase_c_max_open_entry_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_max_cancels_per_cycle=2,
        phase_c_max_replaces_per_cycle=1,
        phase_c_require_pending_intent=False,
        phase_c_require_promotion_ready=False,
        phase_c_require_fresh_judge=False,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_disable_exit_limit_orders=True,
        phase_c_live_order_post_only=True,
        autonomous_max_order_quote="25.00",
        autonomous_max_open_orders=4,
        autonomous_max_new_orders_per_cycle=1,
        autonomous_max_cancels_per_cycle=2,
        autonomous_max_replaces_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=True,
        autonomous_allow_exits=False,
        order_store_max_records=200,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class FakeCoinbaseClient:
    def __init__(self):
        self.orders = []

    def submit_limit_buy_order(self, ticker, quote_size, base_size, limit_price, client_order_id=None, post_only=True):
        self.orders.append({
            "ticker": ticker,
            "side": "BUY",
            "base_size": str(base_size),
            "limit_price": str(limit_price),
            "client_order_id": client_order_id,
            "post_only": post_only,
        })
        return {
            "success": True,
            "success_response": {
                "order_id": "cb-order-direct-1",
                "client_order_id": client_order_id,
                "product_id": ticker,
                "side": "BUY",
            },
        }


def engine(tmp_path: Path, **cfg_overrides):
    e = StrategyEngine.__new__(StrategyEngine)
    e.cfg = cfg(**cfg_overrides)
    e.client = FakeCoinbaseClient()
    e.state = SimpleNamespace(get_positions=lambda: {})
    e.order_store = OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "order_events.jsonl")
    e._phase_c43_new_live_orders_this_cycle = 0
    e._now_iso = lambda: "2026-05-18T00:00:00+00:00"
    e.logged = []
    e._write_jsonl = lambda name, payload: e.logged.append((name, payload))
    return e


def analysis(*, decision="approve_trade", side="BUY"):
    return {
        "ticker": "BTC-USDC",
        "judge": {"decision": decision, "side": side, "size_quote": "20.00", "valid_trade_plan": True},
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "setup_type": "reclaim_retest",
            "entry_zone_low": "74990",
            "entry_zone_high": "75000",
            "preferred_limit_price": "75000",
            "invalidation_price": "74000",
            "stop_loss_price": "74000",
            "take_profit_1": "76000",
            "take_profit_2": "77000",
            "do_not_chase_above": "75100",
            "max_quote_size": "20.00",
        },
        "feature_pack": {
            "market": {"mid_price": "75000", "best_bid": "74999", "best_ask": "75001", "spread_pct": "0.00003"},
            "product_rules": {
                "price_increment": "0.01",
                "base_increment": "0.00000001",
                "quote_increment": "0.01",
                "base_min_size": "0.00000001",
                "quote_min_size": "1.00",
            },
            "decision_context": {
                "pending_order_intent": {
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                }
            },
        },
    }


def execution_plan(*, action="place_limit_buy"):
    return {
        "execution_action": action,
        "prepare_resting_limit_entry": True,
        "read_only": True,
        "expiry_hours": 6,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": "0.00003",
            "best_bid": "75000",
            "best_ask": "75001",
        },
    }


def test_strategy_engine_direct_c43_bridge_submits_without_paper_manager(tmp_path: Path):
    e = engine(tmp_path)
    result = e._maybe_process_phase_c43_live_entry_plan(
        ticker="BTC-USDC",
        analysis=analysis(),
        execution_plan=execution_plan(),
        existing_position=None,
        cycle_source="unit_test",
    )
    assert result["strategy_engine_direct_bridge"] is True
    assert result["live_order_submitted"] is True
    assert e.client.orders
    assert e._phase_c43_new_live_orders_this_cycle == 1
    open_orders = e.order_store.open_entry_orders("BTC-USDC")
    assert len(open_orders) == 1
    assert open_orders[0]["order_id"] == "cb-order-direct-1"
    assert open_orders[0]["exchange_order_id"] == "cb-order-direct-1"
    assert open_orders[0]["client_order_id"].startswith("phasec-BTCUSDC-")


def test_strategy_engine_direct_c43_bridge_does_not_submit_when_live_exits_enabled(tmp_path: Path):
    e = engine(tmp_path, enable_live_exit_orders=True)
    result = e._maybe_process_phase_c43_live_entry_plan(
        ticker="BTC-USDC",
        analysis=analysis(),
        execution_plan=execution_plan(),
        existing_position=None,
        cycle_source="unit_test",
    )
    assert result["live_order_submitted"] is False
    assert not e.client.orders
    assert e.order_store.open_entry_orders("BTC-USDC") == []


def test_strategy_engine_direct_c43_bridge_ignores_existing_positions(tmp_path: Path):
    e = engine(tmp_path)
    result = e._maybe_process_phase_c43_live_entry_plan(
        ticker="BTC-USDC",
        analysis=analysis(),
        execution_plan=execution_plan(),
        existing_position={"ticker": "BTC-USDC", "size": "0.01"},
        cycle_source="unit_test",
    )
    assert result is None
    assert not e.client.orders


def test_strategy_engine_direct_c43_bridge_ignores_non_buy_approve(tmp_path: Path):
    e = engine(tmp_path)
    result = e._maybe_process_phase_c43_live_entry_plan(
        ticker="BTC-USDC",
        analysis=analysis(decision="approve_trade", side="SELL"),
        execution_plan=execution_plan(action="place_limit_sell_close"),
        existing_position=None,
        cycle_source="unit_test",
    )
    assert result is None
    assert not e.client.orders


def test_direct_c43_fill_reconcile_is_retired_without_side_effects(tmp_path: Path):
    e = engine(tmp_path)

    report = e._review_phase_c43_live_entry_fills(cycle_source="unit_test")

    assert report["enabled"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert e.order_store.all_orders() == []


def test_live_maybe_execute_cannot_fall_back_to_generic_market_buy() -> None:
    e = StrategyEngine.__new__(StrategyEngine)
    e.cfg = SimpleNamespace(execution_mode="live")
    e._normalize_decision = lambda judge: "approve_trade"
    e._normalize_side = lambda judge: "BUY"
    e._judge_summary = lambda judge: {}
    e._is_no_trade_decision = lambda judge: False
    e._parse_size_quote = lambda judge: Decimal("20")
    e._clamp_judge_buy_size_quote = lambda judge, feature_pack: Decimal("20")
    e._hard_risk_gate = lambda **kwargs: []
    e._to_decimal = StrategyEngine._to_decimal
    e._estimate_base_size_from_quote = lambda quote, price: Decimal("0.0002")
    e._build_position_plan_snapshot_from_analysis = lambda analysis: {}
    e._build_initial_position_risk_fields = lambda analysis, price: {}
    e._capture_pre_entry_inventory_base = lambda ticker: Decimal("0")
    e._write_jsonl = lambda *_args, **_kwargs: None
    e.executor = SimpleNamespace(execute_trade=lambda **_kwargs: (_ for _ in ()).throw(AssertionError("legacy BUY used")))

    result = e.maybe_execute(
        {
            "ticker": "BTC-USDC",
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "20"},
            "feature_pack": {"market": {"mid_price": "100000"}},
        }
    )

    assert result["status"] == "live_entry_retired_requires_c43_boundary"
    assert result["blocker"] == "generic_market_buy_route_retired"
    assert result["executed"] is False
