from __future__ import annotations

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.phase_core_lifecycle_evidence_gap_report import (  # noqa: E402
    PHASE,
    build_core_lifecycle_evidence_gap_report,
    render_core_lifecycle_evidence_gap_markdown,
)
from tools.build_core_lifecycle_evidence_gap_report import main  # noqa: E402


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _root(tmp_path: Path) -> Path:
    _write(tmp_path / "state/open_orders.json", json.dumps({"orders": {}}))
    _write(
        tmp_path / "state/positions.json",
        json.dumps(
            {
                "BTC-USDC": {
                    "position_size_base": "0",
                    "bot_managed_base": "0",
                    "reserved_base_open_exit_orders": "0.00006490",
                    "monitoring_enabled": False,
                }
            }
        ),
    )
    for rel in (
        "bot/phase_c43_autonomous_entry_live.py",
        "bot/phase_c43_lifecycle_orchestrator.py",
        "bot/phase_c44_poll_to_apply_closeout.py",
        "bot/phase_c45_live_fill_pilot.py",
        "bot/phase_d1_exit_orderbook_scaffold.py",
        "bot/phase_d2_position_executor.py",
        "bot/phase_d3_controlled_live_exits.py",
        "bot/phase_d3_live_exit_reconciliation.py",
        "bot/phase_d4_trailing_preview.py",
        "bot/phase_d4_cancel_replace_planner.py",
        "bot/phase_d5_execution_metrics.py",
        "bot/phase_d6_d5_evidence_adapter.py",
    ):
        _write(tmp_path / rel, "# fixture\n")
    _write(tmp_path / "tests/test_phase_c45_live_fill_pilot.py", "def test_fill_apply_ack_no_coinbase(): pass\n")
    _write(tmp_path / "tests/test_phase_c44_poll_to_apply_closeout.py", "def test_cancel_rejected_apply_ack(): pass\n")
    _write(tmp_path / "tests/test_phase_d3_live_exit_reconciliation.py", "def test_partial_filled_cancelled_duplicate_reservation_ack(): pass\n")
    _write(tmp_path / "tests/test_phase_d4_trailing_preview.py", "def test_cancel_replace_trailing_ack_reservation(): pass\n")
    _write(tmp_path / "tests/test_phase_d5_execution_metrics.py", "def test_latency_slippage_fill_cancel_replace_learning_to_execution(): pass\n")
    (tmp_path / "reports/d6").mkdir(parents=True)
    return tmp_path


def test_core_lifecycle_gap_report_maps_workflow_rows_and_state_hashes(tmp_path: Path) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")

    report = build_core_lifecycle_evidence_gap_report(root=root)

    assert report["phase"] == PHASE
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["current_state_evidence"]["open_orders"]["open_orders"] == 0
    assert report["current_state_evidence"]["open_orders"]["open_d3_exit"] == 0
    areas = {row["area"]: row for row in report["workflow_rows"]}
    assert areas["C4_entry_order_lifecycle"]["status"] == "partial_btc_proven"
    assert areas["D1_fill_to_position_transition"]["status"] == "partial_distributed"
    assert areas["D3_controlled_exit_submit_and_reconcile"]["blocks_full_workflow"] is True
    assert "C4_entry_order_lifecycle" in report["summary"]["btc_24h_review_required_areas"]
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions


def test_core_lifecycle_gap_markdown_contains_required_sections(tmp_path: Path) -> None:
    report = build_core_lifecycle_evidence_gap_report(root=_root(tmp_path))
    markdown = render_core_lifecycle_evidence_gap_markdown(report)

    assert "# Core Lifecycle Evidence Gap Report" in markdown
    assert "## Summary" in markdown
    assert "## Workflow Rows" in markdown
    assert "### C4_entry_order_lifecycle" in markdown
    assert "## Recommended Next Route" in markdown


def test_core_lifecycle_gap_cli_writes_reports_d6_only_and_no_state(tmp_path: Path, monkeypatch) -> None:
    root = _root(tmp_path)
    before_open = (root / "state/open_orders.json").read_text(encoding="utf-8")
    before_positions = (root / "state/positions.json").read_text(encoding="utf-8")
    monkeypatch.chdir(root)

    rc = main(
        [
            "--json-out",
            "reports/d6/core-lifecycle-gap.json",
            "--markdown-out",
            "reports/d6/core-lifecycle-gap.md",
        ]
    )

    assert rc == 0
    payload = json.loads((root / "reports/d6/core-lifecycle-gap.json").read_text(encoding="utf-8"))
    markdown = (root / "reports/d6/core-lifecycle-gap.md").read_text(encoding="utf-8")
    assert payload["phase"] == PHASE
    assert "Core Lifecycle Evidence Gap Report" in markdown
    assert (root / "state/open_orders.json").read_text(encoding="utf-8") == before_open
    assert (root / "state/positions.json").read_text(encoding="utf-8") == before_positions
