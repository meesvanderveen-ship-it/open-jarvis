from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_MULTI_TICKER_PAPER_LIFECYCLE_REPLAY = "multi_ticker_paper_lifecycle_replay_v1"
PROVEN_TINY_TICKER = "BTC-USDC"
DEFAULT_CONFIGURED_TICKERS = [
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
SCENARIOS = [
    "no_order_submitted",
    "order_submitted_open",
    "submit_rejected",
    "cancelled_without_fill",
    "full_fill",
    "partial_fill",
    "D2_plan_preview",
    "D3_exit_preview",
    "D4_cancel_replace_preview",
    "D5_evidence_record",
]


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


def _read_text(path: Path, *, max_bytes: int = 300_000) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(max_bytes).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _configured_tickers_from_config(root: Path) -> List[str]:
    path = root / "bot" / "config.py"
    if not path.exists():
        return []
    text = _read_text(path)
    out: List[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b[A-Z0-9]+-USDC\b", text):
        ticker = _normalize_ticker(match.group(0))
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out


def _configured_tickers(root: Path) -> List[str]:
    config_tickers = _configured_tickers_from_config(root)
    if config_tickers:
        return config_tickers
    gate = _load_json(root / "reports/d6/all-ticker-readiness-gate-20260609.json")
    configured = gate.get("configured_universe") or {}
    tickers = [_normalize_ticker(t) for t in configured.get("tickers") or []]
    return [ticker for ticker in tickers if ticker] or list(DEFAULT_CONFIGURED_TICKERS)


def _rows_by_ticker(rows: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                ticker = _normalize_ticker(row.get("ticker"))
                if ticker:
                    out[ticker] = row
    return out


def _local_mentions(root: Path, ticker: str) -> List[str]:
    rels = [
        "logs/cycle_summary.jsonl",
        "logs/heartbeat_summary.jsonl",
        "logs/loop.log",
        "reports/d6/main-workflow-parity-report-20260609.json",
        "reports/d6/all-ticker-readiness-gate-20260609.json",
        "reports/d6/workflow-ticker-coverage-audit-20260601.json",
        "reports/d6/multi-ticker-workflow-equivalence-report-20260601.json",
        "reports/d6/multi-ticker-workflow-completion-checklist-20260601.json",
    ]
    mentions: List[str] = []
    for rel in rels:
        path = root / rel
        if path.exists() and ticker in _read_text(path):
            mentions.append(rel)
    return mentions


def _old_status_from_parity(parity: Dict[str, Any], ticker: str) -> str:
    rows = parity.get("configured_universe") or []
    for row in rows if isinstance(rows, list) else []:
        if isinstance(row, dict) and _normalize_ticker(row.get("ticker")) == ticker:
            return str(row.get("old_multi_ticker_decision_workflow_status") or "unknown")
    return "unknown"


def _old_status(root: Path, parity: Dict[str, Any], ticker: str) -> str:
    status = _old_status_from_parity(parity, ticker)
    if status in {"seen", "probable"}:
        return status
    mentions = _local_mentions(root, ticker)
    if any(item.startswith("logs/") for item in mentions):
        return "seen"
    if mentions:
        return "probable"
    return "unknown"


def _stage_status(source: Dict[str, Any], key: str, *, old_decision_status: str) -> str:
    source_status = str(source.get(key) or "").strip().lower()
    if source_status in {"proven", "ready"}:
        return "paper_replay_ready"
    if old_decision_status in {"seen", "probable"}:
        return "paper_replay_partial"
    return "blocked_missing_decision_evidence"


def _product_status(row: Dict[str, Any]) -> str:
    status = str(row.get("product_rule_status") or "").strip().lower()
    if status in {"ready", "partial"}:
        return status
    return "missing"


def _data_status(row: Dict[str, Any]) -> str:
    status = str(row.get("data_coverage_status") or "").strip().lower()
    if status in {"ready", "partial"}:
        return status
    return "unknown" if not row else "missing"


def _cache_rows(root: Path) -> Dict[str, Dict[str, Any]]:
    cache = _load_json(root / "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json")
    return _rows_by_ticker(cache.get("per_ticker_matrix"))


def _fixture_summary(root: Path) -> Dict[str, Any]:
    fixture = _load_json(root / "reports/d6/product-rule-fixture-evidence-20260609.json")
    summary = fixture.get("universe_summary")
    return summary if isinstance(summary, dict) else {}


def _cache_product_status(cache_row: Dict[str, Any], fallback_source: Dict[str, Any]) -> str:
    status = str(cache_row.get("product_rule_evidence_status") or "").strip().lower()
    if status in {"ready", "partial", "missing", "unknown"}:
        return status
    return _product_status(fallback_source)


def _evidence_strength(cache_row: Dict[str, Any]) -> str:
    value = str(cache_row.get("evidence_strength") or "").strip().lower()
    if value in {"live_readonly_cached", "local_fixture", "inferred", "missing"}:
        return value
    if cache_row.get("paper_replay_usable"):
        return "inferred"
    return "missing"


def _paper_replay_usable(cache_row: Dict[str, Any], product_rule_status: str) -> bool:
    if isinstance(cache_row.get("paper_replay_usable"), bool):
        return bool(cache_row.get("paper_replay_usable"))
    return product_rule_status in {"ready", "partial"}


def _stage_status_with_fixture(
    source: Dict[str, Any],
    key: str,
    *,
    old_decision_status: str,
    paper_replay_usable: bool,
) -> str:
    if old_decision_status not in {"seen", "probable"}:
        return "blocked_missing_decision_evidence"
    if paper_replay_usable:
        return "paper_replay_ready"
    return _stage_status(source, key, old_decision_status=old_decision_status)


def _paper_lifecycle_status(
    *,
    old_decision_status: str,
    product_rule_status: str,
    data_status: str,
    stage_values: List[str],
    paper_replay_usable: bool,
) -> str:
    if old_decision_status not in {"seen", "probable"}:
        return "blocked_missing_decision_evidence"
    if paper_replay_usable and all(value == "paper_replay_ready" for value in stage_values):
        return "paper_lifecycle_replay_ready"
    if product_rule_status == "missing":
        return "blocked_missing_fixture_evidence"
    if any(value in {"paper_replay_ready", "paper_replay_partial"} for value in stage_values):
        return "paper_lifecycle_replay_partial"
    if data_status in {"missing", "unknown"}:
        return "blocked_missing_lifecycle_mapping"
    return "blocked_missing_lifecycle_mapping"


def _next_step(ticker: str, replay_status: str, product_rule_status: str, evidence_strength: str) -> str:
    if ticker == PROVEN_TINY_TICKER:
        return "eligible for controlled tiny-live review later after fresh operator preflight and exact ACK"
    if product_rule_status in {"missing", "unknown"} or evidence_strength == "missing":
        return "eligible for product-rule evidence cache"
    if replay_status == "paper_lifecycle_replay_ready":
        return "eligible for paper lifecycle fixture review only"
    if replay_status == "paper_lifecycle_replay_partial":
        return "eligible for additional paper lifecycle fixture coverage"
    return "keep analysis-only until evidence improves"


def build_multi_ticker_paper_lifecycle_replay_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    configured = _configured_tickers(project_root)
    malformed_config = not bool(_configured_tickers_from_config(project_root))
    parity = _load_json(project_root / "reports/d6/main-workflow-parity-report-20260609.json")
    all_ticker = _load_json(project_root / "reports/d6/all-ticker-readiness-gate-20260609.json")
    rows = _rows_by_ticker(all_ticker.get("per_ticker_readiness_matrix"))
    cache_rows = _cache_rows(project_root)
    fixture_summary = _fixture_summary(project_root)
    readiness_flags = all_ticker.get("readiness_flags") if isinstance(all_ticker.get("readiness_flags"), dict) else {}
    parity_gate = parity.get("gate_decision") if isinstance(parity.get("gate_decision"), dict) else {}

    replay_matrix: List[Dict[str, Any]] = []
    scenario_coverage: List[Dict[str, Any]] = []
    for ticker in configured:
        source = rows.get(ticker, {})
        cache_row = cache_rows.get(ticker, {})
        old_decision_status = _old_status(project_root, parity, ticker)
        product_rule_status = _cache_product_status(cache_row, source)
        evidence_strength = _evidence_strength(cache_row)
        paper_replay_usable = _paper_replay_usable(cache_row, product_rule_status)
        data_status = _data_status(source)
        stage_statuses = {
            "paper_c4_entry_replay_status": _stage_status_with_fixture(
                source,
                "c4_entry_lifecycle_status",
                old_decision_status=old_decision_status,
                paper_replay_usable=paper_replay_usable,
            ),
            "paper_d1_fill_to_position_replay_status": _stage_status_with_fixture(
                source,
                "d1_fill_to_position_status",
                old_decision_status=old_decision_status,
                paper_replay_usable=paper_replay_usable,
            ),
            "paper_d2_plan_replay_status": _stage_status_with_fixture(
                source,
                "d2_plan_status",
                old_decision_status=old_decision_status,
                paper_replay_usable=paper_replay_usable,
            ),
            "paper_d3_exit_replay_status": _stage_status_with_fixture(
                source,
                "d3_exit_status",
                old_decision_status=old_decision_status,
                paper_replay_usable=paper_replay_usable,
            ),
            "paper_d4_cancel_replace_replay_status": _stage_status_with_fixture(
                source,
                "d4_cancel_replace_status",
                old_decision_status=old_decision_status,
                paper_replay_usable=paper_replay_usable,
            ),
            "paper_d5_evidence_replay_status": _stage_status_with_fixture(
                source,
                "d5_d6_evidence_status",
                old_decision_status=old_decision_status,
                paper_replay_usable=paper_replay_usable,
            ),
        }
        lifecycle_status = _paper_lifecycle_status(
            old_decision_status=old_decision_status,
            product_rule_status=product_rule_status,
            data_status=data_status,
            stage_values=list(stage_statuses.values()),
            paper_replay_usable=paper_replay_usable,
        )
        blockers: List[str] = []
        if old_decision_status not in {"seen", "probable"}:
            blockers.append("blocked_missing_decision_evidence")
        if product_rule_status in {"missing", "unknown"} or evidence_strength == "missing":
            blockers.append("blocked_missing_fixture_evidence")
        if evidence_strength != "live_readonly_cached":
            blockers.append("blocked_missing_live_product_rule_evidence")
        if data_status in {"missing", "unknown"}:
            blockers.append("blocked_missing_data_evidence")
        if any(value == "blocked_missing_decision_evidence" for value in stage_statuses.values()):
            blockers.append("blocked_missing_lifecycle_mapping")
        if stage_statuses["paper_d3_exit_replay_status"] != "paper_replay_ready":
            blockers.append("blocked_missing_exit_mapping")
        if ticker != PROVEN_TINY_TICKER:
            blockers.append("not_current_btc_usdc_tiny_scope")
        else:
            blockers.append("fresh_operator_preflight_and_live_start_ack_missing")
        blockers.append("blocked_ACK_required_for_live_scope")

        caveats = [
            "paper replay labels only; no state write",
            "all-ticker live remains disabled",
            "fresh Coinbase product-rule preflight and exact ACK required before live scope",
        ]
        if evidence_strength == "local_fixture":
            caveats.append("local fixture evidence is paper-only and not Coinbase live product-rule proof")
        if evidence_strength == "live_readonly_cached":
            caveats.append("local readonly cache still requires fresh preflight before live use")

        replay_matrix.append(
            {
                "ticker": ticker,
                "configured": True,
                "old_decision_workflow_status": old_decision_status,
                "product_rule_evidence_strength": evidence_strength,
                "paper_replay_usable": paper_replay_usable,
                **stage_statuses,
                "paper_lifecycle_replay_status": lifecycle_status,
                "product_rule_evidence_status": product_rule_status,
                "data_evidence_status": data_status,
                "live_ready": False,
                "lifecycle_blockers": sorted(set(blockers)),
                "caveats": sorted(set(caveats)),
                "next_step": _next_step(ticker, lifecycle_status, product_rule_status, evidence_strength),
            }
        )
        scenario_coverage.append(
            {
                "ticker": ticker,
                "paper_only": True,
                "state_write_performed": False,
                "scenarios": [
                    {
                        "scenario": scenario,
                        "status": "represented" if lifecycle_status in {"paper_lifecycle_replay_ready", "paper_lifecycle_replay_partial"} else "blocked",
                        "effect": "paper_label_only_no_state_write",
                    }
                    for scenario in SCENARIOS
                ],
            }
        )

    ready_count = sum(1 for row in replay_matrix if row["paper_lifecycle_replay_status"] == "paper_lifecycle_replay_ready")
    partial_count = sum(1 for row in replay_matrix if row["paper_lifecycle_replay_status"] == "paper_lifecycle_replay_partial")
    blocked_count = len(replay_matrix) - ready_count - partial_count
    live_ready_count = sum(1 for row in replay_matrix if row["live_ready"])
    paper_usable_count = sum(1 for row in replay_matrix if row["paper_replay_usable"])
    old_values = {row["old_decision_workflow_status"] for row in replay_matrix}
    if "seen" in old_values:
        old_seen: str | bool = True
    elif "probable" in old_values:
        old_seen = "partial"
    else:
        old_seen = False

    stop_reasons: List[str] = []
    watch_reasons: List[str] = []
    if malformed_config:
        watch_reasons.append("configured_universe_from_config_missing_or_malformed")
    if partial_count or blocked_count:
        watch_reasons.append("paper_lifecycle_replay_partial")
    if any(row["product_rule_evidence_status"] in {"missing", "unknown"} for row in replay_matrix):
        watch_reasons.append("fixture_or_product_rule_evidence_missing_for_some_tickers")
    if any(row["product_rule_evidence_strength"] != "live_readonly_cached" for row in replay_matrix):
        watch_reasons.append("live_product_rule_evidence_missing_for_non_btc")
    if not bool(fixture_summary.get("fixture_completion_ready", False)) and any(
        row["product_rule_evidence_strength"] == "local_fixture" for row in replay_matrix
    ):
        watch_reasons.append("fixture_report_missing_or_not_ready")
    watch_reasons.append("all_ticker_lifecycle_parity_not_live_proven")
    classification = "STOP_NOW" if stop_reasons else "WATCH" if watch_reasons else "OK"

    report = {
        "phase": PHASE_MULTI_TICKER_PAPER_LIFECYCLE_REPLAY,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "paper_only": True,
            "fixture_evidence_consumed": bool(cache_rows),
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_performed": False,
        },
        "classification": classification,
        "stop_reasons": stop_reasons,
        "watch_reasons": sorted(set(watch_reasons)),
        "universe_summary": {
            "configured_ticker_count": len(configured),
            "configured_tickers": configured,
            "product_rule_fixture_evidence_ready": bool(fixture_summary.get("fixture_completion_ready", False)),
            "paper_replay_usable_ticker_count": paper_usable_count,
            "paper_lifecycle_replay_ready_count": ready_count,
            "paper_lifecycle_replay_partial_count": partial_count,
            "blocked_ticker_count": blocked_count,
            "live_ready_ticker_count": live_ready_count,
            "old_multi_ticker_decision_workflow_seen": old_seen,
            "btc_usdc_tiny_scope_ready_for_operator_preflight": bool(
                readiness_flags.get(
                    "btc_usdc_tiny_scope_ready_for_operator_preflight",
                    parity_gate.get("btc_usdc_tiny_scope_ready_for_operator_preflight", True),
                )
            ),
            "all_ticker_lifecycle_parity_ready": False,
            "all_ticker_live_allowed_now": False,
        },
        "per_ticker_replay_matrix": replay_matrix,
        "scenario_coverage": scenario_coverage,
        "gate_decision": {
            "multi_ticker_paper_lifecycle_replay_ready": bool(replay_matrix) and not stop_reasons,
            "fixture_evidence_consumed": bool(cache_rows),
            "paper_lifecycle_replay_ready_count": ready_count,
            "paper_lifecycle_replay_partial_count": partial_count,
            "all_ticker_lifecycle_parity_ready": False,
            "all_ticker_live_allowed_now": False,
            "btc_usdc_tiny_scope_ready_for_operator_preflight": bool(
                readiness_flags.get(
                    "btc_usdc_tiny_scope_ready_for_operator_preflight",
                    parity_gate.get("btc_usdc_tiny_scope_ready_for_operator_preflight", True),
                )
            ),
            "tickers_replay_ready_count": ready_count,
            "tickers_replay_partial_count": partial_count,
            "tickers_blocked_count": blocked_count,
            "recommended_next_steps": [
                "sample-size/OOS/walk-forward acceptance policy",
                "D6 backlearning label export pack",
                "fresh BTC-USDC live-start decision pack only if operator explicitly asks",
            ],
        },
        "learning_backlearning_boundary": {
            "replay_may_produce_evidence_labels": True,
            "replay_does_not_approve_parameters": True,
            "parameter_values_proposed": False,
            "learning_to_execution_ready": False,
            "parameter_change_allowed": False,
            "parameter_review_approved": False,
            "live_learning_allowed": False,
            "live_learning_remains_disabled": True,
        },
    }
    return _json_safe(report)


def render_multi_ticker_paper_lifecycle_replay_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    summary = report.get("universe_summary") or {}
    gate = report.get("gate_decision") or {}
    lines = [
        "# Multi-Ticker Paper Lifecycle Replay",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- paper_only: `{meta.get('paper_only')}`",
        f"- fixture_evidence_consumed: `{meta.get('fixture_evidence_consumed')}`",
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
        f"- product_rule_fixture_evidence_ready: `{summary.get('product_rule_fixture_evidence_ready')}`",
        f"- paper_replay_usable_ticker_count: `{summary.get('paper_replay_usable_ticker_count')}`",
        f"- paper_lifecycle_replay_ready_count: `{summary.get('paper_lifecycle_replay_ready_count')}`",
        f"- paper_lifecycle_replay_partial_count: `{summary.get('paper_lifecycle_replay_partial_count')}`",
        f"- blocked_ticker_count: `{summary.get('blocked_ticker_count')}`",
        f"- live_ready_ticker_count: `{summary.get('live_ready_ticker_count')}`",
        f"- old_multi_ticker_decision_workflow_seen: `{summary.get('old_multi_ticker_decision_workflow_seen')}`",
        f"- btc_usdc_tiny_scope_ready_for_operator_preflight: `{summary.get('btc_usdc_tiny_scope_ready_for_operator_preflight')}`",
        f"- all_ticker_lifecycle_parity_ready: `{summary.get('all_ticker_lifecycle_parity_ready')}`",
        f"- all_ticker_live_allowed_now: `{summary.get('all_ticker_live_allowed_now')}`",
        "",
        "## Gate Decision",
        "",
    ]
    for key, value in gate.items():
        lines.append(f"- {key}: `{'; '.join(value) if isinstance(value, list) else value}`")
    lines.extend(["", "## Per-Ticker Replay Matrix", ""])
    for row in report.get("per_ticker_replay_matrix") or []:
        lines.append(
            f"- {row.get('ticker')}: old_decision=`{row.get('old_decision_workflow_status')}`, "
            f"paper_lifecycle=`{row.get('paper_lifecycle_replay_status')}`, "
            f"product_rules=`{row.get('product_rule_evidence_status')}`, "
            f"strength=`{row.get('product_rule_evidence_strength')}`, "
            f"paper_replay_usable=`{row.get('paper_replay_usable')}`, "
            f"live_ready=`{row.get('live_ready')}`, next=`{row.get('next_step')}`"
        )
    lines.extend(["", "## Learning Boundary", ""])
    learning = report.get("learning_backlearning_boundary") or {}
    for key, value in learning.items():
        lines.append(f"- {key}: `{value}`")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_MULTI_TICKER_PAPER_LIFECYCLE_REPLAY",
    "build_multi_ticker_paper_lifecycle_replay_report",
    "render_multi_ticker_paper_lifecycle_replay_markdown",
]
