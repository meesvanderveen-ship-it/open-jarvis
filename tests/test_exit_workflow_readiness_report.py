from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_exit_workflow_readiness_report import (  # noqa: E402
    PHASE,
    build_exit_workflow_readiness_report,
    build_synthetic_safety_matrix,
    render_exit_workflow_readiness_markdown,
)
from tools.build_exit_workflow_readiness_report import main  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    _write(tmp_path / "state/open_orders.json", '{"orders": {}}\n')
    _write(tmp_path / "state/positions.json", '{"BTC-USDC": {"position_size_base": "0"}}\n')
    _write(
        tmp_path / "bot/phase_d2_position_executor.py",
        "position_executor_plan_ready_no_live_exit_submit\n"
        "is_d2_manageable_open_position\n"
        "build_d2_plan_fingerprint plan_fingerprint\n"
        "build_fee_cost_model expected_net_edge_pct\n"
        "base_increment min_order_quote _quantize_down\n"
        "persist_plan\n",
    )
    _write(
        tmp_path / "bot/phase_d3_controlled_exit_pilot.py",
        "preview_only_submit_live_false ONE_SHOT_ACTUAL_EXIT_SUBMIT_ACK D3_ACK _baseline_sell_flags_safe\n"
        "d3_pilot_replication_enabled d3_pilot_open_d3_exit_order_exists sell_base_exceeds\n",
    )
    _write(
        tmp_path / "bot/phase_d3_controlled_live_exits.py",
        "assert_live_exit_allowed LiveExitBlockedError\n",
    )
    _write(
        tmp_path / "bot/phase_d3_reservation_governance.py",
        "duplicate_labels_detected duplicate_actions_detected available_base_after_reservations reserved_base_open_exit_orders base_increment min_order_quote\n",
    )
    _write(tmp_path / "bot/live_exit_gate.py", "assert_live_exit_allowed\n")
    _write(tmp_path / "bot/phase_d3_live_exit_reconciliation.py", "")
    _write(tmp_path / "bot/phase_d3_open_exit_lifecycle_manager.py", "")
    _write(
        tmp_path / "bot/phase_d4_controlled_cancel_replace.py",
        "preview_reprice_candidate requires_future_ack D4_CONTROLLED_CANCEL_REPLACE_ACK "
        "evaluate_d4_controlled_replacement_submit_allowed no_live_action cancel_replace_allowed\n",
    )
    _write(tmp_path / "bot/phase_d4_cancel_replace_planner.py", "")
    _write(tmp_path / "bot/phase_d4_trailing_preview.py", "trailing preview\n")
    _write(
        tmp_path / "bot/phase_d5_execution_metrics.py",
        "fee_bps_estimate fee_quote slippage_vs_decision_mid_pct slippage_vs_best_bid_or_ask_pct "
        "no_fill_duration_seconds cancel_replace_outcome partial_lifecycle_without_terminal_not_training_eligible "
        "learning_to_execution_allowed False D5_LEARNING_TO_EXECUTION_REQUIRES_SEPARATE_OPERATOR_APPROVAL_AND_ACK\n",
    )
    _write(tmp_path / "bot/phase_d6_d5_evidence_adapter.py", "D5 evidence adapter\n")
    for rel in [
        "tests/test_phase_d2_position_executor.py",
        "tests/test_phase_d3_controlled_exit_pilot.py",
        "tests/test_phase_d3_controlled_live_exits.py",
        "tests/test_phase_d3_reservation_governance.py",
        "tests/test_phase_d4_controlled_cancel_replace.py",
        "tests/test_phase_d4_trailing_preview.py",
        "tests/test_phase_d5_execution_metrics.py",
    ]:
        _write(tmp_path / rel, "")
    (tmp_path / "reports/d6").mkdir(parents=True)
    return tmp_path


def test_synthetic_safety_matrix_reports_exit_risks() -> None:
    matrix = build_synthetic_safety_matrix()

    assert matrix["d3_preview_submit_live_false"]["passed"] is True
    assert matrix["d3_live_submit_requires_flags_ack"]["passed"] is True
    assert matrix["live_exits_disabled_by_default"]["live_exit_allowed_now"] is False
    assert matrix["duplicate_exit_detected"]["passed"] is True
    assert matrix["no_oversell_detected"]["passed"] is True
    assert matrix["base_reservation_detected"]["passed"] is True
    assert matrix["d4_cancel_replace_not_live_default"]["cancel_replace_allowed_now"] is False
    assert matrix["d5_metrics_evidence_only"]["learning_to_execution_ready"] is False
    assert matrix["follower_sell_false"]["follower_sell_ready"] is False


def test_report_flags_master_and_follower_sell_not_ready(tmp_path: Path) -> None:
    report = build_exit_workflow_readiness_report(root=_root(tmp_path))

    assert report["phase"] == PHASE
    assert report["exit_workflow_readiness_report_ready"] is True
    assert report["master_live_exit_ready"] is False
    assert report["follower_sell_ready"] is False
    assert report["follower_ready_for_live"] is False
    assert report["live_exit_allowed_now"] if "live_exit_allowed_now" in report else report["readiness_summary"]["live_exit_allowed_now"] is False
    assert report["d2_position_executor"]["readiness"]["d2_implies_live_sell_permission"] is False
    assert report["d3_controlled_exits"]["readiness"]["preview_distinct_from_live_submit"] is True
    assert report["d3_controlled_exits"]["readiness"]["exact_ack_required"] is True
    assert report["d4_cancel_replace_trailing"]["readiness"]["observe_preview_only_by_default"] is True
    assert report["d5_execution_evidence"]["readiness"]["evidence_only"] is True
    assert "follower_receiver_API_missing_or_unaudited" in report["readiness_summary"]["follower_sell_blockers"]


def test_current_open_d3_exit_is_reported_from_state(tmp_path: Path) -> None:
    root = _root(tmp_path)
    _write(
        root / "state/open_orders.json",
        json.dumps(
            {
                "orders": {
                    "o1": {
                        "ticker": "BTC-USDC",
                        "client_order_id": "phased3-BTCUSDC-TP1-test",
                        "side": "SELL",
                        "status": "open",
                        "phase": "D3_controlled_live_reduce_only_exits",
                    }
                }
            }
        ),
    )

    report = build_exit_workflow_readiness_report(root=root)

    assert report["current_order_state"]["open_orders"] == 1
    assert report["current_order_state"]["open_d3_exit"] == 1
    assert "open_d3_exit_present_requires_lifecycle_review" in report["readiness_summary"]["master_live_exit_blockers"]


def test_markdown_and_cli_write_reports_without_state_mutation(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_exit_workflow_readiness_report(root=root)
    markdown = render_exit_workflow_readiness_markdown(report)
    assert "# Exit Workflow Readiness Report" in markdown
    assert "Master SELL Blockers" in markdown

    monkeypatch.chdir(root)
    rc = main(
        [
            "--json-out",
            "reports/d6/exit-workflow-readiness-report.json",
            "--markdown-out",
            "reports/d6/exit-workflow-readiness-report.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/exit-workflow-readiness-report.json").read_text(encoding="utf-8"))
    assert payload["phase"] == PHASE
    assert payload["master_live_exit_ready"] is False
    assert "Exit Workflow Readiness Report" in (root / "reports/d6/exit-workflow-readiness-report.md").read_text(encoding="utf-8")
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
