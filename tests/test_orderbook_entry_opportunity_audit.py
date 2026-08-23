from __future__ import annotations

import json
from pathlib import Path

from tools.build_orderbook_entry_opportunity_audit import build_orderbook_entry_opportunity_audit, build_workflow_audit, main


def _append(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _row(ticker: str = "ETH-USDC", *, with_level: bool = True, with_target: bool = True) -> dict:
    plan = {
        "plan_action": "prepare_buy",
        "side": "BUY",
        "setup_type": "reclaim_retest",
        "entry_zone_low": "99.50" if with_level else None,
        "entry_zone_high": "100.00" if with_level else None,
        "do_not_chase_above": "100.80",
        "invalidation_price": "98.00",
        "stop_loss": "98.00",
        "take_profit_1": "104.00" if with_target else None,
        "max_quote_size": "20.00",
        "trigger": "trigger_not_ready: wait for reclaim retest",
    }
    return {
        "generated_at": "2026-06-15T14:00:00Z",
        "ticker": ticker,
        "trade_plan": plan,
        "judge": {
            "decision": "wait",
            "side": "NONE",
            "setup_type": "reclaim_retest",
            "trigger_wait_reason": "trigger_not_ready: fresh reclaim confirmation missing",
            "judge_reasons": ["trigger_not_ready but setup has retest level"],
        },
        "feature_pack": {
            "market": {"best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75", "spread_pct": "0.0002"},
            "orderbook_context": {"snapshot_available": True, "best_bid": "99.74", "best_ask": "99.76", "mid_price": "99.75"},
            "decision_context": {
                "product_rules": {
                    "product_id": ticker,
                    "price_increment": "0.01",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "base_min_size": "0.00000001",
                    "quote_min_size": "1.00",
                },
                "recent_exchange_rejections": [],
            },
        },
    }


def test_orderbook_entry_opportunity_audit_counts_qualified_waits(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", _row())
    _append(tmp_path / "logs/analysis.jsonl", _row("BTC-USDC", with_level=False))
    _append(tmp_path / "logs/analysis.jsonl", _row("SOL-USDC", with_target=False))

    report = build_orderbook_entry_opportunity_audit(root=tmp_path, since="2026-06-15T13:35:00Z")
    assert report["decision_rows_total"] == 3
    assert report["wait_trigger_not_ready"] == 3
    assert report["valid_trade_plans"] == 3
    assert report["setups_with_concrete_entrylevel"] == 2
    assert report["setups_with_invalidation"] == 3
    assert report["setups_with_target_or_exit_thesis"] == 2
    assert report["resting_limit_entry_qualified"] == 1
    assert report["precision_context_audit"]["planner_judge_rows_with_product_rules"] == 3
    assert report["precision_context_audit"]["planner_judge_rows_with_execution_feasibility"] == 3
    assert report["coinbase_call_attempted"] is False
    assert "entry_level_missing" in report["not_qualified_reason_counts"]
    assert "target_level_missing" in report["not_qualified_reason_counts"]


def test_orderbook_entry_opportunity_tool_writes_reports(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", _row())
    assert main(["--root", str(tmp_path), "--since", "2026-06-15T13:35:00Z", "--json"]) == 0
    assert (tmp_path / "reports/audits/orderbook-entry-opportunity-audit-latest.json").exists()
    assert (tmp_path / "reports/audits/orderbook-entry-opportunity-audit-latest.md").exists()
    assert (tmp_path / "reports/audits/orderbook-entry-workflow-audit-latest.json").exists()
    assert (tmp_path / "reports/audits/orderbook-entry-workflow-audit-latest.md").exists()
    workflow = build_workflow_audit(build_orderbook_entry_opportunity_audit(root=tmp_path))
    assert workflow["read_only"] is True
    assert "pending_entry_created_preview" in workflow["lifecycle_model"]


def test_orderbook_entry_opportunity_no_data_json_contract(tmp_path: Path) -> None:
    report = build_orderbook_entry_opportunity_audit(root=tmp_path, since="2026-06-15T13:35:00Z")
    assert report["decision_rows_total"] == 0
    assert report["rows"] == 0
    assert report["stdout_valid"] is True
    assert report["audit_window_valid"] is True
    assert report["recommendation"] in {"no_recent_full_cycle", "insufficient_new_data"}
    assert report["reason"] in {"no_full_cycle_since_since_time", "no_decision_rows_in_checked_sources"}
    assert "logs/analysis.jsonl" in report["data_sources_checked"]


def test_orderbook_entry_opportunity_relative_since_and_source_breakdown(tmp_path: Path) -> None:
    _append(tmp_path / "logs/analysis.jsonl", _row())
    report = build_orderbook_entry_opportunity_audit(root=tmp_path, since="24 hours ago")
    assert report["audit_window_valid"] is True
    assert report["stdout_valid"] is True
    assert report["source_breakdown"]
