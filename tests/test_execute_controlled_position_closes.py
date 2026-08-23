from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from bot.controlled_stop_market_exit_executor import (
    BASE_BALANCE_SOURCE_COINBASE_LIVE,
    BASE_BALANCE_SOURCE_TEST_FIXTURE,
)
from bot.coinbase_client import normalize_coinbase_account_balances
from tools.debug_coinbase_base_balances import build_diagnostic_report
from tools.execute_controlled_position_closes import (
    _verified_positions_from_coinbase,
    build_execution_preview_report,
)


ACK = "CLOSE_RISK_INCOMPLETE_POSITIONS_ETH_AVAX_SOL_20260619"
NOW = datetime(2026, 6, 19, tzinfo=timezone.utc)
POSITIONS = ["ETH-USDC", "AVAX-USDC", "SOL-USDC"]
EXCLUDED = ["ADA-USDC"]
JSON_OUT = "reports/live_runs/risk-incomplete-controlled-close-result.json"
MISSING = object()


class FakeAccountsClient:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload if payload is not None else {"accounts": []}
        self.error = error
        self.accounts_calls = 0

    def get_accounts(self):
        self.accounts_calls += 1
        if self.error is not None:
            raise self.error
        return self.payload


class FakeSdkBalance:
    def __init__(self, value: str, currency: str | None = None):
        self.value = value
        self.currency = currency


class FakeSdkAccount:
    def __init__(self, currency: str, available: str | None, hold: str = "0"):
        self.currency = currency
        self.available_balance = FakeSdkBalance(available, currency) if available is not None else None
        self.hold = FakeSdkBalance(hold, currency)


class FakeSdkAccountsResponse:
    def __init__(self, accounts):
        self.accounts = accounts


def _account(currency: str | None, available=MISSING, hold="0"):
    row = {}
    if currency is not None:
        row["currency"] = currency
    if available is not MISSING:
        row["available_balance"] = {"value": str(available), "currency": currency}
    if hold is not MISSING:
        row["hold"] = {"value": str(hold), "currency": currency}
    return row


def _accounts_payload(*accounts):
    return {"accounts": list(accounts)}


def _realistic_redacted_accounts_fixture():
    """Structural fixture derived from the read-only diagnostic, without IDs or secrets."""
    return {
        "accounts": [
            {
                "uuid": "redacted-eth-account",
                "currency": "ETH",
                "available_balance": {"value": "0.0141964735707866", "currency": "ETH"},
                "hold": {"value": "0", "currency": "ETH"},
            },
            {
                "uuid": "redacted-avax-account",
                "currency": "AVAX",
                "available_balance": {"value": "3.67647058", "currency": "AVAX"},
                "hold": {"value": "0", "currency": "AVAX"},
            },
            {
                "uuid": "redacted-sol-account",
                "currency": "SOL",
                "available_balance": {"value": "0.3485292", "currency": "SOL"},
                "hold": {"value": "0", "currency": "SOL"},
            },
        ],
        "cursor": "redacted",
    }


def _live_rows_from_accounts(payload, *, locals_by_ticker=None, error: Exception | None = None):
    locals_by_ticker = locals_by_ticker or {
        "ETH-USDC": "0.01419647",
        "AVAX-USDC": "3.67647058",
        "SOL-USDC": "0.3485292",
    }
    positions = [
        {"ticker": ticker, "local_base": local_base}
        for ticker, local_base in locals_by_ticker.items()
    ]
    return _verified_positions_from_coinbase(
        positions=positions,
        coinbase_client=FakeAccountsClient(payload=payload, error=error),
    )


