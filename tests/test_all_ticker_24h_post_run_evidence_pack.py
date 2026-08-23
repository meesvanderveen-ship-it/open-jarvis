from __future__ import annotations

import json
from pathlib import Path

from bot.phase_all_ticker_24h_post_run_evidence_pack import (
    build_all_ticker_24h_post_run_evidence_pack,
    render_all_ticker_24h_post_run_evidence_pack_markdown,
)


def _write_orders(root: Path) -> None:
    path = root / "state" / "open_orders.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"orders": {}}), encoding="utf-8")


def test_post_run_scaffold_is_report_only_and_warns_without_window(tmp_path: Path) -> None:
    _write_orders(tmp_path)
    report = build_all_ticker_24h_post_run_evidence_pack(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["governance_flags"]["all_ticker_post_run_evidence_scaffold_ready"] is True
    assert report["window"]["operator_must_supply_real_window"] is True
    assert len(report["per_ticker_evidence"]) == 18
    assert report["metadata"]["coinbase_call_attempted"] is False
    assert report["metadata"]["state_write_performed"] is False


def test_supplied_window_removes_missing_window_warning(tmp_path: Path) -> None:
    _write_orders(tmp_path)
    report = build_all_ticker_24h_post_run_evidence_pack(
        root=tmp_path,
        start_utc="2026-06-09T00:00:00Z",
        stop_utc="2026-06-10T00:00:00Z",
    )

    assert report["window"]["operator_must_supply_real_window"] is False
    assert "missing_live_window_warning" not in report["warnings"]


def test_post_run_markdown_renders(tmp_path: Path) -> None:
    _write_orders(tmp_path)
    markdown = render_all_ticker_24h_post_run_evidence_pack_markdown(
        build_all_ticker_24h_post_run_evidence_pack(root=tmp_path)
    )

    assert "All-Ticker 24h Post-Run Evidence Pack" in markdown
    assert "BTC-USDC" in markdown
