from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


PHASE_MAIN_WORKFLOW_PARITY_REPORT = "main_workflow_parity_report_v1"
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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _configured_tickers(root: Path) -> List[str]:
    path = root / "bot" / "config.py"
    if not path.exists():
        return list(DEFAULT_CONFIGURED_TICKERS)
    text = path.read_text(encoding="utf-8", errors="replace")
    out: List[str] = []
    seen: set[str] = set()
    for match in re.finditer(r"\b[A-Z0-9]+-USDC\b", text):
        ticker = _normalize_ticker(match.group(0))
        if ticker and ticker not in seen:
            seen.add(ticker)
            out.append(ticker)
    return out or list(DEFAULT_CONFIGURED_TICKERS)


def _read_text(path: Path, *, max_bytes: int = 250_000) -> str:
    try:
        with path.open("rb") as handle:
            return handle.read(max_bytes).decode("utf-8", errors="replace")
    except Exception:
        return ""


def _local_mentions(root: Path, ticker: str) -> List[str]:
    rels = [
        "logs/cycle_summary.jsonl",
        "logs/heartbeat_summary.jsonl",
        "logs/loop.log",
        "reports/d6/workflow-ticker-coverage-audit-20260601.json",
        "reports/d6/multi-ticker-workflow-equivalence-report-20260601.json",
        "reports/d6/multi-ticker-workflow-completion-checklist-20260601.json",
        "reports/d6/all-ticker-readiness-gate-20260609.json",
    ]
    mentions: List[str] = []
    for rel in rels:
        path = root / rel
        if path.exists() and ticker in _read_text(path):
            mentions.append(rel)
    return mentions


def _all_ticker_matrix(root: Path) -> Dict[str, Dict[str, Any]]:
    payload = _load_json(root / "reports/d6/all-ticker-readiness-gate-20260609.json")
    rows = payload.get("per_ticker_readiness_matrix") or payload.get("per_ticker_readiness") or []
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict):
                ticker = _normalize_ticker(row.get("ticker"))
                if ticker:
                    out[ticker] = row
    return out


def _stage(name: str, status: str, evidence: List[str], blocker: str = "") -> Dict[str, Any]:
    return {"stage": name, "status": status, "evidence": evidence, "blocker": blocker}


def _old_workflow_status(ticker: str, mentions: List[str], *, configured: bool) -> str:
    if mentions and any("logs/" in item for item in mentions):
        return "seen"
    if mentions:
        return "probable"
    if configured:
        return "probable"
    return "unknown"


def _lifecycle_status(ticker: str, matrix_row: Dict[str, Any]) -> str:
    if ticker == PROVEN_TINY_TICKER:
        return "partial"
    if matrix_row:
        return "missing"
    return "unknown"


