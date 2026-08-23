from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from coinbase_executor import CoinbaseExecutor, LegacyExecutionRouteBlockedError


class DummyClient:
    def __init__(self):
        self.calls = []

    def get_product(self, ticker):
        self.calls.append(("get_product", ticker))
        return {"base_increment": "0.00000001", "base_min_size": "0.00000001"}

    def get_best_bid_ask(self, tickers):
        self.calls.append(("get_best_bid_ask", tuple(tickers)))
        return {"pricebooks": [{"bids": [{"price": "100"}], "asks": [{"price": "101"}]}]}

    def get_available_balance(self, symbol):
        self.calls.append(("get_available_balance", symbol))
        return Decimal("1")

    def get_spot_position(self, ticker):
        self.calls.append(("get_spot_position", ticker))
        return {"available_base_balance": "1"}

    def place_market_order(self, **kwargs):
        self.calls.append(("place_market_order", kwargs))
        return {"success": True, "success_response": {"order_id": "cb-1"}}


class DummyFirewall:
    def normalize_order_size(self, **kwargs):
        return kwargs["requested_size"]

    def validate_intent(self, **kwargs):
        return None

    def _quantize_down(self, value, increment):
        return value


def _cfg(**overrides):
    base = dict(
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        enable_phase_d3_actual_exit_submit=False,
        phase_c_disable_exit_limit_orders=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_execute_close_spot_position_blocks_without_coinbase_calls() -> None:
    client = DummyClient()
    executor = CoinbaseExecutor(client=client, firewall=DummyFirewall(), cfg=_cfg())
    with pytest.raises(LegacyExecutionRouteBlockedError):
        executor.execute_close_spot_position(
            "BTC-USDC",
            Decimal("0.1"),
            source_tag="strategy_engine_live_position_exit",
        )
    assert client.calls == []


def test_execute_trade_sell_blocks_without_coinbase_calls() -> None:
    client = DummyClient()
    executor = CoinbaseExecutor(client=client, firewall=DummyFirewall(), cfg=_cfg())
    with pytest.raises(LegacyExecutionRouteBlockedError):
        executor.execute_trade(
            "BTC-USDC",
            "SELL",
            Decimal("0.1"),
            source_tag="strategy_engine_live_position_exit",
        )
    assert client.calls == []


def test_execute_trade_buy_is_retired_without_coinbase_calls() -> None:
    client = DummyClient()
    executor = CoinbaseExecutor(client=client, firewall=DummyFirewall(), cfg=_cfg())
    with pytest.raises(LegacyExecutionRouteBlockedError):
        executor.execute_trade("BTC-USDC", "BUY", Decimal("10"))
    assert client.calls == []


def test_execute_close_spot_position_is_retired_without_coinbase_calls() -> None:
    client = DummyClient()
    executor = CoinbaseExecutor(client=client, firewall=DummyFirewall(), cfg=_cfg())
    with pytest.raises(LegacyExecutionRouteBlockedError):
        executor.execute_close_spot_position("BTC-USDC", Decimal("0.1"))
    assert client.calls == []
