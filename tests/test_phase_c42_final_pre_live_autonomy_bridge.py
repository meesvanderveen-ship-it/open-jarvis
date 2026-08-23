from types import SimpleNamespace

from bot.phase_c42_final_pre_live_autonomy_bridge import (
    C42_FINAL_ARM_ACK,
    C42_AUTONOMOUS_MODE_NAME,
    assess_phase_c42_final_autonomy_bridge,
    build_c42_autonomous_env_preview,
    build_phase_c42_final_pre_live_autonomy_bridge_report,
)


def _cfg(**overrides):
    base = dict(
        enable_phase_c_actual_coinbase_submit=False,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=False,
        phase_c_allowed_tickers=[],
        enable_autonomous_small_live_orderbook_mode=False,
        autonomous_max_order_quote="25.00",
        autonomous_max_open_orders=4,
        autonomous_max_new_orders_per_cycle=1,
        autonomous_max_cancels_per_cycle=2,
        autonomous_max_replaces_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=True,
        autonomous_allow_exits=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ready_c41():
    return {
        "status": "pre_live_ready_no_submit",
        "pre_live_ready_no_submit": True,
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "cancel_attempted_by_this_tool": False,
        "cancel_submitted": False,
        "readiness": {
            "readiness_summary": {
                "deterministic_live_risk_accepted": True,
                "controlled_coinbase_poll_succeeded": True,
            },
            "blockers": [],
        },
        "c40_summary": {
            "counts": {
                "live_open_orders": 0,
                "live_unmanaged_orders": 0,
                "partial_fill_like_orders": 0,
            }
        },
        "c38_summary": {
            "payload_preview_summary": {
                "accepted": True,
                "side": "BUY",
                "post_only": True,
                "size_quote_normalized": "25.00",
                "limit_price": "100.00",
            }
        },
    }


def test_blocked_when_c41_not_ready_and_no_candidate():
    c41 = {
        "status": "pre_live_readiness_blocked",
        "pre_live_ready_no_submit": False,
        "readiness": {"readiness_summary": {}},
        "c40_summary": {"counts": {"live_open_orders": 0, "live_unmanaged_orders": 0, "partial_fill_like_orders": 0}},
        "c38_summary": {"payload_preview_summary": {"accepted": False, "side": "BUY", "post_only": True, "size_quote_normalized": "0"}},
    }
    report = assess_phase_c42_final_autonomy_bridge(cfg=_cfg(), ticker="BTC-USDC", c41_report=c41)
    assert report["status"] == "autonomous_small_live_precheck_blocked"
    assert "c41_pre_live_not_ready" in report["blockers"]
    assert "payload_not_accepted" in report["blockers"]
    assert report["ready_to_arm_autonomous_small_live"] is False


def test_ready_to_arm_when_c41_ready_and_flags_still_safe():
    report = assess_phase_c42_final_autonomy_bridge(cfg=_cfg(), ticker="BTC-USDC", c41_report=_ready_c41())
    assert report["status"] == "ready_to_arm_autonomous_small_live"
    assert report["ready_to_arm_autonomous_small_live"] is True
    assert report["can_arm_autonomous_now"] is False
    assert report["arming_locks"]["actual_submit_enabled"] is False


def test_can_arm_only_with_all_explicit_final_locks():
    cfg = _cfg(
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c_actual_coinbase_submit=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_phase_c_live_small_limit_orders=True,
        phase_c_allowed_tickers=["BTC-USDC"],
    )
    report = assess_phase_c42_final_autonomy_bridge(
        cfg=cfg,
        ticker="BTC-USDC",
        c41_report=_ready_c41(),
        arm_ack=C42_FINAL_ARM_ACK,
        autonomous_mode=C42_AUTONOMOUS_MODE_NAME,
    )
    assert report["status"] == "autonomous_small_live_armed"
    assert report["can_arm_autonomous_now"] is True
    assert not report["blockers"]


def test_rejects_above_25_usdc_and_more_than_4_orders():
    report = assess_phase_c42_final_autonomy_bridge(
        cfg=_cfg(autonomous_max_order_quote="50.00", autonomous_max_open_orders=5),
        ticker="BTC-USDC",
        c41_report=_ready_c41(),
        max_order_quote="50.00",
        max_open_orders=5,
    )
    assert "max_order_quote_invalid_or_above_25" in report["blockers"]
    assert "configured_max_order_quote_invalid_or_above_25" in report["blockers"]
    assert "max_open_orders_invalid_or_above_4" in report["blockers"]
    assert "configured_max_open_orders_invalid_or_above_4" in report["blockers"]


def test_env_preview_contains_autonomous_limits_and_rollback():
    preview = build_c42_autonomous_env_preview(ticker="ETH-USDC")
    lines = preview["staged_autonomous_env_lines"]
    assert "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE=true" in lines
    assert "AUTONOMOUS_MAX_ORDER_QUOTE=25.00" in lines
    assert "AUTONOMOUS_MAX_OPEN_ORDERS=4" in lines
    assert "PHASE_C_ALLOWED_TICKERS=ETH-USDC" in lines
    assert "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE=false" in preview["rollback_env_lines"]


def test_full_report_does_not_submit_or_cancel_by_default():
    report = build_phase_c42_final_pre_live_autonomy_bridge_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        require_controlled_coinbase_poll=False,
    )
    assert report["config_ok"] is True
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["cancel_attempted_by_this_tool"] is False
    assert report["cancel_submitted"] is False
    assert report["status"] in {"autonomous_small_live_precheck_blocked", "ready_to_arm_autonomous_small_live"}
