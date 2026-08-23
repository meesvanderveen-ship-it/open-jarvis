from __future__ import annotations

from pathlib import Path

from bot.full_bot_workflow_completeness_audit import (
    REQUIRED_MODULES,
    REQUIRED_TESTS,
    REQUIRED_TOOLS,
    build_full_bot_workflow_completeness_audit,
    render_full_bot_workflow_completeness_audit_markdown,
)


def _touch(root: Path, rel: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{}\n", encoding="utf-8")


def _complete_tree(root: Path) -> None:
    for rel in list(REQUIRED_MODULES.values()) + list(REQUIRED_TOOLS.values()) + list(REQUIRED_TESTS.values()):
        _touch(root, rel)
    for rel in [
        "docs/CODEX_PROJECT_CONTEXT.md",
        "docs/FULL_BOT_ORCHESTRATOR.md",
        "docs/FULL_BOT_FAILURE_DETERMINATION.md",
        "docs/OPERATOR_24H_LIVE_TEST_RUNBOOK.md",
    ]:
        _touch(root, rel)
    (root / "reports/d6").mkdir(parents=True, exist_ok=True)
    _touch(root, "state/open_orders.json")
    _touch(root, "state/positions.json")


def test_report_only_flags_and_required_fields(tmp_path: Path) -> None:
    _complete_tree(tmp_path)
    report = build_full_bot_workflow_completeness_audit(root=tmp_path)
    assert report["report_only"] is True
    assert report["live_order_submit_attempted"] is False
    assert report["coinbase_write_attempted"] is False
    assert report["state_write_performed"] is False
    assert "workflow_sections" in report
    assert "module_presence" in report
    assert "state_hashes" in report


def test_missing_required_tool_blocks_as_incomplete(tmp_path: Path) -> None:
    _complete_tree(tmp_path)
    (tmp_path / "tools/build_full_bot_orchestrator_report.py").unlink()
    report = build_full_bot_workflow_completeness_audit(root=tmp_path)
    assert report["readiness_verdict"] == "blocked_by_missing_module_or_tool"
    assert report["classification"] == "incomplete_due_missing_module_tool_or_test"


def test_fresh_judge_and_risk_blocker_wins_when_stack_present(tmp_path: Path) -> None:
    _complete_tree(tmp_path)
    report = build_full_bot_workflow_completeness_audit(
        root=tmp_path,
        report_payloads={
            "full_bot_failure_determination_matrix": {
                "matrix": [{"ticker": "XRP-USDC"}],
                "summary": {
                    "any_ticker_phase_c_ready_now": False,
                    "phase_c_ready_tickers": [],
                    "all_p0_items": [],
                    "top_all_ticker_fresh_judge_candidates": ["XRP-USDC"],
                    "top_all_ticker_deterministic_risk_candidates": ["XRP-USDC"],
                    "top_all_ticker_refresh_candidates": ["XRP-USDC"],
                },
            }
        },
    )
    assert report["readiness_verdict"] == "blocked_by_missing_fresh_judge_and_risk"
    assert report["first_real_maker_buy_live_submit_allowed_now"] is False
    assert report["any_ticker_phase_c_ready_now"] is False


def test_phase_c_ready_candidate_can_be_ready_only_without_p0_or_fresh_blockers(tmp_path: Path) -> None:
    _complete_tree(tmp_path)
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
    assert report["sell_market_should_remain_disabled"] is True


def test_markdown_contains_stop_signals_and_commands(tmp_path: Path) -> None:
    _complete_tree(tmp_path)
    report = build_full_bot_workflow_completeness_audit(root=tmp_path)
    text = render_full_bot_workflow_completeness_audit_markdown(report)
    assert "Full Bot Workflow Completeness Audit v1" in text
    assert "DO NOT RUN NOW" in text
    assert "live_order_submit_attempted" in text
