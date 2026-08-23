from __future__ import annotations

import importlib
import os
import subprocess
import sys
import types
from pathlib import Path
from types import SimpleNamespace

from bot.governance_constants import C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE
import pytest

from bot.phase_c43_autonomous_entry_live import build_phase_c43_guard_and_submit_preparation
from bot.order_store import OrderStore


ACK = "I_APPROVE_FULL_WORKFLOW_LIVE_MAX_3_ORDERS_MAX_20_USDC_BUY_AND_SELL_NO_MARKET_NO_REPLICATION"


def _set_full_workflow_env(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    values = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "ENABLE_APPROVED_PARAMETER_PROFILE": "false",
        "OPENAI_API_KEY": "test-openai-key",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "PHASE_C43_RUNTIME_SUBMIT_ACK": C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "AUTONOMOUS_ALLOW_EXITS": "true",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
        "PHASE_D3_RUNTIME_SUBMIT_ACK": "I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "AUTONOMOUS_ENTRY_ONLY_FIRST": "false",
        "MAX_OPEN_POSITIONS": "3",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "3",
        "MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "20.00",
        "PHASE_C_MAX_ORDER_QUOTE": "20.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
        "PHASE_D3_MAX_OPEN_EXIT_ORDERS": "3",
        "PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE": "1",
        "REPLICATION_ENABLED": "false",
        "MARKET_ORDER_ENABLED": "false",
        "ENABLE_MARKET_ORDERS": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "LEARNING_TO_EXECUTION_READY": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
    }
    values.update(overrides)
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def _bot_config(monkeypatch: pytest.MonkeyPatch, **overrides: str):
    _set_full_workflow_env(monkeypatch, **overrides)
    import bot.config as config

    importlib.reload(config)
    cfg = config.BotConfig()
    return cfg


def test_full_workflow_config_accepts_exact_max3x20(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = _bot_config(monkeypatch)
    cfg.validate()
    assert cfg.enable_full_workflow_live_mode is True
    assert cfg.max_open_positions == 3
    assert cfg.autonomous_max_open_orders == 3
    assert str(cfg.phase_c_max_order_quote) == "20.00"
    assert cfg.enable_phase_d3_actual_exit_submit is True
    assert cfg.phase_d3_runtime_submit_ack == "I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS"
    assert os.environ["REPLICATION_ENABLED"] == "false"


@pytest.mark.parametrize(
    ("key", "value", "message"),
    [
        ("AUTONOMOUS_MAX_OPEN_ORDERS", "4", "AUTONOMOUS_MAX_OPEN_ORDERS=3"),
        ("PHASE_C_MAX_ORDER_QUOTE", "20.01", "PHASE_C_MAX_ORDER_QUOTE"),
        ("MARKET_ORDER_ENABLED", "true", "MARKET_ORDER_ENABLED"),
        ("REPLICATION_ENABLED", "true", "REPLICATION_ENABLED"),
        ("LEARNING_TO_EXECUTION_ALLOWED", "true", "LEARNING_TO_EXECUTION_ALLOWED"),
        ("ENABLE_LIVE_EXIT_ORDERS", "false", "ENABLE_LIVE_EXIT_ORDERS"),
        ("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "false", "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"),
        ("PHASE_D3_RUNTIME_SUBMIT_ACK", "", "PHASE_D3_RUNTIME_SUBMIT_ACK"),
    ],
)
def test_full_workflow_config_fails_closed_for_unsafe_or_wrong_caps(
    monkeypatch: pytest.MonkeyPatch,
    key: str,
    value: str,
    message: str,
) -> None:
    cfg = _bot_config(monkeypatch, **{key: value})
    with pytest.raises(ValueError, match=message):
        cfg.validate()


def _candidate() -> tuple[dict, dict, dict]:
    analysis = {
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "20.00", "valid_trade_plan": True},
        "trade_plan": {
            "valid_trade_plan": True,
            "plan_action": "prepare_resting_limit_entry",
            "setup_type": "reclaim_retest",
            "entry_zone_low": "49990",
            "entry_zone_high": "50000",
            "preferred_limit_price": "50000",
            "invalidation_price": "49000",
            "stop_loss_price": "49000",
            "take_profit_1": "51000",
            "take_profit_2": "52000",
            "do_not_chase_above": "50100",
            "max_quote_size": "20.00",
        },
        "feature_pack": {
            "market": {"mid_price": "50000", "best_bid": "49999", "best_ask": "50001", "spread_pct": "0.00004"},
            "decision_context": {
                "product_rules": {
                    "price_increment": "0.01",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "base_min_size": "0.00000001",
                    "quote_min_size": "1.00",
                },
                "pending_order_intent": {
                    "status": "needs_fresh_analysis",
                    "trigger_ready": True,
                    "requires_fresh_judge_and_risk": True,
                }
            }
        },
    }
    execution_plan = {
        "execution_action": "place_limit_buy",
        "prepare_resting_limit_entry": True,
        "read_only": True,
        "orderbook_summary": {"snapshot_available": True, "freshness_status": "fresh", "spread_pct": "0.00004", "best_bid": "49999", "best_ask": "50001"},
    }
    order_intent = {
        "ticker": "BTC-USDC",
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": "20.00",
        "limit_price": "50000",
        "intent_id": "intent-1",
    }
    return analysis, execution_plan, order_intent


class FakeCoinbaseClient:
    def __init__(self) -> None:
        self.orders: list[dict] = []

    def submit_limit_buy_order(self, ticker, quote_size, base_size, limit_price, client_order_id=None, post_only=True):
        self.orders.append({"ticker": ticker, "side": "BUY", "base_size": str(base_size)})
        return {"success": True, "order_id": "cb-order-1", "client_order_id": client_order_id}


def test_full_workflow_entry_submitter_can_run_with_d3_exit_flags_enabled(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=True,
        enable_full_workflow_live_mode=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=True,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote="20.00",
        phase_c_max_open_entry_orders=3,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_disable_exit_limit_orders=False,
        phase_c_live_order_post_only=True,
        autonomous_max_order_quote="20.00",
        autonomous_max_open_orders=3,
        autonomous_max_new_orders_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=False,
        autonomous_allow_exits=True,
        enable_phase_d3_actual_exit_submit=True,
        order_store_max_records=200,
    )
    client = FakeCoinbaseClient()
    analysis, execution_plan, order_intent = _candidate()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg,
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        submit_live=True,
    )
    assert result["live_order_submitted"] is True
    assert client.orders[0]["side"] == "BUY"


