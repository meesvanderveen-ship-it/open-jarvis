from __future__ import annotations

import hashlib
import json
from pathlib import Path

from bot.full_live_parameter_readiness_gate import (
    EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
    build_full_live_parameter_readiness_gate,
)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _env(**overrides: str) -> str:
    values = {
        "EXECUTION_MODE": "live",
        "ENABLE_LIVE_ENTRY_ORDERS": "true",
        "ENABLE_LIVE_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "false",
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
        "ENABLE_LIMIT_ORDER_MANAGER": "true",
        "ALLOWED_TICKERS": "BTC-USDC,ETH-USDC,SOL-USDC,XRP-USDC,ADA-USDC,LINK-USDC,AVAX-USDC,DOGE-USDC,SUI-USDC,LTC-USDC,HBAR-USDC,ATOM-USDC,NEAR-USDC,APT-USDC,INJ-USDC,ARB-USDC,OP-USDC,UNI-USDC",
        "PHASE_C_ALLOWED_TICKERS": "BTC-USDC,ETH-USDC,SOL-USDC,XRP-USDC,ADA-USDC,LINK-USDC,AVAX-USDC,DOGE-USDC,SUI-USDC,LTC-USDC,HBAR-USDC,ATOM-USDC,NEAR-USDC,APT-USDC,INJ-USDC,ARB-USDC,OP-USDC,UNI-USDC",
        "DEFAULT_QUOTE_SIZE_USDC": "20.00",
        "MAX_NOTIONAL_USD": "20.00",
        "PHASE_C_MAX_ORDER_QUOTE": "20.00",
        "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
        "MAX_OPEN_POSITIONS": "5",
        "MAX_NEW_ORDERS_PER_CYCLE": "2",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "2",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "5",
        "AUTONOMOUS_MAX_OPEN_ORDERS": "5",
        "ENABLE_LIVE_EXIT_ORDERS": "false",
        "AUTONOMOUS_ALLOW_EXITS": "false",
        "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "false",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "true",
        "REPLICATION_ENABLED": "false",
        "LEARNING_TO_EXECUTION_READY": "false",
        "LEARNING_TO_EXECUTION_ALLOWED": "false",
        "LIVE_LEARNING_ALLOWED": "false",
        "PARAMETER_CHANGE_ALLOWED": "false",
        "MARKET_ORDER_ENABLED": "false",
    }
    values.update(overrides)
    return "\n".join(f"{key}={value}" for key, value in values.items()) + "\n"


def _root(root: Path, *, phase_c_ready: bool = False, fresh_blockers: bool = True) -> None:
    _write_json(root / "state/open_orders.json", {})
    _write_json(root / "state/positions.json", {})
    _write_json(
        root / "reports/d6/full-bot-failure-determination-matrix-20260610.json",
        {
            "summary": {
                "any_ticker_phase_c_ready_now": phase_c_ready,
                "phase_c_ready_tickers": ["XRP-USDC"] if phase_c_ready else [],
                "all_p0_items": [],
                "top_all_ticker_fresh_judge_candidates": ["XRP-USDC"] if fresh_blockers else [],
                "top_all_ticker_deterministic_risk_candidates": ["XRP-USDC"] if fresh_blockers else [],
                "top_all_ticker_refresh_candidates": [] if phase_c_ready else ["XRP-USDC"],
            }
        },
    )
    _write_json(
        root / "reports/d6/full-bot-workflow-completeness-audit-20260610.json",
        {
            "readiness_verdict": "ready_for_ack_gated_maker_buy_live_submit" if phase_c_ready else "blocked_by_missing_fresh_judge_and_risk",
            "any_ticker_phase_c_ready_now": phase_c_ready,
            "phase_c_ready_tickers_now": ["XRP-USDC"] if phase_c_ready else [],
        },
    )
    _write_json(root / "reports/d6/full-bot-maker-buy-live-adapter-20260610.json", {"blockers": []})
    _write_json(root / "reports/d6/full-bot-near-miss-phase-c-review-20260610.json", {"blockers": []})


def test_no_env_mutation_no_bot_start_no_live_submit_by_default(tmp_path: Path) -> None:
    _root(tmp_path)
    env_path = tmp_path / ".env"
    env_path.write_text(_env(), encoding="utf-8")
    before = env_path.read_text(encoding="utf-8")

    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    assert env_path.read_text(encoding="utf-8") == before
    assert report["env_mutation_performed"] is False
    assert report["bot_start_attempted"] is False
    assert report["live_order_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["replication_enabled"] is False
    assert report["replication_publish_allowed"] is False
    assert report["follower_lifecycle_enabled"] is False


def test_missing_phase_c_ready_candidate_blocks_start(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=False, fresh_blockers=False)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    assert report["classification"] == "blocked_by_missing_fresh_candidate_refresh"
    assert report["full_autonomous_start_allowed_now"] is False
    assert "missing_phase_c_ready_candidate" in report["p1_live_start_blockers"]


def test_missing_fresh_judge_and_risk_blocks_start(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=False, fresh_blockers=True)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    assert report["classification"] == "blocked_by_missing_fresh_judge_and_risk"
    assert "missing_fresh_phase_c_buy_judge_approval" in report["p1_live_start_blockers"]
    assert "missing_deterministic_live_risk_approval" in report["p1_live_start_blockers"]


def test_exact_ack_alone_is_insufficient_without_phase_c_ready_candidate(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=False, fresh_blockers=True)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path, ack=EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK)

    assert report["ack_boundaries"]["exact_ack_present"] is True
    assert report["ack_boundaries"]["ack_alone_is_insufficient"] is True
    assert report["first_real_maker_buy_live_submit_allowed_now"] is False
    assert report["replication_enabled"] is False
    assert report["replication_publish_allowed"] is False


