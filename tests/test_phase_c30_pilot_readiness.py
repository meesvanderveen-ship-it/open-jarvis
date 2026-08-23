from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.phase_c_pilot_readiness import (
    assess_phase_c_candidate_guard,
    assess_phase_c_pilot_config,
    assess_phase_c_pilot_runtime,
    build_phase_c_pilot_readiness_report,
    summarize_phase_c_submit_audit,
)

PRODUCT_RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "quote_min_size": "1.00",
}


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
    return {
        "total_orders": 0,
        "open_orders": 0,
        "diagnostic_order_count": 0,
        "open_entry_orders": [],
    }


def test_c30_default_config_is_not_ready_but_actual_submit_is_safely_disabled():
    result = assess_phase_c_pilot_config(_cfg())
    assert result["pilot_config_ready"] is False
    assert result["actual_coinbase_submit_still_disabled"] is True
    assert "phase_c_master_switch_disabled" in result["blockers"]
    assert "phase_c_allowed_tickers_empty" in result["blockers"]
    assert "actual_coinbase_submit_enabled_in_c30" not in result["blockers"]


def test_c30_one_ticker_config_can_be_ready_only_with_actual_submit_disabled():
    cfg = _cfg(
        enable_phase_c_live_small_limit_orders=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote=Decimal("10.00"),
    )
    result = assess_phase_c_pilot_config(cfg)
    assert result["pilot_config_ready"] is True
    assert result["pilot_ticker"] == "BTC-USDC"
    assert "actual_coinbase_submit_still_disabled" in result["passed_checks"]


def test_c30_blocks_if_actual_coinbase_submit_is_enabled_too_early():
    cfg = _cfg(
        enable_phase_c_live_small_limit_orders=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        enable_phase_c_actual_coinbase_submit=True,
    )
    result = assess_phase_c_pilot_config(cfg)
    assert result["pilot_config_ready"] is False
    assert result["actual_coinbase_submit_still_disabled"] is False
    assert "actual_coinbase_submit_enabled_in_c30" in result["blockers"]


def test_c30_runtime_requires_promotion_context_clean_orders_and_clean_submit_audit():
    cfg = _cfg(enable_phase_c_actual_coinbase_submit=False)
    result = assess_phase_c_pilot_runtime(
        cfg=cfg,
        pilot_ticker="BTC-USDC",
        pending_summary=_pending_ready("BTC-USDC"),
        order_summary=_orders_clean(),
        submit_audit_summary={"submit_audit_clean_for_c30": True, "live_submission_attempted_count": 0, "live_order_submitted_count": 0},
    )
    assert result["runtime_candidate_ready"] is True
    assert "pilot_ticker_has_promotion_ready_intent" in result["passed_checks"]
    assert "submit_audit_has_no_live_attempts_or_submits" in result["passed_checks"]


def test_c30_runtime_blocks_without_matching_promotion_ready_ticker():
    cfg = _cfg()
    result = assess_phase_c_pilot_runtime(
        cfg=cfg,
        pilot_ticker="BTC-USDC",
        pending_summary=_pending_ready("ETH-USDC"),
        order_summary=_orders_clean(),
        submit_audit_summary={"submit_audit_clean_for_c30": True},
    )
    assert result["runtime_candidate_ready"] is False
    assert "pilot_ticker_has_no_promotion_ready_intent" in result["blockers"]


def test_c30_report_separates_config_ready_from_candidate_guard_ready():
    cfg = _cfg(
        enable_phase_c_live_small_limit_orders=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        phase_c_allowed_tickers=["BTC-USDC"],
    )
    report = build_phase_c_pilot_readiness_report(
        cfg=cfg,
        pending_summary=_pending_ready("BTC-USDC"),
        order_summary=_orders_clean(),
        submit_audit_summary={"submit_audit_clean_for_c30": True, "sample_size": 0},
        pilot_ticker="BTC-USDC",
    )
    assert report["pilot_config_ready"] is True
    assert report["runtime_candidate_ready"] is True
    assert report["candidate_guard_ready"] is False
    assert report["candidate_guard_assessment"]["candidate_guard_evaluated"] is False
    assert report["actual_coinbase_submit_still_disabled"] is True
    assert report["c30_safe_to_continue_without_submit"] is True


def test_c30_candidate_guard_uses_existing_phase_c_guard_without_submit():
    cfg = _cfg(
        enable_phase_c_live_small_limit_orders=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote=Decimal("10.00"),
        min_live_order_quote_usdc=Decimal("10.00"),
    )
    candidate = {
        "analysis": {
            "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "10.00", "valid_trade_plan": True},
            "trade_plan": {
                "valid_trade_plan": True,
                "plan_action": "prepare_resting_limit_entry",
                "side": "BUY",
                "entry_zone_low": "49950.00",
                "entry_zone_high": "50000.00",
                "invalidation_price": "49000.00",
                "take_profit_1": "52000.00",
                "max_quote_size": "10.00",
                "trigger": "fresh reclaim ready",
            },
            "feature_pack": {
                "market": {"best_bid": "49990.00", "best_ask": "50000.00", "mid_price": "49995.00", "spread_pct": "0.0002"},
                "orderbook_context": {"snapshot_available": True, "best_bid": "49990.00", "best_ask": "50000.00", "mid_price": "49995.00"},
                "decision_context": {
                    "product_rules": PRODUCT_RULES,
                    "pending_order_intent": {"status": "needs_fresh_analysis", "trigger_ready": True, "requires_fresh_judge_and_risk": True},
                },
            },
        },
        "execution_plan": {
            "read_only": True,
            "execution_action": "place_limit_buy",
            "plan_action": "prepare_resting_limit_entry",
            "prepare_resting_limit_entry": True,
            "trigger_ready": True,
            "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.001"},
        },
        "order_intent": {
            "side": "BUY",
            "execution_action": "place_limit_buy",
                "plan_action": "prepare_resting_limit_entry",
                "prepare_resting_limit_entry": True,
                "trigger_ready": True,
                "size_quote": "10.00",
                "limit_price": "50000",
                "product_rules": PRODUCT_RULES,
            },
        "risk": {"accepted": True, "mode": "live_phase_c"},
    }
    result = assess_phase_c_candidate_guard(cfg=cfg, pilot_ticker="BTC-USDC", candidate=candidate)
    assert result["candidate_guard_evaluated"] is True
    assert result["candidate_guard_ready"] is True
    assert result["guard_result"]["live_submission_attempted"] is False


def test_c30_submit_audit_summary_flags_any_live_attempt(tmp_path):
    p = tmp_path / "phase_c_live_submit.jsonl"
    p.write_text('{"status":"x","live_submission_attempted":true,"live_order_submitted":false,"hard_block_reasons":["test"]}\n', encoding="utf-8")
    result = summarize_phase_c_submit_audit(p)
    assert result["submit_audit_clean_for_c30"] is False
    assert result["live_submission_attempted_count"] == 1
    assert result["hard_block_reasons_sample"] == {"test": 1}