def _row(ticker: str, *, local: str = "1.0", available: str = "2.0", source: str = BASE_BALANCE_SOURCE_TEST_FIXTURE, fixture_verified: bool = True):
    base_asset = ticker.split("-", 1)[0]
    return {
        "ticker": ticker,
        "local_base": local,
        "available_base": available,
        "base_balance_verified": False,
        "base_balance_source": source,
        "base_balance_lookup_attempted": True,
        "base_balance_lookup_success": True,
        "base_balance_lookup_empty": False,
        "base_balance_lookup_product_id": ticker,
        "base_balance_lookup_base_asset": base_asset,
        "base_balance_test_fixture_verified": fixture_verified,
        "coinbase_base_balance_lookup": {
            "lookup_attempted": True,
            "lookup_succeeded": True,
            "lookup_empty": False,
            "source": source,
            "product_id": ticker,
            "base_symbol": base_asset,
            "test_fixture_verified": fixture_verified,
        },
    }


def _rows(*, oversell: bool = False, evidence: bool = True):
    available = "0.5" if oversell else "2.0"
    rows = [
        _row("ETH-USDC", available=available),
        _row("AVAX-USDC"),
        _row("SOL-USDC"),
    ]
    if not evidence:
        for row in rows:
            for key in (
                "base_balance_source",
                "base_balance_lookup_attempted",
                "base_balance_lookup_success",
                "base_balance_lookup_empty",
                "base_balance_lookup_product_id",
                "base_balance_lookup_base_asset",
                "base_balance_test_fixture_verified",
                "coinbase_base_balance_lookup",
            ):
                row.pop(key, None)
            row["base_balance_verified"] = True
    return [
        *rows,
    ]


def _report(**overrides):
    kwargs = {
        "ack": ACK,
        "positions": POSITIONS,
        "exclude": EXCLUDED,
        "require_verified_base": True,
        "block_oversell": True,
        "block_duplicate_exit": True,
        "require_terminal_fill_before_state_write": True,
        "json_out": JSON_OUT,
        "position_rows": _rows(),
        "service_active": False,
        "duplicate_exit_exists": False,
        "now": NOW,
    }
    kwargs.update(overrides)
    return build_execution_preview_report(**kwargs)


def test_eth_usdc_live_account_balance_fixture_verifies_base_lookup() -> None:
    rows = _live_rows_from_accounts(
        _accounts_payload(_account("ETH", "0.0141964735707866")),
        locals_by_ticker={"ETH-USDC": "0.01419647"},
    )

    row = rows[0]
    assert row["base_balance_source"] == BASE_BALANCE_SOURCE_COINBASE_LIVE
    assert row["base_balance_lookup_product_id"] == "ETH-USDC"
    assert row["base_balance_lookup_base_asset"] == "ETH"
    assert row["lookup_base_asset"] == "ETH"
    assert row["base_balance_lookup_attempted"] is True
    assert row["base_balance_lookup_success"] is True
    assert row["available_base"] == "0.0141964735707866"
    assert row["base_balance_verified"] is True


def test_avax_usdc_live_account_balance_fixture_equal_local_verifies() -> None:
    rows = _live_rows_from_accounts(
        _accounts_payload(_account("AVAX", "3.67647058")),
        locals_by_ticker={"AVAX-USDC": "3.67647058"},
    )

    row = rows[0]
    assert row["base_balance_lookup_product_id"] == "AVAX-USDC"
    assert row["base_balance_lookup_base_asset"] == "AVAX"
    assert row["base_balance_lookup_success"] is True
    assert row["available_base"] == "3.67647058"
    assert row["base_balance_verified"] is True


def test_sol_usdc_live_account_balance_fixture_equal_local_verifies() -> None:
    rows = _live_rows_from_accounts(
        _accounts_payload(_account("SOL", "0.3485292")),
        locals_by_ticker={"SOL-USDC": "0.3485292"},
    )

    row = rows[0]
    assert row["base_balance_lookup_product_id"] == "SOL-USDC"
    assert row["base_balance_lookup_base_asset"] == "SOL"
    assert row["base_balance_lookup_success"] is True
    assert row["available_base"] == "0.3485292"
    assert row["base_balance_verified"] is True


