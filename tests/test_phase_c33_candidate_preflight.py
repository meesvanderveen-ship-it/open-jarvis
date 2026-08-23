from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.phase_c33_candidate_preflight import build_phase_c33_final_preflight_report


def _cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=False,
        phase_c_allowed_tickers=[],
        phase_c_max_order_quote=Decimal("10.00"),
        phase_c_max_open_entry_orders=1,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_max_cancels_per_cycle=1,
        phase_c_max_replaces_per_cycle=0,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_entry_order_min_expiry_minutes=15,
        phase_c_entry_order_default_expiry_minutes=60,
        phase_c_entry_order_max_expiry_hours=6,
        phase_c_disable_exit_limit_orders=True,
        phase_c_paper_shadow_log=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        phase_c_live_order_post_only=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _pending_ready(ticker="BTC-USDC"):
    return {
        "total_intents": 1,
        "open_intents": 1,
        "promotion_ready": [{"ticker": ticker, "intent_id": "intent-1"}],
        "trigger_ready": [],
        "needs_fresh_analysis": [{"ticker": ticker, "intent_id": "intent-1"}],
    }


def _orders_clean():
    return {"total_orders": 0, "open_orders": 0, "diagnostic_order_count": 0, "open_entry_orders": []}


def _audit_clean():
    return {"submit_audit_clean_for_c30": True, "live_submission_attempted_count": 0, "live_order_submitted_count": 0, "sample_size": 2}


def _candidate(**overrides):
    base = {
        "ticker": "BTC-USDC",
        "fresh_analysis_id": "analysis-1",
        "analysis": {
            "ticker": "BTC-USDC",
            "analysis_id": "analysis-1",
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "9.50", "confidence": 72},
            "feature_pack": {
                "decision_context": {
                    "pending_order_intent": {
                        "intent_id": "intent-1",
                        "status": "needs_fresh_analysis",
                        "trigger_ready": True,
                        "requires_fresh_judge_and_risk": True,
                    }
                }
            },
        },
        "execution_plan": {
            "read_only": True,
            "execution_action": "place_limit_buy",
            "expiry_minutes": 60,
            "orderbook_summary": {
                "snapshot_available": True,
                "freshness_status": "fresh",
                "spread_pct": "0.001",
                "best_bid": "49999",
                "best_ask": "50001",
            },
        },
        "order_intent": {
            "side": "BUY",
            "execution_action": "place_limit_buy",
            "size_quote": "9.50",
            "limit_price": "50000",
            "expiry_minutes": 60,
            "intent_id": "intent-1",
        },
        "risk": {"accepted": True, "mode": "live_phase_c", "reason": "test"},
        "product_rules": {"base_increment": "0.00000001", "quote_increment": "0.01", "base_min_size": "0.00000001", "quote_min_size": "1"},
    }
    base.update(overrides)
    return base


def test_c33_blocks_without_candidate_snapshot_but_still_does_not_submit():
    report = build_phase_c33_final_preflight_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=None,
    )
    assert report["status"] == "blocked"
    assert report["final_preflight_snapshot_ready"] is False
    assert "candidate_snapshot_not_provided" in report["blockers"]
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["actual_coinbase_submit_currently_enabled"] is False


def test_c33_builds_final_preflight_snapshot_with_valid_candidate_and_no_submit():
    report = build_phase_c33_final_preflight_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=_candidate(),
    )
    assert report["status"] == "final_preflight_snapshot_ready_no_submit"
    assert report["final_preflight_snapshot_ready"] is True
    assert report["ready_for_human_final_pilot_run_review"] is True
    assert report["actual_coinbase_submit_currently_enabled"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["guard_summary"]["guard_allows_live_submit"] is True
    assert report["payload_preview"]["accepted"] is True
    snap = report["final_preflight_snapshot"]
    assert snap["pending_intent_id"] == "intent-1"
    assert snap["fresh_analysis_id"] == "analysis-1"
    assert snap["client_order_id_preview"]
    assert snap["coinbase_payload_preview"]["product_id"] == "BTC-USDC"


def test_c33_blocks_if_actual_submit_already_enabled():
    report = build_phase_c33_final_preflight_report(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=_candidate(),
    )
    assert report["status"] == "blocked"
    assert "actual_coinbase_submit_already_enabled_forbidden" in report["blockers"]
    assert report["live_order_submitted"] is False


def test_c33_blocks_candidate_with_stale_orderbook():
    candidate = _candidate()
    candidate["execution_plan"]["orderbook_summary"]["freshness_status"] = "stale"
    report = build_phase_c33_final_preflight_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=candidate,
    )
    assert report["status"] == "blocked"
    assert "candidate_snapshot_structural_blockers" in report["blockers"]
    assert "candidate_guard_not_ready" in report["blockers"]
    assert report["live_submission_attempted_by_this_tool"] is False


def test_c33_blocks_quote_above_cap():
    candidate = _candidate()
    candidate["order_intent"]["size_quote"] = "10.01"
    candidate["analysis"]["judge"]["size_quote"] = "10.01"
    report = build_phase_c33_final_preflight_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=candidate,
    )
    assert report["status"] == "blocked"
    assert "candidate_snapshot_structural_blockers" in report["blockers"]
    assert "payload_preview_not_accepted" in report["blockers"]
    assert report["live_order_submitted"] is False
