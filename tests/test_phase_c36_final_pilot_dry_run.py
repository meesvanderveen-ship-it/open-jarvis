from __future__ import annotations

from types import SimpleNamespace

from bot.phase_c36_final_pilot_dry_run import build_phase_c36_final_pilot_dry_run_report


def _cfg(**overrides):
    base = dict(
        enable_phase_c_actual_coinbase_submit=False,
        phase_c_max_order_quote="10.00",
        phase_c_live_order_post_only=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ready_c35_report(ticker="BTC-USDC"):
    return {
        "status": "preflight_ready_no_submit",
        "watch_tickers": [ticker],
        "counts": {"watch_ticker_count": 1, "preflight_ready_no_submit": 1, "candidate_found_blocked": 0, "no_candidate": 0},
        "any_preflight_ready_no_submit": True,
        "preflight_ready_tickers": [ticker],
        "blocked_candidate_tickers": [],
        "candidate_summaries": [
            {
                "ticker": ticker,
                "watch_status": "preflight_ready_no_submit",
                "final_preflight_snapshot_ready": True,
                "ready_for_human_final_pilot_run_review": True,
                "judge_decision": "approve_trade",
                "judge_side": "BUY",
                "judge_size_quote": "10.00",
                "order_intent_action": "place_limit_buy",
                "order_intent_side": "BUY",
                "order_intent_size_quote": "10.00",
                "payload_accepted": True,
            }
        ],
        "c34_reports_by_ticker": {
            ticker: {
                "ticker": ticker,
                "final_preflight_snapshot_ready": True,
                "c33_report": {
                    "final_preflight_snapshot": {
                        "ticker": ticker,
                        "pending_intent_id": "pending-test",
                        "fresh_analysis_id": "analysis-test",
                        "post_only": True,
                    },
                    "payload_preview": {
                        "accepted": True,
                        "side": "BUY",
                        "post_only": True,
                        "size_quote_requested": "10.00",
                        "size_quote_normalized": "10.00",
                        "limit_price": "50000",
                        "client_order_id": "phasec-BTCUSDC-test",
                        "coinbase_payload_preview": {"client_order_id": "phasec-BTCUSDC-test"},
                    },
                },
            }
        },
        "submit_audit": {"live_submission_attempted_count": 0, "live_order_submitted_count": 0, "sample_size": 0},
    }


def test_c36_blocks_when_no_preflight_ready_candidate():
    report = build_phase_c36_final_pilot_dry_run_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        c35_report={
            "status": "candidates_blocked_or_waiting",
            "watch_tickers": ["BTC-USDC"],
            "any_preflight_ready_no_submit": False,
            "preflight_ready_tickers": [],
            "candidate_summaries": [],
            "c34_reports_by_ticker": {},
            "submit_audit": {"live_submission_attempted_count": 0, "live_order_submitted_count": 0},
        },
    )
    assert report["status"] == "final_pilot_run_dry_run_blocked"
    assert "c35_has_no_preflight_ready_candidate" in report["blockers"]
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False


def test_c36_ready_report_for_preflight_candidate_still_no_submit():
    report = build_phase_c36_final_pilot_dry_run_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        c35_report=_ready_c35_report("BTC-USDC"),
    )
    assert report["status"] == "final_pilot_run_dry_run_ready_no_submit"
    assert report["dry_run_ready_no_submit"] is True
    assert report["actual_coinbase_submit_currently_enabled"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["final_run_preview"]["would_submit_if_future_final_go_enabled"] is True
    assert report["final_run_preview"]["submit_live_argument_for_c36"] is False


def test_c36_forbids_actual_submit_enabled_even_with_ready_candidate():
    report = build_phase_c36_final_pilot_dry_run_report(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        c35_report=_ready_c35_report("BTC-USDC"),
    )
    assert report["status"] == "final_pilot_run_dry_run_blocked"
    assert "actual_coinbase_submit_enabled_forbidden_in_c36" in report["blockers"]
    assert report["actual_coinbase_submit_currently_enabled"] is True
    assert report["live_order_submitted"] is False


def test_c36_rejects_payload_above_cap():
    c35 = _ready_c35_report("BTC-USDC")
    c35["c34_reports_by_ticker"]["BTC-USDC"]["c33_report"]["payload_preview"]["size_quote_normalized"] = "11.00"
    report = build_phase_c36_final_pilot_dry_run_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        c35_report=c35,
    )
    assert "payload_quote_missing_or_above_cap" in report["blockers"]
    assert report["dry_run_ready_no_submit"] is False


def test_c36_human_ack_is_recorded_but_does_not_submit():
    report = build_phase_c36_final_pilot_dry_run_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        c35_report=_ready_c35_report("BTC-USDC"),
        require_human_go_ack=True,
    )
    assert "human_go_ack_recorded_for_dry_run_review_only" in report["passed_checks"]
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
