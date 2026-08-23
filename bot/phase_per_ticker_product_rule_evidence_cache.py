from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_PER_TICKER_PRODUCT_RULE_EVIDENCE_CACHE = "per_ticker_product_rule_evidence_cache_v1"
PROVEN_TINY_TICKER = "BTC-USDC"
DEFAULT_TICKERS = [
    "BTC-USDC",
    "ETH-USDC",
    "SOL-USDC",
    "XRP-USDC",
    "ADA-USDC",
    "LINK-USDC",
    "AVAX-USDC",
    "DOGE-USDC",
    "SUI-USDC",
    "LTC-USDC",
    "HBAR-USDC",
    "ATOM-USDC",
    "NEAR-USDC",
    "APT-USDC",
    "INJ-USDC",
    "ARB-USDC",
    "OP-USDC",
    "UNI-USDC",
]
RULE_KEYS = {
    "base_increment": ("base_increment", "base_increment_size"),
    "quote_increment": ("quote_increment", "quote_increment_size"),
    "price_increment": ("price_increment", "price_increment_size"),
    "min_order_size": ("min_order_base", "base_min_size", "base_min_order_size", "min_size"),
    "min_notional": ("min_order_quote", "quote_min_size", "quote_min_order_size", "min_notional", "min_market_funds"),
}


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


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _configured_tickers_from_config(root: Path) -> List[str]:
    text = _read_text(root / "bot" / "config.py")
    out: List[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b[A-Z0-9]+-USDC\b", text):
        ticker = _normalize_ticker(match.group(0))
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _configured_tickers(root: Path) -> List[str]:
    tickers = _configured_tickers_from_config(root)
    if tickers:
        return tickers
    replay = _load_json(root / "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json")
    summary = replay.get("universe_summary") if isinstance(replay.get("universe_summary"), dict) else {}
    replay_tickers = [_normalize_ticker(t) for t in summary.get("configured_tickers") or [] if _normalize_ticker(t)]
    return replay_tickers or list(DEFAULT_TICKERS)


def _config_decimal_default(root: Path, field: str, default: str) -> str:
    text = _read_text(root / "bot" / "config.py")
    match = re.search(rf"{re.escape(field)}:.*?_get_decimal_env\([^,]+,\s*[\"']([^\"']+)[\"']", text)
    return match.group(1) if match else default


def _content(payload: Dict[str, Any]) -> Dict[str, Any]:
    content = payload.get("content")
    return content if isinstance(content, dict) else payload


def _dig_product_rules(payload: Dict[str, Any]) -> Dict[str, Any]:
    content = _content(payload)
    candidates = [
        content,
        content.get("product_rules") if isinstance(content.get("product_rules"), dict) else {},
        (content.get("fresh_preflight") or {}).get("product_rules") if isinstance(content.get("fresh_preflight"), dict) else {},
        (payload.get("fresh_preflight") or {}).get("product_rules") if isinstance(payload.get("fresh_preflight"), dict) else {},
    ]
    for candidate in candidates:
        if isinstance(candidate, dict) and any(key in candidate for keys in RULE_KEYS.values() for key in keys):
            return candidate
    return {}


def _value_for(rules: Dict[str, Any], logical_key: str) -> str:
    for key in RULE_KEYS[logical_key]:
        value = rules.get(key)
        if value not in (None, "", "0", 0):
            return str(value)
    return ""


def _fixture_records_from_report(root: Path) -> Dict[str, Dict[str, Any]]:
    payload = _load_json(root / "reports/d6/product-rule-fixture-evidence-20260609.json")
    rows = payload.get("per_ticker_fixture_evidence_matrix")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            ticker = _normalize_ticker(row.get("ticker"))
            if ticker:
                out[ticker] = row
    return out


def _fixture_records_from_file(root: Path) -> Dict[str, Dict[str, Any]]:
    payload = _load_json(root / "fixtures/product_rules/local_product_rule_fixtures_v1.json")
    defaults = payload.get("default_fixture_rules") if isinstance(payload.get("default_fixture_rules"), dict) else {}
    records = payload.get("fixtures") if isinstance(payload.get("fixtures"), list) else []
    out: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        ticker = _normalize_ticker(record.get("ticker"))
        if not ticker:
            continue
        merged = {**defaults, **record}
        out[ticker] = {
            "ticker": ticker,
            "evidence_strength": "local_fixture",
            "evidence_source_type": "fixture",
            "base_increment": str(merged.get("base_increment") or ""),
            "quote_increment": str(merged.get("quote_increment") or ""),
            "price_increment": str(merged.get("price_increment") or ""),
            "min_order_size": str(merged.get("min_order_size") or ""),
            "min_notional": str(merged.get("min_notional") or ""),
            "source_path": str(root / "fixtures/product_rules/local_product_rule_fixtures_v1.json"),
        }
    return out


def _rules_from_fixture_row(row: Dict[str, Any]) -> Dict[str, str]:
    rules = row.get("product_rules") if isinstance(row.get("product_rules"), dict) else row
    return {
        "base_increment": str(rules.get("base_increment") or ""),
        "quote_increment": str(rules.get("quote_increment") or ""),
        "price_increment": str(rules.get("price_increment") or ""),
        "min_order_size": str(rules.get("min_order_size") or ""),
        "min_notional": str(rules.get("min_notional") or ""),
    }


def _status_for_value(value: str) -> str:
    return "ready" if value else "missing"


def _find_local_product_rule_evidence(root: Path, ticker: str) -> Dict[str, Any]:
    reports = sorted((root / "reports" / "d6").glob("*.json")) if (root / "reports" / "d6").exists() else []
    sources: List[str] = []
    merged_rules: Dict[str, Any] = {}
    fixture_only = False
    evidence_strength = "missing"
    evidence_source_type = "missing"
    for path in reports:
        name = path.name.lower()
        text = _read_text(path)
        if ticker not in text:
            continue
        if not any(token in text for token in ("base_increment", "quote_increment", "price_increment", "min_order_quote", "base_min_size")):
            continue
        payload = _load_json(path)
        rules = _dig_product_rules(payload)
        if not rules:
            continue
        source_kind = "fixture_or_report"
        if "product-rules-readiness" in name or "preflight" in name or "scope-packet" in name:
            source_kind = "local_report"
        if "fixture" in name or "test" in name:
            fixture_only = True
            source_kind = "fixture"
        for logical in RULE_KEYS:
            value = _value_for(rules, logical)
            if value and logical not in merged_rules:
                merged_rules[logical] = value
        sources.append(f"{path}:{source_kind}")
        if source_kind == "local_report":
            evidence_strength = "live_readonly_cached"
            evidence_source_type = "local_report"
        elif source_kind == "fixture" and evidence_strength == "missing":
            evidence_strength = "local_fixture"
            evidence_source_type = "fixture"

    fixture_row = _fixture_records_from_report(root).get(ticker) or _fixture_records_from_file(root).get(ticker)
    if fixture_row and evidence_strength == "missing":
        fixture_rules = _rules_from_fixture_row(fixture_row)
        for logical, value in fixture_rules.items():
            if value and logical not in merged_rules:
                merged_rules[logical] = value
        sources.append(f"{fixture_row.get('source_path') or 'local_product_rule_fixture'}:fixture")
        fixture_only = True
        evidence_strength = "local_fixture"
        evidence_source_type = "fixture"
    return {
        "rules": merged_rules,
        "sources": sources,
        "fixture_only": fixture_only and bool(sources),
        "evidence_strength": evidence_strength,
        "evidence_source_type": evidence_source_type,
    }


def _replay_rows(root: Path) -> Dict[str, Dict[str, Any]]:
    payload = _load_json(root / "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json")
    rows = payload.get("per_ticker_replay_matrix")
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                ticker = _normalize_ticker(row.get("ticker"))
                if ticker:
                    out[ticker] = row
    return out


def _blockers(
    *,
    configured: bool,
    product_status: str,
    values: Dict[str, str],
    stale_or_unknown: bool,
) -> List[str]:
    blockers: List[str] = []
    if not configured:
        blockers.append("missing_ticker_config")
    if product_status in {"missing", "unknown"}:
        blockers.append("missing_product_rule_evidence")
    if not values.get("min_order_size"):
        blockers.append("missing_min_size")
    if not values.get("base_increment") or not values.get("quote_increment"):
        blockers.append("missing_increment")
    if not values.get("price_increment"):
        blockers.append("missing_price_increment")
    if not values.get("min_notional"):
        blockers.append("missing_min_notional")
    if stale_or_unknown:
        blockers.append("evidence_stale_or_unknown")
    return sorted(set(blockers))


def _next_step(ticker: str, product_status: str, blockers: List[str]) -> str:
    if ticker == PROVEN_TINY_TICKER and product_status in {"ready", "partial"}:
        return "eligible_for_future_tiny_live_review_after_fresh_preflight_ACK"
    if "missing_product_rule_evidence" in blockers:
        return "collect_local_product_rule_evidence"
    if product_status in {"ready", "partial"}:
        return "eligible_for_paper_lifecycle_replay_upgrade"
    return "keep_paper_only"


def build_per_ticker_product_rule_evidence_cache_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    configured_from_config = _configured_tickers_from_config(project_root)
    configured = _configured_tickers(project_root)
    max_notional = _config_decimal_default(project_root, "max_notional_usd", "25.00")
    default_quote_cap = _config_decimal_default(project_root, "default_quote_size_usdc", "10.00")
    replay = _replay_rows(project_root)

    matrix: List[Dict[str, Any]] = []
    for ticker in configured:
        evidence = _find_local_product_rule_evidence(project_root, ticker)
        values = {key: str(evidence["rules"].get(key) or "") for key in RULE_KEYS}
        present_count = sum(1 for value in values.values() if value)
        if present_count == len(RULE_KEYS) and evidence["evidence_strength"] == "live_readonly_cached":
            status = "ready"
        elif present_count == len(RULE_KEYS):
            status = "partial"
        elif present_count > 0:
            status = "partial"
        else:
            status = "missing"
        stale_or_unknown = status != "ready" or ticker != PROVEN_TINY_TICKER
        blockers = _blockers(
            configured=True,
            product_status=status,
            values=values,
            stale_or_unknown=stale_or_unknown,
        )
        row = {
            "ticker": ticker,
            "configured": True,
            "product_rule_evidence_status": status,
            "evidence_source_type": evidence["evidence_source_type"],
            "evidence_strength": evidence["evidence_strength"],
            "evidence_sources": evidence["sources"],
            "base_increment": values["base_increment"],
            "quote_increment": values["quote_increment"],
            "price_increment": values["price_increment"],
            "min_order_size": values["min_order_size"],
            "min_notional": values["min_notional"],
            "quote_cap": default_quote_cap,
            "max_notional": max_notional,
            "base_increment_status": _status_for_value(values["base_increment"]),
            "quote_increment_status": _status_for_value(values["quote_increment"]),
            "price_increment_status": _status_for_value(values["price_increment"]),
            "min_order_size_status": _status_for_value(values["min_order_size"]),
            "min_notional_status": _status_for_value(values["min_notional"]),
            "sizing_cap_status": "ready" if max_notional and default_quote_cap else "missing",
            "lifecycle_replay_status": (replay.get(ticker) or {}).get("paper_lifecycle_replay_status", "unknown"),
            "live_product_rule_evidence": evidence["evidence_strength"] == "live_readonly_cached",
            "cached_product_rule_evidence": evidence["evidence_strength"] == "live_readonly_cached",
            "fixture_product_rule_evidence": evidence["evidence_strength"] == "local_fixture",
            "inferred_config_evidence": evidence["evidence_strength"] == "inferred",
            "paper_replay_usable": status in {"ready", "partial"} and present_count == len(RULE_KEYS),
            "blockers": blockers,
            "next_step": _next_step(ticker, status, blockers),
            "live_candidate_status": False,
        }
        matrix.append(row)

    ready_count = sum(1 for row in matrix if row["product_rule_evidence_status"] == "ready")
    partial_count = sum(1 for row in matrix if row["product_rule_evidence_status"] == "partial")
    missing_count = sum(1 for row in matrix if row["product_rule_evidence_status"] in {"missing", "unknown"})
    strong_count = sum(1 for row in matrix if row["evidence_strength"] == "live_readonly_cached")
    fixture_count = sum(1 for row in matrix if row["evidence_strength"] == "local_fixture")
    paper_replay_usable_count = sum(1 for row in matrix if row["paper_replay_usable"])
    all_ready = bool(matrix) and ready_count == len(matrix)
    upgraded = [
        row["ticker"]
        for row in matrix
        if row["paper_replay_usable"] and row["lifecycle_replay_status"] == "paper_lifecycle_replay_partial"
    ]
    watch_reasons: List[str] = []
    if not configured_from_config:
        watch_reasons.append("configured_universe_from_config_missing_or_malformed")
    if not all_ready:
        watch_reasons.append("product_rule_evidence_partial_or_missing")
    if missing_count:
        watch_reasons.append("product_rule_evidence_missing_for_some_tickers")

    classification = "OK" if all_ready else "WATCH"
    gate = {
        "per_ticker_product_rule_evidence_cache_ready": bool(matrix),
        "all_ticker_product_rule_evidence_ready": all_ready,
        "all_ticker_lifecycle_parity_ready": False,
        "all_ticker_live_allowed_now": False,
        "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
        "tickers_ready_count": ready_count,
        "tickers_partial_count": partial_count,
        "tickers_missing_count": missing_count,
        "strong_live_or_cached_evidence_count": strong_count,
        "fixture_evidence_count": fixture_count,
        "missing_evidence_count": missing_count,
        "paper_replay_usable_count": paper_replay_usable_count,
        "recommended_next_steps": [
            "sample-size/OOS/walk-forward acceptance policy" if not missing_count else "targeted local product-rule fixture completion",
            "D6 human-review pack",
            "fresh BTC-USDC live-start decision pack only if operator explicitly asks",
        ],
    }
    return _json_safe(
        {
            "phase": PHASE_PER_TICKER_PRODUCT_RULE_EVIDENCE_CACHE,
            "generated_at": generated_at or _now_iso(),
            "metadata": {
                "report_only": True,
                "local_files_only": True,
                "coinbase_call_attempted": False,
                "market_data_fetch_attempted": False,
                "http_call_attempted": False,
                "state_write_performed": False,
                "parameter_mutation_performed": False,
                "learning_to_execution_performed": False,
            },
            "classification": classification,
            "stop_reasons": [],
            "watch_reasons": sorted(set(watch_reasons)),
            "universe_summary": {
                "configured_ticker_count": len(configured),
                "configured_tickers": configured,
                "product_rule_cache_ready": bool(matrix),
                "tickers_with_ready_product_rule_evidence_count": ready_count,
                "tickers_with_partial_product_rule_evidence_count": partial_count,
                "tickers_missing_product_rule_evidence_count": missing_count,
                "strong_live_or_cached_evidence_count": strong_count,
                "fixture_evidence_count": fixture_count,
                "missing_evidence_count": missing_count,
                "paper_replay_usable_count": paper_replay_usable_count,
                "all_ticker_product_rule_evidence_ready": all_ready,
                "all_ticker_live_allowed_now": False,
            },
            "per_ticker_matrix": matrix,
            "paper_lifecycle_replay_integration": {
                "upgraded_tickers_from_partial_to_ready": upgraded,
                "upgrades_any_ticker": bool(upgraded),
                "why_not_all_upgraded": "product-rule evidence remains fixture-only or stale for some tickers"
                if not all_ready
                else "all product-rule evidence is locally ready, but live remains ACK-gated",
                "required_before_replay_or_all_ticker_ready": [
                    "strong live-readonly or cached product-rule evidence for every configured ticker",
                    "per-ticker lifecycle/orderbook evidence beyond paper labels",
                    "fresh preflight and separate all-ticker ACK before any live scope",
                ],
            },
            "gate_decision": gate,
            "learning_backlearning_boundary": {
                "product_rule_evidence_may_feed_later_backlearning_constraints": True,
                "no_parameter_changes_approved": True,
                "learning_to_execution_ready": False,
                "parameter_change_allowed": False,
                "parameter_review_approved": False,
            },
        }
    )


def render_per_ticker_product_rule_evidence_cache_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    summary = report.get("universe_summary") or {}
    gate = report.get("gate_decision") or {}
    lines = [
        "# Per-Ticker Product-Rule Evidence Cache",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- local_files_only: `{meta.get('local_files_only')}`",
        f"- coinbase_call_attempted: `{meta.get('coinbase_call_attempted')}`",
        f"- market_data_fetch_attempted: `{meta.get('market_data_fetch_attempted')}`",
        f"- http_call_attempted: `{meta.get('http_call_attempted')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        f"- learning_to_execution_performed: `{meta.get('learning_to_execution_performed')}`",
        "",
        "## Universe Summary",
        "",
        f"- configured_ticker_count: `{summary.get('configured_ticker_count')}`",
        f"- product_rule_cache_ready: `{summary.get('product_rule_cache_ready')}`",
        f"- ready_count: `{summary.get('tickers_with_ready_product_rule_evidence_count')}`",
        f"- partial_count: `{summary.get('tickers_with_partial_product_rule_evidence_count')}`",
        f"- missing_count: `{summary.get('tickers_missing_product_rule_evidence_count')}`",
        f"- all_ticker_product_rule_evidence_ready: `{summary.get('all_ticker_product_rule_evidence_ready')}`",
        f"- all_ticker_live_allowed_now: `{summary.get('all_ticker_live_allowed_now')}`",
        "",
        "## Gate Decision",
        "",
    ]
    for key, value in gate.items():
        lines.append(f"- {key}: `{'; '.join(value) if isinstance(value, list) else value}`")
    lines.extend(["", "## Per-Ticker Matrix", ""])
    for row in report.get("per_ticker_matrix") or []:
        lines.append(
            f"- {row.get('ticker')}: product_rules=`{row.get('product_rule_evidence_status')}`, "
            f"strength=`{row.get('evidence_strength')}`, source=`{row.get('evidence_source_type')}`, "
            f"base_increment=`{row.get('base_increment')}`, quote_increment=`{row.get('quote_increment')}`, "
            f"price_increment=`{row.get('price_increment')}`, min_notional=`{row.get('min_notional')}`, "
            f"paper_replay_usable=`{row.get('paper_replay_usable')}`, "
            f"live_candidate_status=`{row.get('live_candidate_status')}`, "
            f"next=`{row.get('next_step')}`"
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_PER_TICKER_PRODUCT_RULE_EVIDENCE_CACHE",
    "build_per_ticker_product_rule_evidence_cache_report",
    "render_per_ticker_product_rule_evidence_cache_markdown",
]
