from __future__ import annotations

import json
from pathlib import Path

from tools.test_paper_order_lifecycle import run_scenarios


def test_diagnostic_lifecycle_writes_execution_outcomes(tmp_path: Path):
    result = run_scenarios(
        scenarios=["buy_fill", "buy_keep", "buy_expire", "buy_invalidate", "sell_fill"],
        state_path=tmp_path / "open_orders.json",
        log_path=tmp_path / "order_events.jsonl",
        outcome_log_path=tmp_path / "execution_outcomes.jsonl",
    )

    assert result["execution_outcomes_written"] == 4
    rows = [json.loads(line) for line in (tmp_path / "execution_outcomes.jsonl").read_text().splitlines()]
    assert len(rows) == 4
    by_client_id = {row["client_order_id"]: row for row in rows}
    assert by_client_id["paper-diagnostic-buy_fill"]["primary_label"] == "good_limit_execution"
    assert by_client_id["paper-diagnostic-buy_expire"]["primary_label"] == "expired_correctly"
    assert by_client_id["paper-diagnostic-buy_invalidate"]["primary_label"] == "avoided_bad_entry"
    assert by_client_id["paper-diagnostic-sell_fill"]["primary_label"] == "good_limit_execution"
    assert "paper-diagnostic-buy_keep" not in by_client_id
