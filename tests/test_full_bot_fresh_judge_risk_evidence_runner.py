from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from bot.full_bot_fresh_judge_risk_evidence_runner import build_full_bot_fresh_judge_risk_evidence_report


NOW = datetime(2026, 6, 10, 12, 0, 0, tzinfo=timezone.utc)
ALL = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "ADA-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "DOGE-USDC",
    "SUI-USDC",
    "LTC-USDC",
    "HBAR-USDC",
    "ATOM-USDC",
    "NEAR-USDC",
    "APT-USDC",
    "INJ-USDC",
    "ARB-USDC",
    "OP-USDC",
    "UNI-USDC",
]


def _write_root(root: Path) -> None:
    (root / "state").mkdir(parents=True, exist_ok=True)
    (root / "state/open_orders.json").write_text("{}\n", encoding="utf-8")
    (root / "state/positions.json").write_text("{}\n", encoding="utf-8")
    (root / ".env").write_text("", encoding="utf-8")


def _intent(
    ticker: str,
    *,
    side: str = "BUY",
    quote: str = "20",
    price: str = "1.00",
    target: str = "1.20",
    invalidation: str = "0.90",
    expires_at: str = "2026-06-10T12:30:00Z",
    order_type: str = "limit_maker",
) -> dict:
    return {
        "ticker": ticker,
        "side": side,
        "status": "near_miss_intent",
        "setup_family": "reclaim_reversal",
        "preferred_order_type": order_type,
        "proposed_size_quote": quote,
        "proposed_price": price,
        "target_reference": target,
        "invalidation_reference": invalidation,
        "expires_at": expires_at,
        "intent_id": f"intent-{ticker}",
        "soft_blockers": ["confidence_below_forming_intent_threshold"],
        "orderbook_score": "90",
    }


def _action(ticker: str, **kwargs) -> dict:
    intent = _intent(ticker, **kwargs)
    return {
        "ticker": ticker,
        "side": intent["side"],
        "action_class": "near_miss_maker_buy",
        "classification": "preview_only",
        "details": {"intent": intent},
    }


def _selected(ticker: str, **kwargs) -> dict:
    action = _action(ticker, **kwargs)
    intent = action["details"]["intent"]
    return {
        "ticker": ticker,
        "action_class": "near_miss_maker_buy",
        "classification": "preview_only",
        "side": intent["side"],
        "quote_size": intent["proposed_size_quote"],
        "limit_price": intent["proposed_price"],
        "soft_context_blockers": intent["soft_blockers"],
        "source_action": action,
    }


def _cap_hidden(ticker: str) -> dict:
    row = _selected(ticker)
    row["classification"] = "blocked"
    row["reasons"] = ["max_2_new_orders_per_cycle_reached"]
    return row


