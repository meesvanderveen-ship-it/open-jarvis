from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.show_function_preservation_audit import (
    build_audit_report,
    _inspect_live_exit_gate_coverage,
    _check_env_safety,
    _env_parse,
)


def test_env_safety_accepts_observe_only_flags(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "REPLICATION_ENABLED=false",
                "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
                "ENABLE_LIVE_EXIT_ORDERS=false",
                "AUTONOMOUS_ALLOW_EXITS=false",
                "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true",
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false",
                "ENABLE_LIVE_LIMIT_ORDERS=true",
                "ENABLE_LIVE_ENTRY_ORDERS=true",
                "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    parsed = _env_parse(env)
    safety = _check_env_safety(parsed)
    assert safety["ready"] is True
    assert safety["mode"] == "observe_only_no_submit"
    assert safety["blockers"] == []


def test_env_safety_blocks_live_submit_and_missing_d3_exit_flag(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "REPLICATION_ENABLED=false",
                "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true",
                "ENABLE_LIVE_EXIT_ORDERS=false",
                "AUTONOMOUS_ALLOW_EXITS=false",
                "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    safety = _check_env_safety(_env_parse(env))
    assert safety["ready"] is False
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT_not_false" in safety["blockers"]
    assert "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT_not_false" in safety["blockers"]


def test_env_safety_accepts_exact_full_workflow_live_max3x20_flags(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                "ENABLE_FULL_WORKFLOW_LIVE_MODE=true",
                "EXECUTION_MODE=live",
                "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true",
                "ENABLE_LIVE_EXIT_ORDERS=true",
                "AUTONOMOUS_ALLOW_EXITS=true",
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=true",
                "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=false",
                "AUTONOMOUS_ENTRY_ONLY_FIRST=false",
                "MAX_OPEN_POSITIONS=3",
                "AUTONOMOUS_MAX_OPEN_ORDERS=3",
                "PHASE_C_MAX_OPEN_ENTRY_ORDERS=3",
                "MAX_NEW_ORDERS_PER_CYCLE=1",
                "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1",
                "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1",
                "DEFAULT_QUOTE_SIZE_USDC=20.00",
                "MAX_NOTIONAL_USD=20.00",
                "PHASE_C_MAX_ORDER_QUOTE=20.00",
                "AUTONOMOUS_MAX_ORDER_QUOTE=20.00",
                "PHASE_D3_MAX_EXIT_ORDER_QUOTE=20.00",
                "PHASE_D3_MAX_OPEN_EXIT_ORDERS=3",
                "PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE=1",
                "REPLICATION_ENABLED=false",
                "MARKET_ORDER_ENABLED=false",
                "ENABLE_MARKET_ORDERS=false",
                "ALLOW_MARKET_ORDERS=false",
                "LEARNING_TO_EXECUTION_READY=false",
                "LEARNING_TO_EXECUTION_ALLOWED=false",
                "LIVE_LEARNING_ALLOWED=false",
                "PARAMETER_CHANGE_ALLOWED=false",
                "ENABLE_LIVE_LIMIT_ORDERS=true",
                "ENABLE_LIVE_ENTRY_ORDERS=true",
                "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    safety = _check_env_safety(_env_parse(env))
    assert safety["ready"] is True
    assert safety["mode"] == "full_workflow_live_max3x20"
    assert safety["blockers"] == []
    assert safety["flags"]["REPLICATION_ENABLED"]["value"] == "false"
    assert safety["flags"]["REPLICATION_ENABLED"]["ok"] is True


def test_env_safety_blocks_full_workflow_live_max3x20_replication_enabled(tmp_path: Path) -> None:
    env = tmp_path / ".env"
    env.write_text(
        "\n".join(
            [
                *(f"{key}={value}" for key, value in {
                    "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
                    "EXECUTION_MODE": "live",
                    "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
                    "ENABLE_LIVE_EXIT_ORDERS": "true",
                    "AUTONOMOUS_ALLOW_EXITS": "true",
                    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
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
                    "REPLICATION_ENABLED": "true",
                    "MARKET_ORDER_ENABLED": "false",
                    "ENABLE_MARKET_ORDERS": "false",
                    "ALLOW_MARKET_ORDERS": "false",
                    "LEARNING_TO_EXECUTION_READY": "false",
                    "LEARNING_TO_EXECUTION_ALLOWED": "false",
                    "LIVE_LEARNING_ALLOWED": "false",
                    "PARAMETER_CHANGE_ALLOWED": "false",
                    "ENABLE_LIVE_LIMIT_ORDERS": "true",
                    "ENABLE_LIVE_ENTRY_ORDERS": "true",
                    "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
                }.items())
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    safety = _check_env_safety(_env_parse(env))
    assert safety["ready"] is False
    assert "REPLICATION_ENABLED_not_false" in safety["blockers"]


def test_audit_report_on_current_repository_is_read_only_and_has_core_sections() -> None:
    root = Path(__file__).resolve().parents[1]
    report = build_audit_report(root, window_minutes=240)
    assert report["safety_policy"]["read_only"] is True
    assert report["safety_policy"]["does_not_call_coinbase"] is True
    assert "env_safety" in report
    assert "static_function_preservation" in report
    categories = report["static_function_preservation"]["summary_by_category"]
    for required in ["core", "buy_entry", "sell_exit", "cancel_lifecycle", "learning", "roadmap", "safety"]:
        assert required in categories


def test_cli_json_output_is_valid() -> None:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "tools/show_function_preservation_audit.py", "--json"],
        cwd=root,
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(result.stdout)
    assert payload["tool"] == "show_function_preservation_audit"
    assert payload["safety_policy"]["does_not_submit_orders"] is True


def test_live_exit_gate_coverage_blocks_ungated_sell_sinks(tmp_path: Path) -> None:
    (tmp_path / "bot").mkdir()
    (tmp_path / "coinbase_executor.py").write_text(
        "def execute_trade():\n    pass\n\ndef execute_close_spot_position():\n    pass\n",
        encoding="utf-8",
    )
    (tmp_path / "bot" / "strategy_engine.py").write_text(
        "def _handle_position_action():\n    return 'sell'\n",
        encoding="utf-8",
    )
    (tmp_path / "bot" / "phase_d3_controlled_live_exits.py").write_text(
        "def submit_phase_d3_controlled_exit():\n    pass\n",
        encoding="utf-8",
    )
    coverage = _inspect_live_exit_gate_coverage(tmp_path)
    assert coverage["ready"] is False
    assert "ungated_live_sell_sink:coinbase_executor_execute_trade_gate" in coverage["blockers"]
