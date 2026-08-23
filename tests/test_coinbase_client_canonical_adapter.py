from __future__ import annotations

import importlib.util
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


def _real_module_available(name: str) -> bool:
    """True als de echte module geinstalleerd is.

    De stubs hieronder bestaan zodat deze tests ook draaien zonder numpy of
    pandas. De oude conditie keek naar sys.modules, maar dat is bij het
    eerste gebruik altijd leeg -- ook als de echte module wel geinstalleerd
    is. De stub verdrong dan de echte module voor de rest van de sessie,
    waardoor latere tests over pytest.approx struikelden
    ("module 'numpy' has no attribute 'isscalar'").
    """
    if name in sys.modules:
        return True
    return importlib.util.find_spec(name) is not None

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

from bot.coinbase_client import CoinbaseClient as CanonicalCoinbaseClient
from bot.market_data import CoinbaseClient as MarketDataCoinbaseClient
from bot.strategy_engine import CoinbaseClient as StrategyEngineCoinbaseClient
from coinbase_client import CoinbaseClient as CompatibilityCoinbaseClient


def test_production_runtime_uses_one_coinbase_client_class() -> None:
    assert StrategyEngineCoinbaseClient is CanonicalCoinbaseClient
    assert MarketDataCoinbaseClient is CanonicalCoinbaseClient
    assert CompatibilityCoinbaseClient is CanonicalCoinbaseClient
