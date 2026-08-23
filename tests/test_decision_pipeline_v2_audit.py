from __future__ import annotations

import json
from pathlib import Path

from tools.build_decision_pipeline_v2_audit import build_decision_pipeline_v2_audit, main


def _append_jsonl(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload) + "\n")


def test_decision_pipeline_v2_reports_wait_reasons_and_skips(tmp_path: Path) -> None:
    _append_jsonl(
        tmp_path / "logs/analysis.jsonl",
        {
            "ticker": "BTC-USDC",
            "status": "no_trade",
            "feature_pack": {"ticker": "BTC-USDC", "entry_gate": {"decision": "analyze", "confidence": 55}},
            "entry_gate": {"decision": "analyze", "confidence": 55, "setup_type": "reclaim_reversal"},
            "trade_plan": {
                "plan_action": "no_plan",
                "reason": "Trade planner skipped because expensive judge gate skipped this setup",
                "objective_score": 42,
                "missing_trigger_reasons": ["trigger_ready_false"],
                "source": "trade_planner_skipped_by_expensive_judge_gate",
            },
            "judge": {
                "decision": "wait",
                "side": "NONE",
                "strategy": "mini_analysis_screened_no_expensive_judge",
                "confidence": 55,
                "setup_type": "reclaim_reversal",
                "reasons": ["gpt55_judge_not_called_because_setup_not_good_enough_after_mini_analysis"],
            },
        },
    )
    _append_jsonl(
        tmp_path / "logs/execution.jsonl",
        {"ticker": "BTC-USDC", "status": "no_trade", "executed": False, "reason": "judge_decision_wait"},
    )
    _append_jsonl(
        tmp_path / "logs/phase_c43_lifecycle_service.jsonl",
        {"generated_at": "2026-06-14T00:00:00Z", "summary": {"local_c43_open_orders_seen": 0, "local_d3_open_exit_orders_seen": 0}},
    )

    report = build_decision_pipeline_v2_audit(root=tmp_path)
    row = report["tickers"][0]

    assert report["read_only"] is True
    assert row["ticker"] == "BTC-USDC"
    assert row["planner_called"] is False
    assert row["planner_skip_reason"]
    assert row["objective_score"] == 42
    assert row["expensive_judge_called"] is False
    assert row["judge_skip_reason"]
    assert row["final_decision"] == "wait"
    assert row["live_order_submitted"] is False
    assert row["why_wait"] == "judge_decision_wait"
    assert row["next_condition_to_watch"] == "final_judge_approval_missing"


def test_decision_pipeline_v2_main_writes_reports(tmp_path: Path) -> None:
    _append_jsonl(
        tmp_path / "logs/analysis.jsonl",
        {"ticker": "ETH-USDC", "entry_gate": {"decision": "watch"}, "judge": {"decision": "wait", "side": "NONE"}},
    )
    json_out = tmp_path / "reports/audits/decision-pipeline-v2-latest.json"
    md_out = tmp_path / "reports/audits/decision-pipeline-v2-latest.md"

    code = main(["--root", str(tmp_path), "--json-out", str(json_out), "--md-out", str(md_out)])

    assert code == 0
    assert json_out.exists()
    assert md_out.exists()
    payload = json.loads(json_out.read_text(encoding="utf-8"))
    assert payload["coinbase_call_attempted"] is False