def test_preview_does_not_submit_or_mutate(tmp_path: Path) -> None:
    cfg = SimpleNamespace(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=True,
        enable_live_entry_orders=True,
        enable_live_exit_orders=True,
        enable_full_workflow_live_mode=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        enable_autonomous_small_live_orderbook_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        phase_c_allowed_tickers=["BTC-USDC"],
        phase_c_max_order_quote="20.00",
        phase_c_max_open_entry_orders=3,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_disable_exit_limit_orders=False,
        phase_c_live_order_post_only=True,
        autonomous_max_order_quote="20.00",
        autonomous_max_open_orders=3,
        autonomous_max_new_orders_per_cycle=1,
        autonomous_require_post_only=True,
        autonomous_entry_only_first=False,
        autonomous_allow_exits=True,
        enable_phase_d3_actual_exit_submit=True,
        order_store_max_records=200,
    )
    client = FakeCoinbaseClient()
    analysis, execution_plan, order_intent = _candidate()
    result = build_phase_c43_guard_and_submit_preparation(
        cfg=cfg,
        ticker="BTC-USDC",
        analysis=analysis,
        execution_plan=execution_plan,
        order_intent=order_intent,
        coinbase_client=client,
        order_store=OrderStore(path=tmp_path / "orders.json", log_path=tmp_path / "events.jsonl"),
        submit_live=False,
    )
    assert result["live_order_submitted"] is False
    assert result["live_submission_attempted"] is False
    assert client.orders == []


def _script_env(repo: Path, *, ack: bool) -> dict[str, str]:
    env = os.environ.copy()
    if ack:
        env["FULL_WORKFLOW_LIVE_ACK"] = ACK
    else:
        env.pop("FULL_WORKFLOW_LIVE_ACK", None)
    output = subprocess.check_output(
        ["bash", "tools/operator_full_workflow_live_max3x20_env.sh", "env"],
        cwd=repo,
        env=env,
        text=True,
    )
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def test_operator_script_requires_exact_ack_for_live_exits_and_d3_submit() -> None:
    repo = Path(__file__).resolve().parents[1]
    env = _script_env(repo, ack=False)
    assert env["ENABLE_FULL_WORKFLOW_LIVE_MODE"] == "false"
    assert env["ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT"] == "false"
    assert env["ENABLE_LIVE_EXIT_ORDERS"] == "false"
    assert env["ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"] == "false"
    assert env["MARKET_ORDER_ENABLED"] == "false"
    assert env["REPLICATION_ENABLED"] == "false"
    assert env["LEARNING_TO_EXECUTION_ALLOWED"] == "false"
    assert env["PARAMETER_CHANGE_ALLOWED"] == "false"


