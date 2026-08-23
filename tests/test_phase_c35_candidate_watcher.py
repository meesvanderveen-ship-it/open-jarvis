from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.phase_c35_candidate_watcher import build_phase_c35_candidate_watcher_report


def _cfg(**overrides):
    base = dict(
        execution_mode="live",
        enable_limit_order_manager=True,
        enable_live_limit_orders=False,
        enable_live_entry_orders=False,
        enable_live_exit_orders=False,
        enable_phase_c_live_small_limit_orders=False,
        phase_c_allowed_tickers=[],
        phase_c_max_order_quote=Decimal("10.00"),
        phase_c_max_open_entry_orders=1,
        phase_c_max_new_orders_per_cycle=1,
        phase_c_max_cancels_per_cycle=1,
        phase_c_max_replaces_per_cycle=0,
        phase_c_require_pending_intent=True,
        phase_c_require_promotion_ready=True,
        phase_c_require_fresh_judge=True,
        phase_c_require_risk_approval=True,
        phase_c_require_orderbook_freshness=True,
        phase_c_entry_order_min_expiry_minutes=15,
        phase_c_entry_order_default_expiry_minutes=60,
        phase_c_entry_order_max_expiry_hours=6,
        phase_c_disable_exit_limit_orders=True,
        phase_c_paper_shadow_log=True,
        enable_phase_c_live_submit_infrastructure=True,
        enable_phase_c_actual_coinbase_submit=False,
        phase_c_live_order_post_only=True,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _analysis(ticker="BTC-USDC", approve=True):
    return {
        "ticker": ticker,
        "generated_at": "2026-05-15T12:00:00+00:00",
        "analysis_id": f"analysis-{ticker}",
        "feature_pack": {
            "ticker": ticker,
            "market": {
                "best_bid": "50000",
                "best_ask": "50001",
                "quote_increment": "0.01",
                "base_increment": "0.00000001",
                "quote_min_size": "1",
                "base_min_size": "0.00000001",
            },
        },
        "judge": {
            "decision": "approve_trade" if approve else "wait",
            "side": "BUY" if approve else "NONE",
            "size_quote": "9.50" if approve else 0,
            "confidence": 74,
        },
    }


def _execution_plan(ticker="BTC-USDC", actionable=True):
    return {
        "ticker": ticker,
        "generated_at": "2026-05-15T12:01:00+00:00",
        "read_only": True,
        "execution_action": "place_limit_buy" if actionable else "no_order",
        "expiry_minutes": 60,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "top_of_book": {
                "best_bid": "50000",
                "best_ask": "50001",
                "spread_pct": "0.00002",
            },
        },
    }


def _pending(ticker="BTC-USDC", ready=True):
    return {
        "intent_id": f"intent-{ticker}",
        "ticker": ticker,
        "status": "needs_fresh_analysis" if ready else "waiting",
        "updated_at": "2026-05-15T11:59:00+00:00",
        "last_evaluation": {"trigger_ready": ready, "reason": "test", "current_price": "50000"},
    }


def _intent(ticker="BTC-USDC"):
    return {
        "intent_id": f"intent-{ticker}",
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "order_type": "limit",
        "size_quote": "9.50",
        "limit_price": "50000",
        "expiry_minutes": 60,
        "status": "active",
    }


def _risk(ticker="BTC-USDC"):
    return {"ticker": ticker, "accepted": True, "mode": "live_phase_c", "reason": "test risk accepted"}


def _pending_summary(ticker="BTC-USDC"):
    return {
        "total_intents": 1,
        "open_intents": 1,
        "promotion_ready": [{"ticker": ticker, "intent_id": f"intent-{ticker}"}],
        "needs_fresh_analysis": [{"ticker": ticker, "intent_id": f"intent-{ticker}"}],
        "trigger_ready": [],
    }


def _orders_clean():
    return {"total_orders": 0, "open_orders": 0, "diagnostic_order_count": 0, "open_entry_orders": []}


def _audit_clean():
    return {"live_submission_attempted_count": 0, "live_order_submitted_count": 0, "sample_size": 0}


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def _write_fixture(tmp_path: Path, *, ticker="BTC-USDC", ready=True, approve=True, actionable=True):
    analysis_log = tmp_path / "logs" / "analysis.jsonl"
    plan_log = tmp_path / "logs" / "execution_plans.jsonl"
    order_events = tmp_path / "logs" / "order_events.jsonl"
    paper_log = tmp_path / "logs" / "paper_order_manager.jsonl"
    pending_state = tmp_path / "state" / "pending_order_intents.json"
    _write_jsonl(analysis_log, [_analysis(ticker, approve=approve)])
    _write_jsonl(plan_log, [_execution_plan(ticker, actionable=actionable)])
    _write_jsonl(order_events, [{"generated_at": "2026-05-15T12:02:00+00:00", "intent": _intent(ticker)}] if actionable else [])
    _write_jsonl(paper_log, [])
    pending_state.parent.mkdir(parents=True, exist_ok=True)
    pending_state.write_text(json.dumps({"intents": {f"intent-{ticker}": _pending(ticker, ready=ready)}}), encoding="utf-8")
    return analysis_log, plan_log, pending_state, order_events, paper_log


