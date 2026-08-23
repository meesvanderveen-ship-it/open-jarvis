from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.config import BotConfig, configured_ticker_universe, effective_phase_c_allowed_tickers
from bot.env_ticker_universe import build_env_ticker_universe_workflow_readiness
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness
from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY, build_multi_exit_bracket_lite_plan
from bot.phase_d3_controlled_live_exits import assess_phase_d3_exit_readiness, select_next_phase_d3_exit_intent
from tools.show_pre_live_restart_readiness import build_pre_live_restart_readiness


def _rules(product_id: str) -> dict:
    return {
        "product_id": product_id,
        "price_increment": "0.01",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "quote_min_size": "1.00",
    }


def _cfg(**overrides):
    base = dict(
        allowed_tickers=["BTC-USDC", "ETH-USDC", "SUI-USDC"],
        phase_c_allowed_tickers=[],
        autonomous_allowed_tickers=[],
        enable_phase_c_live_small_limit_orders=True,
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_order_quote=Decimal("100.00"),
        phase_c_max_open_entry_orders=4,
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
        market_order_enabled=False,
        enable_market_orders=False,
        allow_market_orders=False,
        mode_c_market_order_ack="",
        replication_enabled=False,
        replication_lifecycle_enabled=False,
        replication_lifecycle_http_enabled=False,
        max_open_positions=3,
        autonomous_max_order_quote=Decimal("100.00"),
        autonomous_max_open_orders=4,
        autonomous_max_new_orders_per_cycle=1,
        phase_d2_min_expected_net_edge_pct=Decimal("0.0125"),
        phase_d2_min_reward_to_fee_ratio=Decimal("3.0"),
        phase_d2_min_reward_to_risk_ratio=Decimal("1.5"),
        phase_d2_estimated_entry_fee_pct=Decimal("0.0040"),
        phase_d2_estimated_exit_fee_pct=Decimal("0.0040"),
        phase_d2_estimated_spread_slippage_pct=Decimal("0.0020"),
        phase_d2_fee_safety_buffer_pct=Decimal("0.0025"),
        phase_d2_max_tp_orders_per_position=2,
        phase_d2_default_time_limit_hours=48,
        phase_d2_default_trailing_activation_pct=Decimal("0.0250"),
        phase_d2_default_trailing_distance_pct=Decimal("0.0180"),
        phase_d2_allow_add_to_winner=False,
        phase_d2_max_adds_to_winner=0,
        phase_d2_allow_averaging_down=False,
        enable_phase_d3_controlled_live_exits=True,
        enable_phase_d3_actual_exit_submit=False,
        phase_d3_max_exit_order_quote=Decimal("100.00"),
        phase_d3_max_open_exit_orders=4,
        phase_d3_max_new_exit_orders_per_cycle=1,
        phase_d3_exit_order_post_only=True,
        phase_d3_require_reduce_only_local=True,
        autonomous_allow_exits=False,
        autonomous_entry_only_first=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _entry_candidate(ticker: str):
    analysis = {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "20.00", "valid_trade_plan": True},
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "side": "BUY",
            "entry_zone_low": "99.50",
            "entry_zone_high": "100.00",
            "invalidation_price": "98.00",
            "take_profit_1": "104.00",
            "max_quote_size": "20.00",
            "trigger": "fresh reclaim ready",
        },
        "feature_pack": {
            "market": {"best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75", "spread_pct": "0.0002"},
            "orderbook_context": {"snapshot_available": True, "best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75"},
            "decision_context": {
                "product_rules": _rules(ticker),
                "pending_order_intent": {
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                },
            },
        },
    }
    execution_plan = {
        "read_only": True,
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.001"},
    }
    order = {
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "size_quote": "20.00",
        "limit_price": "100",
        "product_rules": _rules(ticker),
    }
    return analysis, execution_plan, order, {"accepted": True, "mode": "live_phase_c"}


def _position(ticker: str) -> dict:
    return {
        "ticker": ticker,
        "status": "open",
        "order_id": f"pos-{ticker}",
        "entry_price": "100.00",
        "position_size_base": "1.00",
        "bot_managed_base": "1.00",
        "position_size_quote": "100.00",
        "stop_price": "97.50",
        "invalidation_price": "97.50",
    }


def test_env_multiple_tickers_parse_and_effective_universe(monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ALLOWED_TICKERS", "btc-usdc, ETH-USDC,SUI-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "ETH-USDC")
    monkeypatch.setenv("AUTONOMOUS_ALLOWED_TICKERS", "SUI-USDC")

    cfg = BotConfig()

    assert cfg.allowed_tickers == ["BTC-USDC", "ETH-USDC", "SUI-USDC"]
    assert configured_ticker_universe(cfg) == ["BTC-USDC", "ETH-USDC", "SUI-USDC"]
    assert effective_phase_c_allowed_tickers(cfg) == ["BTC-USDC", "ETH-USDC", "SUI-USDC"]