def test_operator_script_exact_ack_enables_full_workflow_caps_and_exits() -> None:
    repo = Path(__file__).resolve().parents[1]
    env = _script_env(repo, ack=True)
    assert env["ENABLE_FULL_WORKFLOW_LIVE_MODE"] == "true"
    assert env["AUTONOMOUS_MAX_OPEN_ORDERS"] == "3"
    assert env["MAX_OPEN_POSITIONS"] == "3"
    assert env["PHASE_C_MAX_ORDER_QUOTE"] == "20.00"
    assert env["ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT"] == "true"
    assert env["ENABLE_LIVE_EXIT_ORDERS"] == "true"
    assert env["ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"] == "true"
    assert env["PHASE_D3_RUNTIME_SUBMIT_ACK"] == "I_UNDERSTAND_AND_APPROVE_D3_CONTROLLED_REDUCE_ONLY_LIVE_EXITS"
    assert env["PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"] == "false"
    assert env["AUTONOMOUS_ENTRY_ONLY_FIRST"] == "false"
    assert env["REPLICATION_ENABLED"] == "false"
    assert env["ENABLE_MARKET_ORDERS"] == "false"
    assert env["ALLOW_MARKET_ORDERS"] == "false"
    assert env["LEARNING_TO_EXECUTION_ALLOWED"] == "false"
    assert env["LIVE_LEARNING_ALLOWED"] == "false"
    assert env["PARAMETER_CHANGE_ALLOWED"] == "false"


def test_run_trader_loop_startup_diagnostic_exposes_full_workflow_bridge(monkeypatch: pytest.MonkeyPatch) -> None:
    if "openai" not in sys.modules:
        openai_stub = types.ModuleType("openai")
        openai_stub.OpenAI = object
        sys.modules["openai"] = openai_stub
    if "anthropic" not in sys.modules:
        anthropic_stub = types.ModuleType("anthropic")
        anthropic_stub.Anthropic = object
        sys.modules["anthropic"] = anthropic_stub
    if "pandas" not in sys.modules:
        pandas_stub = types.ModuleType("pandas")
        pandas_stub.DataFrame = object
        pandas_stub.Series = object
        sys.modules["pandas"] = pandas_stub
    if "numpy" not in sys.modules:
        numpy_stub = types.ModuleType("numpy")
        numpy_stub.nan = float("nan")
        numpy_stub.arange = lambda *args, **kwargs: []
        numpy_stub.polyfit = lambda *args, **kwargs: [0]
        sys.modules["numpy"] = numpy_stub

    cfg = SimpleNamespace(
        enable_full_workflow_live_mode=True,
        enable_phase_c43_autonomous_entry_submitter=True,
        enable_phase_c43_lifecycle_orchestrator=True,
        max_open_positions=3,
        autonomous_max_open_orders=3,
        phase_c_max_open_entry_orders=3,
        max_new_orders_per_cycle=1,
        autonomous_max_new_orders_per_cycle=1,
        phase_c_max_new_orders_per_cycle=1,
        default_quote_size_usdc="20.00",
        max_notional_usd="20.00",
        phase_c_max_order_quote="20.00",
        autonomous_max_order_quote="20.00",
        execution_mode="live",
        enable_live_entry_orders=True,
        enable_live_limit_orders=True,
        enable_phase_c_live_small_limit_orders=True,
        enable_phase_c_actual_coinbase_submit=True,
        phase_c43_runtime_submit_ack=C43_AUTONOMOUS_ENTRY_SUBMIT_ACK_VALUE,
        enable_live_exit_orders=True,
        autonomous_allow_exits=True,
        enable_phase_d3_actual_exit_submit=True,
        phase_c43_lifecycle_allow_coinbase_poll=True,
        phase_c43_lifecycle_apply_local=True,
        phase_c43_lifecycle_build_d2_plan=True,
        phase_c43_lifecycle_build_d3_preview=True,
    )
    import run_trader_loop

    report = run_trader_loop._build_full_workflow_runtime_diagnostic(cfg)
    assert report["enabled"] is True
    assert report["replication_enabled"] is False
    assert report["replication_publish_allowed"] is False
    assert report["follower_lifecycle_enabled"] is False
    assert report["strategy_engine_cycle_reachable"] is True
    assert report["phase_c43_entry_submitter_reachable"] is True
    assert report["lifecycle_hook_reachable"] is True
    assert report["caps"]["autonomous_max_open_orders"] == 3
    assert report["safety_policy"]["replication_publish_allowed"] is False
    assert report["safety_policy"]["follower_lifecycle_enabled"] is False
