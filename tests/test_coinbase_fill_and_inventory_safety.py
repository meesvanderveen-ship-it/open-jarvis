from decimal import Decimal
import sys
import types

# Test environment in this sandbox does not install provider SDKs. The strategy
# helper tested here does not use clients, so lightweight stubs are enough.
openai_stub = types.ModuleType("openai")
openai_stub.OpenAI = object
sys.modules.setdefault("openai", openai_stub)
sys.modules.setdefault("anthropic", types.ModuleType("anthropic"))

from bot.coinbase_client import CoinbaseClient
from bot.strategy_engine import StrategyEngine


def assert_close_decimal(actual: str, expected: str, tolerance: str = "0.00000001") -> None:
    actual_d = Decimal(str(actual))
    expected_d = Decimal(str(expected))
    tolerance_d = Decimal(str(tolerance))
    assert abs(actual_d - expected_d) <= tolerance_d, f"{actual_d} != {expected_d}"


def test_quote_sized_ada_buy_fills_are_normalized_to_base_and_quote():
    client = CoinbaseClient(host="example.invalid")
    fills = [
        {"price": "0.2824", "size": "0.012997138064", "commission": "0.000155965656768", "size_in_quote": True},
        {"price": "0.2824", "size": "59.275459388024", "commission": "0.711305512656288", "size_in_quote": True},
    ]
    client.get_recent_fills_for_order = lambda order_id: fills

    summary = client.summarize_fills_for_order("test-ada-buy")

    assert_close_decimal(summary["filled_size_base"], "209.94495937")
    assert_close_decimal(summary["filled_quote_value"], "59.288456526088")
    assert_close_decimal(summary["avg_fill_price"], "0.2824")
    assert summary["saw_quote_sized_fill"] is True
    assert summary["saw_base_sized_fill"] is False


def test_base_sized_eth_sell_fills_remain_base_sized():
    client = CoinbaseClient(host="example.invalid")
    fills = [
        {"price": "2368.6", "size": "0.00143725", "commission": "0.0408512442", "size_in_quote": False},
        {"price": "2368.64", "size": "0.00262518", "commission": "0.0746172762624", "size_in_quote": False},
    ]
    client.get_recent_fills_for_order = lambda order_id: fills

    summary = client.summarize_fills_for_order("test-eth-sell")

    assert_close_decimal(summary["filled_size_base"], "0.00406243")
    assert_close_decimal(summary["filled_quote_value"], "9.6223767052")
    assert summary["saw_quote_sized_fill"] is False
    assert summary["saw_base_sized_fill"] is True


def test_closed_legacy_inventory_is_not_reimported_as_bot_managed():
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.position_epsilon_base = Decimal("0.00000001")

    closed_position = {
        "ticker": "ADA-USDC",
        "status": "closed",
        "position_size_base": "0",
        "bot_managed_base": "0",
        "baseline_inventory_base": "150.656502843912",
        "legacy_inventory_base": "0",
        "close_reason": "stop_loss_hit",
    }

    assert engine._closed_position_has_unmanaged_legacy_inventory(
        closed_position,
        Decimal("150.65650285"),
    ) is True


def test_closed_position_with_new_extra_live_base_can_be_reimported():
    engine = StrategyEngine.__new__(StrategyEngine)
    engine.position_epsilon_base = Decimal("0.00000001")

    closed_position = {
        "ticker": "ADA-USDC",
        "status": "closed",
        "position_size_base": "0",
        "bot_managed_base": "0",
        "baseline_inventory_base": "150.656502843912",
        "legacy_inventory_base": "0",
        "close_reason": "stop_loss_hit",
    }

    assert engine._closed_position_has_unmanaged_legacy_inventory(
        closed_position,
        Decimal("210"),
    ) is False
