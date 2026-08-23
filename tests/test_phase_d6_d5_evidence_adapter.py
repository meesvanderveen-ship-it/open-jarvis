from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_d5_evidence_adapter import build_phase_d6_d5_evidence_adapter_report


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


def test_adapter_maps_d5_metrics_to_evidence_rows(tmp_path: Path):
    source = tmp_path / "reports" / "d5_metrics.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "event_type": "phase_d5_execution_metric",
                "ticker": "BTC-USDC",
                "order_label": "TP_CLOSE",
                "lifecycle_stage": "filled",
                "is_complete_lifecycle_event": True,
                "fill_count": 1,
                "filled_quote": "4.81",
                "fee_quote": "0.01",
                "slippage_vs_decision_mid_pct": "0.02",
            }
        ),
        encoding="utf-8",
    )

    report = build_phase_d6_d5_evidence_adapter_report(input_paths=[source])

    assert report["status"] == "d6_d5_evidence_ready"
    assert report["evidence_row_count"] >= 4
    assert report["evidence_category_counts"]["fill_quality"] >= 1
    assert report["evidence_category_counts"]["slippage_fee_realization"] >= 1
    assert report["evidence_category_counts"]["tiny_notional_lifecycle_overhead"] >= 1
    assert report["parameter_category_counts"]["d5_execution_learning"] >= 1
    assert all(row["parameter_change_allowed"] is False for row in report["evidence_rows"])
    _assert_safe(report)


def test_adapter_reads_jsonl_learning_and_lifecycle_events(tmp_path: Path):
    source = tmp_path / "learning.jsonl"
    events = [
        {
            "event_type": "d5_learning_event",
            "ticker": "ETH-USDC",
            "client_order_id": "example-TP1",
            "lifecycle_branch": "OPEN/open keep_open",
            "no_fill_duration_seconds": 900,
            "stale_order_age_seconds": 900,
            "target_distance_pct": "1.5",
        },
        {
            "event_type": "phase_d4_controlled_cancel_replace_replacement_submitted",
            "product_id": "ETH-USDC",
            "client_order_id": "example-TP1-repl",
            "cancel_replace_outcome": "replacement_submitted",
        },
    ]
    source.write_text("\n".join(json.dumps(event) for event in events), encoding="utf-8")

    report = build_phase_d6_d5_evidence_adapter_report(input_paths=[source])

    assert report["source_summary"][0]["source_type"] == "d5_learning_log"
    assert report["evidence_category_counts"]["no_fill_duration"] >= 1
    assert report["evidence_category_counts"]["cancel_replace_outcome"] >= 1
    assert "d4_dynamic_order_management" in report["parameter_category_counts"]
    _assert_safe(report)


def test_adapter_refuses_state_paths(tmp_path: Path):
    source = tmp_path / "state" / "events.jsonl"
    source.parent.mkdir()
    source.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_d5_evidence_adapter_report(input_paths=[source])


def test_cli_stdout_only(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    source = tmp_path / "evidence.jsonl"
    source.write_text(json.dumps({"event_type": "filled", "ticker": "BTC-USDC", "fill_count": 1}), encoding="utf-8")

    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_d5_evidence_adapter.py", "--input", str(source), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["evidence_row_count"] >= 1
    _assert_safe(report)