def test_normalizer_supports_advanced_trade_dict_accounts_list_and_currency_matching() -> None:
    payload = _realistic_redacted_accounts_fixture()

    normalized = {
        ticker: normalize_coinbase_account_balances(ticker, payload)
        for ticker in POSITIONS
    }

    assert normalized["ETH-USDC"]["lookup_base_asset"] == "ETH"
    assert normalized["AVAX-USDC"]["lookup_base_asset"] == "AVAX"
    assert normalized["SOL-USDC"]["lookup_base_asset"] == "SOL"
    assert all(row["base_balance_lookup_success"] is True for row in normalized.values())


def test_normalizer_supports_sdk_object_attributes_and_nested_available_balance_value() -> None:
    payload = FakeSdkAccountsResponse(
        [
            FakeSdkAccount("ETH", "0.0141964735707866"),
            FakeSdkAccount("AVAX", "3.67647058"),
            FakeSdkAccount("SOL", "0.3485292"),
        ]
    )

    normalized = normalize_coinbase_account_balances("ETH-USDC", payload)

    assert normalized["accounts_count"] == 3
    assert normalized["lookup_base_asset"] == "ETH"
    assert normalized["available_base_balance"] == "0.0141964735707866"
    assert normalized["available_base_balance_field_path"] == "available_balance.value"
    assert normalized["base_balance_lookup_success"] is True


def test_normalizer_supports_balance_value_fallback_when_that_is_the_only_supported_shape() -> None:
    normalized = normalize_coinbase_account_balances(
        "ETH-USDC",
        {"accounts": [{"currency": "ETH", "balance": {"value": "1.25", "currency": "ETH"}}]},
    )

    assert normalized["available_base_balance"] == "1.25"
    assert normalized["available_base_balance_field_path"] == "balance.value"
    assert normalized["base_balance_lookup_success"] is True


def test_normalizer_missing_available_balance_and_empty_accounts_fail_closed() -> None:
    missing = normalize_coinbase_account_balances("ETH-USDC", {"accounts": [{"currency": "ETH", "hold": {"value": "1"}}]})
    empty = normalize_coinbase_account_balances("ETH-USDC", {"accounts": []})

    assert missing["base_balance_lookup_success"] is False
    assert missing["available_base_balance"] == ""
    assert missing["base_balance_lookup_empty"] is True
    assert empty["base_balance_lookup_success"] is False
    assert empty["base_balance_lookup_empty"] is True


def test_read_only_diagnostic_accepts_realistic_redacted_payload_without_order_calls() -> None:
    client = FakeAccountsClient(payload=_realistic_redacted_accounts_fixture())

    diagnostic = build_diagnostic_report(currencies=("ETH", "AVAX", "SOL"), client=client)

    assert diagnostic["read_only"] is True
    assert diagnostic["order_endpoints_used"] is False
    assert diagnostic["account_balance_client_method"] == "get_accounts"
    assert diagnostic["coinbase_call_succeeded"] is True
    assert diagnostic["accounts_count"] == 3
    assert client.accounts_calls == 1
    assert [row["currency"] for row in diagnostic["currencies"]] == ["ETH", "AVAX", "SOL"]
    assert all(row["available_balance_field_path"] == "available_balance.value" for row in diagnostic["currencies"])


def test_empty_coinbase_account_response_fails_closed_before_submit() -> None:
    called = {"value": False}

    def submitter(payload):
        called["value"] = True
        return {"submitted": True, "order_id": "unexpected"}

    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(_accounts_payload()),
        coinbase_submitter=submitter,
    )

    assert called["value"] is False
    assert report["live_submit_attempted"] is False
    assert report["coinbase_call_attempted"] is True
    assert report["balance_lookup_coinbase_call_attempted"] is True
    assert report["order_submit_coinbase_call_attempted"] is False
    assert report["execution_result"]["balance_lookup_coinbase_call_attempted"] is True
    assert report["execution_result"]["order_submit_coinbase_call_attempted"] is False
    assert "coinbase_base_lookup_empty" in report["blockers"]
    assert "base_balance_verification_missing" in report["blockers"]


