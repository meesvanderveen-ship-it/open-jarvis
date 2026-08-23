from __future__ import annotations

import json
from pathlib import Path

from tools.replay_live_entry_guard_incidents import TARGET_INCIDENTS, replay_incidents


RULES = {
    "product_id": "BTC-USDC",
    "price_increment": "0.01",
    "base_increment": "0.00000001",
    "quote_increment": "0.01",
    "quote_min_size": "1.00",
}


def _incident_row(ticker: str, timestamp: str) -> dict:
    return {
        "generated_at": timestamp,
        "ticker": ticker,
        "live_order_submitted": True,
        "risk_snapshot": {
            "quote_size": "20.00",
            "limit_price": "100.00",
            "product_rules": RULES,
            "orderbook_entry_preview": {
                "entry_level": "100.00",
                "invalidation_level": "98.00",
                "target_levels": ["104.00"],
                "spread_pct": "0.001",
                "best_bid": "99.99",
                "best_ask": "100.01",
                "current_mid": "100.00",
            },
        },
        "guard_result": {
            "candidate_summary": {
                "judge_decision": "wait",
                "judge_side": "NONE",
                "plan_action": "prepare_resting_limit_entry",
                "pending_intent_trigger_ready": False,
                "pending_intent_status": "waiting",
                "orderbook_freshness_status": "fresh",
            },
            "config": {
                "phase_c_allowed_tickers": [ticker],
                "phase_c_disable_exit_limit_orders": True,
            },
        },
        "submit_result": {
            "payload": {
                "size_quote_requested": "20.00",
                "limit_price": "100.00",
                "product_rules_used": RULES,
            }
        },
    }


def test_historical_wait_resting_incidents_replay_as_blocked(tmp_path: Path):
    log_path = tmp_path / "logs" / "phase_c_live_submit.jsonl"
    log_path.parent.mkdir(parents=True)
    rows = [_incident_row(item["ticker"], item["timestamp"]) for item in TARGET_INCIDENTS]
    log_path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")

    report = replay_incidents(root=tmp_path)

    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["all_historical_submitted_incidents_blocked_now"] is True
    assert [row["ticker"] for row in report["results"]] == ["ETH-USDC", "AVAX-USDC", "SOL-USDC", "ADA-USDC"]
    assert all(row["current_guard_result"] == "blocked" for row in report["results"])
    assert all(row["block_reason"] == "blocked_wait_decision_cannot_live_submit" for row in report["results"])
    assert all(row["would_submit_now"] is False for row in report["results"])
