from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess

from bot.phase_all_ticker_operator_live_start_gate import (
    ALL_TICKER_ACTUAL_SUBMIT_ACK,
    build_all_ticker_operator_live_start_gate,
)
from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


WRAPPER = Path("tools/operator_all_ticker_tiny_env.sh")
ALL_TICKERS = ",".join(DEFAULT_TICKERS)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_base_root(root: Path, *, selected: str = "OK", open_orders: dict | None = None, audit_status: str = "ok_observe_only") -> None:
    _write_json(root / "state/open_orders.json", {"orders": open_orders or {}})
    _write_json(root / "state/positions.json", {"BTC-USDC": {"ticker": "BTC-USDC", "status": "closed"}})
    _write_json(
        root / "reports/d6/safe-regression-harness-20260609.json",
        {
            "selected_tests": {
                "selected_tests_classification": selected,
                "selected_tests_passed_count": 33 if selected == "OK" else 32,
                "selected_tests_failed_count": 0 if selected == "OK" else 1,
            }
        },
    )
    _write_json(
        root / "reports/d6/all-ticker-live-readonly-preflight-20260609.json",
        _preflight_payload(),
    )
    _write_json(
        root / "audit.json",
        {"overall_status": audit_status, "warnings": []},
    )


def _preflight_payload(*, passed: bool = True, blocked: int = 0, tickers: list[str] | None = None) -> dict:
    selected_tickers = tickers if tickers is not None else list(DEFAULT_TICKERS)
    return {
        "status": "pass" if passed else "blocked",
        "gate_decision": {
            "all_ticker_live_readonly_preflight_attempted": True,
            "all_ticker_live_readonly_preflight_passed": passed,
            "blocked_ticker_count": blocked,
        },
        "per_ticker_preflight": [
            {"ticker": ticker, "blockers": [] if blocked == 0 else ["blocked"]} for ticker in selected_tickers
        ],
    }


def _env(*, ack: bool = False, overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "ALL_TICKER_TINY_WRAPPER_MODE": "true",
        "OPERATOR_ALL_TICKER_TINY_ENV_READY": "true",
        "EXECUTION_MODE": "live",
        "ALLOWED_TICKERS": ALL_TICKERS,
        "PHASE_C_ALLOWED_TICKERS": ALL_TICKERS,
        "DEFAULT_QUOTE_SIZE_USDC": "10",
        "PHASE_C_MAX_ORDER_QUOTE": "10",
        "MAX_NOTIONAL_USD": "10",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "10",
        "MAX_OPEN_POSITIONS": "2",
        "MAX_NEW_ORDERS_PER_CYCLE": "1",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "1",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "2",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true" if ack else "false",
        "ENABLE_LIVE_EXIT_ORDERS": "false",
        "AUTONOMOUS_ALLOW_EXITS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "false",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "true",
        "REPLICATION_ENABLED": "false",
        "LEARNING_TO_EXECUTION_READY": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
    }
    if ack:
        env["ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK"] = ALL_TICKER_ACTUAL_SUBMIT_ACK
    if overrides:
        env.update(overrides)
    return env


def _report(root: Path, *, env: dict[str, str] | None = None, audit_status: str = "ok_observe_only") -> dict:
    return build_all_ticker_operator_live_start_gate(
        root=root,
        environ=env or _env(),
        function_audit_report={"overall_status": audit_status, "warnings": []},
    )


def test_wrapper_file_exists_and_bash_n_passes() -> None:
    assert WRAPPER.exists()
    subprocess.run(["bash", "-n", str(WRAPPER)], check=True)


def test_wrapper_contains_all_18_tickers_and_safety_defaults() -> None:
    text = WRAPPER.read_text(encoding="utf-8")
    for ticker in DEFAULT_TICKERS:
        assert ticker in text
    assert "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false" in text
    assert ALL_TICKER_ACTUAL_SUBMIT_ACK in text
    assert "ENABLE_LIVE_EXIT_ORDERS=false" in text
    assert "AUTONOMOUS_ALLOW_EXITS=false" in text
    assert "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT=false" in text
    assert "REPLICATION_ENABLED=false" in text
    assert "LEARNING_TO_EXECUTION_READY=false" in text
    assert "LIVE_LEARNING_ALLOWED=false" in text
    assert "PARAMETER_CHANGE_ALLOWED=false" in text


