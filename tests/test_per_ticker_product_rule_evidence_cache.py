from __future__ import annotations

import json
from pathlib import Path

from bot.phase_per_ticker_product_rule_evidence_cache import (
    build_per_ticker_product_rule_evidence_cache_report,
    render_per_ticker_product_rule_evidence_cache_markdown,
)


def _write_project(root: Path, *, config_text: str | None = None, include_btc_rules: bool = True) -> None:
    (root / "bot").mkdir(parents=True)
    (root / "reports" / "d6").mkdir(parents=True)
    (root / "state").mkdir(parents=True)
    (root / "state" / "open_orders.json").write_text('{"orders": {}}', encoding="utf-8")
    (root / "bot" / "config.py").write_text(
        config_text
        if config_text is not None
        else (
            "ALLOWED_TICKERS='BTC-USDC,ETH-USDC,SOL-USDC'\n"
            "max_notional_usd: Decimal = field(default_factory=lambda: _get_decimal_env('MAX_NOTIONAL_USD', '25.00'))\n"
            "default_quote_size_usdc: Decimal = field(default_factory=lambda: _get_decimal_env('DEFAULT_QUOTE_SIZE_USDC', '10.00'))\n"
        ),
        encoding="utf-8",
    )
    replay_rows = [
        {"ticker": "BTC-USDC", "paper_lifecycle_replay_status": "paper_lifecycle_replay_partial"},
        {"ticker": "ETH-USDC", "paper_lifecycle_replay_status": "paper_lifecycle_replay_partial"},
        {"ticker": "SOL-USDC", "paper_lifecycle_replay_status": "paper_lifecycle_replay_partial"},
    ]
    (root / "reports" / "d6" / "multi-ticker-paper-lifecycle-replay-20260609.json").write_text(
        json.dumps({"universe_summary": {"configured_tickers": ["BTC-USDC", "ETH-USDC", "SOL-USDC"]}, "per_ticker_replay_matrix": replay_rows}),
        encoding="utf-8",
    )
    if include_btc_rules:
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
                        "status": "product_rules_readiness_passed",
                    }
                }
            ),
            encoding="utf-8",
        )


def test_all_configured_tickers_are_included(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    tickers = [row["ticker"] for row in report["per_ticker_matrix"]]

    assert tickers == ["BTC-USDC", "ETH-USDC", "SOL-USDC"]
    assert report["universe_summary"]["configured_ticker_count"] == 3


def test_local_evidence_is_normalized(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    btc = {row["ticker"]: row for row in report["per_ticker_matrix"]}["BTC-USDC"]

    assert btc["product_rule_evidence_status"] == "ready"
    assert btc["base_increment"] == "0.00000001"
    assert btc["quote_increment"] == "0.01"
    assert btc["price_increment"] == "0.01"
    assert btc["min_order_size"] == "0.00000001"
    assert btc["min_notional"] == "1"


def test_missing_product_rule_evidence_produces_blockers_not_crash(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    eth = {row["ticker"]: row for row in report["per_ticker_matrix"]}["ETH-USDC"]

    assert eth["product_rule_evidence_status"] == "missing"
    assert "missing_product_rule_evidence" in eth["blockers"]
    assert "missing_min_size" in eth["blockers"]
    assert report["classification"] == "WATCH"


def test_non_btc_is_not_marked_live_ready_from_missing_or_fixture_evidence(tmp_path: Path) -> None:
    _write_project(tmp_path)
    fixture = tmp_path / "reports" / "d6" / "eth-usdc-fixture-product-rules.json"
    fixture.write_text(
        json.dumps(
            {
                "content": {
                    "product_id": "ETH-USDC",
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

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    eth = {row["ticker"]: row for row in report["per_ticker_matrix"]}["ETH-USDC"]

    assert eth["product_rule_evidence_status"] == "partial"
    assert eth["evidence_strength"] == "local_fixture"
    assert eth["paper_replay_usable"] is True
    assert eth["live_candidate_status"] is False
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False
    assert report["gate_decision"]["all_ticker_product_rule_evidence_ready"] is False


def test_product_rule_fixture_evidence_report_reduces_missing_count_for_paper(tmp_path: Path) -> None:
    _write_project(tmp_path)
    fixture_report = tmp_path / "reports" / "d6" / "product-rule-fixture-evidence-20260609.json"
    fixture_report.write_text(
        json.dumps(
            {
                "phase": "product_rule_fixture_evidence_v1",
                "per_ticker_fixture_evidence_matrix": [
                    {
                        "ticker": "ETH-USDC",
                        "evidence_source_type": "fixture",
                        "evidence_strength": "local_fixture",
                        "product_rules": {
                            "base_increment": "0.00000001",
                            "quote_increment": "0.01",
                            "price_increment": "0.01",
                            "min_order_size": "0.00000001",
                            "min_notional": "1",
                        },
                        "source_path": "fixture-report",
                    },
                    {
                        "ticker": "SOL-USDC",
                        "evidence_source_type": "fixture",
                        "evidence_strength": "local_fixture",
                        "product_rules": {
                            "base_increment": "0.00000001",
                            "quote_increment": "0.01",
                            "price_increment": "0.01",
                            "min_order_size": "0.00000001",
                            "min_notional": "1",
                        },
                        "source_path": "fixture-report",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    gate = report["gate_decision"]

    assert gate["tickers_ready_count"] == 1
    assert gate["fixture_evidence_count"] == 2
    assert gate["tickers_missing_count"] == 0
    assert gate["paper_replay_usable_count"] == 3
    assert gate["all_ticker_product_rule_evidence_ready"] is False
    assert gate["all_ticker_live_allowed_now"] is False


def test_btc_can_remain_tiny_candidate_while_all_ticker_live_false(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    btc = {row["ticker"]: row for row in report["per_ticker_matrix"]}["BTC-USDC"]

    assert btc["next_step"] == "eligible_for_future_tiny_live_review_after_fresh_preflight_ACK"
    assert btc["live_candidate_status"] is False
    assert report["gate_decision"]["btc_usdc_tiny_scope_ready_for_operator_preflight"] is True
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False


def test_no_external_state_or_parameter_side_effect_flags(tmp_path: Path) -> None:
    _write_project(tmp_path)
    before = (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8")

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    meta = report["metadata"]

    assert meta["coinbase_call_attempted"] is False
    assert meta["market_data_fetch_attempted"] is False
    assert meta["http_call_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert meta["learning_to_execution_performed"] is False
    assert (tmp_path / "state" / "open_orders.json").read_text(encoding="utf-8") == before


def test_malformed_or_empty_universe_fails_safe(tmp_path: Path) -> None:
    _write_project(tmp_path, config_text="# no ticker config\n", include_btc_rules=False)

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)

    assert report["classification"] == "WATCH"
    assert "configured_universe_from_config_missing_or_malformed" in report["watch_reasons"]
    assert report["gate_decision"]["all_ticker_live_allowed_now"] is False
    assert report["per_ticker_matrix"]


def test_report_includes_gate_decision_and_next_steps(tmp_path: Path) -> None:
    _write_project(tmp_path)

    report = build_per_ticker_product_rule_evidence_cache_report(root=tmp_path)
    markdown = render_per_ticker_product_rule_evidence_cache_markdown(report)

    assert report["gate_decision"]["per_ticker_product_rule_evidence_cache_ready"] is True
    assert report["gate_decision"]["recommended_next_steps"]
    assert "Per-Ticker Product-Rule Evidence Cache" in markdown
