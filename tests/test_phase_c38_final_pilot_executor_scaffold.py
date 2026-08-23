from types import SimpleNamespace

from bot.phase_c38_final_pilot_executor_scaffold import (
    C38_FINAL_EXECUTOR_MODE,
    C38_HUMAN_GO_ACK,
    build_phase_c38_final_pilot_executor_report,
)


def cfg(actual=False):
    return SimpleNamespace(
        enable_phase_c_actual_coinbase_submit=actual,
        enable_phase_c_live_submit_infrastructure=True,
        phase_c_max_order_quote="10.00",
        phase_c_live_order_post_only=True,
        phase_c_disable_exit_limit_orders=True,
    )


def c37_actionable():
    return {
        "status": "actionable_preflight_candidates_ready_no_submit",
        "selected_ticker": "BTC-USDC",
        "actionable_preflight_ready_tickers": ["BTC-USDC"],
        "blocked_or_context_tickers": [],
        "counts": {"watch_ticker_count": 1, "actionable_preflight_ready": 1, "blocked_or_context_only": 0},
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "selected_candidate_assessment": {
            "ticker": "BTC-USDC",
            "watch_status": "preflight_ready_no_submit",
            "promotion_status": "actionable_preflight_ready_no_submit",
            "actionable_for_future_pilot_review": True,
            "judge_decision": "approve_trade",
            "judge_side": "BUY",
            "judge_size_quote": "10.00",
            "order_intent_action": "place_limit_buy",
            "order_intent_side": "BUY",
            "order_intent_size_quote": "10.00",
            "payload_accepted": True,
            "blocker_categories": [],
            "raw_blockers": [],
        },
        "candidate_assessments": [
            {
                "ticker": "BTC-USDC",
                "watch_status": "preflight_ready_no_submit",
                "promotion_status": "actionable_preflight_ready_no_submit",
                "actionable_for_future_pilot_review": True,
                "judge_decision": "approve_trade",
                "judge_side": "BUY",
                "judge_size_quote": "10.00",
                "order_intent_action": "place_limit_buy",
                "order_intent_side": "BUY",
                "order_intent_size_quote": "10.00",
                "payload_accepted": True,
                "blocker_categories": [],
                "raw_blockers": [],
            }
        ],
    }


def c36_ready():
    return {
        "status": "final_pilot_run_dry_run_ready_no_submit",
        "selected_ticker": "BTC-USDC",
        "dry_run_ready_no_submit": True,
        "ready_for_future_final_human_pilot_review": True,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": [],
        "final_run_preview": {
            "payload_preview": {
                "accepted": True,
                "client_order_id": "phasec-BTCUSDC-test-12345678",
                "side": "BUY",
                "post_only": True,
                "size_quote_requested": "10.00",
                "size_quote_normalized": "10.00",
                "size_base_normalized": "0.0001",
                "limit_price": "100000",
                "reject_reasons": [],
                "product_rules_used": {
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "base_min_size": "0.00000001",
                    "quote_min_size": "1.00",
                },
            },
            "final_preflight_snapshot": {
                "ticker": "BTC-USDC",
                "pending_intent_id": "pending-test",
                "fresh_analysis_id": "analysis-test",
                "post_only": True,
                "order_intent_snapshot": {
                    "side": "BUY",
                    "execution_action": "place_limit_buy",
                    "size_quote": "10.00",
                    "limit_price": "100000",
                },
            },
        },
    }


class FakeCoinbaseClient:
    def __init__(self):
        self.calls = []

    def place_limit_order(self, **kwargs):
        self.calls.append(kwargs)
        return {"order_id": "fake-order", "success": True, "kwargs": kwargs}


def test_c38_default_is_hardlocked_even_with_ready_candidate():
    report = build_phase_c38_final_pilot_executor_report(
        cfg=cfg(actual=False),
        ticker="BTC-USDC",
        c37_report=c37_actionable(),
        c36_report=c36_ready(),
    )
    assert report["status"] == "final_pilot_executor_hardlocked_no_submit"
    assert report["can_attempt_live_submit"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    blockers = report["hardlock_assessment"]["blockers"]
    assert "executor_mode_not_final_live_pilot" in blockers
    assert "human_go_ack_missing_or_wrong" in blockers
    assert "actual_coinbase_submit_flag_disabled" in blockers
    assert "submit_live_argument_false" in blockers
    assert "coinbase_client_not_provided" in blockers


def test_c38_submit_live_argument_alone_cannot_submit():
    client = FakeCoinbaseClient()
    report = build_phase_c38_final_pilot_executor_report(
        cfg=cfg(actual=False),
        ticker="BTC-USDC",
        c37_report=c37_actionable(),
        c36_report=c36_ready(),
        submit_live=True,
        coinbase_client=client,
    )
    assert report["can_attempt_live_submit"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert client.calls == []
    blockers = report["hardlock_assessment"]["blockers"]
    assert "actual_coinbase_submit_flag_disabled" in blockers
    assert "human_go_ack_missing_or_wrong" in blockers


def test_c38_all_final_hardlocks_use_submitter_with_fake_client_only():
    client = FakeCoinbaseClient()
    report = build_phase_c38_final_pilot_executor_report(
        cfg=cfg(actual=True),
        ticker="BTC-USDC",
        c37_report=c37_actionable(),
        c36_report=c36_ready(),
        executor_mode=C38_FINAL_EXECUTOR_MODE,
        human_go_ack=C38_HUMAN_GO_ACK,
        submit_live=True,
        coinbase_client=client,
    )
    assert report["can_attempt_live_submit"] is True
    assert report["live_submission_attempted_by_this_tool"] is True
    assert report["live_order_submitted"] is True
    assert report["status"] == "final_pilot_executor_submitted_live_order"
    assert len(client.calls) == 1
    call = client.calls[0]
    assert call["ticker"] == "BTC-USDC"
    assert call["side"] == "BUY"
    assert str(call["limit_price"]) == "100000"
    assert call["post_only"] is True


def test_c38_rejects_context_candidate_and_suppressed_payload():
    c37 = c37_actionable()
    c37["actionable_preflight_ready_tickers"] = []
    c37["selected_candidate_assessment"]["actionable_for_future_pilot_review"] = False
    c37["selected_candidate_assessment"]["promotion_status"] = "blocked_or_context_only"
    report = build_phase_c38_final_pilot_executor_report(
        cfg=cfg(actual=True),
        ticker="BTC-USDC",
        c37_report=c37,
        c36_report=c36_ready(),
        executor_mode=C38_FINAL_EXECUTOR_MODE,
        human_go_ack=C38_HUMAN_GO_ACK,
        submit_live=True,
        coinbase_client=FakeCoinbaseClient(),
    )
    assert report["can_attempt_live_submit"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert "c37_selected_candidate_not_actionable" in report["hardlock_assessment"]["blockers"]