def _reports(*, selected: list[dict] | None = None, rejected: list[dict] | None = None) -> dict:
    selected = selected if selected is not None else [_selected("XRP-USDC"), _selected("APT-USDC")]
    rejected = rejected if rejected is not None else [_cap_hidden("BTC-USDC"), _cap_hidden("AVAX-USDC")]
    d6_intents = [*(x["source_action"]["details"]["intent"] for x in selected), *(x["source_action"]["details"]["intent"] for x in rejected)]
    p1 = ["XRP-USDC", "APT-USDC", "BTC-USDC", "AVAX-USDC"]
    return {
        "d6_report": {"near_miss_intents": d6_intents},
        "workflow_audit_report": {"readiness_verdict": "blocked_by_missing_fresh_judge_and_risk"},
        "failure_matrix_report": {
            "summary": {
                "all_p1_items": p1,
                "top_all_ticker_fresh_judge_candidates": ["XRP-USDC", "APT-USDC"],
                "top_all_ticker_deterministic_risk_candidates": ["XRP-USDC", "APT-USDC"],
                "max_new_orders_per_cycle_hidden_tickers": ["BTC-USDC", "AVAX-USDC"],
                "any_ticker_phase_c_ready_now": False,
            },
            "matrix": [
                {
                    "ticker": ticker,
                    "priority": "P1",
                    "root_cause_category": "needs_fresh_judge_review" if ticker in {"XRP-USDC", "APT-USDC"} else "adapter_selection_cap",
                    "phase_c_guard_blockers": ["fresh_judge_buy_approval_missing", "deterministic_live_risk_approval_missing"],
                }
                for ticker in p1
            ],
        },
        "adapter_report": {
            "phase": "full_bot_maker_buy_live_adapter_v1",
            "selected_entry_candidates": selected,
            "rejected_entry_candidates": rejected,
            "reservation_summary": {"open_order_count": 0, "open_order_count_by_ticker": {}, "reserved_quote_open_buy_orders": "0"},
        },
        "near_miss_review_report": {
            "fresh_review_results": [{"ticker": x["ticker"], "status": "not_promoted"} for x in selected],
            "promoted_phase_c_ready_candidates": [],
        },
        "orchestrator_report": {
            "phase": "full_bot_orchestrator_v1",
            "entry_action_candidates": [x["source_action"] for x in selected + rejected],
            "reservation_summary": {"open_order_count": 0, "open_order_count_by_ticker": {}, "reserved_quote_open_buy_orders": "0"},
        },
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


def _report(tmp_path: Path, **kwargs) -> dict:
    _write_root(tmp_path)
    reports = _reports(**kwargs.pop("reports", {}))
    reports.update(kwargs)
    return build_full_bot_fresh_judge_risk_evidence_report(root=tmp_path, generated_at=NOW, **reports)


def _packet(report: dict, ticker: str) -> dict:
    return next(x for x in report["evidence_packets"] if x["ticker"] == ticker)


def test_evidence_only_by_default_no_submit_coinbase_or_state_write(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report["evidence_only"] is True
    assert report["live_order_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["state_hashes"]["unchanged"] is True


def test_all_p1_selected_and_cap_hidden_candidates_are_included(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report["candidates_reviewed"] == ["BTC-USDC", "XRP-USDC", "AVAX-USDC", "APT-USDC"]
    assert _packet(report, "XRP-USDC")["selected_by_adapter"] is True
    assert _packet(report, "BTC-USDC")["cap_hidden_by_adapter"] is True


def test_stale_candidates_require_refresh(tmp_path: Path) -> None:
    selected = [_selected("XRP-USDC", expires_at="2026-06-10T11:59:59Z")]
    report = _report(tmp_path, reports={"selected": selected, "rejected": []})
    assert "stale_candidate_rejected" in _packet(report, "XRP-USDC")["current_blockers"]


def test_missing_judge_or_risk_does_not_promote_and_no_fake_approvals(tmp_path: Path) -> None:
    no_evidence = _report(tmp_path)
    assert no_evidence["fresh_judge_approvals"] == []
    assert no_evidence["deterministic_live_risk_approvals"] == []
    assert no_evidence["phase_c_ready_candidates_after_evidence"] == []

    missing_judge = _report(tmp_path, fresh_review_evidence=_evidence(judge=False, risk=True))
    assert missing_judge["phase_c_ready_candidates_after_evidence"] == []
    assert "XRP-USDC" not in missing_judge["fresh_judge_approvals"]

    missing_risk = _report(tmp_path, fresh_review_evidence=_evidence(judge=True, risk=False))
    assert missing_risk["phase_c_ready_candidates_after_evidence"] == []
    assert "XRP-USDC" not in missing_risk["deterministic_live_risk_approvals"]


def test_valid_fresh_judge_buy_and_deterministic_risk_can_become_phase_c_ready(tmp_path: Path) -> None:
    report = _report(tmp_path, fresh_review_evidence=_evidence())
    assert report["fresh_judge_approvals"] == ["XRP-USDC"]
    assert report["deterministic_live_risk_approvals"] == ["XRP-USDC"]
    assert report["phase_c_ready_candidates_after_evidence"] == ["XRP-USDC"]
    assert report["live_order_submit_attempted"] is False


def test_sell_market_and_quote_over_20_rejected(tmp_path: Path) -> None:
    cases = [
        (_selected("XRP-USDC", side="SELL"), "sell_rejected"),
        (_selected("XRP-USDC", order_type="market"), "market_rejected"),
        (_selected("XRP-USDC", quote="20.01"), "quote_gt_20_rejected"),
    ]
    for selected, blocker in cases:
        report = _report(tmp_path, reports={"selected": [selected], "rejected": []}, fresh_review_evidence=_evidence())
        assert blocker in _packet(report, "XRP-USDC")["current_blockers"]
        assert report["phase_c_ready_candidates_after_evidence"] == []


def test_exact_ack_still_required_for_actual_submit(tmp_path: Path) -> None:
    report = _report(tmp_path, fresh_review_evidence=_evidence())
    assert "DO NOT RUN NOW" in report["exact_actual_submit_command_if_ready"]
    assert "I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET" in report["exact_actual_submit_command_if_ready"]
    assert report["downstream_report_summaries"]["readiness_gate_after_evidence"]["first_real_maker_buy_live_submit_allowed_now"] is False


def test_readiness_gate_remains_blocked_if_no_real_approvals_exist(tmp_path: Path) -> None:
    report = _report(tmp_path)
    assert report["classification"] == "blocked_by_missing_fresh_judge_and_risk"
    assert report["downstream_report_summaries"]["readiness_gate_after_evidence"]["any_ticker_phase_c_ready_now"] is False
