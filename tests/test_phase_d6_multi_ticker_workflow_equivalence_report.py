from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_multi_ticker_backlearning_readiness import build_multi_ticker_workflow_equivalence_report


def test_workflow_equivalence_keeps_non_btc_tickers_blocked_until_evidence_matches(tmp_path: Path):
    events = tmp_path / "logs/order_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        json.dumps({"event_type": "d3_live_exit_reconciled", "order": {"ticker": "BTC-USDC", "side": "SELL", "mode": "live", "live_order_submitted": True}})
        + "\n",
        encoding="utf-8",
    )
    matrix = {
        "rows": [
            {
                "ticker": "BTC-USDC",
                "required_timeframes_missing": ["1H", "4H"],
                "dataset_quality_present": False,
                "baseline_backtest_possible": True,
                "fill_realism_evidence_present": True,
            },
            {
                "ticker": "ETH-USDC",
                "required_timeframes_missing": ["1H", "4H", "1D"],
                "dataset_quality_present": False,
                "baseline_backtest_possible": False,
                "fill_realism_evidence_present": False,
            },
        ]
    }
    report = build_multi_ticker_workflow_equivalence_report(readiness_matrix=matrix, order_events_path=events)
    rows = {row["ticker"]: row for row in report["rows"]}

    assert rows["BTC-USDC"]["lifecycle_evidence"] is True
    assert rows["ETH-USDC"]["lifecycle_evidence"] is False
    assert "missing_live_lifecycle_evidence" in rows["ETH-USDC"]["blockers_before_ticker_can_join_24h_live_test"]
    assert rows["ETH-USDC"]["readiness_for_future_controlled_live_pilot"] == "blocked_until_equivalent_evidence"
    assert report["no_live_action"] is True
