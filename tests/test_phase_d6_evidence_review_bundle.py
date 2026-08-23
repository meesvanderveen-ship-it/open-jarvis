from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from bot.phase_d6_d5_evidence_adapter import build_phase_d6_d5_evidence_adapter_report
from bot.phase_d6_evidence_review_bundle import build_phase_d6_evidence_review_bundle
from bot.phase_d6_fill_realism_assumptions import build_phase_d6_fill_realism_assumption_report
from bot.phase_d6_fill_realism_evidence_adapter import build_phase_d6_fill_realism_evidence_report
from bot.phase_d6_regime_segmentation import build_phase_d6_regime_segmentation_report


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


def _candle(index: int, close: float):
    return {
        "product_id": "BTC-USDC",
        "timeframe": "1D",
        "start": index * 86400,
        "open": str(close),
        "high": str(close * 1.01),
        "low": str(close * 0.99),
        "close": str(close),
        "volume": "10",
    }


def test_combined_bundle_summarizes_inventory_d5_and_regime(tmp_path: Path):
    d5_source = _write_json(
        tmp_path / "research" / "d5.json",
        {"event_type": "filled", "ticker": "BTC-USDC", "order_label": "TP_CLOSE", "fill_count": 1, "filled_quote": "5"},
    )
    d5_report = build_phase_d6_d5_evidence_adapter_report(input_paths=[d5_source])
    candles = _write_json(tmp_path / "research" / "candles.json", [_candle(i, 100 + i * 2) for i in range(30)])
    regime_report = build_phase_d6_regime_segmentation_report(candle_path=candles, window_size=10, step_size=10)

    bundle = build_phase_d6_evidence_review_bundle(
        d5_evidence_reports=[d5_report],
        regime_reports=[regime_report],
    )

    assert bundle["status"] == "d6_combined_evidence_review_bundle_ready"
    assert bundle["parameter_inventory_summary"]["candidate_count"] >= 50
    assert bundle["d5_evidence_summary"]["evidence_row_count"] >= 2
    assert bundle["regime_summary"]["regime_window_count"] == 3
    assert bundle["review_readiness"] in {"exploratory_only", "ready_for_human_research_review"}
    assert "do_not_infer_parameter_change" in bundle["prohibited_interpretations"]
    _assert_safe(bundle)


def test_combined_bundle_can_load_report_paths_from_cli(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    d5_report = {
        "evidence_row_count": 1,
        "evidence_category_counts": {"fill_quality": 1},
        "parameter_category_counts": {"d5_execution_learning": 1},
        "evidence_strength_counts": {"medium": 1},
        "warnings": [],
        "blockers": [],
        "research_only": True,
        "contains_rankings": False,
        "contains_recommendations": False,
        "contains_live_instructions": False,
    }
    regime_report = {
        "regime_window_count": 1,
        "regime_counts": {"range": 1},
        "usable_for_future_research": True,
        "warnings": [],
        "blockers": [],
        "research_only": True,
    }
    d5_path = _write_json(tmp_path / "research" / "d5_report.json", d5_report)
    regime_path = _write_json(tmp_path / "research" / "regime_report.json", regime_report)

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_evidence_review_bundle.py",
            "--d5-evidence",
            str(d5_path),
            "--regime-report",
            str(regime_path),
            "--json",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    bundle = json.loads(result.stdout)
    assert result.stderr == ""
    assert bundle["source_summary"]["d5_evidence_report_count"] == 1
    assert bundle["source_summary"]["regime_report_count"] == 1
    _assert_safe(bundle)


def test_combined_bundle_v2_includes_fill_realism_evidence(tmp_path: Path):
    order_source = _write_json(
        tmp_path / "research" / "orders.json",
        [{"product_id": "BTC-USDC", "side": "SELL", "limit_price": "110", "reference_bid": "100", "reference_ask": "100.1", "base_size": "1"}],
    )
    fill_pack = build_phase_d6_fill_realism_assumption_report(input_paths=[order_source])
    fill_evidence = build_phase_d6_fill_realism_evidence_report(fill_realism_reports=[fill_pack])

    bundle = build_phase_d6_evidence_review_bundle(fill_realism_evidence_reports=[fill_evidence])

    assert bundle["phase"] == "D6_combined_evidence_review_bundle_v2"
    assert bundle["source_summary"]["fill_realism_evidence_report_count"] == 1
    assert bundle["fill_realism_summary"]["evidence_row_count"] == 1
    assert bundle["fill_realism_summary"]["evidence_category_counts"]["fill_probability_context"] == 1
    assert bundle["review_readiness"] == "exploratory_only"
    _assert_safe(bundle)


def test_combined_bundle_cli_accepts_fill_realism_evidence_path(tmp_path: Path):
    repo = Path(__file__).resolve().parents[1]
    fill_evidence = {
        "evidence_row_count": 1,
        "evidence_category_counts": {"post_only_fill_behavior": 1},
        "parameter_category_counts": {"d4_dynamic_order_management": 1},
        "evidence_strength_counts": {"medium": 1},
        "warnings": [],
        "blockers": [],
        "research_only": True,
    }
    fill_path = _write_json(tmp_path / "research" / "fill_evidence.json", fill_evidence)

    result = subprocess.run(
        [
            sys.executable,
            "tools/show_phase_d6_evidence_review_bundle.py",
            "--fill-realism-evidence",
            str(fill_path),
            "--json",
        ],
        cwd=repo,
        text=True,
        capture_output=True,
        check=True,
    )

    bundle = json.loads(result.stdout)
    assert result.stderr == ""
    assert bundle["source_summary"]["fill_realism_evidence_report_count"] == 1
    assert bundle["fill_realism_summary"]["evidence_row_count"] == 1
    _assert_safe(bundle)
