from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.full_bot_workflow_completeness_audit import (
    REQUIRED_MODULES,
    REQUIRED_TESTS,
    REQUIRED_TOOLS,
    build_full_bot_workflow_completeness_audit,
)
from tools.build_live_learning_sidecar import build_live_learning_sidecar_report


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def test_live_learning_sidecar_bundles_existing_learning_reports(tmp_path: Path) -> None:
    _write_json(tmp_path / "state/decision_outcomes.json", {"outcomes": [{"ticker": "BTC-USDC"}]})
    _write_json(
        tmp_path / "logs/decision_outcome_report.json",
        {"missed_opportunities": [{"ticker": "BTC-USDC"}], "false_positive_plans": [], "correct_avoids": []},
    )
    (tmp_path / "logs/execution_outcomes.jsonl").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "logs/execution_outcomes.jsonl").write_text(
        json.dumps({"primary_label": "missed_fill_opportunity", "labels": ["missed_fill_opportunity"]}) + "\n",
        encoding="utf-8",
    )
    _write_json(tmp_path / "logs/trade_learning_report.json", {"d5": "ok"})
    _write_json(tmp_path / "reports/d6/d6-metrics-foundation-20260611.json", {"phase": "D6_metrics_foundation_v1", "warnings": ["too_few_trades"]})
    _write_json(tmp_path / "reports/d6/d6-shadow-learning-report-20260611.json", {"phase": "d6_shadow_learning_report_v1"})

    report = build_live_learning_sidecar_report(root=tmp_path, generated_at="2026-06-11T00:00:00Z")

    assert report["report_only"] is True
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["parameter_mutation_performed"] is False
    assert report["learning_to_execution_bridge_created"] is False
    assert report["decision_outcomes"]["state_records"] == 1
    assert report["execution_outcomes"]["label_counts"]["missed_fill_opportunity"] == 1
    assert report["d5_metrics"] == {"d5": "ok"}
    assert report["d6_metrics"]["phase"] == "D6_metrics_foundation_v1"
    assert report["parameter_recommendations"]


def test_sidecar_watch_does_not_activate_profile_or_mutate_parameters(tmp_path: Path) -> None:
    _write_json(
        tmp_path / "logs/decision_outcome_report.json",
        {"missed_opportunities": [{"ticker": "BTC-USDC"}], "false_positive_plans": [], "correct_avoids": []},
    )

    report = build_live_learning_sidecar_report(root=tmp_path, generated_at="2026-06-11T00:00:00Z")

    assert report["classification"] == "WATCH"
    assert report["approved_parameter_profile_written"] is False
    assert report["parameter_mutation_performed"] is False
    assert report["learning_to_execution_allowed"] is False
    assert report["governance"]["no_automatic_parameter_mutation"] is True


def test_full_workflow_validator_baseline_remains_green(tmp_path: Path) -> None:
    for rel in list(REQUIRED_MODULES.values()) + list(REQUIRED_TOOLS.values()) + list(REQUIRED_TESTS.values()):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    for rel in [
        "docs/CODEX_PROJECT_CONTEXT.md",
        "docs/FULL_BOT_ORCHESTRATOR.md",
        "docs/FULL_BOT_FAILURE_DETERMINATION.md",
        "docs/OPERATOR_24H_LIVE_TEST_RUNBOOK.md",
    ]:
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")
    _write_json(tmp_path / "state/open_orders.json", {"orders": []})
    _write_json(tmp_path / "state/positions.json", {})

    report = build_full_bot_workflow_completeness_audit(
        root=tmp_path,
        report_payloads={
            "full_bot_failure_determination_matrix": {
                "matrix": [{"ticker": "BTC-USDC"}],
                "summary": {
                    "any_ticker_phase_c_ready_now": True,
                    "phase_c_ready_tickers": ["BTC-USDC"],
                    "all_p0_items": [],
                    "top_all_ticker_fresh_judge_candidates": [],
                    "top_all_ticker_deterministic_risk_candidates": [],
                    "top_all_ticker_refresh_candidates": [],
                },
            }
        },
    )
    assert report["readiness_verdict"] == "ready_for_ack_gated_maker_buy_live_submit"
    assert report["first_real_maker_buy_live_submit_allowed_now"] is True
    assert report["report_only"] is True
