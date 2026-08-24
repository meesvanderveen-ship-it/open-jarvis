from decimal import Decimal

from bot.coinbase_client import CoinbaseClient


def test_place_limit_order_ioc_uses_sor_limit_ioc_order_configuration(monkeypatch):
    # Coinbase Advanced Trade has no "limit_limit_ioc" order_configuration variant --
    # the API rejects it with a proto "unknown field" 400. Confirmed live 2026-07-08:
    # every controlled-stop-exit submit attempt failed this way for 6+ hours while a
    # stop-breached position sat unprotected. "sor_limit_ioc" is the real field for
    # this near-market-limit-IOC order shape.
    client = CoinbaseClient()
    captured = {}

    def fake_request(method, path, payload=None, params=None):
        captured["method"] = method
        captured["path"] = path
        captured["payload"] = payload
        return {"success": True, "order_id": "test-order-id"}

    monkeypatch.setattr(client, "_request", fake_request)

    client.place_limit_order_ioc(
        ticker="SOL-USDC",
        side="SELL",
        base_size=Decimal("1.41131232"),
        limit_price=Decimal("78.36"),
        client_order_id="test-client-order-id",
    )

    order_configuration = captured["payload"]["order_configuration"]
    assert "sor_limit_ioc" in order_configuration
    assert "limit_limit_ioc" not in order_configuration
    assert order_configuration["sor_limit_ioc"]["base_size"] == "1.41131232"
    assert order_configuration["sor_limit_ioc"]["limit_price"] == "78.36"
