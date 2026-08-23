from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def write_state(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "orders": {
            "paper-diagnostic-buy": {
                "client_order_id": "paper-diagnostic-buy",
                "ticker": "TEST-B5-USDC",
                "side": "BUY",
                "status": "submitted",
                "reason": "phase_b5_diagnostic_cleanup_test",
            },
            "real-paper-order": {
                "client_order_id": "real-paper-order",
                "ticker": "BTC-USDC",
                "side": "BUY",
                "status": "submitted",
                "reason": "non_diagnostic_paper_order",
            },
        }
    }
    path.write_text(json.dumps(data), encoding="utf-8")


def test_cleanup_diagnostic_paper_orders_dry_run_and_confirm_delete(tmp_path: Path) -> None:
    state_path = tmp_path / "open_orders.json"
    backup_dir = tmp_path / "backups"
    write_state(state_path)

    dry = run_tool("tools/cleanup_diagnostic_paper_orders.py", "--path", str(state_path))
    assert dry.returncode == 0, dry.stderr
    assert "dry_run_no_changes_written" in dry.stdout
    assert "diagnostic_orders_matched: 1" in dry.stdout
    still = json.loads(state_path.read_text(encoding="utf-8"))
    assert len(still["orders"]) == 2

    confirmed = run_tool(
        "tools/cleanup_diagnostic_paper_orders.py",
        "--path",
        str(state_path),
        "--backup-dir",
        str(backup_dir),
        "--confirm-delete",
    )
    assert confirmed.returncode == 0, confirmed.stderr
    assert "delete_confirmed" in confirmed.stdout
    cleaned = json.loads(state_path.read_text(encoding="utf-8"))
    assert list(cleaned["orders"].keys()) == ["real-paper-order"]
    assert any(backup_dir.glob("open_orders.before_diagnostic_cleanup_*.json"))


def test_show_phase_b_status_json_direct_run(tmp_path: Path) -> None:
    state_path = tmp_path / "open_orders.json"
    plans_path = tmp_path / "execution_plans.jsonl"
    outcomes_path = tmp_path / "execution_outcomes.jsonl"
    write_state(state_path)
    plans_path.write_text(json.dumps({"ticker": "BTC-USDC", "execution_action": "no_order"}) + "\n", encoding="utf-8")
    outcomes_path.write_text(json.dumps({"ticker": "TEST-B5-USDC", "primary_label": "correct_no_fill", "source": "paper_diagnostic"}) + "\n", encoding="utf-8")

    result = run_tool(
        "tools/show_phase_b_status.py",
        "--open-orders-path",
        str(state_path),
        "--execution-plans-path",
        str(plans_path),
        "--execution-outcomes-path",
        str(outcomes_path),
        "--json",
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["orders"]["total_orders"] == 2
    assert payload["orders"]["diagnostic_order_count"] == 1
    assert payload["execution_plans"]["by_action_sample"]["no_order"] == 1
    assert payload["execution_outcomes"]["diagnostic_rows_in_sample"] == 1
    assert payload["warnings"]


def test_b4_budget_reserved_tool_runs_directly_without_pythonpath() -> None:
    result = run_tool("tools/test_paper_budget_reserved_balances.py")
    assert result.returncode == 0, result.stderr
    assert "Phase-B.4 paper budget/reserved-balance diagnose" in result.stdout
    assert "paper_order_phase_b4_rejected" in result.stdout
    assert "paper_order_budget_skipped" in result.stdout
