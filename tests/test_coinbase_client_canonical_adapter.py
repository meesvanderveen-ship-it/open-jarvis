from __future__ import annotations

import sys
import types

if "openai" not in sys.modules:
    openai_stub = types.ModuleType("openai")
    openai_stub.OpenAI = object
    sys.modules["openai"] = openai_stub

if "anthropic" not in sys.modules:
    anthropic_stub = types.ModuleType("anthropic")
    anthropic_stub.Anthropic = object
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

from bot.coinbase_client import CoinbaseClient as CanonicalCoinbaseClient
from bot.market_data import CoinbaseClient as MarketDataCoinbaseClient
from bot.strategy_engine import CoinbaseClient as StrategyEngineCoinbaseClient
from coinbase_client import CoinbaseClient as CompatibilityCoinbaseClient


def test_production_runtime_uses_one_coinbase_client_class() -> None:
    assert StrategyEngineCoinbaseClient is CanonicalCoinbaseClient
    assert MarketDataCoinbaseClient is CanonicalCoinbaseClient
    assert CompatibilityCoinbaseClient is CanonicalCoinbaseClient
