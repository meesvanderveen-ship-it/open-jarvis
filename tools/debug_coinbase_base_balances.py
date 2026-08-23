#!/usr/bin/env python3
"""Read-only Coinbase Advanced Trade account/balance diagnostic.

This tool intentionally has no order, cancellation, replacement, or state
write capability.  It calls only ``CoinbaseClient.get_accounts()``, which uses
``GET /api/v3/brokerage/accounts``, and emits a redacted structural summary for
the requested currencies.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from bot.atomic_io import atomic_write_json
from bot.coinbase_client import (
    CoinbaseClient,
    _account_currency,
    _balance_value_with_path,
    _extract_accounts_list,
    normalize_coinbase_account_balances,
)


DEFAULT_CURRENCIES = ("ETH", "AVAX", "SOL")
DEFAULT_JSON_OUT = Path("reports/audits/coinbase-base-balance-diagnostic-latest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_project_dotenv_for_read_only_auth() -> Dict[str, bool]:
    """Use the project's existing dotenv loader without writing the .env file."""
    dotenv_path = PROJECT_ROOT / ".env"
    skipped = os.getenv("BOT_CONFIG_SKIP_DOTENV", "").strip().lower() in {"1", "true", "yes", "on"}
    try:
        import bot.config  # noqa: F401 - module import calls its established read-only dotenv loader

        return {
            "project_dotenv_load_attempted": True,
            "project_dotenv_present": dotenv_path.exists(),
            "project_dotenv_loaded": bool(dotenv_path.exists() and not skipped),
        }
    except Exception:
        return {
            "project_dotenv_load_attempted": True,
            "project_dotenv_present": dotenv_path.exists(),
            "project_dotenv_loaded": False,
        }


def _safe_error_type_and_status(exc: BaseException) -> Dict[str, str]:
    """Do not expose response bodies, credentials, or JWTs in diagnostics."""
    text = str(exc)
    match = re.search(r"\bHTTP error\s+(\d{3}|unknown)\b", text, flags=re.IGNORECASE)
    return {
        "type": type(exc).__name__,
        "http_status": match.group(1) if match else "",
    }


def _payload_shape(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, (list, tuple)):
        return "list"
    return type(value).__name__


def _top_level_keys(value: Any) -> List[str]:
    if isinstance(value, dict):
        return sorted(str(key) for key in value.keys())
    fields = getattr(value, "__dict__", None)
    if isinstance(fields, dict):
        return sorted(str(key) for key in fields.keys() if not str(key).startswith("_"))
    return []


def _redacted_decimal(value: str) -> str:
    """Keep balance evidence useful while avoiding unnecessary precision."""
    text = str(value or "").strip()
    if not text:
        return ""
    if len(text) <= 16:
        return text
    return f"{text[:12]}…"


def _account_summary(account: Any, currency: str, accounts_payload: Any) -> Dict[str, Any]:
    available, available_present, available_path = _balance_value_with_path(
        account,
        "available_balance",
        "available",
        "available_balance_value",
        "available_funds",
        "cash_available",
        "balance",
    )
    hold, hold_present, hold_path = _balance_value_with_path(
        account,
        "hold",
        "hold_balance",
        "hold_balance_value",
        "on_hold",
        "locked",
    )
    total, total_present, total_path = _balance_value_with_path(
        account,
        "balance",
        "total_balance",
        "total",
    )
    observed_currency = _account_currency(account)
    normalized = normalize_coinbase_account_balances(f"{currency}-USDC", accounts_payload)
    return {
        "requested_currency": currency,
        "currency": observed_currency,
        "product_id": f"{currency}-USDC",
        "account_found": bool(observed_currency == currency),
        "available_balance_field_path": available_path,
        "available_balance_present": available_present,
        "available_balance": _redacted_decimal(available) if available_present else "",
        "hold_field_path": hold_path,
        "hold_present": hold_present,
        "hold": _redacted_decimal(hold) if hold_present else "",
        "total_field_path": total_path,
        "total_present": total_present,
        "total": _redacted_decimal(total) if total_present else "",
        "normalizer_lookup_base_asset": str(normalized.get("lookup_base_asset") or ""),
        "normalizer_available_balance_field_path": str(normalized.get("available_base_balance_field_path") or ""),
        "normalizer_available_balance": _redacted_decimal(str(normalized.get("available_base_balance") or "")),
        "normalizer_base_balance_lookup_success": bool(normalized.get("base_balance_lookup_success")),
    }


def build_diagnostic_report(*, currencies: Iterable[str], client: Any | None = None) -> Dict[str, Any]:
    selected = [str(currency).strip().upper() for currency in currencies if str(currency).strip()]
    coinbase_client = client or CoinbaseClient()
    method_name = "get_accounts" if hasattr(coinbase_client, "get_accounts") else "missing"
    report: Dict[str, Any] = {
        "generated_at": _now_iso(),
        "read_only": True,
        "order_endpoints_used": False,
        "client_class": type(coinbase_client).__name__,
        "account_balance_client_method": method_name,
        "account_balance_endpoint": "GET /api/v3/brokerage/accounts",
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": False,
        "response_shape": "",
        "response_top_level_keys": [],
        "accounts_count": 0,
        "currencies": [],
        "error": None,
    }
    if method_name == "missing":
        report["error"] = {"type": "RuntimeError", "http_status": ""}
        return report

    try:
        report["coinbase_call_attempted"] = True
        payload = coinbase_client.get_accounts()
        accounts = _extract_accounts_list(payload)
        report["coinbase_call_succeeded"] = True
        report["response_shape"] = _payload_shape(payload)
        report["response_top_level_keys"] = _top_level_keys(payload)
        report["accounts_count"] = len(accounts)
        for currency in selected:
            account = next((row for row in accounts if _account_currency(row) == currency), None)
            report["currencies"].append(
                _account_summary(account, currency, payload)
                if account is not None
                else {
                    "requested_currency": currency,
                    "currency": "",
                    "product_id": f"{currency}-USDC",
                    "account_found": False,
                    "available_balance_field_path": "",
                    "available_balance_present": False,
                    "available_balance": "",
                    "hold_field_path": "",
                    "hold_present": False,
                    "hold": "",
                    "total_field_path": "",
                    "total_present": False,
                    "total": "",
                    "normalizer_lookup_base_asset": "",
                    "normalizer_available_balance_field_path": "",
                    "normalizer_available_balance": "",
                    "normalizer_base_balance_lookup_success": False,
                }
            )
    except Exception as exc:
        report["error"] = _safe_error_type_and_status(exc)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Read-only Coinbase ETH/AVAX/SOL account-balance diagnostic.")
    parser.add_argument("--currencies", default=",".join(DEFAULT_CURRENCIES))
    parser.add_argument("--json-out", default=str(DEFAULT_JSON_OUT))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    currencies = [item.strip().upper() for item in str(args.currencies).split(",") if item.strip()]
    dotenv_metadata = _load_project_dotenv_for_read_only_auth()
    # Build the client after dotenv loading, so this CLI has the same credential
    # context as normal bot entrypoints. No dotenv file is ever written.
    report = build_diagnostic_report(currencies=currencies)
    report.update(dotenv_metadata)
    output = Path(args.json_out)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(output, report, sort_keys=True)
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["coinbase_call_succeeded"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
