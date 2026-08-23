from types import SimpleNamespace

from bot.phase_c40_live_order_safety_layer import build_phase_c40_live_order_safety_report
from bot.phase_c41_pre_live_readiness import (
    C41_EMERGENCY_CANCEL_ACK,
    C41_EMERGENCY_CANCEL_MODE,
    assess_phase_c41_emergency_cancel_hardlock,
    build_phase_c41_pre_live_readiness_report,
    maybe_execute_phase_c41_emergency_cancel,
)


def cfg(actual=False, exits=False):
    return SimpleNamespace(
        enable_phase_c_actual_coinbase_submit=actual,
        enable_phase_c_live_submit_infrastructure=True,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        enable_live_exit_orders=exits,
        phase_c_max_order_quote="10.00",
        phase_c_live_order_post_only=True,
        phase_c_disable_exit_limit_orders=True,
    )


def c37_ready():
    return {
        "status": "actionable_preflight_candidates_ready_no_submit",
        "actionable_preflight_ready_tickers": ["BTC-USDC"],
        "blocked_or_context_tickers": [],
        "counts": {"watch_ticker_count": 1, "actionable_preflight_ready": 1, "blocked_or_context_only": 0},
        "selected_candidate_assessment": {
            "ticker": "BTC-USDC",
            "watch_status": "preflight_ready_no_submit",
            "promotion_status": "actionable_preflight_ready_no_submit",
            "actionable_for_future_pilot_review": True,
            "judge_decision": "approve_trade",
            "judge_side": "BUY",
            "order_intent_action": "place_limit_buy",
            "order_intent_side": "BUY",
            "order_intent_size_quote": "10.00",
            "payload_accepted": True,
        },
    }


def c38_ready_but_hardlocked():
    return {
        "status": "final_pilot_executor_hardlocked_no_submit",
        "can_attempt_live_submit": False,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "hardlock_assessment": {
            "readiness_locks": {
                "c37_candidate_actionable": True,
                "c36_dry_run_ready_no_submit": True,
                "payload_accepted": True,
                "payload_quote": "10.00",
                "payload_quote_cap": "10.00",
                "post_only": True,
                "entry_only_buy": True,
            }
        },
        "payload_preview_summary": {
            "accepted": True,
            "client_order_id": "phasec-BTCUSDC-test-123",
            "side": "BUY",
            "post_only": True,
            "size_quote_requested": "10.00",
            "size_quote_normalized": "10.00",
            "size_base_normalized": "0.0001",
            "limit_price": "100000",
            "reject_reasons": [],
        },
    }


class FakePollClient:
    def __init__(self, orders=None):
        self.called = False
        self.orders = orders if orders is not None else []

    def list_orders(self, **kwargs):
        self.called = True
        return {"orders": self.orders}


class FakeCancelClient:
    def __init__(self):
        self.cancelled = []

    def cancel_order(self, order_id):
        self.cancelled.append(order_id)
        return {"success": True, "order_id": order_id}


def live_order(**overrides):
    data = {
        "client_order_id": "phasec-BTCUSDC-test-123",
        "order_id": "cb-order-1",
        "product_id": "BTC-USDC",
        "side": "BUY",
        "status": "OPEN",
        "base_size": "0.0001",
        "quote_size": "10.00",
        "limit_price": "100000",
    }
    data.update(overrides)
    return data


