from __future__ import annotations

from pathlib import Path

from bot.order_store import OrderStore
from bot.phase_d2_position_executor import is_d2_manageable_open_position
from bot.phase_d3_base_balance_preflight import build_phase_d3_base_balance_preflight_report
from bot.phase_d3_controlled_live_exits import build_phase_d3_controlled_live_exit_report
from bot.state_store import StateStore


class FakeCoinbaseClient:
    def __init__(self, snapshot=None, error: Exception | None = None):
        self.snapshot = snapshot or {}
        self.error = error
        self.spot_calls = 0
        self.submit_calls = 0
        self.cancel_calls = 0
        self.replace_calls = 0

    def get_spot_position(self, product_id: str):
        self.spot_calls += 1
        if self.error is not None:
            raise self.error
        return dict(self.snapshot)

    def place_limit_order(self, **kwargs):
        self.submit_calls += 1
        raise AssertionError("submit forbidden in read-only preflight")

    def cancel_order(self, *args, **kwargs):
        self.cancel_calls += 1
        raise AssertionError("cancel forbidden in read-only preflight")

    def replace_order(self, *args, **kwargs):
        self.replace_calls += 1
        raise AssertionError("replace forbidden in read-only preflight")


class FakeStateStore:
    def __init__(self, position=None):
        self.position = dict(position) if isinstance(position, dict) else None
        self.write_attempted = False

    def get_position(self, ticker: str):
        return dict(self.position) if isinstance(self.position, dict) else None

    def upsert_position(self, *args, **kwargs):
        self.write_attempted = True
        raise AssertionError("state writes forbidden")


class FakeOrderStore:
    def __init__(self, open_exit_orders=None):
        self._open_exit_orders = [dict(o) for o in (open_exit_orders or [])]
        self.write_attempted = False

    def open_exit_orders(self, ticker=None):
        return list(self._open_exit_orders)

    def upsert_order(self, *args, **kwargs):
        self.write_attempted = True
        raise AssertionError("order writes forbidden")


def _position():
    return {
        "ticker": "BTC-USDC",
        "status": "open",
        "order_id": "76310097-849e-481c-b587-ba44bc3330fe",
        "entry_price": "77042.43",
        "position_size_base": "0.0001297967431275",
        "bot_managed_base": "0.0001297967431275",
        "position_size_quote": "9.9555030025505861625",
        "stop_price": "76000.00",
        "invalidation_price": "76000.00",
        "take_profit_price": "79931.5211250",
        "opened_via_phase_c43_live_order": True,
        "phase_c43_client_order_id": "phasec-BTCUSDC-smoke-20260526003354",
        "phase_c43_exchange_order_id": "76310097-849e-481c-b587-ba44bc3330fe",
    }


def _snapshot(available_base="0.0001297967431275", hold_base="0", available_quote="100.00", hold_quote="0"):
    return {
        "product_id": "BTC-USDC",
        "base_symbol": "BTC",
        "quote_symbol": "USDC",
        "available_base_balance": str(available_base),
        "hold_base_balance": str(hold_base),
        "available_quote_balance": str(available_quote),
        "hold_quote_balance": str(hold_quote),
    }


def test_sufficient_live_base_coherent_true_blockers_empty():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot()),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(),
    )
    assert report["status"] == "d3_base_balance_preflight_ready"
    assert report["blockers"] == []
    assert report["local_vs_live_base_coherent"] is True
    assert report["sufficient_live_base_for_requested_sell"] is True


def test_live_base_missing_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot={"product_id": "BTC-USDC"}),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(),
    )
    assert "live_base_available_missing" in report["blockers"]


def test_live_base_below_requested_sell_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot(available_base="0.00001")),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(),
    )
    assert "live_base_available_below_requested_sell_base" in report["blockers"]


def test_local_position_missing_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot()),
        state_store=FakeStateStore(None),
        order_store=FakeOrderStore(),
    )
    assert "local_position_missing" in report["blockers"]


def test_position_id_mismatch_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="wrong",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot()),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(),
    )
    assert "position_id_mismatch" in report["blockers"]


def test_local_bot_managed_base_below_requested_sell_blocker():
    pos = _position()
    pos["bot_managed_base"] = "0.00001"
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot()),
        state_store=FakeStateStore(pos),
        order_store=FakeOrderStore(),
    )
    assert "local_bot_managed_base_below_requested_sell_base" in report["blockers"]


def test_open_d3_exit_order_exists_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot()),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(
            open_exit_orders=[
                {
                    "client_order_id": "sell-1",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "status": "submitted",
                    "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
                }
            ]
        ),
    )
    assert "open_d3_exit_order_exists" in report["blockers"]


def test_coinbase_client_error_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(error=RuntimeError("boom")),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(),
    )
    assert "coinbase_client_error" in report["blockers"]


def test_coinbase_auth_missing_value_error_gets_explicit_blocker():
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(error=ValueError("COINBASE_API_KEY ontbreekt")),
        state_store=FakeStateStore(_position()),
        order_store=FakeOrderStore(),
    )
    assert "coinbase_auth_missing_for_read_only_balance_check" in report["blockers"]
    assert "coinbase_client_error" not in report["blockers"]
    assert "coinbase_auth_missing_for_read_only_balance_check" in report["warnings"]
    assert "coinbase_client_error_detail:ValueError" in report["warnings"]


def test_tool_does_not_write_state_or_submit_cancel_replace():
    client = FakeCoinbaseClient(snapshot=_snapshot())
    state_store = FakeStateStore(_position())
    order_store = FakeOrderStore()
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=client,
        state_store=state_store,
        order_store=order_store,
    )
    assert report["read_only"] is True
    assert report["no_submit"] is True
    assert state_store.write_attempted is False
    assert order_store.write_attempted is False
    assert client.submit_calls == 0
    assert client.cancel_calls == 0
    assert client.replace_calls == 0


def test_recovered_position_manageable_and_d3_preview_still_no_submit(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = StateStore()
    orders = OrderStore(path=tmp_path / "state" / "open_orders.json", log_path=tmp_path / "logs" / "order_events.jsonl")
    state.upsert_position("BTC-USDC", _position())
    report = build_phase_d3_base_balance_preflight_report(
        ticker="BTC-USDC",
        position_id="76310097-849e-481c-b587-ba44bc3330fe",
        requested_sell_base="0.000064898371563750",
        coinbase_client=FakeCoinbaseClient(snapshot=_snapshot()),
        state_store=state,
        order_store=orders,
    )
    assert report["blockers"] == []
    assert is_d2_manageable_open_position(state.get_position("BTC-USDC")) is True
    d3 = build_phase_d3_controlled_live_exit_report(ticker="BTC-USDC", cfg=type("Cfg", (), {
        "enable_phase_d3_controlled_live_exits": True,
        "enable_phase_d3_actual_exit_submit": False,
        "enable_live_exit_orders": False,
        "autonomous_allow_exits": False,
        "phase_c_disable_exit_limit_orders": True,
        "phase_d3_max_exit_order_quote": "25.00",
        "phase_d3_max_open_exit_orders": 4,
        "phase_d3_max_new_exit_orders_per_cycle": 1,
        "phase_d3_exit_order_post_only": True,
        "phase_d3_require_reduce_only_local": True,
    })(), state_store=state, order_store=orders, submit_live=False)
    assert d3["status"] == "d3_controlled_exit_ready_no_submit"
    assert d3["live_submission_attempted"] is False
    assert d3["live_order_submitted"] is False
