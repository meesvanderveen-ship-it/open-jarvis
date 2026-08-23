from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.show_full_autonomous_run_readiness import build_full_autonomous_run_readiness_report
from bot.config import BotConfig, MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE, MODE_C_MARKET_ORDER_ACK_VALUE


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _set_full_live_env(monkeypatch) -> None:
    env = {
        "BOT_CONFIG_SKIP_DOTENV": "true",
        "OPENAI_API_KEY": "test-key",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": "BTC-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC",
        "MAX_OPEN_POSITIONS": "3",
        "MAX_NEW_ORDERS_PER_CYCLE": "1",
        "DEFAULT_QUOTE_SIZE_USDC": "50.00",
        "MAX_NOTIONAL_USD": "100.00",
        "MIN_LIVE_ORDER_QUOTE_USDC": "50.00",
        "MAX_LIVE_ORDER_QUOTE_USDC": "100.00",
        "ENABLE_DYNAMIC_ENTRY_SIZING": "true",
        "MIN_DYNAMIC_ENTRY_QUOTE_USDC": "50.00",
        "MAX_DYNAMIC_ENTRY_QUOTE_USDC": "100.00",
        "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_EXIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_ENTRY_ONLY_FIRST": "false",
        "AUTONOMOUS_ALLOW_EXITS": "true",
        "PHASE_C_MAX_ORDER_QUOTE": "100.00",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "3",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
        "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "120.00",
        "PHASE_D3_MAX_OPEN_EXIT_ORDERS": "3",
        "PHASE_C43_LIFECYCLE_ALLOW_COINBASE_POLL": "true",
        "PHASE_C43_LIFECYCLE_APPLY_LOCAL": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
        "ENABLE_APPROVED_PARAMETER_PROFILE": "false",
        "ENABLE_CONTROLLED_STOP_MARKET_EXITS": "false",
        "ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL": "false",
        "ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT": "false",
        "ENABLE_AUTONOMOUS_STOP_EXIT_APPLY": "false",
        "ENABLE_BOUNDED_EXPLORATION_MODE": "false",
        "EXPLORATION_ALLOW_MARKET_ORDERS": "false",
        "NEURAL_SHADOW_POLICY_EXECUTION_ALLOWED": "false",
        "MARKET_ORDER_ENABLED": "false",
        "ENABLE_MARKET_ORDERS": "false",
        "ALLOW_MARKET_ORDERS": "false",
        "MODE_B_CONTROLLED_STOP_EXIT_ACK": "",
        "MODE_C_MARKET_ORDER_ACK": "",
        "REPLICATION_ENABLED": "false",
        "REPLICATION_LIFECYCLE_ENABLED": "false",
        "REPLICATION_LIFECYCLE_HTTP_ENABLED": "false",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)


def _seed_open_d3(root: Path) -> None:
    _write_json(
        root / "state/open_orders.json",
        {
            "orders": {
                "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000": {
                    "client_order_id": "phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000",
                    "exchange_order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
                    "order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30d",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "status": "submitted",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "linked_position_id": "76310097-849e-481c-b587-ba44bc3330fe",
                    "remaining_size": "0.00015416",
                    "limit_price": "71554.19",
                }
            }
        },
    )
    _write_json(
        root / "state/positions.json",
        {
            "BTC-USDC": {
                "ticker": "BTC-USDC",
                "status": "open",
                "position_size_base": "0.00015416",
                "bot_managed_base": "0.00015416",
            }
        },
    )


