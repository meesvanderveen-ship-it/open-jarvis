from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_fill_realism_assumptions import build_phase_d6_fill_realism_assumption_report
from bot.phase_d6_fill_realism_evidence_adapter import build_phase_d6_fill_realism_evidence_report


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


def test_fill_realism_evidence_adapter_maps_rows_to_d6_evidence(tmp_path: Path):
    source = _write_json(
        tmp_path / "research" / "orders.json",
        [
            {
                "product_id": "BTC-USDC",
                "order_label": "TP_CLOSE",
                "side": "SELL",
                "limit_price": "110",
                "reference_bid": "100",
                "reference_ask": "100.1",
                "base_size": "1",
                "cancel_replace_count": 2,
            }
        ],
    )
    fill_report = build_phase_d6_fill_realism_assumption_report(input_paths=[source])

    evidence = build_phase_d6_fill_realism_evidence_report(fill_realism_reports=[fill_report])

    assert evidence["status"] == "d6_fill_realism_evidence_ready"
    assert evidence["evidence_row_count"] == 1
    assert evidence["evidence_category_counts"]["fill_probability_context"] == 1
    assert evidence["evidence_category_counts"]["cancel_replace_churn"] == 1
    assert evidence["parameter_category_counts"]["d4_dynamic_order_management"] >= 1
    assert evidence["evidence_rows"][0]["parameter_change_allowed"] is False
    _assert_safe(evidence)


def test_fill_realism_evidence_cli_can_build_from_raw_input(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    source = _write_json(
        tmp_path / "research" / "orders.json",
        [{"product_id": "BTC-USDC", "side": "SELL", "limit_price": "110", "reference_bid": "100", "reference_ask": "100.1", "base_size": "0.01"}],
    )

    result = subprocess.run(
        [sys.executable, "tools/show_phase_d6_fill_realism_evidence_adapter.py", "--input", str(source), "--json"],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    report = json.loads(result.stdout)
    assert result.stderr == ""
    assert report["evidence_row_count"] == 1
    _assert_safe(report)
