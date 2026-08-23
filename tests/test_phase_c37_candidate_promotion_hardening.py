from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from bot.phase_c37_candidate_promotion_hardening import (
    assess_phase_c37_candidate_summary,
    build_phase_c37_candidate_promotion_hardening_report,
    summarize_phase_c37_live_risk_bridge,
)


def _cfg(**overrides):
    base = dict(
        enable_phase_c_actual_coinbase_submit=False,
        phase_c_max_order_quote="10.00",
        phase_c_live_order_post_only=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _blocked_summary(ticker="BTC-USDC"):
    return {
        "ticker": ticker,
        "watch_status": "candidate_found_blocked",
        "blockers": ["pending_intent_not_promotion_ready", "live_risk_result_not_supplied_or_not_found"],
        "judge_decision": "wait",
        "judge_side": "NONE",
        "judge_size_quote": 0.0,
        "order_intent_action": "no_order",
        "order_intent_side": "NONE",
        "order_intent_size_quote": None,
        "payload_accepted": False,
    }


def _ready_summary(ticker="BTC-USDC"):
    return {
        "ticker": ticker,
        "watch_status": "preflight_ready_no_submit",
        "blockers": [],
        "judge_decision": "approve_trade",
        "judge_side": "BUY",
        "judge_size_quote": "9.50",
        "order_intent_action": "place_limit_buy",
        "order_intent_side": "BUY",
        "order_intent_size_quote": "9.50",
        "payload_accepted": True,
    }


def _c35_report(summary):
    t = summary["ticker"]
    ready = summary["watch_status"] == "preflight_ready_no_submit"
    return {
        "status": "preflight_ready_no_submit" if ready else "candidates_blocked_or_waiting",
        "watch_tickers": [t],
        "counts": {
            "watch_ticker_count": 1,
            "no_candidate": 0,
            "candidate_found_blocked": 0 if ready else 1,
            "preflight_ready_no_submit": 1 if ready else 0,
        },
        "any_preflight_ready_no_submit": ready,
        "preflight_ready_tickers": [t] if ready else [],
        "blocked_candidate_tickers": [] if ready else [t],
        "candidate_summaries": [summary],
        "c34_reports_by_ticker": {},
        "submit_audit": {"live_submission_attempted_count": 0, "live_order_submitted_count": 0, "sample_size": 0},
    }


def _c36_report(status="final_pilot_run_dry_run_blocked", accepted=False):
    return {
        "status": status,
        "dry_run_ready_no_submit": accepted,
        "ready_for_future_final_human_pilot_review": accepted,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "blockers": [] if accepted else ["selected_ticker_not_preflight_ready"],
        "final_run_preview": {
            "payload_preview": {
                "accepted": accepted,
                "client_order_id": "phasec-test",
                "size_quote_requested": "9.50" if accepted else "0",
                "size_quote_normalized": "9.50" if accepted else "0",
                "size_base_normalized": "0.00019" if accepted else "0",
                "reject_reasons": [] if accepted else ["missing_or_zero_quote_size"],
            }
        },
    }


def test_c37_assessment_suppresses_wait_no_order_payload_preview():
    assessment = assess_phase_c37_candidate_summary(_blocked_summary())
    assert assessment["promotion_status"] == "blocked_or_context_only"
    assert assessment["actionable_for_future_pilot_review"] is False
    assert assessment["payload_preview_should_be_suppressed"] is True
    assert "judge_not_buy_approval" in assessment["blocker_categories"]
    assert "live_risk_missing_or_not_live" in assessment["blocker_categories"]


def test_c37_assessment_accepts_only_preflight_ready_buy_candidate():
    assessment = assess_phase_c37_candidate_summary(_ready_summary())
    assert assessment["promotion_status"] == "actionable_preflight_ready_no_submit"
    assert assessment["actionable_for_future_pilot_review"] is True
    assert assessment["payload_preview_should_be_suppressed"] is False


def test_c37_report_blocks_context_only_candidates_and_does_not_submit():
    report = build_phase_c37_candidate_promotion_hardening_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        c35_report=_c35_report(_blocked_summary()),
        c36_report=_c36_report(accepted=False),
    )
    assert report["status"] == "no_actionable_candidates_yet"
    assert report["actionable_preflight_ready_tickers"] == []
    assert report["safe_c36_payload_preview"]["payload_preview_suppressed"] is True
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["actual_coinbase_submit_currently_enabled"] is False


def test_c37_report_identifies_actionable_candidate_but_still_no_submit():
    report = build_phase_c37_candidate_promotion_hardening_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        c35_report=_c35_report(_ready_summary()),
        c36_report=_c36_report(status="final_pilot_run_dry_run_ready_no_submit", accepted=True),
        live_risk_by_ticker={"BTC-USDC": {"ticker": "BTC-USDC", "accepted": True, "mode": "live_phase_c", "reason": "ok"}},
    )
    assert report["status"] == "actionable_preflight_candidates_ready_no_submit"
    assert report["actionable_preflight_ready_tickers"] == ["BTC-USDC"]
    assert report["safe_c36_payload_preview"]["payload_preview_suppressed"] is False
    assert report["live_risk_bridge"]["accepted_live_risk_tickers"] == ["BTC-USDC"]
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False


def test_c37_forbids_actual_submit_enabled_even_for_ready_candidate():
    report = build_phase_c37_candidate_promotion_hardening_report(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        c35_report=_c35_report(_ready_summary()),
        c36_report=_c36_report(status="final_pilot_run_dry_run_ready_no_submit", accepted=True),
    )
    assert report["status"] == "blocked_safety_issue"
    assert "actual_coinbase_submit_enabled_forbidden_in_c37" in report["blockers"]
    assert report["actual_coinbase_submit_currently_enabled"] is True
    assert report["live_order_submitted"] is False


def test_c37_live_risk_bridge_loads_dir_and_rejects_paper_risk(tmp_path: Path):
    risk_dir = tmp_path / "risk"
    risk_dir.mkdir()
    (risk_dir / "BTC-USDC.json").write_text(json.dumps({"ticker": "BTC-USDC", "accepted": True, "mode": "live_phase_c"}), encoding="utf-8")
    (risk_dir / "ETH-USDC.json").write_text(json.dumps({"ticker": "ETH-USDC", "accepted": True, "mode": "paper_shadow"}), encoding="utf-8")
    summary = summarize_phase_c37_live_risk_bridge(risk_dir=risk_dir)
    assert summary["accepted_live_risk_tickers"] == ["BTC-USDC"]
    assert summary["count_supplied"] == 2
    assert summary["count_accepted_live"] == 1
    assert summary["blocked_or_non_live_risk"][0]["ticker"] == "ETH-USDC"