def test_sell_market_replication_learning_enabled_block_start(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=True, fresh_blockers=False)
    (tmp_path / ".env").write_text(
        _env(
            ENABLE_LIVE_EXIT_ORDERS="true",
            MARKET_ORDER_ENABLED="true",
            REPLICATION_ENABLED="true",
            LEARNING_TO_EXECUTION_READY="true",
        ),
        encoding="utf-8",
    )
    report = build_full_live_parameter_readiness_gate(root=tmp_path, ack=EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK)

    assert report["classification"] == "unsafe_to_start"
    assert "enable_live_exit_orders_enabled" in report["p0_safety_gaps"]
    assert "market_order_enabled_enabled" in report["p0_safety_gaps"]
    assert "replication_enabled_enabled" in report["p0_safety_gaps"]
    assert "learning_to_execution_ready_enabled" in report["p0_safety_gaps"]
    assert report["replication_enabled"] is True
    assert report["replication_publish_allowed"] is False


def test_safe_recommended_values_and_process_local_recommendation(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=False, fresh_blockers=True)
    (tmp_path / ".env").write_text(
        _env(ALLOWED_TICKERS="BTC-USDC", PHASE_C_MAX_ORDER_QUOTE="25.00", PHASE_C_MAX_NEW_ORDERS_PER_CYCLE="1"),
        encoding="utf-8",
    )
    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    mismatches = {row["key"]: row for row in report["env_mismatches"]}
    assert mismatches["ALLOWED_TICKERS"]["classification"] == "too_restrictive"
    assert mismatches["PHASE_C_MAX_ORDER_QUOTE"]["classification"] == "too_permissive"
    assert mismatches["PHASE_C_MAX_NEW_ORDERS_PER_CYCLE"]["classification"] == "too_restrictive"
    assert report["recommended_env_values"]["PHASE_C_MAX_ORDER_QUOTE"] == "20.00"
    assert report["values_allowed_process_local_only"]["PHASE_C_MAX_ORDER_QUOTE"] == "20.00"


def test_permanent_env_patch_and_full_start_not_emitted_unless_ready(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=False, fresh_blockers=True)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    assert report["exact_env_patch_if_ready"] == ""
    assert report["exact_full_start_command_if_ready"].startswith("DO NOT RUN NOW")
    assert report["exact_actual_submit_command_if_ready"].startswith("DO NOT RUN NOW")


def test_ready_phase_c_with_ack_emits_actual_submit_but_not_full_start_if_env_mismatch(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=True, fresh_blockers=False)
    (tmp_path / ".env").write_text(_env(PHASE_C_MAX_ORDER_QUOTE="25.00"), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path, ack=EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK)

    assert report["classification"] == "blocked_by_env_mismatch"
    assert report["first_real_maker_buy_live_submit_allowed_now"] is False
    assert report["full_autonomous_start_allowed_now"] is False
    assert report["exact_full_start_command_if_ready"].startswith("DO NOT RUN NOW")


def test_ready_phase_c_clean_env_with_ack_allows_ack_gated_submit_command(tmp_path: Path) -> None:
    _root(tmp_path, phase_c_ready=True, fresh_blockers=False)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path, ack=EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK)

    assert report["classification"] == "ready_for_ack_gated_maker_buy_actual_submit"
    assert report["first_real_maker_buy_live_submit_allowed_now"] is True
    assert "tools/build_full_bot_maker_buy_live_adapter_report.py --actual-submit" in report["exact_actual_submit_command_if_ready"]
    assert "run_trader_loop.py" in report["exact_full_start_command_if_ready"]


def test_state_hashes_unchanged(tmp_path: Path) -> None:
    _root(tmp_path)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    before_open = _sha(tmp_path / "state/open_orders.json")
    before_positions = _sha(tmp_path / "state/positions.json")

    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    assert before_open == _sha(tmp_path / "state/open_orders.json")
    assert before_positions == _sha(tmp_path / "state/positions.json")
    assert report["state_hashes"]["unchanged"] is True
    assert report["state_hashes"]["before"] == report["state_hashes"]["after"]


def test_report_only_output_paths_are_under_reports_d6(tmp_path: Path) -> None:
    _root(tmp_path)
    (tmp_path / ".env").write_text(_env(), encoding="utf-8")
    report = build_full_live_parameter_readiness_gate(root=tmp_path)

    assert report["report_only"] is True
    assert report["exact_preview_command"].count("reports/d6/") >= 5
