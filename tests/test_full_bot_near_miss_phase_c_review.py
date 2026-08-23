from __future__ import annotations

from datetime import datetime, timezone

from bot.full_bot_maker_buy_live_adapter import build_full_bot_maker_buy_live_adapter_report
from bot.full_bot_near_miss_phase_c_review import build_full_bot_near_miss_phase_c_review_report


NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)


def _intent(
    ticker: str = "XRP-USDC",
    *,
    side: str = "BUY",
    quote: str = "20",
    price: str = "1.10",
    target: str = "1.20",
    invalidation: str = "1.05",
    expires_at: str = "2026-06-10T12:30:00Z",
    order_type: str = "limit_maker",
) -> dict:
    return {
        "ticker": ticker,
        "side": side,
        "status": "near_miss_intent",
        "preferred_order_type": order_type,
        "proposed_size_quote": quote,
        "proposed_price": price,
        "target_reference": target,
        "invalidation_reference": invalidation,
        "do_not_chase_boundary": "0",
        "expires_at": expires_at,
        "intent_id": f"intent-{ticker}",
        "soft_blockers": ["confidence_below_forming_intent_threshold"],
    }


def _action(**kwargs) -> dict:
    intent = _intent(**kwargs)
    return {
        "action_class": "near_miss_maker_buy",
        "classification": "preview_only",
        "ticker": intent["ticker"],
        "side": intent["side"],
        "details": {"intent": intent},
    }


def _orch(actions: list[dict] | None = None) -> dict:
    return {
        "phase": "full_bot_orchestrator_v1",
        "entry_action_candidates": actions if actions is not None else [_action()],
        "reservation_summary": {
            "open_order_count": 0,
            "open_order_count_by_ticker": {},
            "reserved_quote_open_buy_orders": "0",
        },
    }


def _adapter(actions: list[dict] | None = None) -> dict:
    return build_full_bot_maker_buy_live_adapter_report(orchestrator_report=_orch(actions))


def _selected(**kwargs) -> dict:
    action = _action(**kwargs)
    intent = action["details"]["intent"]
    return {
        "ticker": intent["ticker"],
        "action_class": action["action_class"],
        "classification": action["classification"],
        "side": intent["side"],
        "quote_size": intent["proposed_size_quote"],
        "limit_price": intent["proposed_price"],
        "soft_context_blockers": intent.get("soft_blockers") or [],
        "source_action": action,
    }


def _adapter_with_selected(selection: dict) -> dict:
    return {
        "phase": "full_bot_maker_buy_live_adapter_v1",
        "selected_entry_candidates": [selection],
        "reservation_summary": {"open_order_count": 0},
    }


def _evidence(ticker: str = "XRP-USDC", *, judge: bool = True, risk: bool = True) -> dict:
    return {
        "by_ticker": {
            ticker: {
                "judge": {"decision": "approve_trade" if judge else "wait", "side": "BUY", "approved": judge},
                "risk": {"mode": "deterministic_live_risk", "approved": risk, "accepted": risk, "risk_approved": risk},
            }
        }
    }


def _review(adapter: dict, evidence: dict | None = None) -> dict:
    return build_full_bot_near_miss_phase_c_review_report(adapter_report=adapter, fresh_review_evidence=evidence, now=NOW)


def test_review_only_by_default_and_no_writes_or_submit() -> None:
    report = _review(_adapter())
    assert report["review_only"] is True
    assert report["live_order_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False


def test_selected_xrp_candidate_can_be_reviewed_but_not_fake_promoted() -> None:
    report = _review(_adapter())
    assert report["selected_candidates"][0]["ticker"] == "XRP-USDC"
    assert report["promoted_phase_c_ready_candidates"] == []
    assert "fresh_review_required" in report["blockers"]
    assert "fresh_judge_buy_approval_missing" in report["blockers"]


def test_candidate_without_fresh_judge_approval_is_not_promoted() -> None:
    report = _review(_adapter(), _evidence(judge=False, risk=True))
    assert report["promoted_phase_c_ready_candidates"] == []
    assert "fresh_judge_buy_approval_missing" in report["blockers"]


def test_candidate_without_deterministic_risk_approval_is_not_promoted() -> None:
    report = _review(_adapter(), _evidence(judge=True, risk=False))
    assert report["promoted_phase_c_ready_candidates"] == []
    assert "deterministic_live_risk_approval_missing" in report["blockers"]


def test_existing_phase_c_guard_blockers_remain_without_evidence() -> None:
    report = _review(_adapter())
    guard = report["phase_c_guard_after_review"]
    assert guard["all_phase_c_guards_passed"] is False
    assert "fresh_judge_buy_approval_missing" in guard["blockers"]
    assert "deterministic_live_risk_approval_missing" in guard["blockers"]


def test_sell_market_quote_missing_target_invalidation_and_stale_are_rejected() -> None:
    cases = [
        (_selected(side="SELL"), "sell_rejected"),
        (_selected(order_type="market"), "market_rejected"),
        (_selected(quote="20.01"), "quote_gt_20_rejected"),
        (_selected(target="0"), "missing_target"),
        (_selected(invalidation="0"), "missing_invalidation"),
        (_selected(expires_at="2026-06-10T11:59:59Z"), "stale_candidate_rejected"),
    ]
    for selection, blocker in cases:
        report = _review(_adapter_with_selected(selection), _evidence(ticker=selection["ticker"]))
        assert blocker in report["blockers"]
        assert report["promoted_phase_c_ready_candidates"] == []


def test_promoted_candidate_requires_fresh_judge_buy_and_live_risk_approval() -> None:
    report = _review(_adapter(), _evidence())
    assert len(report["promoted_phase_c_ready_candidates"]) == 1
    assert report["promoted_phase_c_ready_candidates"][0]["ticker"] == "XRP-USDC"
    assert report["fresh_review_results"][0]["judge_review_status"] == "approved_buy"
    assert report["fresh_review_results"][0]["deterministic_risk_review_status"] == "approved_live"
    assert report["phase_c_guard_after_review"]["all_phase_c_guards_passed"] is True


def test_adapter_report_can_consume_promoted_candidate_in_dry_run_and_submit_remains_ack_gated() -> None:
    adapter = _adapter()
    review = _review(adapter, _evidence())
    report = build_full_bot_maker_buy_live_adapter_report(
        orchestrator_report=_orch(),
        phase_c_ready_candidates=review["promoted_phase_c_ready_candidates"],
    )
    assert report["phase_c_guard_summary"]["all_phase_c_guards_passed"] is True
    assert report["actual_submit_allowed"] is False
    assert report["actual_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