def test_wrong_coinbase_currency_fails_closed_with_base_asset_mismatch() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(_accounts_payload(_account("BTC", "10"))),
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "base_asset_mismatch" in report["blockers"]
    rows = report["execution_result"]["base_preflight"]["rows"]
    assert rows[0]["lookup_base_asset"] == "BTC"
    assert rows[0]["base_asset_match"] is False


def test_coinbase_account_exception_fails_closed_with_lookup_failed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(_accounts_payload(), error=RuntimeError("boom")),
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert report["balance_lookup_coinbase_call_attempted"] is True
    assert "coinbase_base_lookup_failed" in report["blockers"]


def test_available_balance_missing_fails_closed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(
            _accounts_payload(
                _account("ETH", MISSING),
                _account("AVAX", "3.67647058"),
                _account("SOL", "0.3485292"),
            )
        ),
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "available_base_missing" in report["blockers"]
    assert "coinbase_base_lookup_empty" in report["blockers"]


def test_available_balance_unparseable_fails_closed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(
            _accounts_payload(
                _account("ETH", "not-a-decimal"),
                _account("AVAX", "3.67647058"),
                _account("SOL", "0.3485292"),
            )
        ),
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "available_base_unparseable" in report["blockers"]


def test_live_lookup_local_base_unparseable_fails_closed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(
            _accounts_payload(
                _account("ETH", "0.0141964735707866"),
                _account("AVAX", "3.67647058"),
                _account("SOL", "0.3485292"),
            ),
            locals_by_ticker={
                "ETH-USDC": "not-a-decimal",
                "AVAX-USDC": "3.67647058",
                "SOL-USDC": "0.3485292",
            },
        ),
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "local_base_unparseable" in report["blockers"]


def test_live_lookup_available_below_local_fails_closed_as_oversell() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(
            _accounts_payload(
                _account("ETH", "0.014"),
                _account("AVAX", "3.67647058"),
                _account("SOL", "0.3485292"),
            )
        ),
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "available_base_below_local_base" in report["blockers"]
    assert "oversell_risk_detected" in report["blockers"]


def test_live_lookup_uses_decimal_tolerance_for_truncated_available_base() -> None:
    rows = _live_rows_from_accounts(
        _accounts_payload(_account("ETH", "1.000000000")),
        locals_by_ticker={"ETH-USDC": "1.000000005"},
    )

    assert rows[0]["base_balance_tolerance"] == "1E-8"
    assert rows[0]["base_balance_verified"] is True


def test_execute_live_with_mocked_live_balance_success_reaches_submit_attempt_path() -> None:
    called = {"value": False}

    def submitter(payload):
        called["value"] = True
        return {"submitted": False}

    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=_live_rows_from_accounts(
            _accounts_payload(
                _account("ETH", "0.0141964735707866"),
                _account("AVAX", "3.67647058"),
                _account("SOL", "0.3485292"),
            )
        ),
        coinbase_submitter=submitter,
    )

    assert called["value"] is True
    assert report["status"] == "execute_live_submit_rejected"
    assert report["balance_lookup_coinbase_call_attempted"] is True
    assert report["order_submit_coinbase_call_attempted"] is True
    assert report["execution_result"]["balance_lookup_coinbase_call_attempted"] is True
    assert report["execution_result"]["order_submit_coinbase_call_attempted"] is True
    assert report["live_submit_attempted"] is True
    assert report["live_order_submitted"] is False


def test_default_mode_is_preview_and_never_live_submits() -> None:
    report = _report()

    assert report["mode"] == "preview"
    assert report["status"] == "ack_gated_preview_ready"
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False
    assert report["state_write_performed"] is False


def test_exact_ack_without_execute_live_does_not_submit() -> None:
    report = _report(mode="validate")

    assert report["ack_matches_required"] is True
    assert report["execution_result"]["would_submit_controlled_close"] is True
    assert report["live_submit_attempted"] is False
    assert report["live_order_submitted"] is False


