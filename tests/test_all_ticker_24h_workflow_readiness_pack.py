from __future__ import annotations

import json
from pathlib import Path

from bot.phase_all_ticker_24h_workflow_readiness_pack import (
    BTC_TICKER,
    build_all_ticker_24h_workflow_readiness_pack,
    render_all_ticker_24h_workflow_readiness_pack_markdown,
)
from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    _write(
        d6 / "btc-usdc-24h-live-start-decision-pack-20260609.json",
        {"governance_flags": {"ready_for_operator_fresh_preflight": True}},
    )
    _write(
        d6 / "multi-ticker-paper-lifecycle-replay-20260609.json",
        {
            "per_ticker_replay_matrix": [
                {"ticker": ticker, "paper_lifecycle_replay_status": "paper_lifecycle_replay_ready"}
                for ticker in DEFAULT_TICKERS
            ]
        },
    )
    _write(
        d6 / "per-ticker-product-rule-evidence-cache-20260609.json",
        {
            "per_ticker_matrix": [
                {
                    "ticker": ticker,
                    "evidence_strength": "live_readonly_cached" if ticker == BTC_TICKER else "local_fixture",
                }
                for ticker in DEFAULT_TICKERS
            ]
        },
    )
    _write(
        d6 / "product-rule-fixture-evidence-20260609.json",
        {
            "per_ticker_fixture_evidence_matrix": [
                {
                    "ticker": ticker,
                    "evidence_strength": "live_readonly_cached" if ticker == BTC_TICKER else "local_fixture",
                }
                for ticker in DEFAULT_TICKERS
            ]
        },
    )


def test_all_18_configured_tickers_included(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_all_ticker_24h_workflow_readiness_pack(root=tmp_path)

    assert report["configured_ticker_count"] == 18
    assert [row["ticker"] for row in report["per_ticker_readiness"]] == list(DEFAULT_TICKERS)
    assert report["metadata"]["coinbase_call_attempted"] is False
    assert report["metadata"]["state_write_performed"] is False


def test_btc_can_be_preflight_candidate_while_non_btc_blocked(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_all_ticker_24h_workflow_readiness_pack(root=tmp_path)
    rows = {row["ticker"]: row for row in report["per_ticker_readiness"]}
    gate = report["gate_decision"]

    assert rows[BTC_TICKER]["all_ticker_candidate_status"] == "ready_for_operator_fresh_preflight"
    for ticker, row in rows.items():
        if ticker != BTC_TICKER:
            assert row["all_ticker_candidate_status"] == "blocked_by_fresh_live_preflight"
            assert "fresh_live_product_rule_preflight_missing" in row["blockers"]
    assert gate["btc_usdc_ready_for_operator_fresh_preflight"] is True
    assert gate["non_btc_tickers_ready_for_operator_fresh_preflight"] is False
    assert gate["all_ticker_live_authorized"] is False
    assert gate["live_start_authorized"] is False


def test_missing_sources_fail_closed_not_live_ready(tmp_path: Path) -> None:
    report = build_all_ticker_24h_workflow_readiness_pack(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["gate_decision"]["all_ticker_live_authorized"] is False
    assert all(row["live_ready"] is False for row in report["per_ticker_readiness"])
    assert report["gate_decision"]["btc_usdc_ready_for_operator_fresh_preflight"] is False


def test_markdown_renders_key_decisions(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_all_ticker_24h_workflow_readiness_pack_markdown(
        build_all_ticker_24h_workflow_readiness_pack(root=tmp_path)
    )

    assert "All-Ticker 24h Workflow Readiness Pack" in markdown
    assert "all_ticker_live_authorized" in markdown
