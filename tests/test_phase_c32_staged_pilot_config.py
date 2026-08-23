from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.phase_c32_staged_pilot_config import (
    assess_phase_c32_current_safety,
    assess_phase_c32_staged_preflight,
    build_phase_c32_env_dry_run_commands,
    build_phase_c32_staged_config,
    build_phase_c32_staged_pilot_report,
)


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


def _audit_clean():
    return {"submit_audit_clean_for_c30": True, "live_submission_attempted_count": 0, "live_order_submitted_count": 0, "sample_size": 2}


def test_c32_builds_in_memory_staged_config_without_mutating_original():
    cfg = _cfg()
    staged = build_phase_c32_staged_config(cfg, ticker="btc/usdc", max_quote="10.00")
    assert cfg.enable_live_limit_orders is False
    assert cfg.enable_live_entry_orders is False
    assert cfg.phase_c_allowed_tickers == []
    assert cfg.enable_phase_c_actual_coinbase_submit is False
    assert staged.enable_live_limit_orders is True
    assert staged.enable_live_entry_orders is True
    assert staged.enable_live_exit_orders is False
    assert staged.enable_phase_c_live_small_limit_orders is True
    assert staged.enable_phase_c_actual_coinbase_submit is False
    assert staged.phase_c_allowed_tickers == ["BTC-USDC"]


def test_c32_current_safety_blocks_if_actual_submit_enabled():
    cfg = _cfg(enable_phase_c_actual_coinbase_submit=True)
    result = assess_phase_c32_current_safety(cfg, submit_audit_summary=_audit_clean())
    assert result["current_env_safe_for_c32_staging"] is False
    assert "actual_coinbase_submit_enabled_danger" in result["blockers"]


def test_c32_staged_preflight_config_ready_without_runtime_candidate():
    cfg = _cfg()
    result = assess_phase_c32_staged_preflight(
        cfg=cfg,
        ticker="BTC-USDC",
        pending_summary={},
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=None,
    )
    assert result["staged_config_dry_run_ready"] is True
    assert result["staged_config_only_ready"] is True
    assert result["actual_coinbase_submit_still_disabled_under_staged_config"] is True
    assert result["live_submission_attempted_by_this_tool"] is False
    assert result["live_order_submitted"] is False
    assert "runtime_candidate_not_ready_yet; wait_for_promotion_ready_or_fresh_candidate" in result["warnings"]


def test_c32_full_report_ready_for_human_review_under_staged_config_with_candidate():
    cfg = _cfg()
    report = build_phase_c32_staged_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=_candidate(),
    )
    assert report["status"] == "staged_config_ready_no_submit"
    assert report["current_env_safe_for_c32_staging"] is True
    assert report["staged_config_dry_run_ready"] is True
    assert report["ready_for_human_final_c31_review_under_staged_config"] is True
    assert report["actual_coinbase_submit_still_disabled_under_staged_config"] is True
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    c31 = report["staged_preflight_assessment"]["c31_report_under_staged_config"]
    assert c31["final_go_no_go_locked_until_human_enables_actual_submit"] is True
    assert c31["actual_coinbase_submit_currently_enabled"] is False


def test_c32_blocks_quote_above_ten_usdc_cap():
    cfg = _cfg()
    result = assess_phase_c32_staged_preflight(
        cfg=cfg,
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        candidate=_candidate(),
        max_quote="10.01",
    )
    assert result["staged_config_dry_run_ready"] is False
    assert "staged_c30_pilot_config_not_ready" in result["blockers"]
    assert "staged_max_quote_invalid_or_above_10_usdc_cap" in result["blockers"]


def test_c32_blocks_dirty_submit_audit():
    cfg = _cfg()
    report = build_phase_c32_staged_pilot_report(
        cfg=cfg,
        ticker="BTC-USDC",
        pending_summary=_pending_ready(),
        order_summary=_orders_clean(),
        submit_audit_summary={"submit_audit_clean_for_c30": False, "live_submission_attempted_count": 1, "live_order_submitted_count": 0},
        candidate=_candidate(),
    )
    assert report["status"] == "blocked"
    assert "current:submit_audit_contains_live_attempts" in report["blockers"]
    assert report["live_order_submitted"] is False


def test_c32_env_preview_keeps_actual_submit_false_in_staged_lines():
    preview = build_phase_c32_env_dry_run_commands(ticker="BTC-USDC", max_quote="10.00")
    staged = "\n".join(preview["staged_env_lines"])
    assert "PHASE_C_ALLOWED_TICKERS=BTC-USDC" in staged
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false" in staged
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true" not in staged
    assert preview["actual_submit_must_remain_false"] is True
