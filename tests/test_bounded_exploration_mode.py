from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from bot.live_order_size_policy import bounded_exploration_report
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness


def _cfg(**overrides):
    base = dict(
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        enable_phase_c_live_small_limit_orders=True,
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote=Decimal("100.00"),
        phase_c_max_open_entry_orders=3,
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
        enable_bounded_exploration_mode=False,
        exploration_min_order_quote_usdc=Decimal("20.00"),
        exploration_max_order_quote_usdc=Decimal("35.00"),
        exploration_allowed_tickers=["BTC-USDC", "ETH-USDC", "SOL-USDC"],
        exploration_allow_market_orders=False,
        exploration_require_hard_risk_green=True,
        exploration_require_fresh_trigger=True,
        exploration_require_no_chase=True,
        exploration_max_spread_pct=Decimal("0.0040"),
        exploration_require_orderbook_snapshot=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _candidate(size_quote="20.00", trigger_ready=True, do_not_chase_above="101"):
    execution_plan = {
        "read_only": True,
        "execution_action": "place_limit_buy",
        "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.001"},
    }
    order = {"side": "BUY", "execution_action": "place_limit_buy", "size_quote": size_quote, "limit_price": "100"}
    analysis = {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": size_quote},
        "trade_plan": {
            "plan_action": "prepare_buy",
            "trigger": "break above 100",
            "stop_loss": "98",
            "do_not_chase_above": do_not_chase_above,
            "max_size_quote": size_quote,
        },
        "feature_pack": {
            "decision_context": {
                "pending_order_intent": {
                    "status": "trigger_ready" if trigger_ready else "watching",
                    "trigger_ready": trigger_ready,
                    "requires_fresh_judge_and_risk": True,
                }
            }
        },
    }
    return analysis, execution_plan, order, {"accepted": True, "mode": "live_phase_c"}


def test_bounded_exploration_default_disabled():
    report = bounded_exploration_report(_cfg())
    assert report["enabled"] is False
    assert report["ready"] is True
    assert report["market_orders_allowed"] is False


def test_bounded_exploration_requires_probe_band_trigger_and_no_chase():
    analysis, execution_plan, order, risk = _candidate(size_quote="40.00")
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(enable_bounded_exploration_mode=True),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
    )
    assert "bounded_exploration_quote_above_max" in result["hard_block_reasons"]

    analysis, execution_plan, order, risk = _candidate(size_quote="20.00", trigger_ready=False)
    analysis["trade_plan"]["trigger"] = ""
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(enable_bounded_exploration_mode=True),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
    )
    assert "bounded_exploration_fresh_trigger_missing" in result["hard_block_reasons"]

    analysis, execution_plan, order, risk = _candidate(size_quote="20.00", do_not_chase_above="99")
    result = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(enable_bounded_exploration_mode=True),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
    )
    assert "bounded_exploration_do_not_chase_above_breached" in result["hard_block_reasons"]


def test_bounded_exploration_market_orders_are_configuration_blocker():
    report = bounded_exploration_report(_cfg(enable_bounded_exploration_mode=True, exploration_allow_market_orders=True))
    assert report["ready"] is False
    assert "bounded_exploration_market_orders_enabled" in report["blockers"]


def test_bounded_exploration_empty_allowlist_uses_configured_universe():
    cfg = _cfg(
        enable_bounded_exploration_mode=True,
        phase_c_allowed_tickers=["SUI-USDC"],
        exploration_allowed_tickers=[],
    )
    report = bounded_exploration_report(cfg)
    assert report["allowed_tickers"] == ["SUI-USDC"]

    analysis, execution_plan, order, risk = _candidate(size_quote="20.00")
    result = evaluate_phase_c_live_entry_readiness(
        cfg=cfg,
        ticker="SUI-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
    )
    assert "ticker_not_in_configured_ticker_universe" not in result["hard_block_reasons"]
    assert "bounded_exploration_ticker_not_allowed" not in result["hard_block_reasons"]
