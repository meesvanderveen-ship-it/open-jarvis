from __future__ import annotations

import json
from pathlib import Path

from tools.show_full_pipeline_health import (
    OPERATOR_CHECKLIST,
    build_full_pipeline_health_report,
    write_full_pipeline_health_report,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_reports(root: Path) -> None:
    _write_json(
        root / "reports/audits/repair-sprint-status-latest.json",
        {
            "service_active": False,
            "stale_lock_likely": True,
            "open_orders": 0,
            "open_positions": 4,
            "position_risk_completion_done": False,
            "safe_to_restart": False,
            "next_operator_action": "review controlled-close ACK plan",
        },
    )
    _write_json(
        root / "reports/audits/risk-incomplete-controlled-close-prep-latest.json",
        {
            "status": "controlled_close_command_preview_ready",
            "ack_required": "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619",
            "will_not_run_now": True,
            "positions_to_close": ["ETH-USDC", "AVAX-USDC", "SOL-USDC"],
            "positions_to_review": ["ADA-USDC"],
        },
    )
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "runtime": {"service_active": False, "stale_lock_likely": True},
            "summary": {
                "all_local_positions_match_fill_evidence": True,
                "all_entry_fills_proven_post_only_limit_maker": True,
                "open_positions": ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"],
            },
        },
    )
    _write_json(
        root / "reports/audits/position-risk-operator-decision-latest.json",
        {"operator_action": "do not run bot yet"},
    )
    _write_json(
        root / "reports/audits/entry-order-type-and-orderbook-usage-audit-latest.json",
        {"summary": {"current_guard_blocks_replay": True}},
    )


def test_full_pipeline_health_report_uses_existing_reports_and_stays_red(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    report = build_full_pipeline_health_report(root=tmp_path)

    assert report["pipeline_health"] == "red"
    assert report["safe_to_restart"] is False
    assert report["service_active"] is False
    assert report["stale_lock_likely"] is True
    assert report["open_orders"] == 0
    assert report["open_positions"] == 4
    assert report["entry_pipeline_contract"] == "pass"
    assert report["fill_to_position_contract"] == "pass"
    assert report["exit_pipeline_contract"] == "blocked_by_position_risk_incomplete"
    assert report["controlled_close_plan_ready"] is True
    assert report["operator_action"] == "review controlled-close ACK plan"
    assert report["terminal_operator_status"] == "do_not_run_bot_yet"
    assert report["operator_checklist"] == OPERATOR_CHECKLIST
    assert "risk_incomplete_positions" in report["blockers"]


def test_full_pipeline_health_blocks_market_flags_explicitly(tmp_path: Path, monkeypatch) -> None:
    _seed_reports(tmp_path)
    monkeypatch.setenv("MARKET_ORDER_ENABLED", "true")

    report = build_full_pipeline_health_report(root=tmp_path)

    assert "market_order_flags_enabled_forbidden_orderbook_workflow" in report["blockers"]
    assert "MARKET_ORDER_ENABLED" in report["market_order_flags_enabled"]


def test_full_pipeline_health_write_report_does_not_touch_state(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    state_path = tmp_path / "state/positions.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text('{"BTC-USDC":{"status":"open"}}\n', encoding="utf-8")
    before = state_path.read_text(encoding="utf-8")

    report = build_full_pipeline_health_report(root=tmp_path)
    write_full_pipeline_health_report(report, root=tmp_path)

    assert state_path.read_text(encoding="utf-8") == before
    assert (tmp_path / "reports/audits/full-pipeline-health-latest.json").exists()
    assert (tmp_path / "reports/audits/full-pipeline-health-latest.md").exists()