def test_execute_live_without_extra_confirmation_blocks_before_submit() -> None:
    report = _report(mode="execute-live", live_confirmation=False)

    assert report["status"] == "blocked_missing_live_execute_confirmation"
    assert report["live_submit_attempted"] is False
    assert report["state_write_performed"] is False
    assert "blocked_missing_live_execute_confirmation" in report["blockers"]


def test_wrong_ack_blocks_execute_live() -> None:
    called = {"value": False}

    def submitter(payload):
        called["value"] = True
        return {"submitted": True, "order_id": "unexpected"}

    report = _report(mode="execute-live", live_confirmation=True, ack="WRONG_ACK", coinbase_submitter=submitter)

    assert report["live_submit_attempted"] is False
    assert called["value"] is False
    assert "exact_ack_required" in report["blockers"]


def test_ada_is_excluded_and_close_list_is_eth_avax_sol_only() -> None:
    report = _report()

    assert report["positions_to_close"] == POSITIONS
    assert report["positions_excluded_from_close"] == EXCLUDED
    assert report["ada_excluded"] is True


def test_service_active_blocks_execute_live() -> None:
    report = _report(mode="execute-live", live_confirmation=True, service_active=True, coinbase_submitter=lambda payload: {"submitted": True})

    assert report["live_submit_attempted"] is False
    assert "service_active_blocks_execute_live" in report["blockers"]
    assert "service_active" in report["blockers"]


def test_unverified_base_blocks_execute_live() -> None:
    report = _report(mode="execute-live", live_confirmation=True, position_rows=_rows(evidence=False), coinbase_submitter=lambda payload: {"submitted": True})

    assert report["live_submit_attempted"] is False
    assert "base_balance_verification_missing" in report["blockers"]
    assert "coinbase_base_lookup_missing" in report["blockers"]


def test_available_base_greater_than_local_with_lookup_evidence_verifies() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=[
            _row("ETH-USDC", local="1.0", available="1.1"),
            _row("AVAX-USDC", local="1.0", available="1.1"),
            _row("SOL-USDC", local="1.0", available="1.1"),
        ],
        coinbase_submitter=lambda payload: {"submitted": True, "order_id": "cb-close-1"},
    )

    assert report["live_submit_attempted"] is True
    assert all(row["base_balance_verified"] is True for row in report["execution_result"]["base_preflight"]["rows"])


def test_available_base_equal_to_local_with_lookup_evidence_verifies() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=[
            _row("ETH-USDC", local="1.0", available="1.0"),
            _row("AVAX-USDC", local="1.0", available="1.0"),
            _row("SOL-USDC", local="1.0", available="1.0"),
        ],
        coinbase_submitter=lambda payload: {"submitted": True, "order_id": "cb-close-1"},
    )

    assert report["live_submit_attempted"] is True
    assert report["execution_result"]["base_preflight"]["base_balances_verified"] is True


def test_eth_truncation_case_with_live_lookup_evidence_verifies() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=[
            _row("ETH-USDC", local="0.01419647", available="0.0141964735707866"),
            _row("AVAX-USDC", local="3.67647058", available="3.67647058"),
            _row("SOL-USDC", local="0.3485292", available="0.3485292"),
        ],
        coinbase_submitter=lambda payload: {"submitted": True, "order_id": "cb-close-1"},
    )

    rows = report["execution_result"]["base_preflight"]["rows"]
    eth = next(row for row in rows if row["ticker"] == "ETH-USDC")
    assert eth["base_balance_verified"] is True
    assert eth["would_oversell"] is False


def test_oversell_blocks_execute_live() -> None:
    report = _report(mode="execute-live", live_confirmation=True, position_rows=_rows(oversell=True), coinbase_submitter=lambda payload: {"submitted": True})

    assert report["live_submit_attempted"] is False
    assert "oversell_risk_detected" in report["blockers"]
    assert "available_base_below_local_base" in report["blockers"]


