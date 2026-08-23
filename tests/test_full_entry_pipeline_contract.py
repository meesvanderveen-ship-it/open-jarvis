from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.order_store import OrderStore
from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
from bot.phase_c43_autonomous_entry_live import build_phase_c43_guard_and_submit_preparation


PRODUCT_RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "quote_min_size": "1.00",
}


def _cfg(**overrides):
    base = dict(
        enable_phase_c43_autonomous_entry_submitter=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c_actual_coinbase_submit=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_live_small_limit_orders=True,
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=False,
        autonomous_allow_exits=False,
        autonomous_entry_only_first=True,
        phase_c_disable_exit_limit_orders=True,
        autonomous_require_post_only=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote=Decimal("100.00"),
        autonomous_max_order_quote=Decimal("100.00"),
        min_live_order_quote_usdc=Decimal("20.00"),
        max_live_order_quote_usdc=Decimal("100.00"),
        phase_c_max_open_entry_orders=4,
        autonomous_max_open_orders=4,
        phase_c_max_new_orders_per_cycle=1,
        autonomous_max_new_orders_per_cycle=1,
        phase_c_require_orderbook_freshness=True,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_live_order_post_only=True,
        market_order_enabled=False,
        enable_market_orders=False,
        allow_market_orders=False,
        mode_c_market_order_ack="",
        replication_enabled=False,
        replication_lifecycle_enabled=False,
        replication_lifecycle_http_enabled=False,
        max_open_positions=3,
        max_new_orders_per_cycle=1,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _candidate():
    execution_plan = {
        "read_only": True,
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": "0.0002",
        },
    }
    order = {
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "plan_action": "prepare_resting_limit_entry",
        "prepare_resting_limit_entry": True,
        "trigger_ready": True,
        "size_quote": "25.00",
        "limit_price": "100.00",
        "client_order_id": "phasec-BTCUSDC-contract",
        "product_rules": PRODUCT_RULES,
    }
    analysis = {
        "judge": {
            "decision": "approve_trade",
            "side": "BUY",
            "size_quote": "25.00",
            "valid_trade_plan": True,
        },
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "side": "BUY",
            "entry_zone_low": "99.50",
            "entry_zone_high": "100.00",
            "invalidation_price": "98.00",
            "take_profit_1": "104.00",
            "max_quote_size": "25.00",
            "trigger": "fresh reclaim ready",
            "stop_loss": "98.00",
        },
        "feature_pack": {
            "market": {
                "best_bid": "99.74",
                "best_ask": "99.76",
                "mid_price": "99.75",
                "spread_pct": "0.0002",
            },
            "orderbook_context": {
                "snapshot_available": True,
                "best_bid": "99.74",
                "best_ask": "99.76",
                "mid_price": "99.75",
            },
            "decision_context": {
                "product_rules": PRODUCT_RULES,
                "pending_order_intent": {
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                },
            },
        },
    }
    return analysis, execution_plan, order


class _AcceptingClient:
    def __init__(self, *, order_id: str = "cb-entry-1") -> None:
        self.order_id = order_id
        self.calls = []

    def submit_limit_buy_order(self, **kwargs):
        self.calls.append(kwargs)
        if not self.order_id:
            return {"success": True, "success_response": {}}
        return {
            "success": True,
            "success_response": {
                "order_id": self.order_id,
                "client_order_id": kwargs["client_order_id"],
            },
        }

    def place_market_order(self, *args, **kwargs):  # pragma: no cover - should not be reached
        raise AssertionError("market order route must not be called")


def _store(tmp_path: Path) -> OrderStore:
    return OrderStore(path=tmp_path / "open_orders.json", log_path=tmp_path / "events.jsonl")


def _run(tmp_path: Path, *, client=None, analysis=None, execution_plan=None, order=None, product_rules=PRODUCT_RULES, open_positions=None):
    base_analysis, base_plan, base_order = _candidate()
    return build_phase_c43_guard_and_submit_preparation(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis=analysis or base_analysis,
        execution_plan=execution_plan or base_plan,
        order_intent=order or base_order,
        coinbase_client=client or _AcceptingClient(),
        order_store=_store(tmp_path),
        submit_live=True,
        product_rules=product_rules,
        open_positions=open_positions or [],
    )


