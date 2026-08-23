from __future__ import annotations

import inspect
import json
import subprocess
import sys
from pathlib import Path

from bot.full_bot_failure_determination_matrix import (
    CONFIGURED_USDC_TICKERS,
    build_full_bot_failure_determination_matrix,
)
import bot.full_bot_failure_determination_matrix as matrix_mod


def _intent(
    ticker: str,
    *,
    soft: list[str] | None = None,
    hard: list[str] | None = None,
    missing: list[str] | None = None,
    target: str = "1.20",
    invalidation: str = "0.90",
    price: str = "1.00",
    confidence: int = 58,
    status: str = "near_miss_intent",
) -> dict:
    return {
        "ticker": ticker,
        "side": "BUY",
        "status": status,
        "setup_family": "reclaim_reversal",
        "confidence": confidence,
        "preferred_order_type": "limit_maker",
        "proposed_size_quote": "20",
        "proposed_price": price,
        "target_reference": target,
        "invalidation_reference": invalidation,
        "hard_blockers": hard or [],
        "soft_blockers": soft if soft is not None else ["confidence_below_forming_intent_threshold"],
        "missing_data_blockers": missing or [],
    }


def _action(ticker: str, *, classification: str = "preview_only", blockers: list[str] | None = None, intent: dict | None = None) -> dict:
    return {
        "ticker": ticker,
        "side": "BUY",
        "action_class": "near_miss_maker_buy",
        "classification": classification,
        "blockers": blockers if blockers is not None else ["confidence_below_forming_intent_threshold"],
        "details": {"intent": intent or _intent(ticker)},
    }


def _selected(ticker: str, *, soft: list[str] | None = None, price: str = "1.00") -> dict:
    action = _action(ticker, intent=_intent(ticker, soft=soft, price=price))
    return {
        "ticker": ticker,
        "action_class": "near_miss_maker_buy",
        "classification": "preview_only",
        "side": "BUY",
        "quote_size": "20",
        "limit_price": price,
        "soft_context_blockers": soft or ["confidence_below_forming_intent_threshold"],
        "source_action": action,
    }


def _rejected_cap(ticker: str, *, soft: list[str] | None = None) -> dict:
    return {
        "ticker": ticker,
        "action_class": "near_miss_maker_buy",
        "classification": "blocked",
        "side": "BUY",
        "quote_size": "20",
        "limit_price": "1.00",
        "soft_context_blockers": soft if soft is not None else ["confidence_below_forming_intent_threshold"],
        "reasons": ["blocked_candidate_rejected", "max_2_new_orders_per_cycle_reached"],
        "source_action": _action(
            ticker,
            classification="blocked",
            blockers=["max_new_orders_per_cycle_reached"] + (soft if soft is not None else ["confidence_below_forming_intent_threshold"]),
            intent=_intent(ticker, soft=soft),
        ),
    }


def _base_reports() -> dict:
    xrp = _intent("XRP-USDC")
    apt = _intent("APT-USDC", soft=["confidence_below_forming_intent_threshold", "bad_volume_or_momentum"], confidence=56)
    avax = _intent("AVAX-USDC")
    btc = _intent("BTC-USDC", soft=["setup_family_unclear", "confidence_below_forming_intent_threshold"], confidence=10)
    return {
        "d6_report": {"preview_ready_intents": [], "near_miss_intents": [xrp, apt, avax, btc]},
        "orchestrator_report": {
            "entry_action_candidates": [
                _action("XRP-USDC", intent=xrp),
                _action("APT-USDC", blockers=apt["soft_blockers"], intent=apt),
                _action("AVAX-USDC", classification="blocked", blockers=["max_new_orders_per_cycle_reached", "confidence_below_forming_intent_threshold"], intent=avax),
                _action("BTC-USDC", classification="blocked", blockers=["max_new_orders_per_cycle_reached", "setup_family_unclear", "confidence_below_forming_intent_threshold"], intent=btc),
            ]
        },
        "adapter_report": {
            "selected_entry_candidates": [
                _selected("XRP-USDC"),
                _selected("APT-USDC", soft=["confidence_below_forming_intent_threshold", "bad_volume_or_momentum"]),
            ],
            "rejected_entry_candidates": [
                _rejected_cap("AVAX-USDC"),
                _rejected_cap("BTC-USDC", soft=["setup_family_unclear", "confidence_below_forming_intent_threshold"]),
            ],
            "phase_c_candidate_snapshots": [],
        },
        "review_report": {
            "fresh_review_results": [
                {
                    "ticker": "XRP-USDC",
                    "status": "not_promoted",
                    "judge_review_status": "missing_or_not_approved",
                    "deterministic_risk_review_status": "missing_or_not_approved",
                    "phase_c_guard_after_review": {"hard_block_reasons": ["fresh_judge_buy_approval_missing", "deterministic_live_risk_approval_missing"]},
                    "blockers": ["fresh_review_required", "fresh_judge_buy_approval_missing", "deterministic_live_risk_approval_missing"],
                },
                {
                    "ticker": "APT-USDC",
                    "status": "not_promoted",
                    "judge_review_status": "missing_or_not_approved",
                    "deterministic_risk_review_status": "missing_or_not_approved",
                    "phase_c_guard_after_review": {"hard_block_reasons": ["fresh_judge_buy_approval_missing", "deterministic_live_risk_approval_missing"]},
                    "blockers": ["fresh_review_required", "fresh_judge_buy_approval_missing", "deterministic_live_risk_approval_missing"],
                },
            ],
            "promoted_phase_c_ready_candidates": [],
        },
    }


