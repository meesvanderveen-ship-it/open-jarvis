from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.config import BotConfig, configured_ticker_universe
from bot.env_ticker_universe import (
    ADA_REVIEW_TICKERS,
    CONTROLLED_CLOSE_REPAIR_TICKERS,
    build_env_ticker_universe_workflow_readiness,
)
from bot.order_store import OrderStore
from bot.phase_c43_autonomous_entry_live import (
    _C43_LIFECYCLE_APPLY_AUTHORITY,
    reconcile_phase_c43_fills_to_positions,
)
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness
from bot.phase_c_live_submitter import prepare_phase_c_live_entry_submission
from bot.phase_d2_position_executor import D2_PLAN_STATUS_READY, build_multi_exit_bracket_lite_plan
from bot.phase_d3_controlled_live_exits import (
    D3_READY_NO_SUBMIT,
    assess_phase_d3_exit_readiness,
    build_phase_d3_exit_payload,
    select_next_phase_d3_exit_intent,
)
from bot.phase_d3_open_exit_lifecycle_manager import build_phase_d3_open_exit_lifecycle_report
from bot.pre_live_startup_gate import assess_pre_live_startup_gate
from tools.show_full_pipeline_health import build_full_pipeline_health_report, write_full_pipeline_health_report
from tools.show_pre_live_restart_readiness import build_pre_live_restart_readiness, write_pre_live_restart_readiness


CONFIGURED = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "SUI-USDC",
    "ADA-USDC",
]


def _rules(ticker: str) -> dict:
    return {
        "product_id": ticker,
        "price_increment": "0.01",
        "base_increment": "0.00000001",
        "quote_increment": "0.01",
        "quote_min_size": "1.00",
    }


def _rules_by_ticker(tickers: list[str] = CONFIGURED) -> dict:
    return {ticker: _rules(ticker) for ticker in tickers}


