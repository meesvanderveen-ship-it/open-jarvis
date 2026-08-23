from bot.phase_d6_historical_data_sources import (
    binance_source_contract,
    coinbase_source_contract,
    normalize_coinbase_candles,
)


def test_source_contract_roles_are_explicit() -> None:
    coinbase = coinbase_source_contract(product="BTC-USDC", timeframe="1H", run_id="r1")
    binance = binance_source_contract(symbol="BTCUSDC", mapped_coinbase_product="BTC-USDC", timeframe="1H", run_id="r1")

    assert coinbase["role"] == "primary_execution_market"
    assert coinbase["account_or_order_endpoint_allowed"] is False
    assert binance["role"] == "secondary_reference_only"
    assert binance["coinbase_cache_mutation_allowed"] is False


def test_normalize_coinbase_candles_adds_provenance() -> None:
    rows = normalize_coinbase_candles(
        [{"start": 10, "open": "1", "high": "2", "low": "0.5", "close": "1.5", "volume": "7"}],
        product="BTC-USDC",
        timeframe="1H",
        run_id="run",
        request_id="req",
    )

    assert rows[0]["source"] == "coinbase"
    assert rows[0]["role"] == "primary_execution_market"
    assert rows[0]["product_id"] == "BTC-USDC"
    assert rows[0]["start"] == 10