def test_strategy_engine_scans_all_allowed_tickers_without_btc_only_filter() -> None:
    source = Path("bot/strategy_engine.py").read_text(encoding="utf-8")

    assert "list(self.cfg.allowed_tickers) + open_position_tickers" in source
    assert "for t in self.cfg.allowed_tickers" in source
    assert "new_entry_tickers = [" in source


def test_supported_env_ticker_with_product_rules_can_reach_entry_preparation() -> None:
    ticker = "SUI-USDC"
    analysis, execution_plan, order, risk = _entry_candidate(ticker)
    report = evaluate_phase_c_live_entry_readiness(
        cfg=_cfg(allowed_tickers=["BTC-USDC", "SUI-USDC"], phase_c_allowed_tickers=[]),
        ticker=ticker,
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        live_risk_result=risk,
        product_rules=_rules(ticker),
    )

    assert report["guard_allows_live_submit"] is True
    assert report["candidate_summary"]["resting_entry_eligible"] is True
    assert "ticker_allowed_for_phase_c" in report["passed_checks"]


def test_unsupported_ticker_gets_explicit_blocker() -> None:
    readiness = build_env_ticker_universe_workflow_readiness(
        cfg=_cfg(allowed_tickers=["BTC-USDC", "DOGE-USDC"], phase_c_allowed_tickers=[]),
        product_rules_by_ticker={"BTC-USDC": _rules("BTC-USDC")},
    )

    assert readiness["eligible_tickers"] == ["BTC-USDC"]
    assert readiness["blocked_tickers"]["DOGE-USDC"] == ["product_rules_missing"]


def test_each_risk_complete_env_ticker_can_get_d2_and_d3_limit_sell_intent() -> None:
    cfg = _cfg(allowed_tickers=["BTC-USDC", "ETH-USDC", "SUI-USDC"], phase_c_allowed_tickers=[])
    for ticker in cfg.allowed_tickers:
        position = _position(ticker)
        plan = build_multi_exit_bracket_lite_plan(cfg=cfg, position=position, exchange_rules=_rules(ticker))
        intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=position, exchange_rules=_rules(ticker))
        readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=position, plan=plan, exit_intent=intent, submit_live=False)

        assert plan["status"] == D2_PLAN_STATUS_READY
        assert intent["side"] == "SELL"
        assert intent["post_only"] is True
        assert readiness["ready"] is True


def test_controlled_close_and_ada_review_scopes_do_not_limit_normal_universe() -> None:
    readiness = build_env_ticker_universe_workflow_readiness(
        cfg=_cfg(allowed_tickers=["BTC-USDC", "ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC", "SUI-USDC"]),
        product_rules_by_ticker={
            "BTC-USDC": _rules("BTC-USDC"),
            "ETH-USDC": _rules("ETH-USDC"),
            "AVAX-USDC": _rules("AVAX-USDC"),
            "SOL-USDC": _rules("SOL-USDC"),
            "ADA-USDC": _rules("ADA-USDC"),
            "SUI-USDC": _rules("SUI-USDC"),
        },
    )

    assert readiness["controlled_close_repair_tickers"] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
    assert readiness["controlled_close_scope_isolated"] is True
    assert readiness["ada_review_scope_isolated"] is True
    assert "BTC-USDC" in readiness["eligible_tickers"]
    assert "SUI-USDC" in readiness["eligible_tickers"]
    assert "ADA-USDC" in readiness["eligible_tickers"]


def test_pre_live_readiness_reports_configured_eligible_blocked_tickers(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ALLOWED_TICKERS", "BTC-USDC,SUI-USDC,DOGE-USDC")
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", "")
    rules_path = tmp_path / "reports/audits/per-ticker-product-rule-evidence-cache-latest.json"
    rules_path.parent.mkdir(parents=True, exist_ok=True)
    rules_path.write_text(json.dumps({"rules_by_ticker": {"BTC-USDC": _rules("BTC-USDC"), "SUI-USDC": _rules("SUI-USDC")}}), encoding="utf-8")

    report = build_pre_live_restart_readiness(root=tmp_path)

    assert report["configured_tickers"] == ["BTC-USDC", "SUI-USDC", "DOGE-USDC"]
    assert report["eligible_tickers"] == ["BTC-USDC", "SUI-USDC"]
    assert report["blocked_tickers"] == {"DOGE-USDC": ["product_rules_missing"]}
