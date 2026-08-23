from __future__ import annotations

import inspect
from decimal import Decimal

from bot.full_bot_maker_buy_live_adapter import (
    EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
    build_full_bot_maker_buy_live_adapter_report,
    select_maker_buy_candidates,
)
import bot.full_bot_maker_buy_live_adapter as adapter


def _intent(ticker: str = "XRP-USDC", *, quote: str = "20", price: str = "1.10", status: str = "near_miss_intent") -> dict:
    return {
        "ticker": ticker,
        "side": "BUY",
        "status": status,
        "preferred_order_type": "limit_maker",
        "proposed_size_quote": quote,
        "proposed_price": price,
        "intent_id": f"intent-{ticker}",
        "soft_blockers": ["confidence_below_forming_intent_threshold"] if status == "near_miss_intent" else [],
    }


def _action(action_class: str = "near_miss_maker_buy", *, ticker: str = "XRP-USDC", side: str = "BUY", quote: str = "20", price: str = "1.10", classification: str = "preview_only", order_type: str = "limit_maker") -> dict:
    intent = _intent(ticker, quote=quote, price=price)
    intent["side"] = side
    intent["preferred_order_type"] = order_type
    return {
        "action_class": action_class,
        "classification": classification,
        "ticker": ticker,
        "side": side,
        "blockers": ["blocked"] if classification == "blocked" else [],
        "details": {"intent": intent},
    }


def _strict_action(ticker: str = "BTC-USDC") -> dict:
    intent = _intent(ticker, status="intent_preview_ready")
    intent["soft_blockers"] = []
    return {
        "action_class": "strict_approve_trade_buy",
        "classification": "ack_required",
        "ticker": ticker,
        "side": "BUY",
        "blockers": [],
        "details": {"intent": intent},
    }


def _orch(actions: list[dict] | None = None, *, open_count: int = 0, reserved: str = "0", by_ticker: dict | None = None) -> dict:
    return {
        "phase": "full_bot_orchestrator_v1",
        "entry_action_candidates": actions if actions is not None else [_action("near_miss_maker_buy", ticker="XRP-USDC"), _action("near_miss_maker_buy", ticker="APT-USDC")],
        "reservation_summary": {
            "open_order_count": open_count,
            "open_order_count_by_ticker": by_ticker or {},
            "reserved_quote_open_buy_orders": reserved,
        },
    }


