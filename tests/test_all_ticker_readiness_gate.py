from __future__ import annotations

import json
from pathlib import Path

from bot.phase_all_ticker_readiness_gate import (
    build_all_ticker_readiness_gate_report,
    render_all_ticker_readiness_gate_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_config(root: Path, tickers: str = "BTC-USDC,ETH-USDC") -> None:
    path = root / "bot" / "config.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f'ALLOWED_TICKERS", "{tickers}"\n', encoding="utf-8")


def _write_state(root: Path, *, orders: dict | None = None) -> None:
    _write_json(root / "state" / "open_orders.json", {"orders": orders or {}})
    _write_json(root / "state" / "positions.json", {"BTC-USDC": {"ticker": "BTC-USDC", "status": "closed"}})


def _write_reports(root: Path, *, tickers: list[str] | None = None, btc_only: bool = False) -> None:
    tickers = tickers or ["BTC-USDC", "ETH-USDC"]
    reports = root / "reports" / "d6"
    _write_json(
        reports / "safe-regression-harness-20260609.json",
        {
            "local_safe_regression_passed": True,
            "readiness_flags": {
                "master_ready_for_operator_preflight": True,
                "follower_ready_for_paper_lifecycle_test": True,
                "state_hygiene_cleanup_preview_ready": True,
            },
        },
    )
    _write_json(
        reports / "d5-d6-evidence-expansion-20260609.json",
        {
            "readiness_and_governance_flags": {
                "d5_d6_evidence_expansion_ready": True,
                "learning_to_execution_ready": False,
                "parameter_change_allowed": False,
            }
        },
    )
    _write_json(reports / "exit-workflow-readiness-report-20260609.json", {"master_live_exit_ready": False})
    _write_json(reports / "core-lifecycle-evidence-gap-report-20260609.json", {"status": "ready"})
    _write_json(reports / "c4-d1-handoff-branch-map-20260609.json", {"target_ticker": "BTC-USDC"})
    _write_json(
        reports / "coverage-backtest-decision-v1-20260601.json",
        {"content": {"backtest_decision": {"normal_backtests_deferred": True}}},
    )
    _write_json(
        reports / "24h-readiness-master-packet-readonly-prelive-v1-20260602.json",
        {
            "content": {
                "go_no_go_matrix": {
                    "final_status": "ready_for_operator_scope_review",
                    "not_ready_for_live_reason": "max_notional_value_and_future_live_acks_missing",
                },
                "preflight": {"product_rules": {"coherent_for_future_scope_review": True}},
            }
        },
    )
    _write_json(
        reports / "replication-lifecycle-golden-payloads-20260609.json",
        {"follower_ready_for_paper_lifecycle_test": True, "simulator_validation_passed": True},
    )
    rows = []
    workflow_rows = []
    for ticker in tickers:
        is_btc = ticker == "BTC-USDC"
        has_lifecycle = is_btc and not btc_only or is_btc
        rows.append(
            {
                "ticker": ticker,
                "configured_in_universe": True,
                "candle_coverage_1h_4h_1d": True,
                "dataset_quality": True,
                "entry_workflow_evidence": has_lifecycle,
                "d2_d3_workflow_evidence": has_lifecycle,
                "lifecycle_evidence": has_lifecycle,
                "product_rules_availability_source_local": False,
            }
        )
        workflow_rows.append(
            {
                "ticker": ticker,
                "live_lifecycle_evidence_present": has_lifecycle,
                "readiness_classification": "live_workflow_proven" if is_btc else "configured_only_missing_coverage",
            }
        )
    _write_json(reports / "multi-ticker-workflow-equivalence-report-20260601.json", {"content": {"rows": rows}})
    _write_json(
        reports / "workflow-ticker-coverage-audit-20260601.json",
        {"content": {"ticker_coverage_table": workflow_rows}},
    )
    _write_json(
        reports / "multi-ticker-workflow-completion-checklist-20260601.json",
        {"content": {"rows": [{"ticker": ticker, "readiness_for_24h_inclusion": "blocked"} for ticker in tickers]}},
    )


def test_btc_only_evidence_keeps_all_ticker_not_ready(tmp_path: Path):
    _write_config(tmp_path, "BTC-USDC,ETH-USDC")
    _write_state(tmp_path)
    _write_reports(tmp_path, tickers=["BTC-USDC", "ETH-USDC"])

    report = build_all_ticker_readiness_gate_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["readiness_flags"]["btc_usdc_tiny_scope_ready_for_operator_preflight"] is True
    assert report["readiness_flags"]["all_ticker_ready"] is False
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False


def test_multiple_configured_tickers_without_lifecycle_evidence_are_blocked(tmp_path: Path):
    _write_config(tmp_path, "BTC-USDC,ETH-USDC,SOL-USDC")
    _write_state(tmp_path)
    _write_reports(tmp_path, tickers=["BTC-USDC", "ETH-USDC", "SOL-USDC"])

    report = build_all_ticker_readiness_gate_report(root=tmp_path)
    eth = next(row for row in report["per_ticker_readiness_matrix"] if row["ticker"] == "ETH-USDC")
    sol = next(row for row in report["per_ticker_readiness_matrix"] if row["ticker"] == "SOL-USDC")

    assert eth["all_ticker_live_status"] == "blocked"
    assert sol["all_ticker_live_status"] == "blocked"
    assert "missing_live_lifecycle_evidence" in eth["blockers"]
    assert report["gate_decision"]["tickers_blocked_count"] >= 2


def test_missing_product_rule_or_data_evidence_is_blocker_not_crash(tmp_path: Path):
    _write_config(tmp_path, "BTC-USDC,UNKNOWN-USDC")
    _write_state(tmp_path)
    _write_reports(tmp_path, tickers=["BTC-USDC"])

    report = build_all_ticker_readiness_gate_report(root=tmp_path)
    unknown = next(row for row in report["per_ticker_readiness_matrix"] if row["ticker"] == "UNKNOWN-USDC")

    assert unknown["data_coverage_status"] == "unknown"
    assert unknown["product_rule_status"] == "unknown"
    assert unknown["all_ticker_live_status"] == "blocked"
    assert any("unknown" in blocker for blocker in unknown["blockers"])


def test_btc_readiness_does_not_imply_all_ticker_readiness(tmp_path: Path):
    _write_config(tmp_path, "BTC-USDC,ETH-USDC")
    _write_state(tmp_path)
    _write_reports(tmp_path, tickers=["BTC-USDC", "ETH-USDC"])

    report = build_all_ticker_readiness_gate_report(root=tmp_path)

    assert report["btc_usdc_scope_status"]["btc_usdc_is_only_operator_ready_tiny_scope"] is True
    assert report["safety_distinctions"]["btc_usdc_tiny_readiness_does_not_imply_all_ticker_readiness"] is True
    assert report["readiness_flags"]["all_ticker_ready"] is False


def test_no_live_fetch_or_state_write_flags(tmp_path: Path):
    _write_config(tmp_path)
    _write_state(tmp_path)
    _write_reports(tmp_path)
    before_orders = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")
    before_positions = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")

    report = build_all_ticker_readiness_gate_report(root=tmp_path)

    assert report["coinbase_call_attempted"] is False
    assert report["market_data_fetch_attempted"] is False
    assert report["state_write_performed"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == before_orders
    assert (tmp_path / "state" / "positions.json").read_text(encoding="utf-8") == before_positions


def test_report_includes_required_readiness_flags(tmp_path: Path):
    _write_config(tmp_path)
    _write_state(tmp_path)
    _write_reports(tmp_path)

    report = build_all_ticker_readiness_gate_report(root=tmp_path)
    markdown = render_all_ticker_readiness_gate_markdown(report)

    for key in (
        "local_safe_regression_passed",
        "btc_usdc_tiny_scope_ready_for_operator_preflight",
        "master_ready_for_operator_preflight",
        "master_ready_for_operator_live_start",
        "master_live_exit_ready",
        "follower_ready_for_paper_lifecycle_test",
        "follower_ready_for_live",
        "follower_sell_ready",
        "lifecycle_parity_ready",
        "all_ticker_ready",
        "all_ticker_live_allowed_now",
        "learning_to_execution_ready",
        "parameter_change_allowed",
        "parameter_review_approved",
        "state_hygiene_cleanup_preview_ready",
        "state_hygiene_apply_ready",
    ):
        assert key in report["readiness_flags"]
        assert key in markdown


def test_empty_universe_fails_safe(tmp_path: Path):
    _write_state(tmp_path)
    _write_reports(tmp_path, tickers=["BTC-USDC"])

    report = build_all_ticker_readiness_gate_report(root=tmp_path, configured_tickers=[])

    assert report["classification"] == "STOP_NOW"
    assert report["readiness_flags"]["all_ticker_ready"] is False
    assert "configured_universe_empty_or_malformed" in report["gate_decision"]["all_ticker_blockers"]


def test_open_order_is_stop_now(tmp_path: Path):
    _write_config(tmp_path)
    _write_state(tmp_path, orders={"o1": {"ticker": "BTC-USDC", "side": "BUY", "status": "open"}})
    _write_reports(tmp_path)

    report = build_all_ticker_readiness_gate_report(root=tmp_path)

    assert report["classification"] == "STOP_NOW"
    assert "open_orders_present" in report["current_state_guard"]["stop_reasons"]
