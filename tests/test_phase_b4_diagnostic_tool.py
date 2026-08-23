from __future__ import annotations

import subprocess
import sys


def test_phase_b4_diagnostic_tool_runs_in_temp_mode():
    result = subprocess.run(
        [sys.executable, "tools/test_paper_budget_reserved_balances.py"],
        cwd=".",
        text=True,
        capture_output=True,
        check=True,
    )
    assert "Phase-B.4 paper budget/reserved-balance diagnose" in result.stdout
    assert '"first_submit": "paper_order_submitted"' in result.stdout
    assert '"duplicate_guard": "paper_order_phase_b4_rejected"' in result.stdout
    assert '"reserved_balance_guard": "paper_order_phase_b4_rejected"' in result.stdout
    assert '"budget_second": "paper_order_budget_skipped"' in result.stdout
