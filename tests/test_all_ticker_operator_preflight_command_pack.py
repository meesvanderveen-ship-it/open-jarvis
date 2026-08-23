from __future__ import annotations

from pathlib import Path

from bot.phase_all_ticker_operator_preflight_command_pack import (
    build_all_ticker_operator_preflight_command_pack,
    render_all_ticker_operator_preflight_command_pack_markdown,
)


def _touch_tools(root: Path, names: list[str]) -> None:
    for name in names:
        path = root / "tools" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("#!/usr/bin/env python3\n", encoding="utf-8")


REQUIRED_TOOLS = [
    "run_safe_regression_harness.py",
    "show_open_orders.py",
    "show_function_preservation_audit.py",
    "show_all_ticker_24h_live_monitor.py",
    "build_all_ticker_24h_post_run_evidence_pack.py",
    "build_all_ticker_live_scope_guard.py",
    "show_all_ticker_live_readonly_preflight.py",
    "build_shadow_parameter_approximation_pack.py",
]


def test_commands_are_templates_only_and_operator_marked(tmp_path: Path) -> None:
    _touch_tools(tmp_path, REQUIRED_TOOLS)
    report = build_all_ticker_operator_preflight_command_pack(root=tmp_path)

    assert report["classification"] == "OK"
    assert report["governance_flags"]["all_ticker_operator_preflight_command_pack_ready"] is True
    for command in report["commands"]:
        assert command["operator_only"] is True
        assert command["codex_must_not_run"] is True
        assert command["executed_by_codex"] is False
        assert "OPERATOR ONLY" in command["purpose"]
        assert "CODEX MUST NOT RUN" in command["purpose"]
    assert report["metadata"]["coinbase_call_attempted"] is False


def test_missing_command_template_fails_safe(tmp_path: Path) -> None:
    _touch_tools(tmp_path, REQUIRED_TOOLS[:-1])
    report = build_all_ticker_operator_preflight_command_pack(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["governance_flags"]["all_ticker_operator_preflight_command_pack_ready"] is False
    assert "shadow_parameter_approximation" in report["missing_command_templates"]
    assert report["governance_flags"]["live_start_authorized"] is False


def test_markdown_contains_operator_only_section(tmp_path: Path) -> None:
    _touch_tools(tmp_path, REQUIRED_TOOLS)
    markdown = render_all_ticker_operator_preflight_command_pack_markdown(
        build_all_ticker_operator_preflight_command_pack(root=tmp_path)
    )

    assert "OPERATOR ONLY" in markdown
    assert "CODEX MUST NOT RUN" in markdown
    assert "show_all_ticker_24h_live_monitor.py" in markdown
