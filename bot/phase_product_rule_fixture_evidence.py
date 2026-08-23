from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_PRODUCT_RULE_FIXTURE_EVIDENCE = "product_rule_fixture_evidence_v1"
PROVEN_TINY_TICKER = "BTC-USDC"
DEFAULT_FIXTURE_PATH = Path("fixtures/product_rules/local_product_rule_fixtures_v1.json")
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
RULE_FIELDS = ("base_increment", "quote_increment", "price_increment", "min_order_size", "min_notional")


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
    return _configured_tickers_from_config(root) or list(DEFAULT_TICKERS)


def _split_ticker(ticker: str) -> tuple[str, str]:
    parts = ticker.split("-", 1)
    return (parts[0], parts[1]) if len(parts) == 2 else (ticker, "")


def _btc_local_product_rules(root: Path) -> Dict[str, Any]:
    path = root / "reports/d6/btc-usdc-product-rules-readiness-v1-20260602.json"
    payload = _load_json(path)
    content = payload.get("content") if isinstance(payload.get("content"), dict) else payload
    if not content:
        return {"rules": {}, "source": "", "timestamp": ""}
    rules = {
        "base_increment": str(content.get("base_increment") or ""),
        "quote_increment": str(content.get("quote_increment") or ""),
        "price_increment": str(content.get("price_increment") or ""),
        "min_order_size": str(content.get("min_order_base") or content.get("base_min_size") or ""),
        "min_notional": str(content.get("min_order_quote") or content.get("quote_min_size") or ""),
    }
    if all(rules.values()):
        return {"rules": rules, "source": str(path), "timestamp": "btc-usdc-product-rules-readiness-v1-20260602"}
    return {"rules": {}, "source": str(path), "timestamp": "btc-usdc-product-rules-readiness-v1-20260602"}