def build_main_workflow_parity_report(
    *,
    root: str | Path = ".",
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    tickers = _configured_tickers(project_root)
    matrix = _all_ticker_matrix(project_root)

    module_checks = {
        "market_data_features": (project_root / "bot" / "strategy_engine.py").exists(),
        "c4_orderbook_entry": (project_root / "bot" / "phase_c43_autonomous_entry_live.py").exists(),
        "d1_fill_to_position": (project_root / "bot" / "phase_c45_live_fill_pilot.py").exists(),
        "d2_position_executor": (project_root / "bot" / "phase_d2_position_executor.py").exists(),
        "d3_controlled_exits": (project_root / "bot" / "phase_d3_controlled_live_exits.py").exists(),
        "d4_cancel_replace": (project_root / "bot" / "phase_d4_controlled_cancel_replace.py").exists(),
        "d5_execution_evidence": (project_root / "bot" / "phase_d5_d6_evidence_expansion.py").exists(),
        "d6_backlearning": (project_root / "bot" / "phase_d6_parameter_review_pack.py").exists(),
        "replication_follower": (project_root / "replication" / "models.py").exists(),
    }

    stages = [
        _stage("market data/features", "implemented" if module_checks["market_data_features"] else "partial", ["bot/strategy_engine.py", "D6 cached coverage reports"]),
        _stage("hard gate", "implemented", ["bot/config.py safety flags", "function preservation audit"]),
        _stage("LLM analyse/judge", "implemented", ["bot/config.py judge settings", "run_trader_loop.py"]),
        _stage("deterministic risk", "implemented", ["phase C risk/preflight modules"]),
        _stage("C4 orderbook entry", "partial" if module_checks["c4_orderbook_entry"] else "missing", ["phase C43 modules"], "live submit still ACK-gated"),
        _stage("C4 lifecycle monitoring", "partial", ["phase C43 lifecycle orchestrator"], "Coinbase poll/apply disabled unless ACK-gated"),
        _stage("D1 fill-to-position", "partial" if module_checks["d1_fill_to_position"] else "missing", ["phase C45 fill pilot"], "local apply requires exact ACK"),
        _stage("D2 position executor", "partial" if module_checks["d2_position_executor"] else "missing", ["phase D2 executor"], "per-ticker lifecycle proof missing"),
        _stage("D3 controlled exits", "partial" if module_checks["d3_controlled_exits"] else "missing", ["exit workflow readiness report"], "live SELL disabled and ACK-gated"),
        _stage("D4 cancel/replace/trailing", "partial" if module_checks["d4_cancel_replace"] else "missing", ["D4 cancel/replace modules"], "cancel/replace live action ACK-gated"),
        _stage("D5 execution evidence", "report_only" if module_checks["d5_execution_evidence"] else "missing", ["D5/D6 evidence expansion report"], "human review only"),
        _stage("D6 backlearning", "report_only" if module_checks["d6_backlearning"] else "missing", ["D6 reports"], "no learning-to-execution"),
        _stage("learning governance", "blocked_by_ACK", ["parameter governance flags"], "parameter review/approval missing"),
        _stage("replication/follower", "partial" if module_checks["replication_follower"] else "missing", ["master-side replication schema/publisher"], "receiver/API code not accessible"),
    ]

    universe: List[Dict[str, Any]] = []
    old_seen_values: List[str] = []
    for ticker in tickers:
        mentions = _local_mentions(project_root, ticker)
        old_status = _old_workflow_status(ticker, mentions, configured=True)
        lifecycle = _lifecycle_status(ticker, matrix.get(ticker, {}))
        old_seen_values.append(old_status)
        blockers = []
        if lifecycle != "proven":
            blockers.append("new_lifecycle_orderbook_flow_not_proven_for_ticker")
        if ticker != PROVEN_TINY_TICKER:
            blockers.append("not_current_btc_usdc_tiny_scope")
            blockers.append("all_ticker_live_ack_missing")
        else:
            blockers.append("fresh_operator_preflight_and_live_start_ack_missing")
        universe.append(
            {
                "ticker": ticker,
                "configured": True,
                "old_multi_ticker_decision_workflow_status": old_status,
                "old_workflow_evidence": mentions or ["configured_universe_and_multi_ticker_decision_code"],
                "new_lifecycle_orderbook_status": lifecycle,
                "tiny_live_candidate_status": "candidate_ack_gated" if ticker == PROVEN_TINY_TICKER else "not_current_scope",
                "all_ticker_live_status": "blocked",
                "blockers": blockers,
                "next_step": "BTC-USDC fresh preflight only if operator asks" if ticker == PROVEN_TINY_TICKER else "paper lifecycle replay/simulation before any live consideration",
            }
        )

    if any(value == "seen" for value in old_seen_values):
        old_seen: str | bool = True
    elif any(value == "probable" for value in old_seen_values):
        old_seen = "partial"
    else:
        old_seen = False

    bridge_plan = [
        {
            "from": "analysis-only",
            "to": "paper lifecycle simulation",
            "action": "Replay old multi-ticker decision outputs into paper lifecycle fixtures without submit/apply.",
        },
        {
            "from": "paper lifecycle simulation",
            "to": "lifecycle candidate",
            "action": "Prove C4/D1/D2/D3/D4/D5 evidence paths per ticker with product-rule and data evidence.",
        },
        {
            "from": "lifecycle candidate",
            "to": "tiny live candidate",
            "action": "Select one ticker, run fresh preflight, enforce caps and require exact operator ACK.",
        },
        {
            "from": "tiny live candidate",
            "to": "all-ticker live candidate",
            "action": "Repeat lifecycle proof per ticker; require all-ticker ACK and keep SELL/follower/learning separate.",
        },
    ]

    backlearning = {
        "parameters_that_can_later_be_estimated": [
            "entry gate confidence thresholds",
            "position sizing bounds",
            "take-profit and stop placement",
            "cancel/replace timing",
            "fee/slippage assumptions",
            "no-fill timeout windows",
        ],
        "evidence_sources_needed": [
            "C4 submit/no-submit evidence",
            "D1 fill-to-position evidence",
            "D2 plan outcomes",
            "D3/D4 exit and cancel/replace evidence",
            "D5 execution metrics",
            "D6 human-review labels",
        ],
        "what_backlearning_can_do_now": "Summarize evidence and prepare human-review packs without recommendations or parameter mutation.",
        "what_live_learning_must_not_do_yet": "No automatic parameter changes, no trading recommendations, no learning-to-execution bridge.",
        "learning_to_execution_ready": False,
        "parameter_change_allowed": False,
        "parameter_review_approved": False,
    }

    gate = {
        "main_workflow_parity_report_ready": True,
        "old_multi_ticker_decision_workflow_seen": old_seen,
        "all_ticker_lifecycle_parity_ready": False,
        "all_ticker_live_allowed_now": False,
        "btc_usdc_tiny_scope_ready_for_operator_preflight": True,
        "recommended_next_steps": [
            "multi-ticker paper lifecycle replay/simulation",
            "per-ticker product-rule/evidence cache",
            "D6 human-review pack after evidence labels are ready",
        ],
    }

    return _json_safe(
        {
            "phase": PHASE_MAIN_WORKFLOW_PARITY_REPORT,
            "generated_at": generated_at or _now_iso(),
            "metadata": {
                "report_only": True,
                "coinbase_call_attempted": False,
                "market_data_fetch_attempted": False,
                "http_call_attempted": False,
                "state_write_performed": False,
                "parameter_mutation_performed": False,
                "learning_to_execution_performed": False,
            },
            "main_workflow_stages": stages,
            "configured_universe": universe,
            "bridge_plan": bridge_plan,
            "backlearning_parameter_section": backlearning,
            "gate_decision": gate,
            "safety_distinctions": [
                "The multi-ticker analysis/decision workflow already exists and has historically run or is represented by configured multi-ticker decision code.",
                "Non-BTC tickers are not nonexistent or unknown; their gap is missing proof through the newer C4/D1/D2/D3/D4/D5 lifecycle/orderbook flow.",
                "BTC-USDC remains the only controlled tiny-live candidate for now.",
                "all_ticker_live_allowed_now=false",
                "learning_to_execution_ready=false",
                "parameter_change_allowed=false",
            ],
        }
    )


def render_main_workflow_parity_markdown(report: Dict[str, Any]) -> str:
    meta = report.get("metadata") or {}
    gate = report.get("gate_decision") or {}
    lines = [
        "# Main Workflow Parity Report",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- report_only: `{meta.get('report_only')}`",
        f"- coinbase_call_attempted: `{meta.get('coinbase_call_attempted')}`",
        f"- market_data_fetch_attempted: `{meta.get('market_data_fetch_attempted')}`",
        f"- http_call_attempted: `{meta.get('http_call_attempted')}`",
        f"- state_write_performed: `{meta.get('state_write_performed')}`",
        f"- parameter_mutation_performed: `{meta.get('parameter_mutation_performed')}`",
        f"- learning_to_execution_performed: `{meta.get('learning_to_execution_performed')}`",
        "",
        "## Gate Decision",
        "",
    ]
    for key, value in gate.items():
        if isinstance(value, list):
            lines.append(f"- {key}: `{'; '.join(value)}`")
        else:
            lines.append(f"- {key}: `{value}`")
    lines.extend(["", "## Workflow Stages", ""])
    for stage in report.get("main_workflow_stages") or []:
        lines.append(f"- {stage.get('stage')}: `{stage.get('status')}` - {stage.get('blocker') or 'no blocker recorded'}")
    lines.extend(["", "## Configured Universe", ""])
    for row in report.get("configured_universe") or []:
        lines.append(
            f"- {row.get('ticker')}: old_decision=`{row.get('old_multi_ticker_decision_workflow_status')}`, "
            f"new_lifecycle=`{row.get('new_lifecycle_orderbook_status')}`, all_ticker_live=`{row.get('all_ticker_live_status')}`"
        )
    lines.extend(["", "## Bridge Plan", ""])
    for item in report.get("bridge_plan") or []:
        lines.append(f"- {item.get('from')} -> {item.get('to')}: {item.get('action')}")
    lines.extend(["", "## Safety Distinctions", ""])
    for item in report.get("safety_distinctions") or []:
        lines.append(f"- {item}")
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_MAIN_WORKFLOW_PARITY_REPORT",
    "build_main_workflow_parity_report",
    "render_main_workflow_parity_markdown",
]
