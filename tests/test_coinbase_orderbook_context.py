from __future__ import annotations

from decimal import Decimal

from bot.coinbase_client import CoinbaseClient
from bot.market_data import MarketDataService


def test_get_product_book_public_endpoint_normalizes_dict_levels():
    client = CoinbaseClient()
    calls = []

    def fake_request(method, path, payload=None, params=None, auth_required=True):
        calls.append((method, path, params, auth_required))
        assert path == "/api/v3/brokerage/market/product_book"
        assert auth_required is False
        assert params == {"product_id": "BTC-USDC", "limit": 5}
        return {
            "pricebook": {
                "product_id": "BTC-USDC",
                "bids": [{"price": "80000", "size": "0.5"}],
                "asks": [{"price": "80010", "size": "0.4"}],
                "time": "2026-05-11T00:00:00Z",
            },
            "last": "80005",
            "mid_market": "80005",
            "spread_bps": "1.25",
            "spread_absolute": "10",
        }

    client._request = fake_request  # type: ignore[method-assign]

    book = client.get_product_book("btc-usdc", limit=5)

    assert calls
    assert book["product_id"] == "BTC-USDC"
    assert book["bids"] == [{"price": "80000", "size": "0.5"}]
    assert book["asks"] == [{"price": "80010", "size": "0.4"}]
    assert book["source_path"] == "/api/v3/brokerage/market/product_book"
    assert book["auth_required"] is False
    assert book["depth_is_top_only"] is False


def test_get_product_book_falls_back_to_authenticated_product_book():
    client = CoinbaseClient()
    calls = []

    def fake_request(method, path, payload=None, params=None, auth_required=True):
        calls.append((path, auth_required))
        if path == "/api/v3/brokerage/market/product_book" and auth_required is False:
            raise RuntimeError("public endpoint unavailable")
        if path == "/api/v3/brokerage/product_book" and auth_required is True:
            return {
                "pricebook": {
                    "product_id": "ETH-USDC",
                    "bids": [["2300", "1.2"]],
                    "asks": [["2301", "1.1"]],
                }
            }
        raise AssertionError(f"unexpected call: {path}, auth={auth_required}")

    client._request = fake_request  # type: ignore[method-assign]

    book = client.get_product_book("ETH-USDC", limit=25)

    assert calls[:2] == [
        ("/api/v3/brokerage/market/product_book", False),
        ("/api/v3/brokerage/product_book", True),
    ]
    assert book["bids"][0] == {"price": "2300", "size": "1.2"}
    assert book["asks"][0] == {"price": "2301", "size": "1.1"}
    assert book["source_path"] == "/api/v3/brokerage/product_book"


def test_get_product_book_falls_back_to_best_bid_ask():
    client = CoinbaseClient()

    def fake_request(method, path, payload=None, params=None, auth_required=True):
        raise RuntimeError("product_book unavailable")

    def fake_best_bid_ask(product_ids):
        assert product_ids == ["SOL-USDC"]
        return {
            "pricebooks": [
                {
                    "product_id": "SOL-USDC",
                    "bids": [{"price": "95", "size": "10"}],
                    "asks": [{"price": "95.1", "size": "11"}],
                    "time": "2026-05-11T00:00:00Z",
                }
            ]
        }

    client._request = fake_request  # type: ignore[method-assign]
    client.get_best_bid_ask = fake_best_bid_ask  # type: ignore[method-assign]

    book = client.get_product_book("SOL-USDC", limit=10)

    assert book["bids"][0] == {"price": "95", "size": "10"}
    assert book["asks"][0] == {"price": "95.1", "size": "11"}
    assert book["source_path"] == "/api/v3/brokerage/best_bid_ask"
    assert book["depth_is_top_only"] is True


def test_market_data_orderbook_context_uses_client_product_book():
    class FakeClient:
        def get_product_book(self, ticker):
            assert ticker == "BTC-USDC"
            return {
                "bids": [
                    {"price": "79999", "size": "1"},
                    {"price": "79998", "size": "2"},
                    {"price": "79997", "size": "3"},
                    {"price": "79996", "size": "4"},
                    {"price": "79995", "size": "5"},
                ],
                "asks": [
                    {"price": "80001", "size": "1"},
                    {"price": "80002", "size": "1"},
                    {"price": "80003", "size": "1"},
                    {"price": "80004", "size": "1"},
                    {"price": "80005", "size": "1"},
                ],
            }

    md = MarketDataService(FakeClient())  # type: ignore[arg-type]
    context = md._build_orderbook_context(
        "BTC-USDC",
        best_bid=Decimal("79999"),
        best_ask=Decimal("80001"),
        mid_price=Decimal("80000"),
    )

    assert context["snapshot_available"] is True
    assert context["top_bid_size"] == "1"
    assert context["top_ask_size"] == "1"
    assert context["bid_depth_top5"] == "15"
    assert context["ask_depth_top5"] == "5"
    assert context["depth_imbalance_top5"] == 0.5
    assert context["book_pressure"] == "bid_heavy"
