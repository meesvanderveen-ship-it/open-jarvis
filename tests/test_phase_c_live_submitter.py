from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.config import MODE_C_MARKET_ORDER_ACK_VALUE
from bot.coinbase_client import CoinbaseClient
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.phase_c_live_submitter import (
    build_phase_c_live_entry_payload,
    prepare_mode_c_market_order_submission,
    prepare_phase_c_live_entry_submission,
    submit_limit_buy_order,
)
from coinbase_client import CoinbaseClient as RuntimeCoinbaseClient


def _cfg(**overrides):
    base = dict(
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_order_quote=Decimal("100.00"),
        phase_c_live_order_post_only=True,
        phase_c_disable_exit_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        market_order_enabled=False,
        enable_market_orders=False,
        allow_market_orders=False,
        mode_c_market_order_ack="",
        replication_enabled=False,
        replication_lifecycle_enabled=False,
        replication_lifecycle_http_enabled=False,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_open_entry_orders=3,
        phase_c_max_new_orders_per_cycle=1,
        autonomous_max_open_orders=3,
        max_open_positions=3,
        max_new_orders_per_cycle=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _intent(size_quote: str):
    return {
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": size_quote,
        "limit_price": "100.00",
        "client_order_id": "phasec-BTCUSDC-test",
    }


def test_phase_c_submitter_blocks_under_min_even_if_product_min_lower():
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_intent=_intent("10.00"),
        guard_result={"guard_allows_live_submit": True},
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
    )
    assert payload["accepted"] is False
    assert "quote_size_below_min_live_order_quote" in payload["reject_reasons"]