def test_c35_reports_preflight_ready_when_c34_and_c33_are_green(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    report = build_phase_c35_candidate_watcher_report(
        cfg=_cfg(),
        tickers=["BTC-USDC"],
        analysis_log_path=paths[0],
        execution_plan_log_path=paths[1],
        pending_intents_path=paths[2],
        order_events_path=paths[3],
        paper_manager_path=paths[4],
        pending_summary=_pending_summary(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_by_ticker={"BTC-USDC": _risk()},
    )
    assert report["status"] == "preflight_ready_no_submit"
    assert report["any_preflight_ready_no_submit"] is True
    assert report["preflight_ready_tickers"] == ["BTC-USDC"]
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["candidate_summaries"][0]["payload_accepted"] is True


def test_c35_blocks_candidate_without_live_risk_but_still_extracts(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    report = build_phase_c35_candidate_watcher_report(
        cfg=_cfg(),
        tickers=["BTC-USDC"],
        analysis_log_path=paths[0],
        execution_plan_log_path=paths[1],
        pending_intents_path=paths[2],
        order_events_path=paths[3],
        paper_manager_path=paths[4],
        pending_summary=_pending_summary(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_by_ticker={},
    )
    assert report["status"] == "candidates_blocked_or_waiting"
    assert report["any_preflight_ready_no_submit"] is False
    assert report["blocked_candidate_tickers"] == ["BTC-USDC"]
    assert "live_risk_result_not_supplied_or_not_found" in report["candidate_summaries"][0]["blockers"]


def test_c35_reports_waiting_candidate_blocked_when_not_promotion_ready(tmp_path: Path):
    paths = _write_fixture(tmp_path, ready=False, approve=False, actionable=False)
    report = build_phase_c35_candidate_watcher_report(
        cfg=_cfg(),
        tickers=["BTC-USDC"],
        analysis_log_path=paths[0],
        execution_plan_log_path=paths[1],
        pending_intents_path=paths[2],
        order_events_path=paths[3],
        paper_manager_path=paths[4],
        pending_summary={"waiting": [{"ticker": "BTC-USDC"}]},
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_by_ticker={"BTC-USDC": _risk()},
    )
    assert report["any_preflight_ready_no_submit"] is False
    assert report["blocked_candidate_tickers"] == ["BTC-USDC"]
    summary = report["candidate_summaries"][0]
    assert summary["watch_status"] == "candidate_found_blocked"
    assert summary["judge_decision"] == "wait"
    assert summary["order_intent_action"] == "no_order"


def test_c35_safety_blocks_if_actual_submit_enabled(tmp_path: Path):
    paths = _write_fixture(tmp_path)
    report = build_phase_c35_candidate_watcher_report(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        tickers=["BTC-USDC"],
        analysis_log_path=paths[0],
        execution_plan_log_path=paths[1],
        pending_intents_path=paths[2],
        order_events_path=paths[3],
        paper_manager_path=paths[4],
        pending_summary=_pending_summary(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_by_ticker={"BTC-USDC": _risk()},
    )
    assert report["status"] == "blocked_safety_issue"
    assert "actual_coinbase_submit_enabled_forbidden" in report["blockers"]
    assert report["live_order_submitted"] is False


def test_c35_resolves_tickers_from_pending_state_when_no_explicit_ticker(tmp_path: Path):
    paths = _write_fixture(tmp_path, ticker="ETH-USDC")
    report = build_phase_c35_candidate_watcher_report(
        cfg=_cfg(),
        tickers=None,
        analysis_log_path=paths[0],
        execution_plan_log_path=paths[1],
        pending_intents_path=paths[2],
        order_events_path=paths[3],
        paper_manager_path=paths[4],
        pending_summary={},
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_by_ticker={"ETH-USDC": _risk("ETH-USDC")},
    )
    assert report["watch_tickers"] == ["ETH-USDC"]
    assert report["candidate_summaries"][0]["ticker"] == "ETH-USDC"
    assert report["live_order_submitted"] is False
