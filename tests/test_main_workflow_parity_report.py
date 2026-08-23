from __future__ import annotations

import json
from pathlib import Path

from bot.phase_main_workflow_parity_report import (
    build_main_workflow_parity_report,
    render_main_workflow_parity_markdown,
)


def _write_project(root: Path) -> None:
    (root / "bot").mkdir(parents=True)
    (root / "reports" / "d6").mkdir(parents=True)
    (root / "replication").mkdir(parents=True)
    (root / "bot" / "config.py").write_text(
        "ALLOWED_TICKERS='BTC-USDC,ETH-USDC,SOL-USDC'\n",
        encoding="utf-8",
    )
    for rel in (
        "bot/strategy_engine.py",
        "bot/phase_c43_autonomous_entry_live.py",
        "bot/phase_c45_live_fill_pilot.py",
        "bot/phase_d2_position_executor.py",
        "bot/phase_d3_controlled_live_exits.py",
        "bot/phase_d4_controlled_cancel_replace.py",
        "bot/phase_d5_d6_evidence_expansion.py",
        "bot/phase_d6_parameter_review_pack.py",
        "replication/models.py",
    ):
        (root / rel).write_text("# fixture\n", encoding="utf-8")
    (root / "reports" / "d6" / "all-ticker-readiness-gate-20260609.json").write_text(
        json.dumps(
            {
                "per_ticker_readiness_matrix": [
                    {"ticker": "BTC-USDC"},
                    {"ticker": "ETH-USDC"},
                    {"ticker": "SOL-USDC"},
                ]
            }
        ),
        encoding="utf-8",
    )
    (root / "logs").mkdir()
    (root / "logs" / "cycle_summary.jsonl").write_text(
        '{"ticker":"ETH-USDC","decision":"hold"}\n{"ticker":"SOL-USDC","decision":"hold"}\n',
        encoding="utf-8",
    )


def test_old_multi_ticker_decision_workflow_is_separate_from_lifecycle(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    rows = {row["ticker"]: row for row in report["configured_universe"]}

    assert rows["ETH-USDC"]["old_multi_ticker_decision_workflow_status"] == "seen"
    assert rows["ETH-USDC"]["new_lifecycle_orderbook_status"] == "missing"
    assert "new_lifecycle_orderbook_flow_not_proven_for_ticker" in rows["ETH-USDC"]["blockers"]


def test_btc_tiny_candidate_does_not_imply_all_ticker_live(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    gate = report["gate_decision"]
    rows = {row["ticker"]: row for row in report["configured_universe"]}

    assert gate["btc_usdc_tiny_scope_ready_for_operator_preflight"] is True
    assert rows["BTC-USDC"]["tiny_live_candidate_status"] == "candidate_ack_gated"
    assert gate["all_ticker_live_allowed_now"] is False


def test_non_btc_configured_tickers_are_not_treated_as_nonexistent(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    rows = {row["ticker"]: row for row in report["configured_universe"]}

    assert rows["ETH-USDC"]["configured"] is True
    assert rows["SOL-USDC"]["configured"] is True
    assert rows["ETH-USDC"]["old_multi_ticker_decision_workflow_status"] in {"seen", "probable"}
    assert rows["SOL-USDC"]["old_multi_ticker_decision_workflow_status"] in {"seen", "probable"}


def test_missing_lifecycle_evidence_blocks_live_readiness(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    rows = {row["ticker"]: row for row in report["configured_universe"]}

    assert rows["ETH-USDC"]["all_ticker_live_status"] == "blocked"
    assert report["gate_decision"]["all_ticker_lifecycle_parity_ready"] is False


def test_learning_and_parameter_flags_remain_false(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    backlearning = report["backlearning_parameter_section"]

    assert backlearning["learning_to_execution_ready"] is False
    assert backlearning["parameter_change_allowed"] is False
    assert backlearning["parameter_review_approved"] is False


def test_report_includes_bridge_next_steps(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    markdown = render_main_workflow_parity_markdown(report)

    assert report["bridge_plan"]
    assert "analysis-only -> paper lifecycle simulation" in markdown
    assert report["gate_decision"]["recommended_next_steps"]


def test_no_live_or_state_side_effect_flags(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_main_workflow_parity_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert meta["learning_to_execution_performed"] is False
