from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from bot.pre_live_startup_gate import (
    STARTUP_BLOCK_EXIT_CODE,
    assess_pre_live_startup_gate,
    enforce_pre_live_startup_gate,
    live_workflow_enabled,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _live_cfg(**overrides):
    payload = {
        "execution_mode": "live",
        "enable_full_workflow_live_mode": True,
        "enable_live_entry_orders": True,
        "enable_live_limit_orders": True,
        "enable_phase_c_live_small_limit_orders": True,
        "enable_phase_c_actual_coinbase_submit": True,
        "enable_live_exit_orders": True,
        "autonomous_allow_exits": True,
        "enable_phase_d3_actual_exit_submit": True,
    }
    payload.update(overrides)
    return SimpleNamespace(**payload)


def _seed_red_health(root: Path) -> None:
    _write_json(
        root / "reports/audits/full-pipeline-health-latest.json",
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
        root / "reports/audits/pre-live-restart-readiness-latest.json",
        {
            "safe_to_restart": False,
            "stale_lock_likely": True,
            "positions_blocking_restart": ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"],
            "controlled_close_plan_ready": True,
            "ada_review_done": False,
        },
    )


def _seed_state(root: Path, positions: object, orders: object | None = None) -> None:
    _write_json(root / "state/positions.json", positions)
    _write_json(root / "state/open_orders.json", {"orders": orders or {}})


def test_startup_gate_blocks_live_start_when_pipeline_health_red(tmp_path: Path) -> None:
    _seed_red_health(tmp_path)
    _seed_state(
        tmp_path,
        {
            "ADA-USDC": {
                "status": "open",
                "position_risk_incomplete": True,
                "protective_stop_status": "position_risk_incomplete",
            }
        },
    )

    report = assess_pre_live_startup_gate(_live_cfg(), root=tmp_path)

    assert live_workflow_enabled(_live_cfg()) is True
    assert report["startup_allowed"] is False
    assert report["operator_action"] == "do_not_run_bot_yet"
    assert report["blockers"] == ["risk_incomplete_positions"]


def test_enforce_startup_gate_raises_before_live_start(tmp_path: Path) -> None:
    _seed_red_health(tmp_path)
    _seed_state(tmp_path, {"ADA-USDC": {"status": "open", "position_risk_incomplete": True}})

    with pytest.raises(SystemExit) as exc:
        enforce_pre_live_startup_gate(_live_cfg(), root=tmp_path)

    assert exc.value.code == STARTUP_BLOCK_EXIT_CODE


def test_startup_gate_allows_non_live_diagnostic_context(tmp_path: Path) -> None:
    _seed_red_health(tmp_path)

    report = assess_pre_live_startup_gate(SimpleNamespace(execution_mode="paper"), root=tmp_path)

    assert report["live_workflow_enabled"] is False
    assert report["startup_allowed"] is True
    assert report["state_write_performed"] is False


def test_startup_gate_allows_live_when_health_and_readiness_are_green(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports/audits/full-pipeline-health-latest.json",
        {"pipeline_health": "green", "safe_to_restart": True, "blockers": []},
    )
    _seed_state(
        tmp_path,
        {
            "BTC-USDC": {
                "status": "open",
                "position_risk_incomplete": False,
                "protective_stop_status": "protective_stop_state_complete",
                "stop_price": "90",
                "invalidation_price": "90",
            }
        },
    )
    _write_json(
        tmp_path / "reports/audits/pre-live-restart-readiness-latest.json",
        {
            "safe_to_restart": True,
            "stale_lock_likely": False,
            "positions_blocking_restart": [],
            "controlled_close_pending": False,
            "ada_review_done": True,
        },
    )

    report = assess_pre_live_startup_gate(_live_cfg(), root=tmp_path)

    assert report["startup_allowed"] is True
    assert report["blockers"] == []


def test_startup_gate_preserves_unknown_health_blocker(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "reports/audits/full-pipeline-health-latest.json",
        {
            "pipeline_health": "red",
            "safe_to_restart": False,
            "blockers": ["market_order_flags_enabled_forbidden_orderbook_workflow"],
        },
    )
    _write_json(
        tmp_path / "reports/audits/pre-live-restart-readiness-latest.json",
        {"safe_to_restart": False, "stale_lock_likely": False, "positions_blocking_restart": [], "ada_review_done": True},
    )

    _seed_state(tmp_path, {})

    report = assess_pre_live_startup_gate(
        _live_cfg(market_order_enabled=True, enable_market_orders=True, allow_market_orders=True),
        root=tmp_path,
    )

    assert report["startup_allowed"] is False
    assert report["blockers"] == ["market_order_flags_enabled_forbidden_orderbook_workflow"]
