from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_workflow_ticker_audit import (
    build_phase_d6_workflow_ticker_audit,
    extract_default_allowed_tickers,
)


def _assert_safe(report):
    assert report["research_only"] is True
    assert report["no_coinbase_call"] is True
    assert report["no_live_action"] is True
    assert report["state_write_performed"] is False
    assert report["no_optimization"] is True
    assert report["parameter_search_performed"] is False
    assert report["parameter_change_allowed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["contains_rankings"] is False
    assert report["contains_recommendations"] is False
    assert report["contains_live_instructions"] is False
    assert report["human_review_required"] is True
    assert report["parameter_review_approved"] is False


def test_extract_default_allowed_tickers_from_config_snippet():
    text = '''allowed_tickers: list[str] = field(default_factory=lambda: _normalize_tickers(_split_csv(_get_optional_env(
        "ALLOWED_TICKERS",
        (
            "BTC-USDC,ETH-USDC,"
            "SOL-USDC"
        ),
    ))))'''
    assert extract_default_allowed_tickers(text) == ["BTC-USDC", "ETH-USDC", "SOL-USDC"]


def test_workflow_ticker_audit_classifies_btc_and_missing_multi_ticker_coverage(tmp_path: Path):
    coverage = tmp_path / "reports" / "d6" / "coverage.json"
    coverage.parent.mkdir(parents=True)
    coverage.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "ticker": "BTC-USDC",
                        "timeframe": "1D",
                        "study_window": "3y",
                        "candle_count": 350,
                        "gap_count": 0,
                        "learning_to_execution_allowed": False,
                        "parameter_change_allowed": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    events = tmp_path / "logs" / "order_events.jsonl"
    events.parent.mkdir(parents=True)
    events.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "event_type": "phase_c43_live_entry_filled",
                        "order": {
                            "ticker": "BTC-USDC",
                            "product_id": "BTC-USDC",
                            "side": "BUY",
                            "mode": "live",
                            "live_order_submitted": True,
                        },
                    }
                ),
                json.dumps(
                    {
                        "event_type": "d3_live_exit_reconciled",
                        "order": {
                            "ticker": "BTC-USDC",
                            "product_id": "BTC-USDC",
                            "side": "SELL",
                            "mode": "live",
                            "live_order_submitted": True,
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    report = build_phase_d6_workflow_ticker_audit(
        config_text='"ALLOWED_TICKERS", ("BTC-USDC,ETH-USDC,SOL-USDC") ,',
        order_events_path=events,
        coverage_manifest_paths=[coverage],
        final_readiness_packet={"content": {"final_status": "ready_for_future_prompt_review_ack_required"}},
        controlled_live_test_audit_plan={
            "content": {
                "status": "controlled_live_test_audit_plan_ready",
                "chosen_future_route": {"route": "C_observe_then_one_controlled_micro_order_if_preflight_passes"},
            }
        },
        state_hashes_before={"state/open_orders.json": "a"},
        state_hashes_after={"state/open_orders.json": "a"},
    )

    rows = {row["ticker"]: row for row in report["ticker_coverage_table"]}
    assert rows["BTC-USDC"]["readiness_classification"] == "live_workflow_proven"
    assert rows["BTC-USDC"]["entry_workflow_tested"] is True
    assert rows["BTC-USDC"]["exit_workflow_tested"] is True
    assert rows["ETH-USDC"]["readiness_classification"] == "configured_only_missing_coverage"
    assert rows["SOL-USDC"]["blocker_status_for_btc_usdc_only_live_test"] == "out_of_scope_for_first_live_test_non_blocking_warning"
    assert report["workflow_correctness_conclusion"]["btc_usdc_end_to_end_workflow_coherent"] is True
    assert report["workflow_correctness_conclusion"]["multi_ticker_live_workflow_coherent"] is False
    assert report["backlearning_audit"]["executed_on_all_configured_tickers"] is False
    assert "Gate_5_exact_live_test_ACK_missing" in report["blockers"]
    _assert_safe(report)