def _report(**overrides: dict) -> dict:
    kwargs = _base_reports()
    kwargs.update(overrides)
    return build_full_bot_failure_determination_matrix(**kwargs)


def _row(report: dict, ticker: str) -> dict:
    return next(row for row in report["matrix"] if row["ticker"] == ticker)


def test_all_18_configured_tickers_are_included_even_when_absent() -> None:
    report = build_full_bot_failure_determination_matrix()
    assert [row["ticker"] for row in report["matrix"]] == CONFIGURED_USDC_TICKERS
    assert report["summary"]["total_configured_tickers"] == 18
    assert all(row["root_cause_category"] == "no_candidate_seen" for row in report["matrix"])


def test_xrp_style_selected_near_miss_needs_fresh_judge_and_risk() -> None:
    report = _report()
    row = _row(report, "XRP-USDC")
    assert row["adapter_selected"] is True
    assert row["root_cause_category"] == "needs_fresh_judge_review"
    assert "needs_deterministic_live_risk" in row["secondary_root_causes"]
    assert row["priority"] == "P1"


def test_apt_style_selected_near_miss_with_bad_volume_is_classified_correctly() -> None:
    report = _report()
    row = _row(report, "APT-USDC")
    assert row["root_cause_category"] == "needs_fresh_judge_review"
    assert row["volume_momentum_blockers"] == ["bad_volume_or_momentum"]
    assert "soft_near_miss_threshold" in row["secondary_root_causes"]


def test_avax_candidate_blocked_by_max_new_orders_becomes_adapter_selection_cap() -> None:
    report = _report()
    row = _row(report, "AVAX-USDC")
    assert row["adapter_rejected"] is True
    assert row["root_cause_category"] == "adapter_selection_cap"
    assert row["priority"] == "P1"


def test_absent_ticker_becomes_no_candidate_seen() -> None:
    report = _report()
    assert _row(report, "UNI-USDC")["root_cause_category"] == "no_candidate_seen"


def test_missing_target_or_invalidation_classification_works() -> None:
    bad = _intent("SOL-USDC", missing=["missing_target_reference"], target="")
    report = build_full_bot_failure_determination_matrix(d6_report={"near_miss_intents": [bad]})
    row = _row(report, "SOL-USDC")
    assert row["root_cause_category"] == "missing_target_or_invalidation"
    assert row["priority"] == "P1"


def test_missing_orderbook_classification_works() -> None:
    bad = _intent("ETH-USDC", missing=["proposed_price_missing"], price="")
    report = build_full_bot_failure_determination_matrix(d6_report={"near_miss_intents": [bad]})
    assert _row(report, "ETH-USDC")["root_cause_category"] == "missing_market_or_orderbook_data"