def test_available_base_below_local_fails_closed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=[
            _row("ETH-USDC", local="1.0", available="0.99"),
            _row("AVAX-USDC", local="1.0", available="1.0"),
            _row("SOL-USDC", local="1.0", available="1.0"),
        ],
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert report["execution_result"]["base_preflight"]["rows"][0]["base_balance_verified"] is False
    assert "available_base_below_local_base" in report["blockers"]


def test_available_base_parse_error_fails_closed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=[
            _row("ETH-USDC", local="1.0", available="not-a-decimal"),
            _row("AVAX-USDC", local="1.0", available="1.0"),
            _row("SOL-USDC", local="1.0", available="1.0"),
        ],
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "available_base_unparseable" in report["blockers"]


def test_local_base_parse_error_fails_closed() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        position_rows=[
            _row("ETH-USDC", local="not-a-decimal", available="1.0"),
            _row("AVAX-USDC", local="1.0", available="1.0"),
            _row("SOL-USDC", local="1.0", available="1.0"),
        ],
        coinbase_submitter=lambda payload: {"submitted": True},
    )

    assert report["live_submit_attempted"] is False
    assert "local_base_unparseable" in report["blockers"]


def test_unverified_mock_source_fails_closed() -> None:
    rows = [
        _row("ETH-USDC", source=BASE_BALANCE_SOURCE_TEST_FIXTURE, fixture_verified=False),
        _row("AVAX-USDC", source=BASE_BALANCE_SOURCE_TEST_FIXTURE, fixture_verified=False),
        _row("SOL-USDC", source=BASE_BALANCE_SOURCE_TEST_FIXTURE, fixture_verified=False),
    ]
    report = _report(mode="execute-live", live_confirmation=True, position_rows=rows, coinbase_submitter=lambda payload: {"submitted": True})

    assert report["live_submit_attempted"] is False
    assert "coinbase_base_lookup_unverified_source" in report["blockers"]


def test_duplicate_exit_blocks_execute_live() -> None:
    report = _report(mode="execute-live", live_confirmation=True, duplicate_exit_exists=True, coinbase_submitter=lambda payload: {"submitted": True})

    assert report["live_submit_attempted"] is False
    assert "duplicate_open_exit_detected" in report["blockers"]
    assert "duplicate_exit_exists" in report["blockers"]


def test_pending_fill_does_not_write_state() -> None:
    report = _report(
        mode="execute-live",
        live_confirmation=True,
        coinbase_submitter=lambda payload: {"submitted": True, "order_id": "cb-close-1"},
        terminal_fill_evidence={"normalized_status": "open", "filled_base": "0"},
    )

    assert report["status"] == "submitted_pending_terminal_fill"
    assert report["live_submit_attempted"] is True
    assert report["live_order_submitted"] is True
    assert report["state_write_performed"] is False
    assert report["execution_result"]["next_operator_action"] == "run reconcile/check tool"


def test_terminal_fill_required_before_state_write_and_happy_path_applies() -> None:
    applied = {"called": False}

    def apply(payload):
        applied["called"] = True
        return {"state_write_performed": True}

    report = _report(
        mode="execute-live",
        live_confirmation=True,
        coinbase_submitter=lambda payload: {"submitted": True, "order_id": "cb-close-1"},
        terminal_fill_evidence={"normalized_status": "filled", "filled_base": "3", "fill_count": 3},
        state_apply_callback=apply,
    )

    assert report["status"] == "submitted_terminal_fill_applied"
    assert report["live_order_submitted"] is True
    assert report["state_write_performed"] is True
    assert applied["called"] is True


def test_json_output_path_must_be_under_reports_live_runs() -> None:
    report = _report(json_out=str(Path("reports/audits/not-live-run.json")))

    assert "json_out_must_be_under_reports_live_runs" in report["blockers"]
