import json
from pathlib import Path

from tools.build_bot_runtime_forensics import build_reports


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload) + "\n")


def _minimal_repo(tmp_path: Path) -> Path:
    (tmp_path / "logs").mkdir()
    (tmp_path / "state").mkdir()
    (tmp_path / "reports" / "audits").mkdir(parents=True)
    (tmp_path / "reports" / "research").mkdir(parents=True)
    (tmp_path / ".env").write_text(
        "\n".join(
            [
                "DEFAULT_QUOTE_SIZE_USDC=20.00",
                "MAX_NOTIONAL_USD=100.00",
                "AUTONOMOUS_MAX_ORDER_QUOTE=100.00",
                "PHASE_C_MAX_ORDER_QUOTE=100.00",
                "PHASE_D3_MAX_EXIT_ORDER_QUOTE=100.00",
                "AUTONOMOUS_MAX_OPEN_ORDERS=3",
                "MAX_OPEN_POSITIONS=3",
                "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    _write_json(
        tmp_path / "state" / "approved_parameter_profile.json",
        {
            "profile_name": "fee_aware_default_quote_50_bounded_v1",
            "profile_hash": "fixture",
            "parameters": {
                "DEFAULT_QUOTE_SIZE_USDC": "50.00",
                "MAX_NOTIONAL_USD": "100.00",
                "AUTONOMOUS_MAX_ORDER_QUOTE": "100.00",
                "PHASE_C_MAX_ORDER_QUOTE": "100.00",
                "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "100.00",
                "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
                "MAX_OPEN_POSITIONS": "3",
                "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
            },
        },
    )
    _write_json(tmp_path / "state" / "open_orders.json", [])
    _write_json(tmp_path / "state" / "positions.json", [])
    return tmp_path


def test_amount_audit_handles_default_profile_and_cheap_asset_quote_to_base(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    _write_json(
        root / "state" / "open_orders.json",
        [
            {
                "ticker": "ADA-USDC",
                "status": "filled",
                "exchange_order_id": "coinbase-1",
                "client_order_id": "client-1",
                "updated_at": "2026-06-18T04:06:27+00:00",
                "quote_size": "20.00",
                "base_size": "121.21212121",
                "price": "0.165",
            }
        ],
    )

    reports = build_reports(root, include_journal=False, journal_since=None, journal_limit=0)

    amount = reports["amount"]
    assert amount["configured"]["env_default_quote"] == "20.00"
    assert amount["configured"]["approved_profile_default_quote"] == "50.00"
    assert amount["configured"]["default_quote"] == "50.00"
    assert amount["violations"] == []
    assert not [item for item in amount["suspicious_records"] if item["incident_type"] == "quote_base_confusion"]


def test_amount_audit_flags_quote_size_used_as_base_size(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    _write_json(
        root / "state" / "open_orders.json",
        [
            {
                "ticker": "ETH-USDC",
                "status": "submitted",
                "exchange_order_id": "coinbase-2",
                "updated_at": "2026-06-18T04:06:27+00:00",
                "quote_size": "25.00",
                "base_size": "25.00",
                "price": "1750.00",
            }
        ],
    )

    reports = build_reports(root, include_journal=False, journal_since=None, journal_limit=0)

    assert [
        item
        for item in reports["amount"]["suspicious_records"]
        if item["incident_type"] == "quote_base_confusion"
    ]


def test_wait_cycle_with_live_submit_attempt_becomes_p0_incident(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    _append_jsonl(
        root / "logs" / "cycle_summary.jsonl",
        {
            "generated_at": "2026-06-17T00:09:16+00:00",
            "total": 8,
            "wait": 8,
            "valid_trade_plans": 0,
            "live_submit_attempted": 3,
        },
    )

    reports = build_reports(root, include_journal=False, journal_since=None, journal_limit=0)

    incidents = reports["incidents"]["incidents"]
    assert any(item["incident_type"] == "preview_wait_live_submit_attempt" for item in incidents)
    assert any(item["severity"] == "P0" for item in incidents)


def test_open_orders_state_dict_is_included_in_timeline(tmp_path: Path) -> None:
    root = _minimal_repo(tmp_path)
    _write_json(
        root / "state" / "open_orders.json",
        {
            "orders": {
                "client-1": {
                    "ticker": "BTC-USDC",
                    "status": "filled",
                    "exchange_order_id": "coinbase-1",
                    "client_order_id": "client-1",
                    "updated_at": "2026-06-18T04:06:27+00:00",
                    "quote_size": "10.00",
                    "base_size": "0.0001",
                    "price": "100000.00",
                }
            },
            "updated_at": "2026-06-18T04:06:28+00:00",
        },
    )

    reports = build_reports(root, include_journal=False, journal_since=None, journal_limit=0)

    full = reports["timeline"]["splits"]["full_available_log_history"]
    assert any(event["source"] == "open_orders" and event["client_order_id"] == "client-1" for event in full)