def test_stale_candidate_classification_works() -> None:
    selected = _selected("LINK-USDC")
    review = {
        "fresh_review_results": [
            {
                "ticker": "LINK-USDC",
                "status": "not_promoted",
                "judge_review_status": "approved_buy",
                "deterministic_risk_review_status": "approved_live",
                "phase_c_guard_after_review": {"hard_block_reasons": ["stale_candidate_rejected"]},
                "blockers": ["stale_candidate_rejected"],
            }
        ]
    }
    report = build_full_bot_failure_determination_matrix(
        d6_report={"near_miss_intents": [_intent("LINK-USDC", soft=[])]},
        adapter_report={"selected_entry_candidates": [selected]},
        review_report=review,
    )
    assert _row(report, "LINK-USDC")["root_cause_category"] == "stale_candidate_needs_refresh"


def test_phase_c_ready_fixture_becomes_phase_c_ready() -> None:
    selected = _selected("HBAR-USDC", soft=[])
    review = {
        "fresh_review_results": [
            {
                "ticker": "HBAR-USDC",
                "status": "promoted_phase_c_ready",
                "judge_review_status": "approved_buy",
                "deterministic_risk_review_status": "approved_live",
                "phase_c_guard_after_review": {"hard_block_reasons": []},
                "blockers": [],
            }
        ],
        "promoted_phase_c_ready_candidates": [{"ticker": "HBAR-USDC"}],
    }
    report = build_full_bot_failure_determination_matrix(
        d6_report={"near_miss_intents": [_intent("HBAR-USDC", soft=[], status="intent_preview_ready")]},
        adapter_report={"selected_entry_candidates": [selected]},
        review_report=review,
    )
    row = _row(report, "HBAR-USDC")
    assert row["root_cause_category"] == "phase_c_ready"
    assert row["priority"] == "P1"


def test_priority_scoring_and_summary_counts_are_correct() -> None:
    report = _report()
    assert report["summary"]["count_by_priority"]["P1"] == 4
    assert report["summary"]["count_by_priority"]["P4"] == 14
    assert report["summary"]["count_by_root_cause_category"]["needs_fresh_judge_review"] == 2
    assert report["summary"]["count_by_root_cause_category"]["adapter_selection_cap"] == 2
    assert report["summary"]["max_new_orders_per_cycle_hides_viable_candidates"] is True
    assert "AVAX-USDC" in report["summary"]["max_new_orders_per_cycle_hidden_tickers"]


def test_no_live_submit_no_coinbase_write_no_state_write_flags_and_source() -> None:
    report = _report()
    assert report["live_order_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False
    source = inspect.getsource(matrix_mod)
    assert "prepare_phase_c_live_entry_submission" not in source
    assert "coinbase_client" not in source
    assert "actual_submit" not in source


def test_cli_report_outputs_only_under_reports_d6(tmp_path: Path) -> None:
    reports = tmp_path / "reports" / "d6"
    state = tmp_path / "state"
    reports.mkdir(parents=True)
    state.mkdir()
    (reports / "d6-multi-order-intent-preview-calibrated-20260610.json").write_text(json.dumps({"near_miss_intents": [_intent("XRP-USDC")]}))
    (state / "open_orders.json").write_text(json.dumps({"orders": {}}))
    (state / "positions.json").write_text(json.dumps({}))
    cmd = [
        sys.executable,
        "tools/build_full_bot_failure_determination_matrix.py",
        "--root",
        str(tmp_path),
        "--all-configured-tickers",
        "--json-out",
        "reports/d6/full-bot-failure-determination-matrix-20260610.json",
        "--markdown-out",
        "reports/d6/full-bot-failure-determination-matrix-20260610.md",
    ]
    subprocess.run(cmd, check=True)
    assert (reports / "full-bot-failure-determination-matrix-20260610.json").exists()
    assert (reports / "full-bot-failure-determination-matrix-20260610.md").exists()
    bad = [
        sys.executable,
        "tools/build_full_bot_failure_determination_matrix.py",
        "--root",
        str(tmp_path),
        "--all-configured-tickers",
        "--json-out",
        "../bad.json",
        "--markdown-out",
        "reports/d6/ok.md",
    ]
    failed = subprocess.run(bad, text=True, capture_output=True)
    assert failed.returncode != 0
    assert "Refusing to write outside reports/d6" in failed.stderr or "Refusing to write outside reports/d6" in failed.stdout
