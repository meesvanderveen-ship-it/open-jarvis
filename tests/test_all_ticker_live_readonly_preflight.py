from __future__ import annotations

import json
from pathlib import Path

from bot.phase_all_ticker_live_readonly_preflight import (
    CoinbaseReadonlyProductBalanceAdapter,
    build_all_ticker_live_readonly_preflight,
    collect_all_ticker_live_readonly_snapshot,
    render_all_ticker_live_readonly_preflight_markdown,
)
from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_sources(root: Path) -> None:
    d6 = root / "reports" / "d6"
    _write(
        d6 / "per-ticker-product-rule-evidence-cache-20260609.json",
        {
            "per_ticker_matrix": [
                {
                    "ticker": ticker,
                    "evidence_strength": "live_readonly_cached" if ticker == "BTC-USDC" else "local_fixture",
                    "evidence_source_type": "local_report" if ticker == "BTC-USDC" else "fixture",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "price_increment": "0.01",
                    "min_order_size": "0.00000001",
                    "min_notional": "1.00",
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
                    "evidence_strength": "local_fixture",
                    "evidence_source_type": "fixture",
                    "base_increment": "0.00000001",
                    "quote_increment": "0.01",
                    "price_increment": "0.01",
                    "min_order_size": "0.00000001",
                    "min_notional": "1.00",
                }
                for ticker in DEFAULT_TICKERS
                if ticker != "BTC-USDC"
            ]
        },
    )
    _write(root / "state" / "open_orders.json", {"orders": {}})
    _write(
        d6 / "safe-regression-harness-20260609.json",
        {
            "selected_tests": {
                "selected_tests_classification": "OK",
                "selected_tests_passed_count": 30,
                "selected_tests_failed_count": 0,
            }
        },
    )


class FakeReadonlyClient:
    def __init__(self, *, product_error: Exception | None = None, balance_error: Exception | None = None, malformed: bool = False):
        self.product_error = product_error
        self.balance_error = balance_error
        self.malformed = malformed
        self.product_calls: list[str] = []
        self.balance_calls: list[str] = []

    def get_product_rule(self, ticker: str) -> dict:
        self.product_calls.append(ticker)
        if self.product_error is not None:
            raise self.product_error
        if self.malformed:
            return {}
        return {
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "price_increment": "0.01",
            "min_order_size": "0.00000001",
            "min_notional": "1.00",
        }

    def get_balances(self, ticker: str) -> dict:
        self.balance_calls.append(ticker)
        if self.balance_error is not None:
            raise self.balance_error
        return {"available_base": "0", "hold_base": "0", "available_quote": "100", "hold_quote": "0"}

    def place_limit_order(self, *args, **kwargs):
        raise AssertionError("submit forbidden")

    def cancel_order(self, *args, **kwargs):
        raise AssertionError("cancel forbidden")

    def replace_order(self, *args, **kwargs):
        raise AssertionError("replace forbidden")

    def lifecycle_apply(self, *args, **kwargs):
        raise AssertionError("lifecycle apply forbidden")


class FakeBroadCoinbaseClient:
    def __init__(self):
        self.product_calls: list[str] = []
        self.spot_calls: list[str] = []
        self.submit_calls = 0
        self.cancel_calls = 0
        self.replace_calls = 0
        self.reprice_calls = 0

    def get_product(self, product_id: str) -> dict:
        self.product_calls.append(product_id)
        return {
            "product_id": product_id,
            "base_increment": "0.00000001",
            "quote_increment": "0.01",
            "price_increment": "0.01",
            "base_min_size": "0.00000001",
            "quote_min_size": "1.00",
        }

    def get_spot_position(self, product_id: str) -> dict:
        self.spot_calls.append(product_id)
        return {
            "available_base_balance": "0",
            "hold_base_balance": "0",
            "available_quote_balance": "100",
            "hold_quote_balance": "0",
        }

    def place_limit_order(self, *args, **kwargs):
        self.submit_calls += 1
        raise AssertionError("submit forbidden")

    def cancel_order(self, *args, **kwargs):
        self.cancel_calls += 1
        raise AssertionError("cancel forbidden")

    def replace_order(self, *args, **kwargs):
        self.replace_calls += 1
        raise AssertionError("replace forbidden")

    def reprice_order(self, *args, **kwargs):
        self.reprice_calls += 1
        raise AssertionError("reprice forbidden")


