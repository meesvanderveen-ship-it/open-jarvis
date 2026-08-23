from __future__ import annotations

from datetime import datetime, timezone

from tools.build_latest_run_summary import (
    _determine_cycle_anchor,
    _dominant_setup_type,
    _latest_decisions_for_cycle,
    _notable_guards,
    _operator_takeaway,
    _overall_decision,
    _ticker_reason,
)


def test_overall_decision_prioritises_approve_trade():
    assert _overall_decision({"approve_trade": 1, "wait": 7}) == "approve_trade"


def test_overall_decision_falls_back_to_wait():
    assert _overall_decision({"approve_trade": 0, "wait": 8, "reject": 0}) == "wait"


def test_overall_decision_no_decisions_recorded():
    assert _overall_decision({}) == "no_decisions_recorded"


def test_overall_decision_reject_wins_when_dominant():
    assert _overall_decision({"reject": 3, "wait": 1}) == "reject"


def test_determine_cycle_anchor_picks_most_recent():
    live = {
        "last_full_cycle_time": "2026-06-23T16:12:01Z",
        "last_heartbeat_time": "2026-06-23T17:00:00Z",
    }
    cycle_type, anchor = _determine_cycle_anchor(live)
    assert cycle_type == "heartbeat"
    assert anchor == datetime(2026, 6, 23, 17, 0, 0, tzinfo=timezone.utc)


def test_determine_cycle_anchor_unknown_when_missing():
    cycle_type, anchor = _determine_cycle_anchor({})
    assert cycle_type == "unknown"
    assert anchor is None


def test_latest_decisions_for_cycle_filters_outside_window_and_dedupes_by_ticker():
    anchor = datetime(2026, 6, 23, 17, 0, 0, tzinfo=timezone.utc)
    records = [
        {"ticker": "BTC-USDC", "created_at": "2026-06-23T16:50:00Z", "decision": "wait"},
        {"ticker": "BTC-USDC", "created_at": "2026-06-23T16:55:00Z", "decision": "wait"},
        {"ticker": "ETH-USDC", "created_at": "2026-06-23T10:00:00Z", "decision": "wait"},  # too old
    ]
    result = _latest_decisions_for_cycle(records, anchor)
    tickers = {r["ticker"] for r in result}
    assert tickers == {"BTC-USDC"}
    assert len(result) == 1
    assert result[0]["created_at"] == "2026-06-23T16:55:00Z"


def test_dominant_setup_type_majority_vote():
    decisions = [
        {"entry_gate": {"setup_type": "reclaim_reversal"}},
        {"entry_gate": {"setup_type": "reclaim_reversal"}},
        {"trade_plan": {"setup_type": "mean_reversion"}},
    ]
    assert _dominant_setup_type(decisions) == "reclaim_reversal"


def test_dominant_setup_type_unknown_when_no_data():
    assert _dominant_setup_type([]) == "unknown"


def test_notable_guards_reflect_disabled_market_orders_and_no_exposure():
    live = {
        "approved_profile_status": {"hash_valid": True, "loaded": True},
        "replication_status": {"replication_enabled": False},
        "stale_lock_detected": False,
    }
    pipeline = {"market_order_flags_enabled": [], "open_positions": 0, "open_orders": 0}
    guards = _notable_guards(live, pipeline)
    assert "market_orders_disabled" in guards
    assert "open_positions=0" in guards
    assert "approved_profile_valid" in guards
    assert "replication_disabled" in guards


def test_notable_guards_flags_stale_lock():
    live = {"approved_profile_status": {}, "replication_status": {}, "stale_lock_detected": True}
    pipeline = {"market_order_flags_enabled": ["MARKET_ORDER_ENABLED"], "open_positions": 1, "open_orders": 2}
    guards = _notable_guards(live, pipeline)
    assert "market_orders_enabled" in guards
    assert "stale_process_lock_detected" in guards
    assert "approved_profile_not_confirmed" in guards


def test_operator_takeaway_no_exposure_no_setup():
    takeaway = _operator_takeaway("wait", {"open_positions": 0, "open_orders": 0})
    assert "no open exposure" in takeaway


def test_operator_takeaway_approve_trade():
    takeaway = _operator_takeaway("approve_trade", {"open_positions": 0, "open_orders": 0})
    assert "approved" in takeaway.lower()


def test_ticker_reason_prefers_trade_plan_trigger():
    record = {"trade_plan": {"trigger": "close above resistance"}, "entry_gate": {"setup_type": "breakout"}}
    assert _ticker_reason(record) == "close above resistance"


def test_ticker_reason_falls_back_to_entry_gate():
    record = {"entry_gate": {"decision": "analyze", "setup_type": "range_chop"}}
    assert "range_chop" in _ticker_reason(record)
