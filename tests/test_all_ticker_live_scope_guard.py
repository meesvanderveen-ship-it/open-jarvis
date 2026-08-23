from __future__ import annotations

import json
from pathlib import Path

from bot.phase_all_ticker_live_scope_guard import (
    build_all_ticker_live_scope_guard,
    render_all_ticker_live_scope_guard_markdown,
)


def _write_harness(root: Path, *, selected: str = "OK", open_orders: int = 0, all_ticker_open: bool = False) -> None:
    path = root / "reports" / "d6" / "safe-regression-harness-20260609.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "selected_tests": {"selected_tests_classification": selected},
                "open_order_summary": {"open_orders": open_orders},
                "readiness_flags": {"all_ticker_live_allowed_now": all_ticker_open},
            }
        ),
        encoding="utf-8",
    )


def _write_env(root: Path, text: str = "") -> None:
    (root / ".env").write_text(text, encoding="utf-8")


def test_current_safe_state_passes_guard(tmp_path: Path) -> None:
    _write_harness(tmp_path)
    _write_env(tmp_path, "REPLICATION_ENABLED=false\nPARAMETER_CHANGE_ALLOWED=false\nLEARNING_TO_EXECUTION_ALLOWED=false\n")
    report = build_all_ticker_live_scope_guard(root=tmp_path)

    assert report["classification"] == "OK"
    assert report["governance_flags"]["all_ticker_live_scope_guard_ready"] is True
    assert report["guard"]["all_ticker_live_allowed_now"] is False
    assert report["metadata"]["coinbase_call_attempted"] is False
    assert report["metadata"]["state_write_performed"] is False


def test_guard_fails_closed_on_selected_harness_watch(tmp_path: Path) -> None:
    _write_harness(tmp_path, selected="WATCH")
    report = build_all_ticker_live_scope_guard(root=tmp_path)

    assert report["classification"] == "STOP_NOW"
    assert "selected_harness_not_ok" in report["stop_reasons"]


def test_guard_fails_closed_on_open_orders(tmp_path: Path) -> None:
    _write_harness(tmp_path, open_orders=1)
    report = build_all_ticker_live_scope_guard(root=tmp_path)

    assert "open_orders_nonzero" in report["stop_reasons"]


def test_guard_fails_closed_on_open_live_flags(tmp_path: Path) -> None:
    _write_harness(tmp_path, all_ticker_open=True)
    _write_env(tmp_path, "REPLICATION_ENABLED=true\nPARAMETER_CHANGE_ALLOWED=true\nLEARNING_TO_EXECUTION_ALLOWED=true\n")
    report = build_all_ticker_live_scope_guard(root=tmp_path)

    assert report["classification"] == "STOP_NOW"
    assert "all_ticker_live_flag_open" in report["stop_reasons"]
    assert "replication_enabled" in report["stop_reasons"]
    assert "parameter_mutation_enabled" in report["stop_reasons"]
    assert "learning_to_execution_enabled" in report["stop_reasons"]


def test_guard_markdown_renders(tmp_path: Path) -> None:
    _write_harness(tmp_path)
    markdown = render_all_ticker_live_scope_guard_markdown(build_all_ticker_live_scope_guard(root=tmp_path))

    assert "All-Ticker Live Scope Guard" in markdown
    assert "live_start_authorized" in markdown