def test_not_run_report_includes_all_tickers_and_no_live_action(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_all_ticker_live_readonly_preflight(root=tmp_path)

    assert report["status"] == "not_run"
    assert report["operator_command_required"] is True
    assert report["configured_ticker_count"] == 18
    assert [row["ticker"] for row in report["per_ticker_preflight"]] == list(DEFAULT_TICKERS)
    meta = report["metadata"]
    assert meta["coinbase_call_attempted"] is False
    assert meta["order_action_attempted"] is False
    assert meta["state_write_performed"] is False
    assert meta["env_mutation_performed"] is False
    assert meta["parameter_mutation_performed"] is False
    assert all(row["live_readonly_product_rule_attempted"] is False for row in report["per_ticker_preflight"])


def test_non_btc_fixture_only_remains_blocked(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    rows = {row["ticker"]: row for row in build_all_ticker_live_readonly_preflight(root=tmp_path)["per_ticker_preflight"]}

    assert rows["ETH-USDC"]["product_rule_source"] == "fixture"
    assert rows["ETH-USDC"]["live_entry_preflight_status"] == "not_run"
    assert "live_product_rule_evidence_missing" in rows["ETH-USDC"]["blockers"]
    assert rows["ETH-USDC"]["recommended_scope"] == "blocked_by_product_rule"


def test_open_orders_block_readiness(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    _write(tmp_path / "state" / "open_orders.json", {"orders": {"o1": {"ticker": "BTC-USDC", "status": "submitted"}}})
    report = build_all_ticker_live_readonly_preflight(root=tmp_path)

    assert any("open_orders_present" in row["blockers"] for row in report["per_ticker_preflight"])
    assert report["gate_decision"]["all_ticker_live_readonly_preflight_passed"] is False


def test_injected_live_snapshot_can_pass_report_only(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    snapshot = {
        "per_ticker_readonly": [
            {
                "ticker": ticker,
                "base_increment": "0.00000001",
                "quote_increment": "0.01",
                "price_increment": "0.01",
                "min_order_size": "0.00000001",
                "min_notional": "1.00",
                "available_quote": "100",
                "available_base": "0",
                "estimated_tiny_order_quote": "1.00",
                "live_readonly_product_rule_attempted": True,
                "live_readonly_product_rule_passed": True,
                "live_readonly_balance_attempted": True,
                "live_readonly_balance_passed": True,
                "min_notional_pass": True,
                "cap_pass": True,
                "balance_pass": True,
            }
            for ticker in DEFAULT_TICKERS
        ]
    }
    report = build_all_ticker_live_readonly_preflight(root=tmp_path, live_readonly_snapshot=snapshot)

    assert report["status"] == "pass"
    assert report["gate_decision"]["all_ticker_live_readonly_preflight_attempted"] is True
    assert report["gate_decision"]["all_ticker_live_readonly_preflight_passed"] is True
    assert report["gate_decision"]["all_ticker_live_authorized"] is False
    assert report["metadata"]["order_action_attempted"] is False
    assert report["gate_decision"]["live_start_authorized"] is False


def test_collect_live_snapshot_uses_only_readonly_methods() -> None:
    client = FakeReadonlyClient()
    snapshot = collect_all_ticker_live_readonly_snapshot(client)

    assert client.product_calls == list(DEFAULT_TICKERS)
    assert client.balance_calls == list(DEFAULT_TICKERS)
    assert snapshot["coinbase_call_attempted"] is True
    assert all(row["live_readonly_product_rule_passed"] for row in snapshot["per_ticker_readonly"])
    assert all(row["live_readonly_balance_passed"] for row in snapshot["per_ticker_readonly"])


def test_narrow_adapter_never_calls_order_cancel_replace_reprice_methods() -> None:
    broad = FakeBroadCoinbaseClient()
    adapter = CoinbaseReadonlyProductBalanceAdapter(broad)
    snapshot = collect_all_ticker_live_readonly_snapshot(adapter, tickers=["BTC-USDC"])

    assert snapshot["per_ticker_readonly"][0]["ticker"] == "BTC-USDC"
    assert broad.product_calls == ["BTC-USDC"]
    assert broad.spot_calls == ["BTC-USDC"]
    assert broad.submit_calls == 0
    assert broad.cancel_calls == 0
    assert broad.replace_calls == 0
    assert broad.reprice_calls == 0


def test_missing_product_rule_fails_closed(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    snapshot = collect_all_ticker_live_readonly_snapshot(FakeReadonlyClient(product_error=RuntimeError("boom")))
    report = build_all_ticker_live_readonly_preflight(root=tmp_path, live_readonly_snapshot=snapshot)

    assert report["status"] == "blocked"
    assert any("live_product_rule_read_failed" in row["blockers"] for row in report["per_ticker_preflight"])


def test_missing_balance_fails_closed(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    snapshot = collect_all_ticker_live_readonly_snapshot(FakeReadonlyClient(balance_error=RuntimeError("boom")))
    report = build_all_ticker_live_readonly_preflight(root=tmp_path, live_readonly_snapshot=snapshot)

    assert report["status"] == "blocked"
    assert any("live_balance_read_failed" in row["blockers"] for row in report["per_ticker_preflight"])


def test_malformed_product_rules_fail_closed(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    snapshot = {"per_ticker_readonly": [{"ticker": ticker} for ticker in DEFAULT_TICKERS]}
    report = build_all_ticker_live_readonly_preflight(root=tmp_path, live_readonly_snapshot=snapshot)

    assert report["status"] == "blocked"
    assert report["gate_decision"]["all_ticker_live_readonly_preflight_passed"] is False
    assert any("product_rule_fields_missing" in row["blockers"] for row in report["per_ticker_preflight"])


def test_selected_tests_not_ok_blocks_readiness(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    _write(
        tmp_path / "reports/d6/safe-regression-harness-20260609.json",
        {"selected_tests": {"selected_tests_classification": "STOP_NOW", "selected_tests_failed_count": 1}},
    )
    snapshot = collect_all_ticker_live_readonly_snapshot(FakeReadonlyClient())
    report = build_all_ticker_live_readonly_preflight(root=tmp_path, live_readonly_snapshot=snapshot)

    assert report["gate_decision"]["all_ticker_live_readonly_preflight_passed"] is False
    assert any("selected_tests_not_ok" in row["blockers"] for row in report["per_ticker_preflight"])


def test_all_live_authorization_flags_remain_false(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    snapshot = collect_all_ticker_live_readonly_snapshot(FakeReadonlyClient())
    report = build_all_ticker_live_readonly_preflight(root=tmp_path, live_readonly_snapshot=snapshot)
    gate = report["gate_decision"]

    assert gate["all_ticker_live_authorized"] is False
    assert gate["live_start_authorized"] is False
    assert all(row["live_ready"] is False for row in report["per_ticker_preflight"])
    assert all(row["all_ticker_live_authorized"] is False for row in report["per_ticker_preflight"])


def test_audit_warning_is_classified_not_hidden(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    report = build_all_ticker_live_readonly_preflight(
        root=tmp_path,
        function_audit_report={
            "overall_status": "ok_observe_only",
            "warnings": ["filled_c43_without_position_created:phasec-BTCUSDC-smoke-20260524151451"],
        },
    )

    audit = report["function_preservation_audit"]
    assert audit["audit_warning_status"] == "stale_historical_warning_known_safe"
    assert "filled_c43_without_position_created:phasec-BTCUSDC-smoke-20260524151451" in audit["warnings"]


def test_markdown_contains_preflight_status(tmp_path: Path) -> None:
    _write_sources(tmp_path)
    markdown = render_all_ticker_live_readonly_preflight_markdown(
        build_all_ticker_live_readonly_preflight(root=tmp_path)
    )

    assert "All-Ticker Live-Readonly Preflight" in markdown
    assert "BTC-USDC" in markdown