def test_current_open_d3_baseline_ready_with_stop_exit_preview_only(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    _seed_open_d3(tmp_path)

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-11T00:00:00Z")

    assert report["recommendation"] == "ready_for_mode_a_bounded_autonomous_live_run"
    assert report["open_orders_summary"]["open_d3_exit"] == 1
    assert report["controlled_stop_exit_readiness"]["preview_only_is_acceptable_for_bounded_run"] is True
    assert report["mode_a_readiness"]["ready"] is True
    assert report["mode_a_readiness"]["reason"] == "autonomous entries and D3 exits ready; stop-exit preview-only"
    assert report["mode_b_readiness"]["ready"] is False
    assert report["mode_b_readiness"]["reason"] == "controlled stop-exit apply disabled and requires ACK"
    assert report["single_process_guard_readiness"]["ready"] is True
    assert report["atomic_write_readiness"]["ready"] is True
    assert report["balanced_start_profile_status"]["safe_to_activate_now"] is False
    assert report["learning_sidecar_status"]["recommendation"] in {"keep_current_baseline", "no_change"}
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["live_order_size_policy"]["min_quote_usdc"] == "50.00"
    assert report["live_order_size_policy"]["max_quote_usdc"] == "100.00"
    assert report["bounded_exploration"]["enabled"] is False
    assert report["planner_judge_handoff"]["prepare_buy_prompt_enforced"] is True
    assert report["neural_shadow_passivity"]["execution_allowed"] is False
    assert report["research_prior_parameters"]["safe_to_live_activate_now"] is False
    assert report["research_prior_parameters"]["requires_operator_review"] is True
    assert report["backtesting_parameter_bridge"]["safe_to_live_activate_now"] is False
    assert report["backtesting_parameter_bridge"]["requires_operator_review"] is True
    assert report["market_order_status"]["status"] == "disabled"
    assert report["live_order_size_policy"]["market_orders_allowed"] is False


def test_readiness_tool_never_writes_state_env_or_orders(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    _seed_open_d3(tmp_path)
    open_orders = tmp_path / "state/open_orders.json"
    positions = tmp_path / "state/positions.json"
    before = (_sha(open_orders), _sha(positions))

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-11T00:00:00Z")
    after = (_sha(open_orders), _sha(positions))

    assert before == after
    assert report["env_write_performed"] is False
    assert report["service_touched"] is False
    assert report["coinbase_submit_attempted"] is False
    assert report["coinbase_cancel_attempted"] is False


def test_readiness_blocks_duplicate_d3_exit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    _seed_open_d3(tmp_path)
    payload = json.loads((tmp_path / "state/open_orders.json").read_text(encoding="utf-8"))
    payload["orders"]["phased3-BTCUSDC-TP2-bc3330fe-0T2153114172199999"] = {
        **payload["orders"]["phased3-BTCUSDC-TP1-bc3330fe-0T2153114172190000"],
        "client_order_id": "phased3-BTCUSDC-TP2-bc3330fe-0T2153114172199999",
        "exchange_order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30e",
        "order_id": "81edc268-cf15-4f25-b30b-f0d5b3abb30e",
    }
    _write_json(tmp_path / "state/open_orders.json", payload)

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-11T00:00:00Z")

    assert report["recommendation"] == "not_ready_p0_runtime_bug"
    assert "duplicate_open_d3_exit" in report["current_blockers"]


def test_stop_exit_apply_true_without_mode_b_ack_blocks_config_and_readiness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    monkeypatch.setenv("ENABLE_CONTROLLED_STOP_MARKET_EXITS", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY", "true")
    _seed_open_d3(tmp_path)

    cfg = BotConfig()
    try:
        cfg.validate()
    except ValueError as exc:
        assert "MODE_B_CONTROLLED_STOP_EXIT_ACK" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("BotConfig.validate should fail without Mode B ACK")

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")
    assert report["mode_a_readiness"]["ready"] is False
    assert "mode_b_stop_exit_apply_ack_missing" in report["current_blockers"]
    assert report["mode_b_ack_readiness"]["ack_valid"] is False


def test_mode_b_readiness_requires_exact_ack(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    monkeypatch.setenv("ENABLE_CONTROLLED_STOP_MARKET_EXITS", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_CANCEL", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_SUBMIT", "true")
    monkeypatch.setenv("ENABLE_AUTONOMOUS_STOP_EXIT_APPLY", "true")
    monkeypatch.setenv("MODE_B_CONTROLLED_STOP_EXIT_ACK", MODE_B_CONTROLLED_STOP_EXIT_ACK_VALUE)
    _seed_open_d3(tmp_path)

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")

    assert report["mode_a_readiness"]["ready"] is False
    assert report["mode_b_ack_readiness"]["ack_valid"] is True
    assert report["mode_b_readiness"]["ready"] is True


def test_mode_c_market_orders_true_without_ack_blocks_readiness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    _seed_open_d3(tmp_path)
    monkeypatch.setenv("MARKET_ORDER_ENABLED", "true")
    monkeypatch.setenv("ENABLE_MARKET_ORDERS", "true")
    monkeypatch.setenv("ALLOW_MARKET_ORDERS", "true")
    monkeypatch.delenv("MODE_C_MARKET_ORDER_ACK", raising=False)

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")

    assert report["market_order_status"]["status"] == "blocked"
    assert report["live_order_size_policy"]["market_orders_allowed"] is False
    assert "market_orders_enabled_without_ack" in report["current_blockers"]
    assert "mode_c_market_order_ack_missing" in report["current_blockers"]


def test_mode_c_market_orders_true_with_replication_blocks_readiness(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    _seed_open_d3(tmp_path)
    monkeypatch.setenv("MARKET_ORDER_ENABLED", "true")
    monkeypatch.setenv("ENABLE_MARKET_ORDERS", "true")
    monkeypatch.setenv("ALLOW_MARKET_ORDERS", "true")
    monkeypatch.setenv("MODE_C_MARKET_ORDER_ACK", MODE_C_MARKET_ORDER_ACK_VALUE)
    monkeypatch.setenv("REPLICATION_ENABLED", "true")

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")

    assert report["market_order_status"]["status"] == "blocked"
    assert report["live_order_size_policy"]["market_orders_allowed"] is False
    assert "market_orders_enabled_with_replication" in report["current_blockers"]


def test_mode_c_market_orders_exact_ack_replication_false_ready(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    _set_full_live_env(monkeypatch)
    _seed_open_d3(tmp_path)
    monkeypatch.setenv("MARKET_ORDER_ENABLED", "true")
    monkeypatch.setenv("ENABLE_MARKET_ORDERS", "true")
    monkeypatch.setenv("ALLOW_MARKET_ORDERS", "true")
    monkeypatch.setenv("MODE_C_MARKET_ORDER_ACK", MODE_C_MARKET_ORDER_ACK_VALUE)
    monkeypatch.setenv("REPLICATION_ENABLED", "false")
    monkeypatch.setenv("REPLICATION_LIFECYCLE_ENABLED", "false")
    monkeypatch.setenv("REPLICATION_LIFECYCLE_HTTP_ENABLED", "false")
    monkeypatch.setenv("ENABLE_FULL_WORKFLOW_LIVE_MODE", "false")

    report = build_full_autonomous_run_readiness_report(root=tmp_path, generated_at="2026-06-14T00:00:00Z")

    assert report["market_order_status"]["ready"] is True
    assert report["live_order_size_policy"]["market_orders_allowed"] is True
    assert report["mode_c_market_order_readiness"]["ack_valid"] is True
    assert report["mode_c_market_order_readiness"]["replication_disabled"] is True
    assert "market_orders_enabled_without_ack" not in report["current_blockers"]
    assert "market_orders_enabled_with_replication" not in report["current_blockers"]
    assert report["neural_shadow_passivity"]["execution_allowed"] is False
    assert report["learning_status"]["learning_mode"] in {"approved_profile_active", "report_only", "unsafe_disabled"}
