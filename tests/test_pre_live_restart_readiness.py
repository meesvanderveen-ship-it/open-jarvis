from __future__ import annotations

import json
from pathlib import Path

from tools.show_pre_live_restart_readiness import (
    REQUIRED_OPERATOR_ACTIONS,
    build_pre_live_restart_readiness,
    write_pre_live_restart_readiness,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_reports(root: Path, *, risk_incomplete: bool = True, stale_lock: bool = True) -> None:
    open_positions = ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"] if risk_incomplete else []
    _write_json(
        root / "reports/audits/repair-sprint-status-latest.json",
        {
            "service_active": False,
            "stale_lock_likely": stale_lock,
            "open_orders": 0,
            "open_positions": len(open_positions),
            "position_risk_completion_done": not risk_incomplete,
            "safe_to_restart": False,
        },
    )
    _write_json(
        root / "reports/audits/full-pipeline-health-latest.json",
        {
            "pipeline_health": "red",
            "safe_to_restart": False,
            "service_active": False,
            "stale_lock_likely": stale_lock,
            "open_orders": 0,
            "open_positions": len(open_positions),
            "blockers": ["risk_incomplete_positions"] if risk_incomplete else ["runtime_not_safe_to_restart"],
        },
    )
    _write_json(
        root / "reports/audits/risk-incomplete-controlled-close-prep-latest.json",
        {
            "status": "controlled_close_command_preview_ready",
            "will_not_run_now": True,
            "positions_to_close": ["ETH-USDC", "AVAX-USDC", "SOL-USDC"],
            "positions_to_review": ["ADA-USDC"],
        },
    )
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "runtime": {"service_active": False, "stale_lock_likely": stale_lock},
            "summary": {
                "live_d2_d3_allowed_now": not risk_incomplete,
                "open_positions": open_positions,
            },
        },
    )
    _write_json(
        root / "reports/audits/stale-lock-operator-plan-latest.json",
        {
            "safe_to_remove_after_operator_ack": stale_lock,
            "lock_removed": False,
        },
    )


def _seed_state(root: Path, positions: object, orders: object | None = None) -> None:
    _write_json(root / "state/positions.json", positions)
    _write_json(root / "state/open_orders.json", {"orders": orders or {}})


def test_safe_to_restart_false_with_risk_incomplete_positions(tmp_path: Path) -> None:
    _seed_reports(tmp_path, risk_incomplete=True, stale_lock=False)
    _seed_state(
        tmp_path,
        {
            "ETH-USDC": {"status": "closed"},
            "AVAX-USDC": {"status": "closed"},
            "SOL-USDC": {"status": "closed"},
            "ADA-USDC": {"status": "open", "position_risk_incomplete": True},
        },
    )

    report = build_pre_live_restart_readiness(root=tmp_path)

    assert report["safe_to_restart"] is False
    assert report["reason"] == "risk_incomplete_positions"
    assert report["positions_blocking_restart"] == ["ADA-USDC"]
    assert report["required_operator_actions"] == REQUIRED_OPERATOR_ACTIONS
    assert report["terminal_operator_status"] == "do_not_run_bot_yet"


def test_stale_lock_report_does_not_block_current_state_readiness(tmp_path: Path) -> None:
    _seed_reports(tmp_path, risk_incomplete=False, stale_lock=True)
    _seed_state(
        tmp_path,
        {
            "BTC-USDC": {
                "status": "open",
                "stop_price": "90",
                "invalidation_price": "90",
                "protective_stop_status": "protective_stop_state_complete",
            }
        },
    )

    report = build_pre_live_restart_readiness(root=tmp_path)

    assert report["safe_to_restart"] is True
    assert report["reason"] == "ready"
    assert report["stale_lock_likely"] is False
    assert report["positions_blocking_restart"] == []


def test_safe_to_restart_clears_when_mocked_blockers_are_resolved(tmp_path: Path) -> None:
    _seed_reports(tmp_path, risk_incomplete=False, stale_lock=False)
    _write_json(
        tmp_path / "reports/audits/repair-sprint-status-latest.json",
        {
            "service_active": False,
            "stale_lock_likely": False,
            "open_orders": 0,
            "open_positions": 1,
            "position_risk_completion_done": True,
            "safe_to_restart": True,
        },
    )
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    _write_json(
        tmp_path / "reports/audits/full-pipeline-health-latest.json",
        {
            "pipeline_health": "green",
            "safe_to_restart": True,
            "service_active": False,
            "stale_lock_likely": False,
            "open_orders": 0,
            "open_positions": 1,
            "blockers": [],
        },
    )
    _write_json(
        tmp_path / "state/positions.json",
        {
            "ETH-USDC": {
                "status": "open",
                "position_size_base": "0.1",
                "stop_price": "1900",
                "invalidation_price": "1900",
                "protective_stop_status": "protective_stop_state_complete",
                "position_risk_incomplete": False,
            }
        },
    )

    report = build_pre_live_restart_readiness(root=tmp_path)

    assert report["safe_to_restart"] is True
    assert report["reason"] == "ready"
    assert report["positions_blocking_restart"] == []
    assert report["controlled_close_pending"] is False
    assert report["terminal_operator_status"] == "ready_for_operator_restart"


def test_write_readiness_report_does_not_touch_state(tmp_path: Path) -> None:
    _seed_reports(tmp_path, risk_incomplete=True, stale_lock=True)
    state_path = tmp_path / "state/positions.json"
    _write_json(state_path, {"ETH-USDC": {"status": "open", "position_risk_incomplete": True}})
    _write_json(tmp_path / "state/open_orders.json", {"orders": {}})
    before = state_path.read_text(encoding="utf-8")

    report = build_pre_live_restart_readiness(root=tmp_path)
    write_pre_live_restart_readiness(report, root=tmp_path)

    assert state_path.read_text(encoding="utf-8") == before
    assert (tmp_path / "reports/audits/pre-live-restart-readiness-latest.json").exists()
    assert (tmp_path / "reports/audits/pre-live-restart-readiness-latest.md").exists()
