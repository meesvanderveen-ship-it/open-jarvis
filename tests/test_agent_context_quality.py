from __future__ import annotations

import json
from pathlib import Path

from bot.agent_context_quality import build_agent_context_quality_report, build_context_matrix
from tools.build_agent_workflow_information_audit import build_agent_map, build_report


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def test_agent_context_quality_flags_precision_and_reject_reason_gap(tmp_path: Path) -> None:
    _append(
        tmp_path / "logs/analysis.jsonl",
        {
            "ticker": "ETH-USDC",
            "feature_pack": {
                "market": {"mid_price": "100", "spread_pct": "0.001"},
                "raw_context": {"1h": {"closes": [99, 100]}},
                "indicators": {"15m": {}, "1h": {"atr_14": "2"}, "4h": {}},
                "microstructure": {"1h": {"volume_vs_avg": "1.2"}},
                "structure": {"nearest_support": "98"},
                "decision_context": {"live_learning": {"enabled": True}},
                "risk_context": {"open_positions_count": 0},
            },
            "trade_plan": {"plan_action": "prepare_buy", "setup_type": "breakout_retest", "trigger": "retest", "stop_loss": "98"},
            "judge": {"decision": "wait", "confidence": 60, "setup_type": "breakout_retest"},
        },
    )
    matrix = build_context_matrix(tmp_path)
    by_field = {row["context_field"]: row for row in matrix}

    assert by_field["product_precision"]["priority"] == "P0"
    assert by_field["last_failed_submit_reason"]["priority"] == "P0"
    report = build_agent_context_quality_report(tmp_path)
    assert report["coinbase_call_attempted"] is False
    assert report["state_write_performed"] is False
    assert report["runtime_proof"]["decision_rows"] == 1


def test_agent_workflow_information_audit_contract() -> None:
    agent_map = build_agent_map()
    report = build_report(".")

    assert any(row["agent_or_component"] == "final judge" for row in agent_map)
    assert report["read_only"] is True
    assert report["coinbase_call_attempted"] is False
    assert "STATUS B" in report["readiness"]
    assert report["live_side_effects"] is False
