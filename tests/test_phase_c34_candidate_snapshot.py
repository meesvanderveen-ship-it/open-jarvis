from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

from bot.phase_c34_candidate_snapshot import (
    build_phase_c34_candidate_from_sources,
    build_phase_c34_candidate_snapshot_report,
)


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


def _analysis(ticker="BTC-USDC"):
    return {
        "ticker": ticker,
        "generated_at": "2026-05-15T12:00:00+00:00",
        "analysis_id": "analysis-1",
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
        "judge": {"decision": "approve_trade", "side": "BUY", "size_quote": "9.50", "confidence": 74},
    }


def _execution_plan(ticker="BTC-USDC"):
    return {
        "ticker": ticker,
        "generated_at": "2026-05-15T12:01:00+00:00",
        "read_only": True,
        "execution_action": "place_limit_buy",
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


def _pending(ticker="BTC-USDC"):
    return {
        "intent_id": "intent-1",
        "ticker": ticker,
        "status": "needs_fresh_analysis",
        "updated_at": "2026-05-15T11:59:00+00:00",
        "last_evaluation": {"trigger_ready": True, "reason": "test", "current_price": "50000"},
    }


def _intent(ticker="BTC-USDC"):
    return {
        "intent_id": "intent-1",
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "order_type": "limit",
        "size_quote": "9.50",
        "limit_price": "50000",
        "expiry_minutes": 60,
        "status": "active",
    }


def _risk():
    return {"accepted": True, "mode": "live_phase_c", "reason": "test risk accepted"}


def _summary():
    return {
        "total_intents": 1,
        "open_intents": 1,
        "promotion_ready": [{"ticker": "BTC-USDC", "intent_id": "intent-1"}],
        "needs_fresh_analysis": [{"ticker": "BTC-USDC", "intent_id": "intent-1"}],
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


def test_c34_builds_c33_compatible_candidate_but_does_not_submit():
    candidate = build_phase_c34_candidate_from_sources(
        ticker="BTC-USDC",
        analysis=_analysis(),
        execution_plan=_execution_plan(),
        pending_intent=_pending(),
        logged_order_intent=_intent(),
        live_risk_result=_risk(),
    )
    assert candidate["ticker"] == "BTC-USDC"
    assert candidate["analysis"]["feature_pack"]["decision_context"]["pending_order_intent"]["intent_id"] == "intent-1"
    assert candidate["order_intent"]["limit_price"] == "50000"
    assert candidate["order_intent"]["size_quote"] == "9.50"
    assert candidate["risk"]["accepted"] is True
    assert candidate["safety_policy"]["no_submit_in_c34"] is True


def test_c34_report_can_extract_from_logs_and_reach_final_preflight_ready_with_real_risk(tmp_path: Path):
    analysis_log = tmp_path / "logs" / "analysis.jsonl"
    plan_log = tmp_path / "logs" / "execution_plans.jsonl"
    order_events = tmp_path / "logs" / "order_events.jsonl"
    paper_log = tmp_path / "logs" / "paper_order_manager.jsonl"
    pending_state = tmp_path / "state" / "pending_order_intents.json"
    _write_jsonl(analysis_log, [_analysis()])
    _write_jsonl(plan_log, [_execution_plan()])
    _write_jsonl(order_events, [{"generated_at": "2026-05-15T12:02:00+00:00", "intent": _intent()}])
    _write_jsonl(paper_log, [])
    pending_state.parent.mkdir(parents=True, exist_ok=True)
    pending_state.write_text(json.dumps({"intents": {"intent-1": _pending()}}), encoding="utf-8")

    report = build_phase_c34_candidate_snapshot_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis_log_path=analysis_log,
        execution_plan_log_path=plan_log,
        pending_intents_path=pending_state,
        order_events_path=order_events,
        paper_manager_path=paper_log,
        pending_summary=_summary(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_result=_risk(),
    )
    assert report["candidate_snapshot_extracted"] is True
    assert report["candidate_snapshot_structural_extraction_ready"] is True
    assert report["final_preflight_snapshot_ready"] is True
    assert report["live_submission_attempted_by_this_tool"] is False
    assert report["live_order_submitted"] is False
    assert report["c33_report"]["payload_preview"]["accepted"] is True


def test_c34_blocks_without_live_risk_and_does_not_fabricate_approval(tmp_path: Path):
    analysis_log = tmp_path / "analysis.jsonl"
    plan_log = tmp_path / "execution_plans.jsonl"
    pending_state = tmp_path / "pending_order_intents.json"
    order_events = tmp_path / "order_events.jsonl"
    paper_log = tmp_path / "paper_order_manager.jsonl"
    _write_jsonl(analysis_log, [_analysis()])
    _write_jsonl(plan_log, [_execution_plan()])
    _write_jsonl(order_events, [{"generated_at": "2026-05-15T12:02:00+00:00", "intent": _intent()}])
    _write_jsonl(paper_log, [])
    pending_state.write_text(json.dumps({"intents": {"intent-1": _pending()}}), encoding="utf-8")

    report = build_phase_c34_candidate_snapshot_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis_log_path=analysis_log,
        execution_plan_log_path=plan_log,
        pending_intents_path=pending_state,
        order_events_path=order_events,
        paper_manager_path=paper_log,
        pending_summary=_summary(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_result=None,
    )
    assert report["candidate_snapshot_extracted"] is True
    assert "live_risk_result_not_supplied_or_not_found" in report["blockers"]
    assert report["final_preflight_snapshot_ready"] is False
    assert report["candidate"]["risk"] == {}
    assert report["live_order_submitted"] is False


def test_c34_blocks_when_pending_intent_is_not_promotion_ready(tmp_path: Path):
    pending = _pending()
    pending["status"] = "active"
    pending["last_evaluation"] = {"trigger_ready": False}
    report = build_phase_c34_candidate_snapshot_report(
        cfg=_cfg(),
        ticker="BTC-USDC",
        analysis_log_path=tmp_path / "missing_analysis.jsonl",
        execution_plan_log_path=tmp_path / "missing_plan.jsonl",
        pending_intents_path=tmp_path / "missing_pending.json",
        order_events_path=tmp_path / "missing_events.jsonl",
        paper_manager_path=tmp_path / "missing_paper.jsonl",
        pending_summary={},
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_result=_risk(),
    )
    assert report["final_preflight_snapshot_ready"] is False
    assert "latest_analysis_not_found" in report["blockers"]
    assert "latest_execution_plan_not_found" in report["blockers"]
    assert report["live_submission_attempted_by_this_tool"] is False


def test_c34_detects_actual_submit_enabled_as_forbidden_even_with_valid_inputs(tmp_path: Path):
    analysis_log = tmp_path / "analysis.jsonl"
    plan_log = tmp_path / "execution_plans.jsonl"
    pending_state = tmp_path / "pending_order_intents.json"
    order_events = tmp_path / "order_events.jsonl"
    paper_log = tmp_path / "paper_order_manager.jsonl"
    _write_jsonl(analysis_log, [_analysis()])
    _write_jsonl(plan_log, [_execution_plan()])
    _write_jsonl(order_events, [{"generated_at": "2026-05-15T12:02:00+00:00", "intent": _intent()}])
    _write_jsonl(paper_log, [])
    pending_state.write_text(json.dumps({"intents": {"intent-1": _pending()}}), encoding="utf-8")
    report = build_phase_c34_candidate_snapshot_report(
        cfg=_cfg(enable_phase_c_actual_coinbase_submit=True),
        ticker="BTC-USDC",
        analysis_log_path=analysis_log,
        execution_plan_log_path=plan_log,
        pending_intents_path=pending_state,
        order_events_path=order_events,
        paper_manager_path=paper_log,
        pending_summary=_summary(),
        order_summary=_orders_clean(),
        submit_audit_summary=_audit_clean(),
        live_risk_result=_risk(),
    )
    assert report["actual_coinbase_submit_currently_enabled"] is True
    assert report["final_preflight_snapshot_ready"] is False
    assert report["live_order_submitted"] is False
