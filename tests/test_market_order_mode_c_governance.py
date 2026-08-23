from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.config import MODE_C_MARKET_ORDER_ACK_VALUE
from bot.phase_c_live_guard import evaluate_mode_c_market_order_guard, mode_c_market_order_readiness
from bot.phase_c_live_submitter import prepare_mode_c_market_order_submission


def _cfg(**overrides):
    base = dict(
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_open_entry_orders=3,
        phase_c_max_new_orders_per_cycle=1,
        autonomous_max_open_orders=3,
        max_open_positions=3,
        max_new_orders_per_cycle=1,
        market_order_enabled=False,
        enable_market_orders=False,
        allow_market_orders=False,
        mode_c_market_order_ack="",
        replication_enabled=False,
        replication_lifecycle_enabled=False,
        replication_lifecycle_http_enabled=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _armed_cfg(**overrides):
    return _cfg(
        market_order_enabled=True,
        enable_market_orders=True,
        allow_market_orders=True,
        mode_c_market_order_ack=MODE_C_MARKET_ORDER_ACK_VALUE,
        **overrides,
    )


def _buy_inputs(quote: str = "20.00"):
    return {
        "analysis": {
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": quote},
            "trade_plan": {"trigger": "reclaim", "stop_loss": "95", "target": "110"},
        },
        "execution_plan": {"execution_action": "place_market_buy", "read_only": True},
        "order_intent": {"side": "BUY", "execution_action": "place_market_buy", "size_quote": quote},
        "live_risk_result": {"accepted": True, "mode": "live"},
    }


def test_market_order_mode_c_disabled_is_valid_but_not_ready():
    status = mode_c_market_order_readiness(cfg=_cfg())
    assert status["status"] == "disabled"
    assert status["blockers"] == []


def test_market_order_mode_c_requires_exact_ack_and_replication_off():
    missing_ack = mode_c_market_order_readiness(
        cfg=_cfg(market_order_enabled=True, enable_market_orders=True, allow_market_orders=True)
    )
    assert "market_orders_enabled_without_ack" in missing_ack["blockers"]

    replication_on = mode_c_market_order_readiness(cfg=_armed_cfg(replication_lifecycle_http_enabled=True))
    assert "market_orders_enabled_with_replication" in replication_on["blockers"]

    ready = mode_c_market_order_readiness(cfg=_armed_cfg())
    assert ready["ready"] is True
    assert ready["replication_disabled"] is True


def test_market_buy_quote_rails_and_preview_no_live_call():
    low = _buy_inputs("19.99")
    low_guard = evaluate_mode_c_market_order_guard(cfg=_armed_cfg(), ticker="BTC-USDC", side="BUY", **low)
    assert "market_order_quote_below_min" in low_guard["hard_block_reasons"]

    high = _buy_inputs("100.01")
    high_guard = evaluate_mode_c_market_order_guard(cfg=_armed_cfg(), ticker="BTC-USDC", side="BUY", **high)
    assert "market_order_quote_above_max" in high_guard["hard_block_reasons"]

    class NoLiveClient:
        def place_market_order(self, **kwargs):
            raise AssertionError("no live Coinbase calls in tests")

    good = _buy_inputs("20.00")
    preview = prepare_mode_c_market_order_submission(
        cfg=_armed_cfg(),
        ticker="BTC-USDC",
        side="BUY",
        coinbase_client=NoLiveClient(),
        submit_live=False,
        **good,
    )
    assert preview["guard_result"]["guard_allows_market_order"] is True
    assert preview["payload"]["accepted"] is True
    assert preview["live_submission_attempted"] is False
    assert preview["live_order_submitted"] is False
    assert preview["audit_log_fields"]["order_type"] == "market"


def test_market_sell_requires_bot_position_and_no_oversell():
    no_position = evaluate_mode_c_market_order_guard(
        cfg=_armed_cfg(),
        ticker="BTC-USDC",
        side="SELL",
        order_intent={"side": "SELL", "base_size": "0.01", "estimated_price": "5000"},
        live_risk_result={"accepted": True, "mode": "live"},
    )
    assert "market_sell_without_position" in no_position["hard_block_reasons"]

    oversell = evaluate_mode_c_market_order_guard(
        cfg=_armed_cfg(),
        ticker="BTC-USDC",
        side="SELL",
        order_intent={"side": "SELL", "base_size": "0.02", "estimated_price": "5000"},
        live_risk_result={"accepted": True, "mode": "live"},
        existing_position={"ticker": "BTC-USDC", "status": "open", "bot_managed_base": "0.01"},
    )
    assert "market_sell_oversell" in oversell["hard_block_reasons"]


def test_market_sell_local_apply_requires_terminal_fill_evidence_policy():
    result = prepare_mode_c_market_order_submission(
        cfg=_armed_cfg(),
        ticker="BTC-USDC",
        side="SELL",
        order_intent={"side": "SELL", "base_size": "0.01", "estimated_price": "5000"},
        live_risk_result={"accepted": True, "mode": "live"},
        existing_position={"ticker": "BTC-USDC", "status": "open", "bot_managed_base": "0.01"},
        submit_live=False,
    )
    assert result["safety_policy"]["no_local_apply_without_terminal_fill_evidence"] is True
    assert result["payload"]["safety_policy"]["terminal_fill_evidence_required_before_local_apply"] is True


def test_mode_c_submit_flag_cannot_call_coinbase_after_route_retirement():
    class Client:
        calls = 0

        def place_market_order(self, **kwargs):
            self.calls += 1
            raise AssertionError("retired route must not reach Coinbase")

    client = Client()
    result = prepare_mode_c_market_order_submission(
        cfg=_armed_cfg(),
        ticker="BTC-USDC",
        side="BUY",
        coinbase_client=client,
        submit_live=True,
        **_buy_inputs("20.00"),
    )

    assert result["status"] == "mode_c_market_order_retired"
    assert "mode_c_market_execution_route_retired" in result["hard_block_reasons"]
    assert result["live_submission_attempted"] is False
    assert result["live_order_submitted"] is False
    assert client.calls == 0