def test_default_mode_is_preview_only_and_no_writes() -> None:
    report = build_full_bot_maker_buy_live_adapter_report(orchestrator_report=_orch())
    assert report["preview_only"] is True
    assert report["exact_ack_present"] is False
    assert report["actual_submit_allowed"] is False
    assert report["actual_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False


def test_exact_ack_required_for_actual_submit_and_invalid_ack_does_not_submit() -> None:
    for ack in ("", "WRONG_ACK"):
        report = build_full_bot_maker_buy_live_adapter_report(orchestrator_report=_orch([_strict_action()]), ack=ack, actual_submit_requested=True, coinbase_client=object())
        assert report["exact_ack_present"] is False
        assert report["actual_submit_allowed"] is False
        assert report["actual_submit_attempted"] is False
        assert "exact_ack_required_for_actual_submit" in report["blockers"]


def test_no_ack_means_no_submit_even_with_client() -> None:
    calls = []

    def fake_submitter(**kwargs):
        calls.append(kwargs)
        return {"live_submission_attempted": bool(kwargs["submit_live"]), "live_order_submitted": False, "hard_block_reasons": []}

    report = build_full_bot_maker_buy_live_adapter_report(
        orchestrator_report=_orch([_strict_action()]),
        actual_submit_requested=True,
        coinbase_client=object(),
        phase_c_submitter=fake_submitter,
    )
    assert calls and calls[0]["submit_live"] is False
    assert report["actual_submit_attempted"] is False


def test_sell_market_and_blocked_candidates_are_rejected() -> None:
    selected, rejected = select_maker_buy_candidates(
        _orch(
            [
                _action(ticker="SELL-USDC", side="SELL"),
                _action(ticker="MKT-USDC", order_type="market"),
                _action(ticker="BLOCK-USDC", classification="blocked"),
                _action(ticker="OK-USDC"),
            ]
        )
    )
    assert [x["ticker"] for x in selected] == ["OK-USDC"]
    reasons = {r["ticker"]: r["reasons"] for r in rejected}
    assert any("side_not_buy:SELL" in x for x in reasons["SELL-USDC"])
    assert "market_candidate_rejected" in reasons["MKT-USDC"]
    assert "blocked_candidate_rejected" in reasons["BLOCK-USDC"]


def test_max_2_new_orders_per_cycle_enforced() -> None:
    selected, rejected = select_maker_buy_candidates(_orch([_action(ticker="A-USDC"), _action(ticker="B-USDC"), _action(ticker="C-USDC")]))
    assert [x["ticker"] for x in selected] == ["A-USDC", "B-USDC"]
    assert "max_2_new_orders_per_cycle_reached" in rejected[-1]["reasons"]


def test_max_5_open_orders_cap_enforced() -> None:
    selected, rejected = select_maker_buy_candidates(_orch([_action(ticker="A-USDC")], open_count=5))
    assert selected == []
    assert "max_5_open_orders_total_reached" in rejected[0]["reasons"]


def test_max_1_open_order_per_ticker_enforced() -> None:
    selected, rejected = select_maker_buy_candidates(_orch([_action(ticker="XRP-USDC")], by_ticker={"XRP-USDC": 1}))
    assert selected == []
    assert "max_1_open_order_per_ticker_reached" in rejected[0]["reasons"]


def test_max_20_usdc_order_cap_enforced() -> None:
    selected, rejected = select_maker_buy_candidates(_orch([_action(ticker="A-USDC", quote="20.01")]))
    assert selected == []
    assert "max_20_usdc_order_cap_exceeded" in rejected[0]["reasons"]


def test_max_100_usdc_reserved_quote_enforced() -> None:
    selected, rejected = select_maker_buy_candidates(_orch([_action(ticker="A-USDC", quote="20")], reserved="90"))
    assert selected == []
    assert "max_100_usdc_reserved_quote_reached" in rejected[0]["reasons"]


def test_phase_c_guard_blockers_stop_live_readiness_for_near_miss() -> None:
    report = build_full_bot_maker_buy_live_adapter_report(
        orchestrator_report=_orch(),
        ack=EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
        actual_submit_requested=True,
        coinbase_client=object(),
    )
    assert report["actual_submit_allowed"] is False
    assert "phase_c_guard_blockers_present" in report["blockers"]
    assert "blocked_missing_fresh_approve_trade" in report["phase_c_guard_summary"]["blockers"]
    assert report["actual_submit_attempted"] is False


def test_adapter_does_not_bypass_phase_c_fresh_evidence_requirements() -> None:
    calls = []

    def fake_submitter(**kwargs):
        calls.append(kwargs)
        return {"live_submission_attempted": bool(kwargs["submit_live"]), "live_order_submitted": True, "hard_block_reasons": []}

    report = build_full_bot_maker_buy_live_adapter_report(
        orchestrator_report=_orch([_strict_action()]),
        ack=EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
        actual_submit_requested=True,
        coinbase_client=object(),
        phase_c_submitter=fake_submitter,
    )
    assert calls and calls[0]["submit_live"] is False
    assert report["actual_submit_allowed"] is False
    assert "phase_c_guard_blockers_present" in report["blockers"]
    assert report["phase_c_guard_summary"]["phase_c_route_used"].endswith("prepare_phase_c_live_entry_submission")
    assert report["phase_c_guard_summary"]["direct_coinbase_submitter_introduced"] is False
    source = inspect.getsource(adapter)
    assert ".place_limit_order(" not in source


def test_no_state_or_coinbase_write_in_preview() -> None:
    report = build_full_bot_maker_buy_live_adapter_report(orchestrator_report=_orch([_strict_action()]))
    assert report["actual_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False


def test_disabled_surfaces_remain_disabled() -> None:
    report = build_full_bot_maker_buy_live_adapter_report(orchestrator_report=_orch())
    flags = report["safety_flags"]
    assert flags["live_exits_enabled"] is False
    assert flags["d3_actual_exit_submit_enabled"] is False
    assert flags["replication_enabled"] is False
    assert flags["learning_to_execution_allowed"] is False
    assert flags["parameter_mutation_allowed"] is False
    assert flags["market_orders_enabled"] is False
    assert flags["sell_enabled"] is False


def test_phase_c_quote_cap_is_20() -> None:
    report = build_full_bot_maker_buy_live_adapter_report(orchestrator_report=_orch([_strict_action()]))
    cfg = report["phase_c_candidate_snapshots"][0]["guard_result"]["config"]
    assert Decimal(cfg["phase_c_max_order_quote"]) == Decimal("20.00")
