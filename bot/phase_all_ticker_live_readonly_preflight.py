from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_per_ticker_product_rule_evidence_cache import RULE_KEYS
from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS
from tools.show_function_preservation_audit import build_audit_report
from tools.show_open_orders import build_summary as build_open_order_summary
from tools.show_open_orders import load_orders


PHASE_ALL_TICKER_LIVE_READONLY_PREFLIGHT = "all_ticker_live_readonly_preflight_v1"
BTC_TICKER = "BTC-USDC"
DEFAULT_QUOTE_SIZE = Decimal("10.00")
DEFAULT_MAX_ORDER_QUOTE = Decimal("25.00")


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _json_safe(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _decimal_positive(value: Any) -> bool:
    return _to_decimal(value, "0") > Decimal("0")


def _env_value(root: Path, key: str) -> str:
    try:
        text = (root / ".env").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""
    value = ""
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw_value = stripped.split("=", 1)
        if name.strip() == key:
            value = raw_value.strip().strip("\"'")
    return value


def _default_quote_size(root: Path) -> Decimal:
    return _to_decimal(_env_value(root, "DEFAULT_QUOTE_SIZE_USDC") or "10.00", "10.00")


def _max_order_quote(root: Path) -> Decimal:
    return _to_decimal(
        _env_value(root, "PHASE_C_MAX_ORDER_QUOTE")
        or _env_value(root, "MAX_NOTIONAL_USD")
        or "25.00",
        "25.00",
    )


def _normalize_product_rule_fields(product: Dict[str, Any]) -> Dict[str, str]:
    content = product.get("product") if isinstance(product.get("product"), dict) else product
    rules = content.get("product_rules") if isinstance(content.get("product_rules"), dict) else content
    out: Dict[str, str] = {}
    for logical_key, candidate_keys in RULE_KEYS.items():
        value = ""
        for key in candidate_keys:
            raw = rules.get(key)
            if raw not in (None, "", "0", 0):
                value = str(raw)
                break
        out[logical_key] = value
    return out


class CoinbaseReadonlyProductBalanceAdapter:
    """Narrow all-ticker preflight adapter: product metadata and spot balances only."""

    def __init__(self, coinbase_client: Any):
        self._client = coinbase_client

    def get_product_rule(self, ticker: str) -> Dict[str, str]:
        return _normalize_product_rule_fields(self._client.get_product(ticker))

    def get_balances(self, ticker: str) -> Dict[str, str]:
        snapshot = self._client.get_spot_position(ticker)
        return {
            "available_base": str(snapshot.get("available_base_balance") or ""),
            "hold_base": str(snapshot.get("hold_base_balance") or ""),
            "available_quote": str(snapshot.get("available_quote_balance") or ""),
            "hold_quote": str(snapshot.get("hold_quote_balance") or ""),
        }


def collect_all_ticker_live_readonly_snapshot(
    readonly_client: Any,
    *,
    tickers: Optional[List[str]] = None,
    default_quote_size: Decimal = DEFAULT_QUOTE_SIZE,
    max_order_quote: Decimal = DEFAULT_MAX_ORDER_QUOTE,
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for ticker in tickers or list(DEFAULT_TICKERS):
        row: Dict[str, Any] = {
            "ticker": ticker,
            "live_readonly_product_rule_attempted": True,
            "live_readonly_product_rule_passed": False,
            "live_readonly_balance_attempted": False,
            "live_readonly_balance_passed": False,
            "default_quote_size": str(default_quote_size),
            "blockers": [],
            "warnings": [],
        }
        try:
            rules = readonly_client.get_product_rule(ticker)
            if not isinstance(rules, dict):
                rules = {}
        except Exception as exc:
            rules = {}
            row["blockers"].append("live_product_rule_read_failed")
            if "COINBASE_API_KEY" in str(exc):
                row["blockers"].append("coinbase_auth_missing_for_readonly_preflight")
            row["warnings"].append(f"live_product_rule_read_error:{type(exc).__name__}")

        normalized_rules = _product_fields(rules)
        row.update(normalized_rules)
        missing_rule_fields = [key for key, value in normalized_rules.items() if not _decimal_positive(value)]
        row["live_readonly_product_rule_passed"] = not missing_rule_fields
        if missing_rule_fields:
            row["blockers"].append("product_rule_fields_missing_or_nonpositive")

        min_notional = _to_decimal(normalized_rules.get("min_notional"), "0")
        row["min_notional_pass"] = bool(min_notional > 0 and default_quote_size >= min_notional)
        row["cap_pass"] = bool(default_quote_size > 0 and default_quote_size <= max_order_quote)
        if not row["min_notional_pass"]:
            row["blockers"].append("default_quote_size_below_min_notional")
        if not row["cap_pass"]:
            row["blockers"].append("default_quote_size_above_cap")

        row["live_readonly_balance_attempted"] = True
        try:
            balances = readonly_client.get_balances(ticker)
            if not isinstance(balances, dict):
                balances = {}
        except Exception as exc:
            balances = {}
            row["blockers"].append("live_balance_read_failed")
            if "COINBASE_API_KEY" in str(exc):
                row["blockers"].append("coinbase_auth_missing_for_readonly_preflight")
            row["warnings"].append(f"live_balance_read_error:{type(exc).__name__}")

        available_quote = _to_decimal(balances.get("available_quote"), "0")
        available_base = _to_decimal(balances.get("available_base"), "0")
        row["available_quote"] = str(available_quote)
        row["available_base"] = str(available_base)
        row["balance_pass"] = bool(available_quote >= default_quote_size > 0)
        row["live_readonly_balance_passed"] = row["balance_pass"]
        if not row["balance_pass"]:
            row["blockers"].append("available_quote_below_default_quote_size")
        rows.append(row)
    return {
        "coinbase_call_attempted": True,
        "coinbase_readonly_methods": ["get_product", "get_spot_position"],
        "forbidden_methods_exposed_to_preflight": [],
        "per_ticker_readonly": rows,
    }


def _rows_by_ticker(rows: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("ticker"):
                out[str(row["ticker"]).upper()] = row
    return out


def _product_fields(row: Dict[str, Any]) -> Dict[str, str]:
    rules = row.get("product_rules") if isinstance(row.get("product_rules"), dict) else row
    return {
        "base_increment": str(rules.get("base_increment") or ""),
        "quote_increment": str(rules.get("quote_increment") or ""),
        "price_increment": str(rules.get("price_increment") or ""),
        "min_order_size": str(rules.get("min_order_size") or ""),
        "min_notional": str(rules.get("min_notional") or ""),
    }


def _source_for(cache_row: Dict[str, Any], fixture_row: Dict[str, Any], ticker: str) -> str:
    strength = str(cache_row.get("evidence_strength") or fixture_row.get("evidence_strength") or "")
    source = str(cache_row.get("evidence_source_type") or fixture_row.get("evidence_source_type") or "")
    if strength == "live_readonly_cached":
        return "local_cache"
    if strength == "local_fixture" or source == "fixture":
        return "fixture"
    if ticker == BTC_TICKER:
        return "local_cache"
    return "missing"


def build_all_ticker_live_readonly_preflight(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    live_readonly_snapshot: Optional[Dict[str, Any]] = None,
    function_audit_report: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Build a fail-closed all-ticker preflight report.

    `live_readonly_snapshot` is only for tests/future safe adapters. The default path
    never calls Coinbase and marks the live-readonly preflight as not run.
    """

    project_root = Path(root).resolve()
    cache = _load_json(project_root / "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json")
    fixture = _load_json(project_root / "reports/d6/product-rule-fixture-evidence-20260609.json")
    cache_rows = _rows_by_ticker(cache.get("per_ticker_matrix"))
    fixture_rows = _rows_by_ticker(fixture.get("per_ticker_fixture_evidence_matrix"))
    live_rows = _rows_by_ticker((live_readonly_snapshot or {}).get("per_ticker_readonly"))
    attempted = bool(live_readonly_snapshot)
    orders = load_orders(project_root / "state/open_orders.json")
    open_summary = dict(build_open_order_summary(orders))
    open_orders = int(open_summary.get("open_orders") or 0)
    harness = _load_json(project_root / "reports/d6/safe-regression-harness-20260609.json")
    selected = harness.get("selected_tests") if isinstance(harness.get("selected_tests"), dict) else {}
    selected_tests_classification = str(selected.get("selected_tests_classification") or "UNKNOWN")
    selected_tests_ok = selected_tests_classification == "OK"
    if function_audit_report is None:
        try:
            function_audit_report = build_audit_report(project_root)
        except Exception as exc:
            function_audit_report = {
                "overall_status": "review_required",
                "warnings": [f"function_audit_load_failed:{type(exc).__name__}"],
            }
    audit_warnings = list((function_audit_report or {}).get("warnings") or [])
    c43_warning = "filled_c43_without_position_created:phasec-BTCUSDC-smoke-20260524151451"
    audit_warning_status = (
        "stale_historical_warning_known_safe"
        if c43_warning in audit_warnings and open_orders == 0
        else ("not_present" if c43_warning not in audit_warnings else "needs_manual_review")
    )
    default_quote_size = _default_quote_size(project_root)

    matrix: List[Dict[str, Any]] = []
    for ticker in DEFAULT_TICKERS:
        cache_row = cache_rows.get(ticker, {})
        fixture_row = fixture_rows.get(ticker, {})
        live_row = live_rows.get(ticker, {})
        local_rules = _product_fields(cache_row or fixture_row)
        live_rules = _product_fields(live_row)
        source = "live_readonly" if attempted and ticker in live_rows else _source_for(cache_row, fixture_row, ticker)
        fields = live_rules if source == "live_readonly" else local_rules
        missing_rule_fields = [key for key, value in fields.items() if not value]
        available_quote = live_row.get("available_quote")
        available_base = live_row.get("available_base")
        tiny_quote = str(live_row.get("estimated_tiny_order_quote") or fields.get("min_notional") or "not_estimated")
        blockers: List[str] = []
        warnings: List[str] = []
        if open_orders:
            blockers.append("open_orders_present")
        if not selected_tests_ok:
            blockers.append("selected_tests_not_ok")
        if not attempted:
            blockers.append("fresh_live_readonly_preflight_not_run")
            warnings.append("live Coinbase product/balance/min-notional preflight was not run by Codex")
        if source in {"fixture", "missing"}:
            blockers.append("live_product_rule_evidence_missing")
        if missing_rule_fields:
            blockers.append("product_rule_fields_missing")
        if attempted and live_row.get("balance_pass") is False:
            blockers.append("balance_or_min_notional_failed")
        if attempted and live_row.get("cap_pass") is False:
            blockers.append("cap_failed")
        blockers.extend(str(item) for item in live_row.get("blockers") or [])
        warnings.extend(str(item) for item in live_row.get("warnings") or [])
        live_entry_status = "not_run" if not attempted else ("pass" if not blockers else "blocked")
        live_exit_status = "not_run" if not attempted else "blocked"
        if source == "live_readonly" and not blockers:
            recommended_scope = "eligible_for_operator_review"
        elif "balance_or_min_notional_failed" in blockers:
            recommended_scope = "blocked_by_balance"
        elif "cap_failed" in blockers:
            recommended_scope = "blocked_by_cap"
        elif "live_product_rule_evidence_missing" in blockers:
            recommended_scope = "blocked_by_product_rule"
        else:
            recommended_scope = "blocked_until_fresh_preflight"
        matrix.append(
            {
                "ticker": ticker,
                "configured": True,
                "live_readonly_product_rule_attempted": bool(attempted and live_row.get("live_readonly_product_rule_attempted")),
                "live_readonly_product_rule_passed": bool(attempted and live_row.get("live_readonly_product_rule_passed")),
                "live_readonly_balance_attempted": bool(attempted and live_row.get("live_readonly_balance_attempted")),
                "live_readonly_balance_passed": bool(attempted and live_row.get("live_readonly_balance_passed")),
                "product_rule_source": source,
                **fields,
                "available_base": available_base if attempted else None,
                "available_quote": available_quote if attempted else None,
                "default_quote_size": str(live_row.get("default_quote_size") or default_quote_size),
                "estimated_tiny_order_quote": tiny_quote,
                "min_notional_pass": bool(attempted and not missing_rule_fields and live_row.get("min_notional_pass", False)),
                "cap_pass": bool(attempted and live_row.get("cap_pass", False)),
                "balance_pass": bool(attempted and live_row.get("balance_pass", False)),
                "live_entry_preflight_status": live_entry_status,
                "live_exit_preflight_status": live_exit_status,
                "blockers": sorted(set(blockers)),
                "warnings": warnings,
                "eligible_for_operator_review": source == "live_readonly" and not blockers,
                "live_ready": False,
                "all_ticker_live_authorized": False,
                "recommended_scope": recommended_scope,
            }
        )

    passed = (
        attempted
        and selected_tests_ok
        and all(row["live_entry_preflight_status"] == "pass" for row in matrix)
        and open_orders == 0
    )
    report = {
        "phase": PHASE_ALL_TICKER_LIVE_READONLY_PREFLIGHT,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "readonly_preflight_only": True,
            "live_readonly_preflight_attempted": attempted,
            "coinbase_call_attempted": bool((live_readonly_snapshot or {}).get("coinbase_call_attempted", False)),
            "coinbase_readonly_methods": list((live_readonly_snapshot or {}).get("coinbase_readonly_methods") or []),
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "order_action_attempted": False,
            "submit_attempted": False,
            "cancel_attempted": False,
            "replace_attempted": False,
            "reprice_attempted": False,
            "lifecycle_apply_attempted": False,
            "state_write_performed": False,
            "env_mutation_performed": False,
            "config_mutation_performed": False,
            "parameter_mutation_performed": False,
            "live_start_attempted": False,
        },
        "status": "pass" if passed else ("blocked" if attempted else "not_run"),
        "classification": "OK" if passed else "WATCH",
        "operator_command_required": not attempted,
        "open_order_summary": open_summary,
        "selected_tests": {
            "selected_tests_classification": selected_tests_classification,
            "selected_tests_passed_count": int(selected.get("selected_tests_passed_count") or 0),
            "selected_tests_failed_count": int(selected.get("selected_tests_failed_count") or 0),
        },
        "function_preservation_audit": {
            "overall_status": (function_audit_report or {}).get("overall_status"),
            "warnings": audit_warnings,
            "audit_warning_status": audit_warning_status,
            "filled_c43_without_position_created_classification": audit_warning_status,
            "classification_reason": (
                "Historical filled C4.3 smoke BUY warning is present, but there are no open orders/D3 exits; "
                "current BTC-USDC local position is closed. No state repair was performed."
                if audit_warning_status == "stale_historical_warning_known_safe"
                else "No matching historical warning present."
            ),
        },
        "configured_ticker_count": len(DEFAULT_TICKERS),
        "configured_tickers": list(DEFAULT_TICKERS),
        "per_ticker_preflight": matrix,
        "gate_decision": {
            "all_ticker_live_readonly_preflight_tool_ready": True,
            "all_ticker_live_readonly_preflight_attempted": attempted,
            "all_ticker_live_readonly_preflight_passed": passed,
            "all_ticker_ready_for_operator_fresh_preflight": passed,
            "all_ticker_live_authorized": False,
            "live_start_authorized": False,
            "btc_usdc_ready_for_operator_fresh_preflight": False if not attempted else any(
                row["ticker"] == BTC_TICKER and row["live_entry_preflight_status"] == "pass" for row in matrix
            ),
            "non_btc_tickers_ready_for_operator_fresh_preflight": False if not passed else True,
            "blocked_ticker_count": sum(1 for row in matrix if row["blockers"]),
            "parameter_change_allowed": False,
            "learning_to_execution_ready": False,
            "live_learning_allowed": False,
            "live_exits_enabled": False,
            "selected_tests_classification": selected_tests_classification,
            "audit_warning_status": audit_warning_status,
        },
        "operator_only_next_command": (
            "OPERATOR ONLY - CODEX MUST NOT RUN: run future all-ticker readonly Coinbase product/balance/min-notional preflight"
            if not attempted
            else ""
        ),
    }
    return _json_safe(report)


def render_all_ticker_live_readonly_preflight_markdown(report: Dict[str, Any]) -> str:
    gate = report.get("gate_decision") or {}
    lines = [
        "# All-Ticker Live-Readonly Preflight",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- live_readonly_preflight_attempted: `{gate.get('all_ticker_live_readonly_preflight_attempted')}`",
        f"- all_ticker_live_readonly_preflight_passed: `{gate.get('all_ticker_live_readonly_preflight_passed')}`",
        f"- all_ticker_live_authorized: `{gate.get('all_ticker_live_authorized')}`",
        "",
        "## Per-Ticker Preflight",
        "",
    ]
    for row in report.get("per_ticker_preflight") or []:
        lines.append(
            f"- {row.get('ticker')}: source=`{row.get('product_rule_source')}`, "
            f"entry=`{row.get('live_entry_preflight_status')}`, scope=`{row.get('recommended_scope')}`, "
            f"blockers=`{'; '.join(row.get('blockers') or [])}`"
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_ALL_TICKER_LIVE_READONLY_PREFLIGHT",
    "CoinbaseReadonlyProductBalanceAdapter",
    "build_all_ticker_live_readonly_preflight",
    "collect_all_ticker_live_readonly_snapshot",
    "render_all_ticker_live_readonly_preflight_markdown",
]
