from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d6_controlled_live_test_audit_plan import (
    build_controlled_live_test_audit_plan,
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


def test_controlled_live_test_audit_plan_classifies_gaps(tmp_path: Path):
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
        json.dumps(
            {
                "event_type": "d3_live_exit_reconciled",
                "order": {
                    "ticker": "BTC-USDC",
                    "product_id": "BTC-USDC",
                    "mode": "live",
                    "live_order_submitted": True,
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )
    report = build_controlled_live_test_audit_plan(
        config_text='"ALLOWED_TICKERS", ("BTC-USDC,ETH-USDC") ,',
        order_events_path=events,
        coverage_manifest_paths=[coverage],
        final_readiness_packet={"content": {"final_status": "ready_for_future_prompt_review_ack_required"}},
        live_readiness_report={"content": {"overall_status": "readiness_plan_ready_future_live_test_requires_exact_ack"}},
        governance_evidence_report={"content": {"overall_status": "pass", "historical_evidence_summary": {"evidence_row_count": 1}}},
        state_hashes_before={"state/open_orders.json": "a"},
        state_hashes_after={"state/open_orders.json": "a"},
    )

    assert report["backlearning_status"]["actual_parameter_search_performed"] is False
    assert report["backlearning_status"]["learning_to_execution_enabled"] is False
    assert report["crypto_coverage_status"]["d6_coverage"]["covered_tickers"] == ["BTC-USDC"]
    assert report["crypto_coverage_status"]["missing_d6_coverage_tickers"] == ["ETH-USDC"]
    assert report["chosen_future_route"]["route"] == "C_observe_then_one_controlled_micro_order_if_preflight_passes"
    assert "required_live_boundary_acks_missing" in report["blockers"]
    _assert_safe(report)
