from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from bot.phase_d6_fill_realism_assumptions import build_phase_d6_fill_realism_assumption_report


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


def _write_json(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_fill_realism_classifies_post_only_contexts(tmp_path: Path):
    source = _write_json(
        tmp_path / "research" / "orders.json",
        [
            {
                "product_id": "BTC-USDC",
                "order_label": "TP_CLOSE",
                "side": "SELL",
                "limit_price": "102",
                "reference_bid": "100",
                "reference_ask": "100.1",
                "base_size": "1",
                "no_fill_duration_seconds": 120,
            },
            {
                "product_id": "BTC-USDC",
                "order_label": "TP_CLOSE",
                "side": "SELL",
                "limit_price": "99",
                "reference_bid": "100",
                "reference_ask": "100.1",
                "base_size": "0.00001",
            },
        ],
    )

    report = build_phase_d6_fill_realism_assumption_report(input_paths=[source])

    assert report["status"] == "d6_fill_realism_assumption_report_ready"
    assert report["order_candidate_count"] == 2
    assert report["aggregate_summary"]["fill_realism_class_counts"]["plausible_maker_near_market"] == 1
    assert report["aggregate_summary"]["fill_realism_class_counts"]["tiny_notional_high_overhead"] == 1
    assert report["aggregate_summary"]["tiny_notional_count"] == 1
    assert report["aggregate_summary"]["evidence_category_counts"]["post_only_fill_behavior"] == 2
    assert report["aggregate_summary"]["evidence_category_counts"]["no_fill_duration"] == 1
    assert all(row["parameter_change_allowed"] is False for row in report["fill_realism_rows"])
    _assert_safe(report)


def test_fill_realism_marks_missing_orderbook_context(tmp_path: Path):
    source = _write_json(tmp_path / "research" / "orders.json", [{"product_id": "ETH-USDC", "side": "SELL", "limit_price": "2000"}])
    report = build_phase_d6_fill_realism_assumption_report(input_paths=[source])

    assert report["aggregate_summary"]["fill_realism_class_counts"]["insufficient_orderbook_context"] == 1
    assert report["aggregate_summary"]["evidence_strength_counts"]["insufficient"] == 1
    assert "missing_orderbook_context" in report["warning_counts"]
    _assert_safe(report)


def test_fill_realism_refuses_state_paths(tmp_path: Path):
    source = _write_json(tmp_path / "state" / "orders.json", [{"side": "SELL"}])
    with pytest.raises(ValueError, match="state"):
        build_phase_d6_fill_realism_assumption_report(input_paths=[source])


def test_fill_realism_cli_stdout_only(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    source = _write_json(
        tmp_path / "research" / "orders.json",
        [{"product_id": "BTC-USDC", "side": "SELL", "limit_price": "110", "reference_bid": "100", "reference_ask": "100.1", "base_size": "0.01"}],
    )

    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_fill_realism_assumptions.py", "--input", str(source), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["order_candidate_count"] == 1
    _assert_safe(report)