def _cfg(**overrides):
    base = dict(
        allowed_tickers=list(CONFIGURED),
        phase_c_allowed_tickers=list(CONFIGURED),
        autonomous_allowed_tickers=[],
        execution_mode="live",
        enable_full_workflow_live_mode=True,
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        enable_phase_c43_autonomous_entry_submitter=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_resting_limit_entry_preview=True,
        enable_resting_limit_entry_live_submit=False,
        phase_c_live_order_post_only=True,
        autonomous_require_post_only=True,
        phase_c_disable_exit_limit_orders=True,
        phase_c_paper_shadow_log=True,
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_order_quote=Decimal("100.00"),
        autonomous_max_order_quote=Decimal("100.00"),
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
        enable_orderbook_entry_planner=True,
        enable_bounded_exploration_mode=False,
        exploration_allowed_tickers=[],
        exploration_allow_market_orders=False,
        exploration_min_order_quote_usdc=Decimal("20.00"),
        exploration_max_order_quote_usdc=Decimal("35.00"),
        exploration_require_hard_risk_green=True,
        exploration_require_fresh_trigger=True,
        exploration_require_no_chase=True,
        exploration_max_spread_pct=Decimal("0.0040"),
        exploration_require_orderbook_snapshot=True,
        market_order_enabled=False,
        enable_market_orders=False,
        allow_market_orders=False,
        mode_c_market_order_ack="",
        replication_enabled=False,
        replication_lifecycle_enabled=False,
        replication_lifecycle_http_enabled=False,
        max_open_positions=4,
        autonomous_max_open_orders=4,
        max_new_orders_per_cycle=1,
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


def _candidate(ticker: str, *, decision: str = "approve_trade", side: str = "BUY", preview_only: bool = False, quote: str = "20.00") -> tuple[dict, dict, dict, dict]:
    analysis = {
        "preview_only": preview_only,
        "judge": {
            "decision": decision,
            "side": side,
            "size_quote": quote,
            "valid_trade_plan": decision == "approve_trade",
        },
        "trade_plan": {
            "valid_trade_plan": decision == "approve_trade",
            "plan_action": "prepare_resting_limit_entry",
            "side": "BUY",
            "entry_zone_low": "99.50",
            "entry_zone_high": "100.00",
            "stop_loss": "97.50",
            "invalidation_price": "97.50",
            "take_profit_1": "104.00",
            "take_profit_price": "104.00",
            "max_quote_size": quote,
            "trigger": "fresh reclaim ready",
            "setup_type": "reclaim_reversal",
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
    order_intent = {
        "ticker": ticker,
        "client_order_id": f"paper-{ticker.replace('-', '')}-candidate",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "size_quote": quote,
        "limit_price": "100.00",
        "product_rules": _rules(ticker),
    }
    risk = {"accepted": True, "approved": True, "risk_approved": True, "mode": "live_phase_c"}
    return analysis, execution_plan, order_intent, risk


class FakeStateStore:
    def __init__(self) -> None:
        self.positions: dict[str, dict] = {}

    def create_position(self, *, ticker, side, order_id, entry_price, position_size_base, position_size_quote, entry_reason="", extra=None):
        position = {
            "ticker": ticker,
            "status": "open",
            "last_side": side,
            "order_id": order_id,
            "entry_price": str(entry_price),
            "position_size_base": str(position_size_base),
            "position_size_quote": str(position_size_quote),
            "bot_managed_base": str(position_size_base),
            "entry_reason": entry_reason,
        }
        if extra:
            position.update(extra)
        self.positions[str(ticker).upper()] = position
        return position

    def get_position(self, ticker):
        return self.positions.get(str(ticker).upper())

    def get_positions(self):
        return dict(self.positions)

    def upsert_position(self, ticker, payload):
        existing = self.positions.get(str(ticker).upper(), {})
        existing.update(payload)
        self.positions[str(ticker).upper()] = existing
        return existing


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_product_rules(root: Path, tickers: list[str] = CONFIGURED) -> None:
    _write_json(root / "reports/audits/per-ticker-product-rule-evidence-cache-latest.json", {"rules_by_ticker": _rules_by_ticker(tickers)})


def test_env_universe_parses_and_repair_scopes_stay_isolated(monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ALLOWED_TICKERS", ",".join(CONFIGURED))
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", ",".join(CONFIGURED))

    cfg = BotConfig()
    readiness = build_env_ticker_universe_workflow_readiness(cfg=cfg, product_rules_by_ticker=_rules_by_ticker())

    assert configured_ticker_universe(cfg) == CONFIGURED
    assert readiness["eligible_tickers"] == CONFIGURED
    assert readiness["blocked_tickers"] == {}
    assert readiness["controlled_close_repair_tickers"] == CONTROLLED_CLOSE_REPAIR_TICKERS
    assert readiness["ada_review_tickers"] == ADA_REVIEW_TICKERS
    assert set(CONTROLLED_CLOSE_REPAIR_TICKERS) < set(readiness["eligible_tickers"])
    assert "ADA-USDC" in readiness["eligible_tickers"]


def test_full_mocked_entry_fill_d2_d3_lifecycle_orderbook_path(tmp_path: Path) -> None:
    cfg = _cfg()
    ticker = "SUI-USDC"
    analysis, execution_plan, order_intent, risk = _candidate(ticker)

    guard = evaluate_phase_c_live_entry_readiness(
        cfg=cfg,
        ticker=ticker,
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        live_risk_result=risk,
        product_rules=_rules(ticker),
    )
    assert guard["guard_allows_live_submit"] is True
    assert guard["candidate_summary"]["resting_entry_eligible"] is True

    submit_prep = prepare_phase_c_live_entry_submission(
        cfg=cfg,
        ticker=ticker,
        order_intent=order_intent,
        guard_result=guard,
        coinbase_client=None,
        product_rules=_rules(ticker),
        submit_live=False,
    )
    payload = submit_prep["payload"]
    preview = payload["coinbase_payload_preview"]
    limit_gtc = preview["order_configuration"]["limit_limit_gtc"]
    assert payload["accepted"] is True
    assert payload["order_type"] == "limit_limit_gtc"
    assert preview["side"] == "BUY"
    assert "market_market_ioc" not in preview["order_configuration"]
    assert limit_gtc["post_only"] is True
    assert submit_prep["live_submission_attempted"] is False
    assert submit_prep["live_order_submitted"] is False

    order_store = OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "order_events.jsonl")
    client_order_id = str(preview["client_order_id"])
    exchange_order_id = "cb-buy-sui-1"
    order_store.upsert_order(
        {
            "client_order_id": client_order_id,
            "exchange_order_id": exchange_order_id,
            "order_id": exchange_order_id,
            "ticker": ticker,
            "product_id": ticker,
            "side": "BUY",
            "status": "submitted",
            "mode": "live",
            "source_mode": "autonomous_small_live",
            "phase": "C43_autonomous_entry_live",
            "execution_action": "place_limit_buy",
            "size_base": limit_gtc["base_size"],
            "size_quote": payload["size_quote_normalized"],
            "remaining_size": limit_gtc["base_size"],
            "remaining_quote": payload["size_quote_normalized"],
            "limit_price": limit_gtc["limit_price"],
            "post_only": True,
            "opened_via_phase_c43": True,
            "trade_plan_snapshot": analysis["trade_plan"],
            "stop_price": "97.50",
            "invalidation_price": "97.50",
        }
    )
    state = FakeStateStore()
    fill_report = reconcile_phase_c43_fills_to_positions(
        cfg=cfg,
        order_store=order_store,
        state_store=state,
        live_orders_snapshot=[
            {
                "client_order_id": client_order_id,
                "exchange_order_id": exchange_order_id,
                "product_id": ticker,
                "side": "BUY",
                "status": "FILLED",
                "filled_size": limit_gtc["base_size"],
                "filled_value": payload["size_quote_normalized"],
                "average_filled_price": limit_gtc["limit_price"],
            }
        ],
        allow_coinbase_poll=False,
        tickers=[ticker],
        apply_local=True,
        _apply_authority=_C43_LIFECYCLE_APPLY_AUTHORITY,
    )
    assert fill_report["coinbase_call_attempted"] is False
    assert fill_report["actions"][0]["action"] == "filled_to_position"
    position = state.get_position(ticker)
    assert Decimal(position["position_size_base"]) > Decimal("0")
    assert Decimal(position["entry_price"]) > Decimal("0")
    assert Decimal(position["stop_price"]) > Decimal("0")
    assert Decimal(position["invalidation_price"]) > Decimal("0")
    assert position["position_risk_incomplete"] is False
    assert position["protective_stop_status"] == "protective_stop_state_complete"
    assert position["opened_via_phase_c43_live_order"] is True
    assert position["phase_c43_client_order_id"] == client_order_id
    assert position["phase_c43_exchange_order_id"] == exchange_order_id

    plan = build_multi_exit_bracket_lite_plan(cfg=cfg, position=position, exchange_rules=_rules(ticker))
    assert plan["status"] == D2_PLAN_STATUS_READY
    assert plan["position_id"] == exchange_order_id
    assert plan["exits"]

    exit_store = OrderStore(path=tmp_path / "exit_orders.json", log_path=tmp_path / "exit_events.jsonl")
    intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=position, order_store=exit_store, exchange_rules=_rules(ticker))
    d3_readiness = assess_phase_d3_exit_readiness(cfg=cfg, position=position, plan=plan, exit_intent=intent, order_store=exit_store, submit_live=False)
    d3_payload = build_phase_d3_exit_payload(cfg=cfg, exit_intent=intent)
    sell_preview = d3_payload["coinbase_payload_preview"]
    sell_gtc = sell_preview["order_configuration"]["limit_limit_gtc"]
    assert d3_readiness["status"] == D3_READY_NO_SUBMIT
    assert d3_readiness["ready"] is True
    assert intent["side"] == "SELL"
    assert intent["execution_action"] == "place_limit_sell"
    assert intent["reduce_only_local"] is True
    assert d3_payload["accepted"] is True
    assert sell_preview["side"] == "SELL"
    assert "market_market_ioc" not in sell_preview["order_configuration"]
    assert sell_gtc["post_only"] is True

    exit_order_id = "cb-sell-sui-1"
    exit_store.upsert_order(
        {
            "client_order_id": intent["client_order_id"],
            "exchange_order_id": exit_order_id,
            "order_id": exit_order_id,
            "ticker": ticker,
            "product_id": ticker,
            "side": "SELL",
            "status": "submitted",
            "mode": "live",
            "source_mode": "phase_d3_live_exit",
            "phase": "D3_controlled_live_reduce_only_exits",
            "execution_action": "place_limit_sell",
            "linked_position_id": intent["position_id"],
            "d3_exit_label": intent["label"],
            "size_base": intent["size_base"],
            "remaining_size": str(Decimal(intent["size_base"]) / Decimal("2")),
            "limit_price": intent["limit_price"],
            "post_only": True,
            "reduce_only_local": True,
        }
    )
    duplicate_intent = select_next_phase_d3_exit_intent(cfg=cfg, plan=plan, position=position, order_store=exit_store, exchange_rules=_rules(ticker))
    assert "duplicate_exit_label_already_open_for_position" in duplicate_intent["blockers"]

    open_lifecycle = build_phase_d3_open_exit_lifecycle_report(
        ticker=ticker,
        client_order_id=intent["client_order_id"],
        exchange_order_id=exit_order_id,
        linked_position_id=intent["position_id"],
        order_store=exit_store,
        state_store=state,
        snapshot={"normalized_status": "open", "remaining_size": intent["size_base"], "evidence_source": "test_fixture", "coinbase_call_succeeded": True},
        apply_local=False,
    )
    filled_lifecycle = build_phase_d3_open_exit_lifecycle_report(
        ticker=ticker,
        client_order_id=intent["client_order_id"],
        exchange_order_id=exit_order_id,
        linked_position_id=intent["position_id"],
        order_store=exit_store,
        state_store=state,
        snapshot={
            "normalized_status": "filled",
            "filled_base": intent["size_base"],
            "filled_quote": intent["estimated_quote_value"],
            "avg_fill_price": intent["limit_price"],
            "fill_count": 1,
            "remaining_size": "0",
            "evidence_source": "test_terminal_fill_fixture",
            "coinbase_call_succeeded": True,
        },
        apply_local=False,
    )
    cancelled_lifecycle = build_phase_d3_open_exit_lifecycle_report(
        ticker=ticker,
        client_order_id=intent["client_order_id"],
        exchange_order_id=exit_order_id,
        linked_position_id=intent["position_id"],
        order_store=exit_store,
        state_store=state,
        snapshot={"normalized_status": "cancelled", "remaining_size": intent["size_base"], "evidence_source": "test_cancel_fixture", "coinbase_call_succeeded": True},
        apply_local=False,
    )
    assert open_lifecycle["normalized_status"] == "open"
    assert filled_lifecycle["normalized_status"] == "filled"
    assert filled_lifecycle["status"] == "d3_open_exit_lifecycle_reconcile_preview_ready"
    assert filled_lifecycle["state_write_performed"] is False
    assert cancelled_lifecycle["normalized_status"] == "cancelled"
    assert cancelled_lifecycle["state_write_performed"] is False


def test_entry_fail_closed_cases_are_explicit(tmp_path: Path) -> None:
    cfg = _cfg()
    ticker = "SUI-USDC"

    def blockers_for(*, mutate_analysis=None, mutate_execution=None, mutate_order=None, product_rules=None, open_positions=None, open_order_tickers=None, quote="20.00"):
        analysis, execution_plan, order_intent, risk = _candidate(ticker, quote=quote)
        if mutate_analysis:
            mutate_analysis(analysis)
        if mutate_execution:
            mutate_execution(execution_plan)
        if mutate_order:
            mutate_order(order_intent)
        return evaluate_phase_c_live_entry_readiness(
            cfg=cfg,
            ticker=ticker,
            analysis=analysis,
            execution_plan=execution_plan,
            order_intent=order_intent,
            live_risk_result=risk,
            open_live_entry_orders_count=0,
            open_live_entry_order_tickers=open_order_tickers or [],
            open_positions=open_positions or [],
            product_rules=product_rules if product_rules is not None else _rules(ticker),
        )["hard_block_reasons"]

    assert "blocked_wait_decision_cannot_live_submit" in blockers_for(mutate_analysis=lambda a: a["judge"].update({"decision": "wait", "side": "NONE", "valid_trade_plan": False}))
    assert "blocked_missing_fresh_approve_trade" in blockers_for(mutate_analysis=lambda a: a["judge"].update({"side": "NONE"}))
    assert "blocked_preview_only_cannot_live_submit" in blockers_for(mutate_analysis=lambda a: a.update({"preview_only": True}))
    assert "blocked_missing_product_rules" in blockers_for(
        product_rules={},
        mutate_analysis=lambda a: (
            a["feature_pack"]["decision_context"].pop("product_rules", None),
            a["feature_pack"].pop("product_rules", None),
            a.pop("product_rules", None),
        ),
        mutate_order=lambda o: o.pop("product_rules", None),
    )
    assert "orderbook_snapshot_missing" in blockers_for(mutate_execution=lambda e: e["orderbook_summary"].update({"snapshot_available": False}))
    assert "blocked_open_position_same_ticker" in blockers_for(open_positions=[{"ticker": ticker, "status": "open", "position_size_base": "1"}])
    assert "blocked_open_order_same_ticker" in blockers_for(open_order_tickers=[ticker])
    assert "quote_size_below_min_live_order_quote" in blockers_for(quote="10.00")
    assert "quote_size_above_max_live_order_quote" in blockers_for(quote="120.00")
    assert "phase_c_market_order_entry_blocked" in blockers_for(
        mutate_execution=lambda e: e.update({"execution_action": "place_market_buy"}),
        mutate_order=lambda o: o.update({"execution_action": "place_market_buy", "order_type": "market"}),
    )


def test_risk_incomplete_d2_blocks_with_action_route() -> None:
    cfg = _cfg()
    position = {
        "ticker": "SUI-USDC",
        "status": "open",
        "order_id": "pos-risk-incomplete",
        "entry_price": "100.00",
        "position_size_base": "1.00",
        "position_size_quote": "100.00",
        "bot_managed_base": "1.00",
        "stop_price": "0",
        "invalidation_price": "0",
    }
    plan = build_multi_exit_bracket_lite_plan(cfg=cfg, position=position, exchange_rules=_rules("SUI-USDC"))
    assert plan["status"] != D2_PLAN_STATUS_READY
    assert "position_risk_incomplete_stop_or_invalidation_missing" in plan["blockers"]
    assert plan["risk_incomplete_action_route"]["route"] == "controlled_close_or_risk_reconstruction"


def test_unsupported_ticker_has_explicit_blocker() -> None:
    readiness = build_env_ticker_universe_workflow_readiness(
        cfg=_cfg(allowed_tickers=["BTC-USDC", "DOGE-USDC"], phase_c_allowed_tickers=["BTC-USDC", "DOGE-USDC"]),
        product_rules_by_ticker={"BTC-USDC": _rules("BTC-USDC")},
    )
    assert readiness["blocked_tickers"]["DOGE-USDC"] == ["product_rules_missing"]


def test_current_production_blockers_remain_red_when_unresolved(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports/audits/full-pipeline-health-latest.json",
        {
            "pipeline_health": "red",
            "safe_to_restart": False,
            "stale_lock_likely": True,
            "blockers": [
                "risk_incomplete_positions",
                "stale_lock_requires_operator_cleanup",
                "controlled_close_not_executed",
                "ada_review_not_completed",
            ],
        },
    )
    _write_json(
        tmp_path / "reports/audits/pre-live-restart-readiness-latest.json",
        {
            "safe_to_restart": False,
            "stale_lock_likely": True,
            "positions_blocking_restart": ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"],
            "controlled_close_pending": True,
            "ada_review_done": False,
        },
    )
    _write_json(
        tmp_path / "state/positions.json",
        {
            "ETH-USDC": {"status": "closed"},
            "AVAX-USDC": {"status": "closed"},
            "SOL-USDC": {"status": "closed"},
            "ADA-USDC": {"status": "open", "position_risk_incomplete": True},
        },
    )
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    gate = assess_pre_live_startup_gate(_cfg(enable_phase_c_actual_coinbase_submit=True), root=tmp_path)
    assert gate["startup_allowed"] is False
    assert gate["blockers"] == ["risk_incomplete_positions"]


def test_mocked_unblocked_readiness_can_be_green(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("BOT_CONFIG_SKIP_DOTENV", "true")
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    monkeypatch.setenv("ALLOWED_TICKERS", ",".join(CONFIGURED))
    monkeypatch.setenv("PHASE_C_ALLOWED_TICKERS", ",".join(CONFIGURED))
    monkeypatch.delenv("MARKET_ORDER_ENABLED", raising=False)
    monkeypatch.delenv("ENABLE_MARKET_ORDERS", raising=False)
    monkeypatch.delenv("ALLOW_MARKET_ORDERS", raising=False)
    _seed_product_rules(tmp_path)
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(
        tmp_path / "state/positions.json",
        {
            "SUI-USDC": {
                "ticker": "SUI-USDC",
                "status": "open",
                "order_id": "pos-green",
                "entry_price": "100.00",
                "position_size_base": "1.00",
                "position_size_quote": "100.00",
                "bot_managed_base": "1.00",
                "stop_price": "97.50",
                "invalidation_price": "97.50",
                "protective_stop_status": "protective_stop_state_complete",
                "position_risk_incomplete": False,
            }
        },
    )
    _write_json(
        tmp_path / "reports/audits/repair-sprint-status-latest.json",
        {"service_active": False, "stale_lock_likely": False, "open_orders": 0, "open_positions": 1, "position_risk_completion_done": True, "safe_to_restart": True},
    )
    _write_json(
        tmp_path / "reports/audits/risk-incomplete-controlled-close-prep-latest.json",
        {"status": "no_controlled_close_pending", "will_not_run_now": True, "positions_to_close": [], "positions_to_review": []},
    )
    _write_json(
        tmp_path / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "runtime": {"service_active": False, "stale_lock_likely": False},
            "summary": {
                "all_local_positions_match_fill_evidence": True,
                "all_entry_fills_proven_post_only_limit_maker": True,
                "open_positions": ["SUI-USDC"],
                "live_d2_d3_allowed_now": True,
            },
        },
    )
    _write_json(tmp_path / "reports/audits/position-risk-operator-decision-latest.json", {"operator_action": "none"})
    _write_json(tmp_path / "reports/audits/entry-order-type-and-orderbook-usage-audit-latest.json", {"summary": {"current_guard_blocks_replay": True}})

    health = build_full_pipeline_health_report(root=tmp_path)
    write_full_pipeline_health_report(health, root=tmp_path)
    readiness = build_pre_live_restart_readiness(root=tmp_path)
    write_pre_live_restart_readiness(readiness, root=tmp_path)
    gate = assess_pre_live_startup_gate(_cfg(enable_phase_c_actual_coinbase_submit=True), root=tmp_path)

    assert health["pipeline_health"] == "green"
    assert health["safe_to_restart"] is True
    assert health["blocked_tickers"] == {}
    assert readiness["safe_to_restart"] is True
    assert readiness["terminal_operator_status"] == "ready_for_operator_restart"
    assert gate["startup_allowed"] is True
