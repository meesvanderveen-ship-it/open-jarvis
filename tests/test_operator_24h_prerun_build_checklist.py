from __future__ import annotations

import json
from pathlib import Path

from bot.phase_operator_24h_prerun_build_checklist import (
    build_operator_24h_prerun_build_checklist,
    render_operator_24h_prerun_build_checklist_markdown,
)


def _write(path: Path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _write_ready_sources(root: Path) -> None:
    _write(root / "tests/test_btc_usdc_24h_monitor.py", "def test_ok(): pass\n")
    _write(root / "tools/show_btc_usdc_24h_live_monitor.py", "# monitor\n")
    _write(root / "tools/build_btc_usdc_24h_post_run_evidence_pack.py", "# post run\n")
    d6 = root / "reports" / "d6"
    _write(d6 / "roadmap-readiness-decision-map-20260609.json", {"phase": "map"})
    _write(d6 / "controlled-learning-governance-20260609.json", {"phase": "governance"})
    _write(d6 / "d6-shadow-learning-report-20260609.json", {"phase": "shadow"})
    _write(
        d6 / "safe-regression-harness-20260609.json",
        {
            "classification": "WATCH",
            "selected_tests": {"selected_tests_classification": "OK"},
            "open_order_summary": {"open_orders": 0, "open_d3_exit": 0},
            "readiness_flags": {
                "master_ready_for_operator_preflight": True,
                "learning_to_execution_ready": False,
                "parameter_change_allowed": False,
                "all_ticker_live_allowed_now": False,
                "follower_ready_for_live": False,
            },
            "report_references": {},
        },
    )


def test_checklist_can_be_build_complete_without_live_authorization(tmp_path: Path) -> None:
    _write_ready_sources(tmp_path)
    report = build_operator_24h_prerun_build_checklist(root=tmp_path)
    flags = report["governance_flags"]

    assert report["status"] == "build_complete_for_operator_live_start_review"
    assert flags["build_complete_for_operator_live_start_review"] is True
    assert flags["live_start_authorized"] is False
    assert flags["operator_manual_start_required"] is True
    assert flags["codex_must_not_start_24h_test"] is True


def test_missing_monitor_test_makes_checklist_incomplete(tmp_path: Path) -> None:
    _write_ready_sources(tmp_path)
    (tmp_path / "tests/test_btc_usdc_24h_monitor.py").unlink()

    report = build_operator_24h_prerun_build_checklist(root=tmp_path)

    assert report["status"] == "build_incomplete"
    assert any(row["name"] == "monitor test exists" for row in report["failed_checks"])


def test_learning_parameter_all_ticker_and_follower_gates_remain_closed(tmp_path: Path) -> None:
    _write_ready_sources(tmp_path)
    flags = build_operator_24h_prerun_build_checklist(root=tmp_path)["governance_flags"]

    assert flags["learning_to_execution_ready"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["all_ticker_live_allowed_now"] is False
    assert flags["follower_ready_for_live"] is False


def test_checklist_no_external_or_state_side_effects(tmp_path: Path) -> None:
    _write_ready_sources(tmp_path)
    meta = build_operator_24h_prerun_build_checklist(root=tmp_path)["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert meta["live_run_started"] is False


def test_checklist_markdown_renders(tmp_path: Path) -> None:
    _write_ready_sources(tmp_path)
    markdown = render_operator_24h_prerun_build_checklist_markdown(
        build_operator_24h_prerun_build_checklist(root=tmp_path)
    )

    assert "Operator 24h Pre-Run Build Checklist" in markdown
    assert "live_start_authorized" in markdown
