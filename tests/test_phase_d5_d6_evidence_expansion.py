from __future__ import annotations

import json
from pathlib import Path

from bot.phase_d5_d6_evidence_expansion import (
    build_d5_d6_evidence_expansion_report,
    render_d5_d6_evidence_expansion_markdown,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_fixture_state(root: Path, *, include_direct_fee: bool = True) -> None:
    _write_json(
        root / "state" / "open_orders.json",
        {
            "orders": {
                "old-tp1": {
                    "client_order_id": "phased3-BTCUSDC-TP1-old",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "status": "cancelled",
                    "submitted_at": "2026-05-28T16:00:00+00:00",
                    "closed_at": "2026-05-28T18:00:00+00:00",
                    "filled_base": "0",
                    "remaining_size": "0.0001",
                },
                "repl-tp1": {
                    "client_order_id": "phased4-BTCUSDC-TP1-repl",
                    "replacement_of_client_order_id": "phased3-BTCUSDC-TP1-old",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "status": "filled",
                    "submitted_at": "2026-05-28T18:00:30+00:00",
                    "filled_at": "2026-05-28T19:00:00+00:00",
                    "filled_base": "0.0001",
                    "filled_quote": "7.40",
                    "fees_paid": "0.01",
                },
                "old-tp-close": {
                    "client_order_id": "phased3-BTCUSDC-TPCLOSE-old",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "status": "cancelled",
                    "submitted_at": "2026-05-30T21:32:30+00:00",
                    "closed_at": "2026-05-30T21:50:29+00:00",
                    "filled_base": "0",
                    "remaining_size": "0.00006490",
                },
                "tp-close-repl": {
                    "client_order_id": "phased3-BTCUSDC-TPCLOSE-repl",
                    "replacement_of_client_order_id": "phased3-BTCUSDC-TPCLOSE-old",
                    "exchange_order_id": "exchange-tp-close",
                    "ticker": "BTC-USDC",
                    "side": "SELL",
                    "phase": "D3_controlled_live_reduce_only_exits",
                    "status": "filled",
                    "submitted_at": "2026-05-30T21:50:29+00:00",
                    "filled_at": "2026-05-31T02:38:19+00:00",
                    "filled_base": "0.00006490",
                    "filled_quote": "4.8026000",
                    "fees_paid": "0",
                    "last_fill_delta_fees": "0",
                },
            }
        },
    )
    _write_json(
        root / "state" / "positions.json",
        {
            "BTC-USDC": {
                "ticker": "BTC-USDC",
                "status": "closed",
                "position_size_base": "0",
                "last_d3_reconcile_fees_delta": "0",
            }
        },
    )
    context = "TP_CLOSE direct Coinbase snapshot total_fees=0.0288156 and lifecycle fees stayed 0.\n"
    if not include_direct_fee:
        context = "TP_CLOSE lifecycle evidence is present but direct fee evidence is missing.\n"
    path = root / "docs" / "CODEX_PROJECT_CONTEXT.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(context, encoding="utf-8")


def test_missing_optional_logs_do_not_crash(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert any(reason.startswith("optional_evidence_source_missing:logs/") for reason in report["watch_reasons"])


def test_fee_discrepancy_is_watch_and_human_review_required(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)
    fee = report["fee_evidence"]

    assert report["classification"] == "WATCH"
    assert fee["tp_close_fee_discrepancy_status"] == "gap_present"
    assert fee["fee_gap_present"] is True
    assert fee["human_review_required"] is True
    assert fee["direct_exchange_fee_evidence"]["fee_quote"] == "0.0288156"


def test_no_fill_duration_summary_works_with_timestamps(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)
    no_fill = report["no_fill_duration"]

    assert no_fill["open_no_fill_event_count"] == 2
    assert no_fill["duration_buckets"]["1h-6h"] == 1
    assert no_fill["duration_buckets"]["15m-1h"] == 1
    assert no_fill["duration_seconds_max"] == "7200"


def test_cancel_replace_timing_summary_works_with_fixture_events(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)
    timing = report["cancel_replace_timing"]

    assert timing["cancel_replace_chain_count"] == 2
    tp1 = next(row for row in timing["chains"] if row["replacement_client_order_id"] == "phased4-BTCUSDC-TP1-repl")
    assert tp1["cancel_to_replacement_seconds"] == "30"
    assert tp1["terminal_evidence_present"] is True
    tp_close = next(
        row for row in timing["chains"] if row["replacement_client_order_id"] == "phased3-BTCUSDC-TPCLOSE-repl"
    )
    assert tp_close["cancel_to_replacement_seconds"] == "0"


def test_partial_fill_absence_is_represented_safely(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)
    partial = report["partial_fill_evidence"]

    assert partial["partial_fills_present"] is False
    assert partial["status"] == "absent"
    assert partial["events"] == []


def test_governance_flags_remain_human_review_only(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)
    flags = report["readiness_and_governance_flags"]

    assert flags["d5_d6_evidence_expansion_ready"] is True
    assert flags["human_review_ready"] is True
    assert flags["learning_to_execution_ready"] is False
    assert flags["parameter_change_allowed"] is False
    assert flags["parameter_review_approved"] is False
    assert flags["master_live_exit_ready"] is False
    assert flags["follower_ready_for_live"] is False


def test_no_state_writes(tmp_path: Path):
    _write_fixture_state(tmp_path)
    orders_before = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")
    positions_before = (tmp_path / "state" / "positions.json").read_text(encoding="utf-8")

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)

    assert report["state_write_performed"] is False
    assert report["coinbase_call_attempted"] is False
    assert report["market_data_fetch_attempted"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == orders_before
    assert (tmp_path / "state" / "positions.json").read_text(encoding="utf-8") == positions_before


def test_markdown_includes_required_flags(tmp_path: Path):
    _write_fixture_state(tmp_path)

    report = build_d5_d6_evidence_expansion_report(root=tmp_path)
    markdown = render_d5_d6_evidence_expansion_markdown(report)

    assert "learning_to_execution_ready" in markdown
    assert "parameter_change_allowed" in markdown
    assert "d5_d6_evidence_expansion_ready" in markdown