def test_wrapper_requires_exact_ack_for_actual_submit_true(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK"] = "WRONG"
    script = (
        "printf '%s' \"$ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT:$ENABLE_LIVE_EXIT_ORDERS:"
        "$AUTONOMOUS_ALLOW_EXITS:$ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT:$REPLICATION_ENABLED:"
        "$LEARNING_TO_EXECUTION_READY:$LIVE_LEARNING_ALLOWED\""
    )
    no_ack = subprocess.run(
        [str(WRAPPER), "bash", "-lc", script],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert no_ack.stdout == "false:false:false:false:false:false:false"

    env["ALL_TICKER_TINY_ACTUAL_SUBMIT_ACK"] = ALL_TICKER_ACTUAL_SUBMIT_ACK
    with_ack = subprocess.run(
        [str(WRAPPER), "bash", "-lc", "printf '%s' \"$ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT\""],
        check=True,
        text=True,
        capture_output=True,
        env=env,
    )
    assert with_ack.stdout == "true"


def test_start_gate_blocks_without_ack(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    report = _report(tmp_path)

    assert report["all_ticker_operator_live_start_gate_ready"] is True
    assert report["ready_for_operator_ack"] is True
    assert report["live_start_authorized"] is False
    assert "all_ticker_ack_missing" in report["blockers"]


def test_start_gate_blocks_if_preflight_missing(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    (tmp_path / "reports/d6/all-ticker-live-readonly-preflight-20260609.json").unlink()
    report = _report(tmp_path, env=_env(ack=True))

    assert report["live_start_authorized"] is False
    assert "all_ticker_live_readonly_preflight_missing" in report["blockers"]


def test_start_gate_blocks_if_preflight_failed(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    _write_json(tmp_path / "reports/d6/all-ticker-live-readonly-preflight-20260609.json", _preflight_payload(passed=False, blocked=18))
    report = _report(tmp_path, env=_env(ack=True))

    assert "all_ticker_live_readonly_preflight_failed" in report["blockers"]
    assert "blocked_ticker_count_nonzero" in report["blockers"]


def test_start_gate_blocks_if_open_orders_nonzero(tmp_path: Path) -> None:
    _write_base_root(tmp_path, open_orders={"o1": {"ticker": "BTC-USDC", "side": "BUY", "status": "submitted"}})
    report = _report(tmp_path, env=_env(ack=True))

    assert "open_orders_nonzero" in report["blockers"]
    assert report["governance_flags"]["open_orders"] == 1


def test_start_gate_blocks_if_audit_not_ok(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    report = _report(tmp_path, env=_env(ack=True), audit_status="review_required")

    assert "function_preservation_audit_not_ok" in report["blockers"]


def test_start_gate_blocks_if_selected_tests_not_ok(tmp_path: Path) -> None:
    _write_base_root(tmp_path, selected="WATCH")
    report = _report(tmp_path, env=_env(ack=True))

    assert "selected_tests_not_ok" in report["blockers"]
    assert report["governance_flags"]["selected_tests_classification"] == "WATCH"


def test_start_gate_blocks_if_ticker_count_incomplete(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    _write_json(
        tmp_path / "reports/d6/all-ticker-live-readonly-preflight-20260609.json",
        _preflight_payload(tickers=list(DEFAULT_TICKERS)[:-1]),
    )
    report = _report(tmp_path, env=_env(ack=True))

    assert "preflight_ticker_count_incomplete" in report["blockers"]


def test_start_gate_blocks_if_caps_exceed_tiny_bounds(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    report = _report(tmp_path, env=_env(ack=True, overrides={"PHASE_C_MAX_ORDER_QUOTE": "11"}))

    assert "caps_exceed_tiny_conservative_bounds" in report["blockers"]


def test_start_gate_blocks_disabled_safety_flags(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    report = _report(
        tmp_path,
        env=_env(
            ack=True,
            overrides={
                "ENABLE_LIVE_EXIT_ORDERS": "true",
                "AUTONOMOUS_ALLOW_EXITS": "true",
                "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
                "REPLICATION_ENABLED": "true",
                "LEARNING_TO_EXECUTION_READY": "true",
                "LIVE_LEARNING_ALLOWED": "true",
                "PARAMETER_CHANGE_ALLOWED": "true",
            },
        ),
    )

    for blocker in [
        "live_exits_enabled",
        "autonomous_exits_enabled",
        "d3_actual_exit_submit_enabled",
        "replication_enabled",
        "learning_to_execution_ready",
        "live_learning_allowed",
        "parameter_change_allowed",
    ]:
        assert blocker in report["blockers"]


def test_start_gate_passes_only_for_operator_review_with_ack(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    report = _report(tmp_path, env=_env(ack=True))

    assert report["all_ticker_operator_live_start_gate_ready"] is True
    assert report["ready_for_operator_ack"] is False
    assert report["live_start_authorized"] is True
    assert report["codex_must_not_start_live_test"] is True
    assert report["operator_manual_start_required"] is True
    assert report["blockers"] == []


def test_report_builder_does_not_write_state_or_call_order_actions(tmp_path: Path) -> None:
    _write_base_root(tmp_path)
    before_open = _sha(tmp_path / "state/open_orders.json")
    before_positions = _sha(tmp_path / "state/positions.json")
    report = _report(tmp_path, env=_env(ack=True))
    after_open = _sha(tmp_path / "state/open_orders.json")
    after_positions = _sha(tmp_path / "state/positions.json")

    assert before_open == after_open
    assert before_positions == after_positions
    meta = report["metadata"]
    assert meta["state_write_performed"] is False
    assert meta["coinbase_call_attempted"] is False
    assert meta["order_action_attempted"] is False
    assert meta["submit_attempted"] is False
    assert meta["cancel_attempted"] is False
    assert meta["replace_attempted"] is False
    assert meta["config_mutation_performed"] is False
    assert meta["env_mutation_performed"] is False
    assert meta["parameter_mutation_performed"] is False
