from __future__ import annotations

import json
from pathlib import Path

from tools.run_repair_sprint_status import (
    OPERATOR_CHECKLIST,
    build_repair_backlog,
    build_stale_lock_plan,
    build_status,
    write_reports,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")


def _seed_reports(root: Path) -> None:
    _write_json(
        root / "reports/audits/position-risk-reconstruction-preview-latest.json",
        {
            "runtime": {
                "service_active": False,
                "run_trader_loop_process_found": False,
                "lock_pid": "1627274",
                "stale_lock_likely": True,
            },
            "summary": {
                "open_positions": ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"],
                "live_d2_d3_allowed_now": False,
                "reason_live_d2_d3_blocked": "position_risk_incomplete",
            },
        },
    )
    _write_json(
        root / "reports/audits/reconstructed-d2-d3-exit-preview-latest.json",
        {"summary": {"positions_with_current_stop_breach": ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]}},
    )
    _write_json(
        root / "reports/audits/position-risk-operator-decision-latest.json",
        {"answers": {"order_fill_evidence": "post-only maker fill evidence"}},
    )
    _write_json(
        root / "reports/audits/entry-order-type-and-orderbook-usage-audit-latest.json",
        {"summary": {"current_guard_blocks_replay": True}},
    )
    _write_json(root / "reports/audits/p0-live-entry-guard-patch-latest.json", {"guard": "wait blocked"})
    _write_json(
        root / "reports/audits/market-order-entry-guard-patch-latest.json",
        {"market_order_entry": "blocked"},
    )
    _write_json(
        root / "reports/audits/open-orders-and-positions-reconciliation-preview-latest.json",
        {"reconciliation_preview_source": {"open_orders_current": 0, "open_positions_current": 4}},
    )


def test_stale_lock_plan_is_preview_only_and_removes_nothing(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    plan = build_stale_lock_plan(root=tmp_path)

    assert plan["lock_path"] == "state/run_trader_loop.lock"
    assert plan["lock_pid"] == "1627274"
    assert plan["service_active"] is False
    assert plan["process_exists"] is False
    assert plan["safe_to_remove_after_operator_ack"] is True
    assert plan["command_preview"] == "rm -f /root/apps/Crypto/coinbase_bot/state/run_trader_loop.lock"
    assert plan["do_not_execute_now"] is True
    assert plan["lock_removed"] is False


def test_status_blocks_restart_while_positions_are_risk_incomplete(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    status = build_status(root=tmp_path)

    assert status["service_active"] is False
    assert status["stale_lock_likely"] is True
    assert status["open_orders"] == 0
    assert status["open_positions"] == 4
    assert status["p0_entry_guard_fixed_on_disk"] is True
    assert status["p0_entry_guard_runtime_loaded"] is False
    assert status["position_risk_completion_done"] is False
    assert status["controlled_close_preview_ready"] is True
    assert status["safe_to_restart"] is False
    assert status["next_operator_action"] == "review controlled-close ACK plan"
    assert status["operator_checklist"] == OPERATOR_CHECKLIST
    assert status["lock_removed"] is False
    assert status["service_restart_attempted"] is False


def test_repair_backlog_has_concrete_p0_items(tmp_path: Path) -> None:
    _seed_reports(tmp_path)

    backlog = build_repair_backlog(root=tmp_path)

    assert backlog["repair_sprint_status"] == "in_progress"
    assert backlog["do_not_run_bot_yet"] is True
    assert [item["id"] for item in backlog["p0_items"]] == ["P0-001", "P0-002"]
    assert backlog["p0_items"][0]["fix_now"] is True
    assert "tools/prepare_risk_incomplete_position_action.py" in backlog["p0_items"][0]["files_to_change"]
    assert "tools/run_repair_sprint_status.py" in backlog["p0_items"][1]["files_to_change"]


def test_write_reports_writes_backlog_status_and_stale_lock_plan_only(tmp_path: Path) -> None:
    _seed_reports(tmp_path)
    state_path = tmp_path / "state/run_trader_loop.lock"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text("1627274\n", encoding="utf-8")
    before_lock = state_path.read_text(encoding="utf-8")

    written = write_reports(root=tmp_path)

    assert state_path.read_text(encoding="utf-8") == before_lock
    assert written == {
        "backlog": "reports/audits/repair-sprint-backlog-latest.json",
        "stale_lock_plan": "reports/audits/stale-lock-operator-plan-latest.json",
        "status": "reports/audits/repair-sprint-status-latest.json",
    }
    for relative in written.values():
        assert (tmp_path / relative).exists()
    stale_lock = json.loads((tmp_path / written["stale_lock_plan"]).read_text(encoding="utf-8"))
    status = json.loads((tmp_path / written["status"]).read_text(encoding="utf-8"))
    assert stale_lock["lock_removed"] is False
    assert status["safe_to_restart"] is False
