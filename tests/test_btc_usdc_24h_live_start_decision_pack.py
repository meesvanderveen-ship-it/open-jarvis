from __future__ import annotations

import json
from pathlib import Path

from bot.phase_btc_usdc_24h_live_start_decision_pack import (
    build_btc_usdc_24h_live_start_decision_pack,
    render_btc_usdc_24h_live_start_decision_pack_markdown,
)


def _write(path: Path, payload: dict | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")


def _write_state(root: Path, *, open_order: bool = False) -> None:
    orders = {}
    if open_order:
        orders["open"] = {"client_order_id": "open", "ticker": "BTC-USDC", "side": "BUY", "status": "submitted"}
    _write(root / "state/open_orders.json", {"orders": orders})
    _write(root / "state/positions.json", {"BTC-USDC": {"position_size_base": "0"}})


def _write_tools(root: Path) -> None:
    for rel in (
        "tools/run_safe_regression_harness.py",
        "tools/show_open_orders.py",
        "tools/show_function_preservation_audit.py",
        "tools/operator_btc_usdc_tiny_env.sh",
        "tools/show_btc_usdc_tiny_live_preflight.py",
        "tools/show_btc_usdc_24h_live_monitor.py",
        "tools/build_btc_usdc_24h_post_run_evidence_pack.py",
        "run_trader_loop.py",
        "tests/test_btc_usdc_24h_monitor.py",
    ):
        _write(root / rel, "# fixture\n")


def _write_reports(root: Path, *, selected: str = "OK", remaining_local: int = 0) -> None:
    d6 = root / "reports/d6"
    _write(
        d6 / "safe-regression-harness-20260609.json",
        {
            "classification": "WATCH",
            "readiness_flags": {"local_safe_regression_passed": True},
            "selected_tests": {
                "selected_tests_classification": selected,
                "selected_tests_passed_count": 25 if selected == "OK" else 24,
                "selected_tests_failed_count": 0 if selected == "OK" else 1,
            },
        },
    )
    _write(
        d6 / "operator-24h-prerun-build-checklist-20260609.json",
        {
            "governance_flags": {
                "operator_24h_prerun_build_checklist_ready": True,
                "build_complete_for_operator_live_start_review": True,
            }
        },
    )
    _write(
        d6 / "unresolved-blocker-ledger-20260609.json",
        {"governance_flags": {"unresolved_blocker_ledger_ready": True, "remaining_locally_buildable_item_count": remaining_local}},
    )
    _write(
        d6 / "roadmap-readiness-decision-map-20260609.json",
        {"governance_flags": {"roadmap_readiness_decision_map_ready": True}},
    )
    _write(d6 / "d6-shadow-learning-report-20260609.json", {"phase": "shadow"})
    _write(d6 / "controlled-learning-governance-20260609.json", {"phase": "controlled"})


def _ready_root(root: Path) -> None:
    _write_state(root)
    _write_tools(root)
    _write_reports(root)


def test_ready_for_operator_fresh_preflight_but_not_live_authorized(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["decision_status"] == "ready_for_operator_fresh_preflight"
    assert report["ready_for_operator_fresh_preflight"] is True
    assert report["governance_flags"]["live_start_authorized"] is False
    assert report["governance_flags"]["operator_manual_start_required"] is True
    assert report["governance_flags"]["codex_must_not_start_live_test"] is True


def test_no_live_or_mutation_side_effect_flags(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    meta = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["order_action_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert meta["learning_to_execution_performed"] is False


def test_learning_all_ticker_and_follower_remain_false(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    flags = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )["governance_flags"]

    assert flags["learning_to_execution_ready"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["all_ticker_live_allowed_now"] is False
    assert flags["follower_ready_for_live"] is False


def test_missing_command_template_fails_safe(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    (tmp_path / "tools/show_btc_usdc_tiny_live_preflight.py").unlink()

    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["decision_status"] == "not_ready_local_blockers"
    assert "missing_command_template" in report["current_safety_state"]["blockers"]


def test_open_orders_nonzero_blocks_stop_now(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    _write_state(tmp_path, open_order=True)

    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["decision_status"] == "blocked_by_STOP"
    assert "open_orders_nonzero" in report["current_safety_state"]["blockers"]


def test_selected_tests_not_ok_blocks(tmp_path: Path) -> None:
    _write_state(tmp_path)
    _write_tools(tmp_path)
    _write_reports(tmp_path, selected="STOP_NOW")

    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["decision_status"] == "not_ready_local_blockers"
    assert "selected_tests_not_ok" in report["current_safety_state"]["blockers"]


def test_remaining_local_items_block(tmp_path: Path) -> None:
    _write_state(tmp_path)
    _write_tools(tmp_path)
    _write_reports(tmp_path, remaining_local=1)

    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["decision_status"] == "not_ready_local_blockers"
    assert "local_build_closure_incomplete" in report["current_safety_state"]["blockers"]


def test_malformed_reports_fail_safe(tmp_path: Path) -> None:
    _write_state(tmp_path)
    _write_tools(tmp_path)
    _write(tmp_path / "reports/d6/safe-regression-harness-20260609.json", "not-json")

    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["decision_status"] == "not_ready_local_blockers"
    assert "selected_tests_not_ok" in report["current_safety_state"]["blockers"]


def test_operator_commands_are_marked_codex_must_not_run(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    report = build_btc_usdc_24h_live_start_decision_pack(
        root=tmp_path,
        function_audit_report={"overall_status": "ok_observe_only"},
    )

    assert report["operator_only_commands_do_not_run_by_codex"]
    assert all(row["codex_must_not_run"] for row in report["operator_only_commands_do_not_run_by_codex"])
    assert any("run_trader_loop.py" in row["command"] for row in report["operator_only_commands_do_not_run_by_codex"])


def test_markdown_renders_operator_only_section(tmp_path: Path) -> None:
    _ready_root(tmp_path)
    markdown = render_btc_usdc_24h_live_start_decision_pack_markdown(
        build_btc_usdc_24h_live_start_decision_pack(
            root=tmp_path,
            function_audit_report={"overall_status": "ok_observe_only"},
        )
    )

    assert "BTC-USDC 24h Live-Start Decision Pack" in markdown
    assert "OPERATOR ONLY - CODEX MUST NOT RUN" in markdown
