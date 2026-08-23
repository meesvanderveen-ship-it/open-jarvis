from __future__ import annotations

import json
from pathlib import Path

from bot.phase_product_rule_fixture_evidence import (
    build_product_rule_fixture_evidence_report,
    render_product_rule_fixture_evidence_markdown,
)


def _write_project(root: Path, *, fixture_payload: dict | None = None) -> None:
    (root / "bot").mkdir(parents=True)
    (root / "reports" / "d6").mkdir(parents=True)
    (root / "fixtures" / "product_rules").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    (root / "state" / "open_orders.json").write_text('{"orders": {}}', encoding="utf-8")
    (root / "bot" / "config.py").write_text(
        "ALLOWED_TICKERS='BTC-USDC,ETH-USDC,SOL-USDC'\n",
        encoding="utf-8",
    )
    (root / "reports" / "d6" / "btc-usdc-product-rules-readiness-v1-20260602.json").write_text(
        json.dumps(
            {
                "content": {
                    "product_id": "BTC-USDC",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "price_increment": "0.01",
                    "min_order_base": "0.00000001",
                    "min_order_quote": "1",
                }
            }
        ),
        encoding="utf-8",
    )
    fixture = fixture_payload or {
        "schema_version": "test_fixture_v1",
        "default_fixture_rules": {
            "quote_currency": "USDC",
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "price_increment": "0.01",
            "min_order_size": "0.00000001",
            "min_notional": "1",
        },
        "fixtures": [
            {"ticker": "ETH-USDC", "base_currency": "ETH"},
            {"ticker": "SOL-USDC", "base_currency": "SOL"},
        ],
    }
    (root / "fixtures" / "product_rules" / "local_product_rule_fixtures_v1.json").write_text(
        json.dumps(fixture),
        encoding="utf-8",
    )


def test_all_configured_tickers_are_included(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_product_rule_fixture_evidence_report(root=tmp_path)
    tickers = [row["ticker"] for row in report["per_ticker_fixture_evidence_matrix"]]

    assert tickers == ["BTC-USDC", "ETH-USDC", "SOL-USDC"]
    assert report["universe_summary"]["configured_ticker_count"] == 3


def test_fixture_evidence_loads_for_non_btc_tickers(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_product_rule_fixture_evidence_report(root=tmp_path)
    rows = {row["ticker"]: row for row in report["per_ticker_fixture_evidence_matrix"]}

    assert rows["ETH-USDC"]["evidence_source_type"] == "fixture"
    assert rows["ETH-USDC"]["evidence_strength"] == "local_fixture"
    assert rows["ETH-USDC"]["base_increment"] == "0.00000001"
    assert rows["ETH-USDC"]["paper_replay_usable"] is True


def test_missing_fields_create_blockers_not_crash(tmp_path: Path) -> None:
    _write_project(
        tmp_path,
        fixture_payload={
            "schema_version": "bad_fixture",
            "fixtures": [{"ticker": "ETH-USDC", "base_currency": "ETH"}],
        },
    )

    report = build_product_rule_fixture_evidence_report(root=tmp_path)
    eth = {row["ticker"]: row for row in report["per_ticker_fixture_evidence_matrix"]}["ETH-USDC"]

    assert eth["paper_replay_usable"] is False
    assert "missing_base_increment" in eth["blockers"]
    assert report["classification"] == "WATCH"


def test_fixture_evidence_never_marks_live_ready(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_product_rule_fixture_evidence_report(root=tmp_path)
    non_btc = [row for row in report["per_ticker_fixture_evidence_matrix"] if row["ticker"] != "BTC-USDC"]

    assert all(row["live_ready"] is False for row in non_btc)
    assert all(row["fixture_product_rule_evidence"] is True for row in non_btc)
    assert report["universe_summary"]["all_ticker_live_allowed_now"] is False


def test_no_external_or_state_side_effect_flags(tmp_path: Path) -> None:
    _write_project(tmp_path)
    before = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")

    report = build_product_rule_fixture_evidence_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert meta["learning_to_execution_performed"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == before


def test_malformed_fixture_fails_safe(tmp_path: Path) -> None:
    _write_project(tmp_path)
    (tmp_path / "fixtures" / "product_rules" / "local_product_rule_fixtures_v1.json").write_text(
        "{not-json",
        encoding="utf-8",
    )

    report = build_product_rule_fixture_evidence_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert report["universe_summary"]["missing_evidence_ticker_count"] == 2


def test_markdown_contains_safety_boundary(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_product_rule_fixture_evidence_report(root=tmp_path)
    markdown = render_product_rule_fixture_evidence_markdown(report)

    assert "Product-Rule Fixture Evidence" in markdown
    assert "local fixtures do not authorize live trading" in markdown
