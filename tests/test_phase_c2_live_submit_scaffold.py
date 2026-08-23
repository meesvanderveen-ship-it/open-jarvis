from __future__ import annotations

from decimal import Decimal
import os
import sys
import types

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")
os.environ.setdefault("COINBASE_API_KEY", "test-coinbase-key")
os.environ.setdefault("COINBASE_API_SECRET", "test-coinbase-secret")

if "coinbase_auth" not in sys.modules:
    mod = types.ModuleType("coinbase_auth")
    mod.generate_coinbase_rest_jwt = lambda *args, **kwargs: "test-jwt"
    sys.modules["coinbase_auth"] = mod

import pytest

from bot.config import BotConfig
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness
from bot.phase_c_live_submitter import (
    build_phase_c_live_entry_payload,
    prepare_phase_c_live_entry_submission,
)


def _cfg(**overrides):
    cfg = BotConfig()
    for key, value in overrides.items():
        setattr(cfg, key, value)
    return cfg


def _order():
    return {
        "intent_id": "intent-test-123",
        "ticker": "BTC-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": "10",
        "limit_price": "50000",
        "client_order_id": "paper-BTCUSDC-place-limit-buy-test",
    }


def test_c2_payload_builder_creates_base_sized_limit_preview_without_submit():
    cfg = _cfg(phase_c_max_order_quote=Decimal("10"))
    payload = build_phase_c_live_entry_payload(
        cfg=cfg,
        ticker="BTC-USDC",
        order_intent=_order(),
        guard_result={"guard_allows_live_submit": False},
        product_rules={"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1"},
    )
    assert payload["accepted"] is True
    assert payload["side"] == "BUY"
    assert payload["order_type"] == "limit_limit_gtc"
    assert Decimal(payload["size_base_normalized"]) == Decimal("0.0002")
    assert payload["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]["post_only"] is True
    assert payload["safety_policy"]["no_coinbase_submit_in_payload_builder"] is True


def test_c2_prepare_blocks_when_actual_submit_flag_is_false_even_if_guard_allows():
    cfg = _cfg(
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        phase_c_max_order_quote=Decimal("10"),
    )
    result = prepare_phase_c_live_entry_submission(
        cfg=cfg,
        ticker="BTC-USDC",
        order_intent=_order(),
        guard_result={"guard_allows_live_submit": True, "hard_block_reasons": [], "passed_checks": []},
        coinbase_client=object(),
        submit_live=True,
    )
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert "phase_c_actual_coinbase_submit_disabled" in result["hard_block_reasons"]


class FakeCoinbase:
    def __init__(self):
        self.calls = []

    def place_limit_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"success": True, "order_id": "abc"}


def test_c2_submit_branch_requires_explicit_submit_argument_and_extra_flag():
    cfg = _cfg(
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=True,
        phase_c_max_order_quote=Decimal("10"),
    )
    client = FakeCoinbase()
    blocked = prepare_phase_c_live_entry_submission(
        cfg=cfg,
        ticker="BTC-USDC",
        order_intent=_order(),
        guard_result={"guard_allows_live_submit": True, "hard_block_reasons": [], "passed_checks": []},
        coinbase_client=client,
        submit_live=False,
    )
    assert blocked["live_submission_attempted"] is False
    assert client.calls == []
    assert "submit_live_argument_false" in blocked["hard_block_reasons"]

    submitted = prepare_phase_c_live_entry_submission(
        cfg=cfg,
        ticker="BTC-USDC",
        order_intent=_order(),
        guard_result={"guard_allows_live_submit": True, "hard_block_reasons": [], "passed_checks": []},
        coinbase_client=client,
        submit_live=True,
    )
    assert submitted["live_submission_attempted"] is True
    assert submitted["live_order_submitted"] is True
    assert client.calls and client.calls[0]["side"] == "BUY"


def test_coinbase_limit_method_payload_shape(monkeypatch):
    from bot.coinbase_client import CoinbaseClient

    client = CoinbaseClient(host="api.coinbase.com", timeout=1)
    captured = {}

    def fake_request(method, path, payload=None, **kwargs):
        captured.update({"method": method, "path": path, "payload": payload})
        return {"ok": True}

    monkeypatch.setattr(client, "_request", fake_request)
    result = client.place_limit_order(
        ticker="BTC-USDC",
        side="BUY",
        base_size=Decimal("0.0002"),
        limit_price=Decimal("50000"),
        client_order_id="test-client-id",
        post_only=True,
    )
    assert result == {"ok": True}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v3/brokerage/orders"
    assert captured["payload"]["client_order_id"] == "test-client-id"
    assert captured["payload"]["order_configuration"]["limit_limit_gtc"]["base_size"] == "0.0002"
    assert captured["payload"]["order_configuration"]["limit_limit_gtc"]["limit_price"] == "50000"


def test_config_blocks_actual_submit_without_phase_c_master_switch():
    cfg = _cfg(enable_phase_c_actual_coinbase_submit=True, enable_phase_c_live_small_limit_orders=False)
    with pytest.raises(ValueError, match="ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT"):
        cfg.validate()
