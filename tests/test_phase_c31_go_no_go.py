from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.phase_c31_go_no_go import (
    assess_phase_c31_pre_go_no_go,
    build_phase_c31_env_preview,
    build_phase_c31_go_no_go_report,
)


def _cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=True,
        phase_c_allowed_tickers=["BTC-USDC"],
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


def _candidate():
    return {
        "analysis": {
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "9.50"},
            "feature_pack": {"decision_context": {"pending_order_intent": {"status": "needs_fresh_analysis", "trigger_ready": True, "requires_fresh_judge_and_risk": True}}},
        },
        "execution_plan": {
            "read_only": True,
            "execution_action": "place_limit_buy",
            "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.001"},
        },
        "order_intent": {"side": "BUY", "execution_action": "place_limit_buy", "size_quote": "9.50", "limit_price": "50000"},
        "risk": {"accepted": True, "mode": "live_phase_c"},
    }


def test_c31_blocks_default_safe_c30_disabled_config():
    cfg = _cfg(
        enable_phase_c_live_small_limit_orders=False,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        phase_c_allowed_tickers=[],
    )
    report = build_phase_c31_go_no_go_report(
        cfg=cfg,
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary={"submit_audit_clean_for_c30": True, "live_submission_attempted_count": 0, "live_order_submitted_count": 0},
        ticker="BTC-USDC",
        candidate=_candidate(),
    )
    assert report["ready_for_human_final_c31_review"] is False
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert "c30_pilot_config_not_ready" in report["blockers"]


def test_c31_ready_for_human_review_when_c30_runtime_and_guard_are_green_but_actual_submit_false():
    cfg = _cfg()
    report = build_phase_c31_go_no_go_report(
        cfg=cfg,
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary={"submit_audit_clean_for_c30": True, "live_submission_attempted_count": 0, "live_order_submitted_count": 0},
        ticker="BTC-USDC",
        candidate=_candidate(),
    )
    assert report["ready_for_human_final_c31_review"] is True
    assert report["final_go_no_go_locked_until_human_enables_actual_submit"] is True
    assert report["actual_coinbase_submit_currently_enabled"] is False
    assert report["live_order_submitted"] is False
    assert report["status"] == "ready_for_human_final_c31_review_no_submit_yet"


def test_c31_blocks_if_actual_submit_is_enabled_before_final_go():
    cfg = _cfg(enable_phase_c_actual_coinbase_submit=True)
    c30_report = {
        "pilot_ticker": "BTC-USDC",
        "pilot_config_ready": True,
        "submit_infrastructure_ready": True,
        "actual_coinbase_submit_still_disabled": False,
        "runtime_candidate_ready": True,
        "candidate_guard_ready": True,
        "runtime_assessment": {"submit_audit": {"live_submission_attempted_count": 0, "live_order_submitted_count": 0}},
    }
    result = assess_phase_c31_pre_go_no_go(cfg=cfg, c30_report=c30_report, ticker="BTC-USDC")
    assert result["ready_for_human_final_c31_review"] is False
    assert "actual_coinbase_submit_already_enabled" in result["blockers"]
    assert "actual_submit_enabled_before_final_human_go" in result["blockers"]


def test_c31_blocks_when_candidate_guard_missing_unless_config_only_mode():
    cfg = _cfg()
    c30_report = {
        "pilot_ticker": "BTC-USDC",
        "pilot_config_ready": True,
        "submit_infrastructure_ready": True,
        "actual_coinbase_submit_still_disabled": True,
        "runtime_candidate_ready": True,
        "candidate_guard_ready": False,
        "runtime_assessment": {"submit_audit": {"live_submission_attempted_count": 0, "live_order_submitted_count": 0}},
    }
    full = assess_phase_c31_pre_go_no_go(cfg=cfg, c30_report=c30_report, ticker="BTC-USDC", require_candidate_guard=True)
    config_only = assess_phase_c31_pre_go_no_go(cfg=cfg, c30_report=c30_report, ticker="BTC-USDC", require_candidate_guard=False)
    assert "candidate_guard_not_ready_or_missing_fresh_snapshot" in full["blockers"]
    assert config_only["ready_for_human_final_c31_review"] is True
    assert "candidate_guard_not_required_for_config_only_review_but_required_before_real_submit" in config_only["warnings"]


def test_c31_env_preview_separates_staged_preflight_from_actual_submit_arm():
    preview = build_phase_c31_env_preview(ticker="BTC-USDC", max_quote="10.00")
    staged = "\n".join(preview["staged_preflight_env"])
    final = "\n".join(preview["final_actual_submit_arm_env"])
    rollback = "\n".join(preview["rollback_env"])
    assert "PHASE_C_ALLOWED_TICKERS=BTC-USDC" in staged
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false" in staged
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true" in final
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false" in rollback


def test_c31_blocks_submit_audit_with_prior_live_attempt():
    cfg = _cfg()
    c30_report = {
        "pilot_ticker": "BTC-USDC",
        "pilot_config_ready": True,
        "submit_infrastructure_ready": True,
        "actual_coinbase_submit_still_disabled": True,
        "runtime_candidate_ready": True,
        "candidate_guard_ready": True,
        "runtime_assessment": {"submit_audit": {"live_submission_attempted_count": 1, "live_order_submitted_count": 0}},
    }
    result = assess_phase_c31_pre_go_no_go(cfg=cfg, c30_report=c30_report, ticker="BTC-USDC")
    assert result["ready_for_human_final_c31_review"] is False
    assert "submit_audit_contains_live_attempts" in result["blockers"]