def test_c41_default_is_blocked_and_does_not_submit_or_cancel(tmp_path):
    report = build_phase_c41_pre_live_readiness_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        order_store_path=tmp_path / "orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert report["status"] == "pre_live_readiness_blocked"
    assert report["pre_live_ready_no_submit"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["cancel_attempted_by_this_tool"] is False
    assert report["cancel_submitted"] is False
    blockers = report["readiness"]["blockers"]
    assert "c37_selected_ticker_not_actionable" in blockers
    assert "controlled_coinbase_open_order_poll_not_succeeded" in blockers
    assert "deterministic_live_risk_missing_or_not_accepted" in blockers


def test_c41_ready_no_submit_with_actionable_candidate_risk_and_successful_empty_poll(tmp_path):
    client = FakePollClient(orders=[])
    report = build_phase_c41_pre_live_readiness_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        c37_report=c37_ready(),
        c38_report=c38_ready_but_hardlocked(),
        live_risk_by_ticker={"BTC-USDC": {"ticker": "BTC-USDC", "accepted": True, "mode": "live_entry_pre_submit"}},
        coinbase_client=client,
        allow_coinbase_poll=True,
        order_store_path=tmp_path / "orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert client.called is True
    assert report["status"] == "pre_live_ready_no_submit"
    assert report["pre_live_ready_no_submit"] is True
    assert report["actual_coinbase_submit_currently_enabled"] is False
    assert report["live_order_submitted"] is False
    assert report["cancel_submitted"] is False


def test_c41_blocks_unmanaged_live_order_even_with_risk_and_candidate(tmp_path):
    report = build_phase_c41_pre_live_readiness_report(
        cfg=cfg(),
        ticker="BTC-USDC",
        c37_report=c37_ready(),
        c38_report=c38_ready_but_hardlocked(),
        live_risk_by_ticker={"BTC-USDC": {"ticker": "BTC-USDC", "accepted": True, "mode": "live_entry_pre_submit"}},
        live_orders_snapshot=[live_order(client_order_id="manual-web-order")],
        require_controlled_coinbase_poll=False,
        order_store_path=tmp_path / "orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert report["pre_live_ready_no_submit"] is False
    blockers = report["readiness"]["blockers"]
    assert "unmanaged_live_open_orders_detected" in blockers


def test_c41_actual_submit_enabled_is_pre_live_blocker(tmp_path):
    report = build_phase_c41_pre_live_readiness_report(
        cfg=cfg(actual=True),
        ticker="BTC-USDC",
        c37_report=c37_ready(),
        c38_report=c38_ready_but_hardlocked(),
        live_risk_by_ticker={"BTC-USDC": {"ticker": "BTC-USDC", "accepted": True, "mode": "live_entry_pre_submit"}},
        coinbase_client=FakePollClient(orders=[]),
        allow_coinbase_poll=True,
        order_store_path=tmp_path / "orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    assert "actual_coinbase_submit_enabled_before_final_live_window" in report["readiness"]["blockers"]


def test_c41_emergency_cancel_is_hardlocked_by_default(tmp_path):
    c40 = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        live_orders_snapshot=[live_order(client_order_id="manual-web-order")],
        order_store_path=tmp_path / "orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    hardlock = assess_phase_c41_emergency_cancel_hardlock(c40_report=c40)
    assert hardlock["can_attempt_emergency_cancel"] is False
    assert "emergency_cancel_mode_not_final" in hardlock["blockers"]
    assert "human_emergency_cancel_ack_missing_or_wrong" in hardlock["blockers"]
    assert "cancel_live_argument_false" in hardlock["blockers"]


def test_c41_emergency_cancel_requires_all_hardlocks_then_uses_fake_client(tmp_path):
    c40 = build_phase_c40_live_order_safety_report(
        cfg=cfg(),
        live_orders_snapshot=[live_order(client_order_id="manual-web-order")],
        order_store_path=tmp_path / "orders.json",
        order_events_path=tmp_path / "events.jsonl",
    )
    client = FakeCancelClient()
    result = maybe_execute_phase_c41_emergency_cancel(
        c40_report=c40,
        emergency_cancel_mode=C41_EMERGENCY_CANCEL_MODE,
        human_cancel_ack=C41_EMERGENCY_CANCEL_ACK,
        cancel_live=True,
        coinbase_client=client,
    )
    assert result["cancel_attempted_by_this_tool"] is True
    assert result["cancel_submitted"] is True
    assert client.cancelled == ["cb-order-1"]
