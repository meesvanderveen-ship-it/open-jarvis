from bot.coinbase_order_snapshot import normalize_coinbase_order_snapshot, normalize_order_status, summarize_fills


def test_normalize_cancelled_order_snapshot_uses_local_identifiers():
    snap = normalize_coinbase_order_snapshot(
        {"order": {"order_id": "cb-1", "product_id": "BTC-USDC", "side": "BUY", "status": "CANCELLED"}},
        fallback_local_order={"client_order_id": "phasec-BTCUSDC-1", "ticker": "BTC-USDC"},
    )
    assert snap["client_order_id"] == "phasec-BTCUSDC-1"
    assert snap["exchange_order_id"] == "cb-1"
    assert snap["normalized_status"] == "cancelled"
    assert snap["safety_policy"]["does_not_cancel"] is True


def test_summarize_fills_handles_quote_sized_buy_fill():
    summary = summarize_fills([
        {"price": "50000", "size": "25.00", "size_in_quote": True},
    ])
    assert summary["fill_count"] == 1
    assert summary["filled_quote"] == "25.00"
    assert summary["filled_base"] == "0.0005"
    assert float(summary["avg_fill_price"]) == 50000.0


def test_normalize_filled_snapshot_with_fills():
    snap = normalize_coinbase_order_snapshot(
        {"order_id": "cb-2", "product_id": "ETH-USDC", "side": "BUY", "status": "FILLED", "average_filled_price": "2500"},
        fills=[{"price": "2500", "size": "0.01", "size_in_quote": False}],
        fallback_local_order={"client_order_id": "phasec-ETHUSDC-1"},
    )
    assert snap["normalized_status"] == "filled"
    assert snap["filled_base"] == "0.01"
    assert snap["filled_quote"] == "25.00"


def test_status_partial_when_open_with_filled_base():
    assert normalize_order_status("OPEN", filled_base="0.1") == "partially_filled"


def test_non_zero_filled_quote_wins_over_zero_and_inference():
    snap = normalize_coinbase_order_snapshot(
        {
            "order_id": "cb-3",
            "product_id": "BTC-USDC",
            "side": "BUY",
            "status": "FILLED",
            "filled_size": "0.0001309",
            "average_filled_price": "76392.09",
            "raw_order": {"filled_quote": "0", "filled_value": "9.999724581"},
        },
        fallback_local_order={"filled_quote_value": "0"},
    )
    assert snap["filled_quote"] == "9.999724581"
