from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.phase_product_rule_fixture_evidence import DEFAULT_TICKERS


PHASE_ALL_TICKER_24H_WORKFLOW_READINESS_PACK = "all_ticker_24h_workflow_readiness_pack_v1"
BTC_TICKER = "BTC-USDC"


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


def _rows_by_ticker(rows: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(rows, list):
        for row in rows:
            if isinstance(row, dict) and row.get("ticker"):
                out[str(row["ticker"]).upper()] = row
    return out


def build_all_ticker_24h_workflow_readiness_pack(
    *, root: str | Path = ".", generated_at: Optional[str] = None
) -> Dict[str, Any]:
    project_root = Path(root).resolve()
    btc_pack = _load_json(project_root / "reports/d6/btc-usdc-24h-live-start-decision-pack-20260609.json")
    replay = _load_json(project_root / "reports/d6/multi-ticker-paper-lifecycle-replay-20260609.json")
    product_cache = _load_json(project_root / "reports/d6/per-ticker-product-rule-evidence-cache-20260609.json")
    fixture = _load_json(project_root / "reports/d6/product-rule-fixture-evidence-20260609.json")
    live_preflight = _load_json(project_root / "reports/d6/all-ticker-live-readonly-preflight-20260609.json")
    shadow_params = _load_json(project_root / "reports/d6/shadow-parameter-approximation-pack-20260609.json")
    replay_rows = _rows_by_ticker(replay.get("per_ticker_replay_matrix"))
    cache_rows = _rows_by_ticker(product_cache.get("per_ticker_matrix"))
    fixture_rows = _rows_by_ticker(fixture.get("per_ticker_fixture_evidence_matrix"))
    tickers = list(DEFAULT_TICKERS)
    source_reports_present = bool(btc_pack and replay and product_cache and fixture)
    preflight_gate = (
        live_preflight.get("gate_decision")
        if isinstance(live_preflight.get("gate_decision"), dict)
        else {}
    )
    preflight_rows = _rows_by_ticker(live_preflight.get("per_ticker_preflight"))
    preflight_attempted = bool(preflight_gate.get("all_ticker_live_readonly_preflight_attempted", False))
    preflight_passed = bool(preflight_gate.get("all_ticker_live_readonly_preflight_passed", False))
    shadow_flags = (
        shadow_params.get("governance_flags")
        if isinstance(shadow_params.get("governance_flags"), dict)
        else {}
    )

    btc_ready = bool((btc_pack.get("governance_flags") or {}).get("ready_for_operator_fresh_preflight"))
    matrix: List[Dict[str, Any]] = []
    for ticker in tickers:
        cache_row = cache_rows.get(ticker, {})
        fixture_row = fixture_rows.get(ticker, {})
        replay_row = replay_rows.get(ticker, {})
        strength = str(
            cache_row.get("evidence_strength")
            or fixture_row.get("evidence_strength")
            or ("live_readonly_cached" if ticker == BTC_TICKER else "local_fixture")
        )
        paper_status = str(
            replay_row.get("paper_lifecycle_replay_status")
            or ("paper_lifecycle_replay_ready" if replay_row or fixture_row or cache_row else "unknown")
        )
        is_btc = ticker == BTC_TICKER
        preflight_row = preflight_rows.get(ticker, {})
        preflight_status = str(preflight_row.get("live_entry_preflight_status") or "not_run")
        preflight_blockers = list(preflight_row.get("blockers") or [])
        blockers = []
        warnings = []
        if preflight_passed and preflight_status == "pass":
            candidate_status = "ready_for_operator_fresh_preflight"
            live_product_status = "pass"
            balance_status = "pass"
            warnings.append("fresh readonly preflight passed; exact all-ticker ACK still required")
        elif is_btc and btc_ready:
            candidate_status = "ready_for_operator_fresh_preflight"
            live_product_status = "fresh_preflight_required"
            balance_status = "fresh_preflight_required"
            warnings.append("BTC-USDC ready only for operator fresh preflight; not live-authorized")
        else:
            candidate_status = "blocked_by_fresh_live_preflight" if not preflight_attempted else "blocked_by_preflight_result"
            live_product_status = "blocked_fresh_live_readonly_product_rule_preflight_missing"
            balance_status = "blocked_balance_or_min_notional_preflight_missing"
            blockers.extend(["fresh_live_product_rule_preflight_missing", "balance_or_min_notional_preflight_missing"])
            warnings.append("paper/fixture evidence is not live Coinbase proof")
        blockers.extend(preflight_blockers)
        matrix.append(
            {
                "ticker": ticker,
                "configured": True,
                "product_rule_evidence_strength": strength,
                "paper_replay_status": paper_status,
                "live_product_rule_preflight_status": live_product_status,
                "live_readonly_preflight_status": preflight_status,
                "balance_or_min_notional_preflight_status": balance_status,
                "live_entry_scope_status": "operator_fresh_preflight_required",
                "live_exit_scope_status": "disabled_ack_required",
                "all_ticker_candidate_status": candidate_status,
                "blockers": sorted(set(blockers)),
                "warnings": warnings,
                "operator_required_actions": [
                    "run fresh all-ticker live-readonly product/balance/min-notional preflight",
                    "confirm all-ticker caps and allowed universe",
                    "provide exact all-ticker live ACK before any manual run",
                ],
                "live_ready": False,
            }
        )

    non_btc_ready = preflight_passed and all(
        row["all_ticker_candidate_status"] == "ready_for_operator_fresh_preflight"
        for row in matrix
        if row["ticker"] != BTC_TICKER
    )
    report = {
        "phase": PHASE_ALL_TICKER_24H_WORKFLOW_READINESS_PACK,
        "generated_at": generated_at or _now_iso(),
        "metadata": {
            "report_only": True,
            "all_ticker_decision_pack_only": True,
            "codex_must_not_start_live_test": True,
            "operator_manual_start_required": True,
            "all_ticker_live_authorized": False,
            "live_start_authorized": False,
            "coinbase_call_attempted": False,
            "market_data_fetch_attempted": False,
            "http_call_attempted": False,
            "order_action_attempted": False,
            "lifecycle_apply_attempted": False,
            "service_restart_attempted": False,
            "env_mutation_performed": False,
            "state_write_performed": False,
            "parameter_mutation_performed": False,
            "learning_to_execution_performed": False,
        },
        "classification": "OK" if source_reports_present else "WATCH",
        "configured_ticker_count": len(tickers),
        "configured_tickers": tickers,
        "per_ticker_readiness": matrix,
        "gate_decision": {
            "all_ticker_24h_workflow_readiness_pack_ready": True,
            "all_ticker_workflow_built_locally": True,
            "all_ticker_live_readonly_preflight_tool_ready": bool(
                preflight_gate.get("all_ticker_live_readonly_preflight_tool_ready", False)
            ),
            "all_ticker_live_readonly_preflight_attempted": preflight_attempted,
            "all_ticker_live_readonly_preflight_passed": preflight_passed,
            "btc_usdc_ready_for_operator_fresh_preflight": btc_ready,
            "non_btc_tickers_ready_for_operator_fresh_preflight": non_btc_ready,
            "all_ticker_ready_for_operator_fresh_preflight": preflight_passed,
            "all_ticker_live_authorized": False,
            "live_start_authorized": False,
            "codex_must_not_start_live_test": True,
            "parameter_values_approved": False,
            "parameter_change_allowed": False,
            "ready_to_change_parameters": False,
            "shadow_parameter_approximation_pack_ready": bool(
                shadow_flags.get("shadow_parameter_approximation_pack_ready", False)
            ),
            "blocked_non_btc_ticker_count": sum(1 for row in matrix if row["ticker"] != BTC_TICKER and row["blockers"]),
        },
        "hard_blockers": [
            "fresh all-ticker live-readonly Coinbase product-rule preflight not run",
            "fresh all-ticker balance/min-notional preflight not run",
            "exact all-ticker live ACK missing",
            "all_ticker_live_allowed_now=false",
            "Codex must not start live test",
        ],
    }
    return _json_safe(report)


def render_all_ticker_24h_workflow_readiness_pack_markdown(report: Dict[str, Any]) -> str:
    gate = report.get("gate_decision") or {}
    lines = [
        "# All-Ticker 24h Workflow Readiness Pack",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- classification: `{report.get('classification')}`",
        f"- all_ticker_workflow_built_locally: `{gate.get('all_ticker_workflow_built_locally')}`",
        f"- all_ticker_ready_for_operator_fresh_preflight: `{gate.get('all_ticker_ready_for_operator_fresh_preflight')}`",
        f"- all_ticker_live_authorized: `{gate.get('all_ticker_live_authorized')}`",
        "",
        "## Per-Ticker Readiness",
        "",
    ]
    for row in report.get("per_ticker_readiness") or []:
        lines.append(
            f"- {row.get('ticker')}: `{row.get('all_ticker_candidate_status')}`, "
            f"evidence=`{row.get('product_rule_evidence_strength')}`, blockers=`{'; '.join(row.get('blockers') or [])}`"
        )
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "PHASE_ALL_TICKER_24H_WORKFLOW_READINESS_PACK",
    "build_all_ticker_24h_workflow_readiness_pack",
    "render_all_ticker_24h_workflow_readiness_pack_markdown",
]