def _load_fixture_records(root: Path, fixture_path: str | Path | None) -> Dict[str, Dict[str, Any]]:
    path = Path(fixture_path) if fixture_path else root / DEFAULT_FIXTURE_PATH
    if not path.is_absolute():
        path = root / path
    payload = _load_json(path)
    defaults = payload.get("default_fixture_rules") if isinstance(payload.get("default_fixture_rules"), dict) else {}
    records = payload.get("fixtures") if isinstance(payload.get("fixtures"), list) else []
    out: Dict[str, Dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        ticker = _normalize_ticker(record.get("ticker"))
        if not ticker:
            continue
        base, quote = _split_ticker(ticker)
        merged = {**defaults, **record}
        out[ticker] = {
            "ticker": ticker,
            "base_currency": str(merged.get("base_currency") or base),
            "quote_currency": str(merged.get("quote_currency") or quote),
            "base_increment": str(merged.get("base_increment") or ""),
            "quote_increment": str(merged.get("quote_increment") or ""),
            "price_increment": str(merged.get("price_increment") or ""),
            "min_order_size": str(merged.get("min_order_size") or ""),
            "min_notional": str(merged.get("min_notional") or ""),
            "evidence_timestamp_or_version": str(
                record.get("evidence_timestamp_or_version")
                or payload.get("evidence_timestamp_or_version")
                or payload.get("schema_version")
                or "local_fixture"
            ),
            "fixture_path": str(path),
        }
    return out


def _blockers_for(values: Dict[str, Any]) -> List[str]:
    blockers = [f"missing_{field}" for field in RULE_FIELDS if not str(values.get(field) or "")]
    return sorted(set(blockers))


def build_product_rule_fixture_evidence_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
    fixture_path: str | Path | None = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    tickers = _configured_tickers(project_root)
    fixtures = _load_fixture_records(project_root, fixture_path)
    btc_rules = _btc_local_product_rules(project_root)

    matrix: List[Dict[str, Any]] = []
    for ticker in tickers:
        base, quote = _split_ticker(ticker)
        if ticker == PROVEN_TINY_TICKER and btc_rules["rules"]:
            values = dict(btc_rules["rules"])
            source_type = "local_report"
            strength = "live_readonly_cached"
            blockers: List[str] = []
            paper_usable = True
            caveats = ["local readonly cache only; fresh Coinbase preflight still required before live use"]
            source_path = btc_rules["source"]
            timestamp = btc_rules["timestamp"]
        else:
            fixture = fixtures.get(ticker, {})
            values = {field: str(fixture.get(field) or "") for field in RULE_FIELDS}
            blockers = _blockers_for(values)
            source_type = "fixture" if fixture else "missing"
            strength = "local_fixture" if fixture else "missing"
            paper_usable = bool(fixture) and not blockers
            caveats = [
                "paper-only local fixture grid",
                "not Coinbase live product-rule proof",
                "fresh readonly Coinbase product-rule preflight required before any live scope",
            ] if fixture else ["no local fixture or cached product-rule evidence"]
            source_path = str(fixture.get("fixture_path") or "")
            timestamp = str(fixture.get("evidence_timestamp_or_version") or "")
        row = {
            "ticker": ticker,
            "base_currency": base,
            "quote_currency": quote,
            "evidence_source_type": source_type,
            "evidence_strength": strength,
            "evidence_timestamp_or_version": timestamp,
            "source_path": source_path,
            "product_rules": dict(values),
            "base_increment": values["base_increment"],
            "quote_increment": values["quote_increment"],
            "price_increment": values["price_increment"],
            "min_order_size": values["min_order_size"],
            "min_notional": values["min_notional"],
            "live_product_rule_evidence": strength == "live_readonly_cached",
            "cached_product_rule_evidence": strength == "live_readonly_cached",
            "fixture_product_rule_evidence": strength == "local_fixture",
            "inferred_config_evidence": strength == "inferred",
            "missing_evidence": strength == "missing",
            "live_ready": False,
            "paper_replay_usable": paper_usable,
            "blockers": blockers,
            "caveats": caveats,
            "next_step": "fresh_preflight_required_for_live_review" if strength == "live_readonly_cached" else (
                "usable_for_paper_lifecycle_replay_only" if paper_usable else "collect_local_product_rule_fixture"
            ),
        }
        matrix.append(row)

    live_cached_count = sum(1 for row in matrix if row["evidence_strength"] == "live_readonly_cached")
    fixture_count = sum(1 for row in matrix if row["evidence_strength"] == "local_fixture")
    missing_count = sum(1 for row in matrix if row["evidence_strength"] == "missing" or row["blockers"])
    paper_usable_count = sum(1 for row in matrix if row["paper_replay_usable"])
    fixture_complete = bool(matrix) and missing_count == 0
    classification = "OK" if fixture_complete else "WATCH"
    return _json_safe(
        {
            "phase": PHASE_PRODUCT_RULE_FIXTURE_EVIDENCE,
            "generated_at": generated_at or _now_iso(),
            "metadata": {
                "report_only": True,
                "local_files_only": True,
                "fixture_only_where_applicable": True,
                "coinbase_call_attempted": False,
                "market_data_fetch_attempted": False,
                "http_call_attempted": False,
                "state_write_performed": False,
                "parameter_mutation_performed": False,
                "learning_to_execution_performed": False,
            },
            "classification": classification,
            "stop_reasons": [],
            "watch_reasons": [] if fixture_complete else ["fixture_evidence_missing_or_incomplete"],
            "universe_summary": {
                "configured_ticker_count": len(tickers),
                "configured_tickers": tickers,
                "fixture_evidence_ticker_count": fixture_count,
                "live_readonly_cached_ticker_count": live_cached_count,
                "missing_evidence_ticker_count": missing_count,
                "paper_replay_usable_ticker_count": paper_usable_count,
                "fixture_completion_ready": fixture_complete,
                "all_ticker_live_allowed_now": False,
            },
            "per_ticker_fixture_evidence_matrix": matrix,
            "product_rule_cache_integration": {
                "fixture_evidence_can_reduce_missing_count_for_paper_replay": fixture_complete,
                "fixture_evidence_is_not_strong_live_evidence": True,
                "all_ticker_product_rule_evidence_ready": False,
                "all_ticker_live_allowed_now": False,
            },
            "replay_all_ticker_integration": {
                "paper_replay_usefulness_may_improve": paper_usable_count == len(matrix),
                "multi_ticker_paper_lifecycle_replay_ready": True,
                "all_ticker_lifecycle_parity_ready": False,
                "all_ticker_live_allowed_now": False,
            },
            "safety_boundaries": [
                "local fixtures do not authorize live trading",
                "local fixtures do not authorize all-ticker live",
                "local fixtures do not replace fresh Coinbase product-rule preflight",
                "local fixtures do not authorize parameter changes",
            ],
        }
    )


def render_product_rule_fixture_evidence_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    summary = report.get("universe_summary") or {}
    lines = [
        "# Product-Rule Fixture Evidence",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- local_files_only: `{meta.get('local_files_only')}`",
        f"- fixture_only_where_applicable: `{meta.get('fixture_only_where_applicable')}`",
        f"- coinbase_call_attempted: `{meta.get('coinbase_call_attempted')}`",
        f"- market_data_fetch_attempted: `{meta.get('market_data_fetch_attempted')}`",
        f"- http_call_attempted: `{meta.get('http_call_attempted')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        "",
        "## Universe Summary",
        "",
    ]
    for key, value in summary.items():
        lines.append(f"- {key}: `{'; '.join(value) if isinstance(value, list) else value}`")
    lines.extend(["", "## Per-Ticker Fixture Evidence", ""])
    for row in report.get("per_ticker_fixture_evidence_matrix") or []:
        lines.append(
            f"- {row.get('ticker')}: strength=`{row.get('evidence_strength')}`, "
            f"source=`{row.get('evidence_source_type')}`, paper_replay_usable=`{row.get('paper_replay_usable')}`, "
            f"live_ready=`{row.get('live_ready')}`, blockers=`{'; '.join(row.get('blockers') or [])}`"
        )
    lines.extend(["", "## Safety Boundaries", ""])
    for item in report.get("safety_boundaries") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_PRODUCT_RULE_FIXTURE_EVIDENCE",
    "build_product_rule_fixture_evidence_report",
    "render_product_rule_fixture_evidence_markdown",
]