def test_phase_c_submitter_accepts_20_but_does_not_call_client_when_disabled():
    class Client:
        calls = 0

        def submit_limit_buy_order(self, **kwargs):
            self.calls += 1
            return {"order_id": "unexpected"}

    client = Client()
    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_intent=_intent("20.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=client,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["payload"]["accepted"] is True
    assert result["payload"]["order_type"] == "limit_limit_gtc"
    assert "limit_limit_gtc" in result["payload"]["coinbase_payload_preview"]["order_configuration"]
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "phase_c_actual_coinbase_submit_disabled" in result["hard_block_reasons"]
    assert client.calls == 0


def test_phase_c_submitter_runtime_authority_blocks_before_client_call():
    class Client:
        calls = 0

        def submit_limit_buy_order(self, **kwargs):
            self.calls += 1
            raise AssertionError("missing runtime authority must block before Coinbase")

    client = Client()
    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True, phase_c43_runtime_submit_ack=""),
        ticker="BTC-USDC",
        order_intent=_intent("20.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=client,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert "phase_c43_runtime_submit_ack_missing_or_invalid" in result["hard_block_reasons"]
    assert result["live_submission_attempted"] is False
    assert client.calls == 0


def test_coinbase_client_limit_buy_alias_uses_advanced_trade_limit_payload(monkeypatch):
    captured = {}
    client = CoinbaseClient(host="example.test")

    def fake_request(method, path, payload=None, params=None, auth_required=True):
        captured.update({"method": method, "path": path, "payload": payload, "auth_required": auth_required})
        return {"success": True, "success_response": {"order_id": "cb-buy-1", "client_order_id": payload["client_order_id"]}}

    monkeypatch.setattr(client, "_request", fake_request)
    response = client.submit_limit_buy_order(
        ticker="BTC-USDC",
        quote_size=Decimal("50.00"),
        base_size=Decimal("0.0005"),
        limit_price=Decimal("100000"),
        client_order_id="phasec-BTCUSDC-alias",
        post_only=True,
    )
    assert response["success_response"]["order_id"] == "cb-buy-1"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/brokerage/orders"
    payload = captured["payload"]
    assert payload["side"] == "BUY"
    assert payload["product_id"] == "BTC-USDC"
    assert payload["order_configuration"]["limit_limit_gtc"]["base_size"] == "0.0005"
    assert payload["order_configuration"]["limit_limit_gtc"]["post_only"] is True


def test_runtime_coinbase_client_limit_buy_alias_uses_advanced_trade_limit_payload(monkeypatch):
    captured = {}
    client = RuntimeCoinbaseClient(host="example.test")

    def fake_request(method, path, payload=None, params=None, auth_required=True):
        captured.update({"method": method, "path": path, "payload": payload, "auth_required": auth_required})
        return {"success": True, "success_response": {"order_id": "cb-buy-runtime", "client_order_id": payload["client_order_id"]}}

    monkeypatch.setattr(client, "_request", fake_request)
    response = client.submit_limit_buy_order(
        ticker="BTC-USDC",
        quote_size=Decimal("50.00"),
        base_size=Decimal("0.0005"),
        limit_price=Decimal("100000"),
        client_order_id="phasec-BTCUSDC-runtime",
        post_only=True,
    )
    assert response["success_response"]["order_id"] == "cb-buy-runtime"
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/brokerage/orders"
    payload = captured["payload"]
    assert payload["side"] == "BUY"
    assert payload["product_id"] == "BTC-USDC"
    assert payload["order_configuration"]["limit_limit_gtc"]["base_size"] == "0.0005"
    assert payload["order_configuration"]["limit_limit_gtc"]["post_only"] is True


def test_limit_buy_adapter_rejects_noncanonical_client_method():
    class Client:
        def __init__(self):
            self.calls = []

        def place_limit_order(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "success_response": {"order_id": "cb-buy-2", "client_order_id": kwargs["client_order_id"]}}

    client = Client()
    result = submit_limit_buy_order(
        coinbase_client=client,
        ticker="BTC-USDC",
        quote_size=Decimal("50.00"),
        base_size=Decimal("0.0005"),
        limit_price=Decimal("100000"),
        client_order_id="phasec-BTCUSDC-place",
        post_only=True,
    )
    assert result["submitted"] is False
    assert result["error"] == "coinbase_client_missing_canonical_submit_limit_buy_order"
    assert client.calls == []


def test_limit_buy_adapter_rejects_sdk_create_order_fallback():
    class Client:
        def __init__(self):
            self.calls = []

        def create_order(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "order_id": "cb-buy-3"}

    client = Client()
    result = submit_limit_buy_order(
        coinbase_client=client,
        ticker="ETH-USDC",
        quote_size=Decimal("50.00"),
        base_size=Decimal("0.025"),
        limit_price=Decimal("2000"),
        client_order_id="phasec-ETHUSDC-create",
        post_only=True,
    )
    assert result["submitted"] is False
    assert result["error"] == "coinbase_client_missing_canonical_submit_limit_buy_order"
    assert client.calls == []


def test_phase_c_submitter_missing_limit_method_is_blocker_not_crash():
    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        order_intent=_intent("50.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=object(),
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "coinbase_limit_buy_submit_route_not_supported" in result["hard_block_reasons"]


def test_phase_c_submitter_success_requires_exchange_order_id():
    class Client:
        def submit_limit_buy_order(self, **kwargs):
            return {"success": True}

    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        order_intent=_intent("50.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=Client(),
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["live_submission_attempted"] is True
    assert result["live_order_submitted"] is False
    assert result["status"] == "phase_c_live_order_submit_unconfirmed_no_order_id"
    assert result["reject_reason"] == "coinbase_success_without_order_id"


def test_phase_c_submitter_quote_50_and_post_only_reach_mocked_submit():
    class Client:
        def __init__(self):
            self.calls = []

        def submit_limit_buy_order(self, **kwargs):
            self.calls.append(kwargs)
            return {"success": True, "order_id": "cb-buy-50"}

    client = Client()
    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        order_intent=_intent("50.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=client,
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["live_order_submitted"] is True
    assert result["exchange_order_id"] == "cb-buy-50"
    assert result["payload"]["order_type"] == "limit_limit_gtc"
    assert result["coinbase_submit_adapter"]["client_method"] == "submit_limit_buy_order"
    assert result["payload"]["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]["post_only"] is True
    assert result["payload"]["size_quote_requested"] == "50.00"
    assert client.calls[0]["base_size"] == Decimal("0.5")
    assert client.calls[0]["post_only"] is True


def test_phase_c_submitter_requires_post_only_limit_configuration():
    class Client:
        def submit_limit_buy_order(self, **kwargs):
            raise AssertionError("post-only blocker must prevent live submit attempt")

    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True, phase_c_live_order_post_only=False),
        ticker="BTC-USDC",
        order_intent=_intent("50.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=Client(),
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "phase_c_limit_order_post_only_required" in result["hard_block_reasons"]


def test_phase_c_payload_quantizes_quote_50_btc_to_base_and_price_increments():
    intent = {
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": "50.00",
        "limit_price": "65000.009",
        "client_order_id": "phasec-BTCUSDC-precision",
    }
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_intent=intent,
        guard_result={"guard_allows_live_submit": True},
        product_rules={
            "quote_min_size": "1.00",
            "base_increment": "0.00000001",
            "price_increment": "0.01",
            "quote_increment": "0.01",
        },
    )
    gtc = payload["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]
    assert payload["accepted"] is True
    assert gtc["limit_price"] == "65000.00"
    assert gtc["base_size"] == "0.00076923"
    assert gtc["post_only"] is True


def test_phase_c_payload_quantizes_sol_base_size_before_submit_payload():
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="SOL-USDC",
        order_intent={
            "side": "BUY",
            "execution_action": "place_limit_buy",
            "size_quote": "25.00",
            "limit_price": "72.81",
            "client_order_id": "phasec-SOLUSDC-precision",
        },
        guard_result={"guard_allows_live_submit": True},
        product_rules={
            "quote_min_size": "1.00",
            "base_min_size": "0.01",
            "base_increment": "0.01",
            "price_increment": "0.01",
            "quote_increment": "0.01",
        },
    )
    gtc = payload["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]
    assert payload["accepted"] is True
    assert gtc["limit_price"] == "72.81"
    assert gtc["base_size"] == "0.34"
    assert payload["precision_normalization"]["raw_base_size"].startswith("0.343")
    assert "base_size_rounded_down_to_base_increment" in payload["precision_normalization"]["warnings"]


def test_phase_c_payload_quantizes_xrp_price_before_submit_payload():
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="XRP-USDC",
        order_intent={
            "side": "BUY",
            "execution_action": "place_limit_buy",
            "size_quote": "25.00",
            "limit_price": "1.20665",
            "client_order_id": "phasec-XRPUSDC-precision",
        },
        guard_result={"guard_allows_live_submit": True},
        product_rules={
            "quote_min_size": "1.00",
            "base_min_size": "0.000001",
            "base_increment": "0.000001",
            "price_increment": "0.0001",
            "quote_increment": "0.01",
        },
    )
    gtc = payload["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]
    assert payload["accepted"] is True
    assert gtc["limit_price"] == "1.2066"
    assert Decimal(gtc["base_size"]).as_tuple().exponent >= Decimal("0.000001").as_tuple().exponent
    assert "limit_price_rounded_down_to_price_increment" in payload["precision_normalization"]["warnings"]


def test_phase_c_payload_blocks_live_submit_when_product_increments_missing():
    payload = build_phase_c_live_entry_payload(
        cfg=_cfg(),
        ticker="BTC-USDC",
        order_intent={
            "side": "BUY",
            "execution_action": "place_limit_buy",
            "size_quote": "50.00",
            "limit_price": "65000",
            "client_order_id": "phasec-BTCUSDC-no-rules",
        },
        guard_result={"guard_allows_live_submit": True},
        product_rules={},
    )
    assert payload["accepted"] is False
    assert "precision:product_rules_missing" in payload["reject_reasons"]
    assert "precision:base_increment_missing" in payload["reject_reasons"]
    assert "precision:price_increment_missing" in payload["reject_reasons"]


def test_limit_buy_adapter_extracts_nested_success_response_order_id():
    class Client:
        def submit_limit_buy_order(self, **kwargs):
            return {"success": True, "response": {"success_response": {"order_id": "nested-order-1"}}}

    result = submit_limit_buy_order(
        coinbase_client=Client(),
        ticker="BTC-USDC",
        quote_size=Decimal("50.00"),
        base_size=Decimal("0.00076923"),
        limit_price=Decimal("65000.00"),
        client_order_id="phasec-BTCUSDC-nested",
        post_only=True,
    )
    assert result["submitted"] is True
    assert result["exchange_order_id"] == "nested-order-1"


def test_phase_c_submitter_exchange_error_stays_not_submitted_with_reject_reason():
    class Client:
        def submit_limit_buy_order(self, **kwargs):
            return {
                "success": False,
                "error_response": {
                    "error": "INVALID_PRICE_PRECISION",
                    "message": "Too many decimals in order price",
                    "preview_failure_reason": "PREVIEW_INVALID_PRICE_PRECISION",
                },
            }

    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        order_intent=_intent("50.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=Client(),
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "price_increment": "0.01", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["live_submission_attempted"] is True
    assert result["live_order_submitted"] is False
    assert result["reject_reason"] == "INVALID_PRICE_PRECISION"
    assert result["preview_failure_reason"] == "PREVIEW_INVALID_PRICE_PRECISION"


def test_phase_c_submitter_max_quote_100_still_blocks_101():
    result = prepare_phase_c_live_entry_submission(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True, phase_c_max_order_quote=Decimal("100.00")),
        ticker="BTC-USDC",
        order_intent=_intent("101.00"),
        guard_result={"guard_allows_live_submit": True},
        coinbase_client=object(),
        product_rules={"quote_min_size": "1.00", "base_increment": "0.00000001", "quote_increment": "0.01"},
        submit_live=True,
    )
    assert result["payload"]["accepted"] is False
    assert "quote_size_above_max_live_order_quote" in result["payload"]["reject_reasons"]
    assert result["live_submission_attempted"] is False


def test_mode_c_market_buy_20_100_reaches_submit_preview_without_live_call():
    class Client:
        calls = 0

        def place_market_order(self, **kwargs):
            self.calls += 1
            raise AssertionError("live Coinbase market order must not be called in preview")

    cfg = _cfg(
        market_order_enabled=True,
        enable_market_orders=True,
        allow_market_orders=True,
        mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
    )
    result = prepare_mode_c_market_order_submission(
        cfg=cfg,
        ticker="BTC-USDC",
        side="BUY",
        order_intent={"side": "BUY", "execution_action": "place_market_buy", "size_quote": "20.00"},
        analysis={
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "20.00"},
            "trade_plan": {"trigger": "reclaim", "stop_loss": "95", "target": "110"},
        },
        execution_plan={"execution_action": "place_market_buy", "read_only": True},
        live_risk_result={"accepted": True, "mode": "live"},
        coinbase_client=Client(),
        submit_live=False,
    )
    assert result["guard_result"]["guard_allows_market_order"] is True
    assert result["payload"]["accepted"] is True
    assert result["payload"]["order_type"] == "market"
    assert result["audit_log_fields"]["order_type"] == "market"
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "submit_live_argument_false" in result["hard_block_reasons"]


def test_mode_c_market_route_not_supported_blocker_when_submit_armed_without_route():
    cfg = _cfg(
        market_order_enabled=True,
        enable_market_orders=True,
        allow_market_orders=True,
        mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
    )
    result = prepare_mode_c_market_order_submission(
        cfg=cfg,
        ticker="BTC-USDC",
        side="BUY",
        order_intent={"side": "BUY", "execution_action": "place_market_buy", "size_quote": "20.00"},
        analysis={
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "20.00"},
            "trade_plan": {"trigger": "reclaim", "stop_loss": "95", "target": "110"},
        },
        execution_plan={"execution_action": "place_market_buy", "read_only": True},
        live_risk_result={"accepted": True, "mode": "live"},
        coinbase_client=object(),
        submit_live=True,
    )
    assert "mode_c_market_execution_route_retired" in result["hard_block_reasons"]
    assert result["live_submission_attempted"] is False