def test_happy_path_entry_accept_writes_local_open_order_only_after_exchange_id(tmp_path: Path) -> None:
    store = _store(tmp_path)
    analysis, execution_plan, order = _candidate()
    client = _AcceptingClient(order_id="cb-entry-accepted")

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        coinbase_client=client,
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
        open_positions=[],
    )

    assert result["guard_result"]["guard_allows_live_submit"] is True
    assert result["risk_snapshot"]["risk_approved"] is True
    assert result["submit_result"]["payload"]["coinbase_payload_preview"]["side"] == "BUY"
    assert result["submit_result"]["payload"]["coinbase_payload_preview"]["order_configuration"]["limit_limit_gtc"]["post_only"] is True
    assert result["live_order_submitted"] is True
    assert result["local_order_record"]["exchange_order_id"] == "cb-entry-accepted"
    assert result["local_order_record"]["stop_price"] == "98.00"
    assert result["local_order_record"]["invalidation_price"] == "98.00"
    assert result["local_order_record"]["entry_risk_state_complete"] is True
    assert store.open_entry_orders("BTC-USDC")[0]["exchange_order_id"] == "cb-entry-accepted"
    assert client.calls[0]["post_only"] is True


@pytest.mark.parametrize(
    ("mutator", "expected_blocker"),
    [
        (lambda analysis, plan, order: analysis["judge"].update({"decision": "wait", "side": "NONE", "valid_trade_plan": False}), "blocked_wait_decision_cannot_live_submit"),
        (lambda analysis, plan, order: analysis["judge"].update({"valid_trade_plan": False}) or analysis["trade_plan"].update({"valid_trade_plan": False}), "blocked_valid_trade_plan_false"),
        (lambda analysis, plan, order: plan.update({"orderbook_summary": {"snapshot_available": False}}), "orderbook_snapshot_missing"),
        (lambda analysis, plan, order: order.update({"execution_action": "place_market_buy", "order_type": "market", "order_configuration": {"market_market_ioc": {"quote_size": "25.00"}}}) or plan.update({"execution_action": "place_market_buy"}), "mode_c_market_payload_not_accepted"),
        (lambda analysis, plan, order: order.update({"size_quote": "101.00"}) or analysis["judge"].update({"size_quote": "101.00"}), "quote_size_above_max_live_order_quote"),
    ],
)
def test_entry_fail_closed_cases_do_not_submit(tmp_path: Path, mutator, expected_blocker: str) -> None:
    analysis, execution_plan, order = _candidate()
    mutator(analysis, execution_plan, order)
    client = _AcceptingClient()

    result = _run(tmp_path, client=client, analysis=analysis, execution_plan=execution_plan, order=order)

    assert result["live_order_submitted"] is False
    assert expected_blocker in str(result)
    assert _store(tmp_path).open_entry_orders("BTC-USDC") == []


def test_missing_product_rules_blocks_entry_submit(tmp_path: Path) -> None:
    analysis, execution_plan, order = _candidate()
    order.pop("product_rules")
    analysis["feature_pack"]["decision_context"].pop("product_rules")

    result = _run(tmp_path, analysis=analysis, execution_plan=execution_plan, order=order, product_rules={})

    assert result["live_order_submitted"] is False
    assert "product_precision_context_missing" in result["risk_snapshot"]["blockers"]


def test_same_ticker_open_position_blocks_entry_submit(tmp_path: Path) -> None:
    result = _run(
        tmp_path,
        open_positions=[{"ticker": "BTC-USDC", "status": "open", "position_size_base": "0.1"}],
    )

    assert result["live_order_submitted"] is False
    assert "blocked_open_position_same_ticker" in result["guard_result"]["hard_block_reasons"]


def test_exchange_accept_missing_exchange_order_id_does_not_create_open_order(tmp_path: Path) -> None:
    store = _store(tmp_path)
    analysis, execution_plan, order = _candidate()

    result = build_phase_c43_guard_and_submit_preparation(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order,
        coinbase_client=_AcceptingClient(order_id=""),
        order_store=store,
        submit_live=True,
        product_rules=PRODUCT_RULES,
        open_positions=[],
    )

    assert result["live_submission_attempted"] is True
    assert result["live_order_submitted"] is False
    assert result["submit_result"]["status"] == "phase_c_live_order_submit_unconfirmed_no_order_id"
    assert store.open_entry_orders("BTC-USDC") == []
