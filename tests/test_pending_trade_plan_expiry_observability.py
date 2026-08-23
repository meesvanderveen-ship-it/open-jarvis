from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from bot.pending_trade_plans import PendingTradePlanStore, build_pending_plan_observability


def _plan(plan_id: str, ticker: str, status: str, hours: int = 6):
    now = datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc)
    return {
        "plan_id": plan_id,
        "ticker": ticker,
        "status": status,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": (now + timedelta(hours=hours)).isoformat(),
        "confidence": 72,
        "trade_plan": {
            "plan_action": "prepare_breakout",
            "setup_type": "breakout_retest",
            "entry_zone_low": "0.274",
            "entry_zone_high": "0.281",
            "trigger": "retest with volume confirmation",
            "stop_loss": "0.263",
            "do_not_chase_above": "0.291",
            "invalidation": "4h close below reclaimed support",
        },
        "evaluation_history": [
            {
                "evaluated_at": now.isoformat(),
                "status": status,
                "reason": f"reason_{status}",
                "current_price": "0.278",
            }
        ],
        "safety_policy": "monitor only",
    }


def test_build_pending_plan_observability_counts_and_sections():
    plans = [
        _plan("p1", "ADA-USDC", "trigger_ready"),
        _plan("p2", "SOL-USDC", "waiting"),
        _plan("p3", "ETH-USDC", "expired"),
    ]
    summary = build_pending_plan_observability(
        plans,
        now=datetime(2026, 5, 13, 12, 0, tzinfo=timezone.utc),
    )

    assert summary["total_plans"] == 3
    assert summary["trigger_ready_count"] == 1
    assert summary["active_count"] == 1
    assert summary["final_count"] == 1
    assert summary["status_counts"]["trigger_ready"] == 1
    assert summary["ticker_counts"]["ADA-USDC"] == 1
    assert summary["actionable_trigger_ready"][0]["ticker"] == "ADA-USDC"
    assert summary["actionable_trigger_ready"][0]["requires_fresh_judge_and_risk"] is True
    assert "never authorize execution" in summary["safety_policy"]


def test_store_observability_summary_reads_state(tmp_path: Path):
    state_path = tmp_path / "pending_trade_plans.json"
    payload = {"updated_at": "2026-05-13T12:00:00+00:00", "plans": [_plan("p1", "ADA-USDC", "waiting")]}
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    store = PendingTradePlanStore(path=state_path)
    summary = store.observability_summary()

    assert summary["total_plans"] == 1
    assert summary["active_or_waiting"][0]["plan_id"] == "p1"


def test_store_observability_can_hide_final_statuses(tmp_path: Path):
    state_path = tmp_path / "pending_trade_plans.json"
    payload = {"plans": [_plan("p1", "ADA-USDC", "waiting"), _plan("p2", "SOL-USDC", "expired")]}
    state_path.write_text(json.dumps(payload), encoding="utf-8")

    store = PendingTradePlanStore(path=state_path)
    summary = store.observability_summary(include_final=False)

    assert summary["total_plans"] == 1
    assert summary["status_counts"] == {"waiting": 1}
