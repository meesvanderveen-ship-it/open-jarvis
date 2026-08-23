from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.full_bot_failure_determination_matrix import CONFIGURED_USDC_TICKERS, load_json_file, load_latest_report
from bot.full_bot_maker_buy_live_adapter import EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK


FULL_LIVE_PARAMETER_READINESS_GATE_PHASE = "full_live_parameter_readiness_gate_v1"

CORE_LIVE_KEYS = [
    "EXECUTION_MODE",
    "ENABLE_LIVE_ENTRY_ORDERS",
    "ENABLE_LIVE_LIMIT_ORDERS",
    "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS",
    "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT",
    "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE",
    "ENABLE_LIMIT_ORDER_MANAGER",
]

SCOPE_CAP_KEYS = [
    "ALLOWED_TICKERS",
    "PHASE_C_ALLOWED_TICKERS",
    "DEFAULT_QUOTE_SIZE_USDC",
    "MAX_NOTIONAL_USD",
    "PHASE_C_MAX_ORDER_QUOTE",
    "AUTONOMOUS_MAX_ORDER_QUOTE",
    "MAX_OPEN_POSITIONS",
    "MAX_NEW_ORDERS_PER_CYCLE",
    "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE",
    "PHASE_C_MAX_OPEN_ENTRY_ORDERS",
    "AUTONOMOUS_MAX_OPEN_ORDERS",
]

MUST_REMAIN_DISABLED_KEYS = [
    "ENABLE_LIVE_EXIT_ORDERS",
    "AUTONOMOUS_ALLOW_EXITS",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT",
    "REPLICATION_ENABLED",
    "LEARNING_TO_EXECUTION_READY",
    "LEARNING_TO_EXECUTION_ALLOWED",
    "LIVE_LEARNING_ALLOWED",
    "PARAMETER_CHANGE_ALLOWED",
    "MARKET_ORDER_ENABLED",
    "ENABLE_MARKET_ORDERS",
    "ALLOW_MARKET_ORDERS",
    "MARKET_BUY_ENABLED",
    "MARKET_SELL_ENABLED",
]

BOOLEAN_TRUE = {"1", "true", "yes", "on"}
FINAL_ORDER_STATUSES = {"filled", "done", "completed", "cancelled", "canceled", "expired", "failed", "rejected", "submit_rejected", "replaced"}

ALL_TICKERS = ",".join(CONFIGURED_USDC_TICKERS)

RECOMMENDED_ENV_VALUES: Dict[str, str] = {
    "EXECUTION_MODE": "live",
    "ENABLE_LIVE_ENTRY_ORDERS": "true",
    "ENABLE_LIVE_LIMIT_ORDERS": "true",
    "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
    "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "false",
    "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE": "true",
    "ENABLE_LIMIT_ORDER_MANAGER": "true",
    "ALLOWED_TICKERS": ALL_TICKERS,
    "PHASE_C_ALLOWED_TICKERS": ALL_TICKERS,
    "DEFAULT_QUOTE_SIZE_USDC": "20.00",
    "MAX_NOTIONAL_USD": "20.00",
    "PHASE_C_MAX_ORDER_QUOTE": "20.00",
    "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
    "MAX_OPEN_POSITIONS": "5",
    "MAX_NEW_ORDERS_PER_CYCLE": "2",
    "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "2",
    "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "5",
    "AUTONOMOUS_MAX_OPEN_ORDERS": "5",
    "ENABLE_LIVE_EXIT_ORDERS": "false",
    "AUTONOMOUS_ALLOW_EXITS": "false",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "false",
    "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "true",
    "REPLICATION_ENABLED": "false",
    "LEARNING_TO_EXECUTION_READY": "false",
    "LEARNING_TO_EXECUTION_ALLOWED": "false",
    "LIVE_LEARNING_ALLOWED": "false",
    "PARAMETER_CHANGE_ALLOWED": "false",
    "MARKET_ORDER_ENABLED": "false",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_env_text(text: str) -> Dict[str, str]:
    values: Dict[str, str] = {}
    pending_key = ""
    pending_parts: List[str] = []
    for raw in text.splitlines():
        line = raw.strip()
        if pending_key:
            pending_parts.append(raw)
            if raw.endswith("\\n"):
                continue
            values[pending_key] = "\n".join(pending_parts)
            pending_key = ""
            pending_parts = []
            continue
        if not line or line.startswith("#") or "=" not in raw:
            continue
        key, value = raw.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        values[key] = value
        if value.startswith("-----BEGIN") and not value.endswith("\\n"):
            pending_key = key
            pending_parts = [value]
    return values


def _as_bool(value: Any) -> bool:
    return str(value or "").strip().lower() in BOOLEAN_TRUE


def _decimal(value: Any) -> Decimal:
    try:
        text = str(value or "").strip()
        return Decimal(text) if text else Decimal("0")
    except (InvalidOperation, TypeError, ValueError):
        return Decimal("0")


def _int(value: Any) -> int:
    try:
        return int(_decimal(value))
    except Exception:
        return 0


def _split_tickers(value: Any) -> List[str]:
    return [part.strip().upper() for part in str(value or "").split(",") if part.strip()]


def _normalize_for_compare(key: str, value: Any) -> Any:
    if key in {"ALLOWED_TICKERS", "PHASE_C_ALLOWED_TICKERS"}:
        return _split_tickers(value)
    if key in {
        "DEFAULT_QUOTE_SIZE_USDC",
        "MAX_NOTIONAL_USD",
        "PHASE_C_MAX_ORDER_QUOTE",
        "AUTONOMOUS_MAX_ORDER_QUOTE",
    }:
        return _decimal(value)
    if key in {
        "MAX_OPEN_POSITIONS",
        "MAX_NEW_ORDERS_PER_CYCLE",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS",
        "AUTONOMOUS_MAX_OPEN_ORDERS",
    }:
        return _int(value)
    if key.startswith("ENABLE_") or key.startswith("ALLOW_") or key.startswith("AUTONOMOUS_ALLOW") or key in {
        "REPLICATION_ENABLED",
        "LEARNING_TO_EXECUTION_READY",
        "LEARNING_TO_EXECUTION_ALLOWED",
        "LIVE_LEARNING_ALLOWED",
        "PARAMETER_CHANGE_ALLOWED",
        "MARKET_ORDER_ENABLED",
        "MARKET_BUY_ENABLED",
        "MARKET_SELL_ENABLED",
    }:
        return _as_bool(value)
    return str(value or "").strip().lower()


def _mismatch_direction(key: str, current: Any, recommended: Any) -> str:
    cur = _normalize_for_compare(key, current)
    rec = _normalize_for_compare(key, recommended)
    if cur == rec:
        return "matches"
    if isinstance(cur, Decimal) and isinstance(rec, Decimal):
        return "too_permissive" if cur > rec else "too_restrictive"
    if isinstance(cur, int) and isinstance(rec, int):
        return "too_permissive" if cur > rec else "too_restrictive"
    if isinstance(cur, list) and isinstance(rec, list):
        cur_set = set(cur)
        rec_set = set(rec)
        if cur_set > rec_set:
            return "too_permissive"
        if cur_set < rec_set:
            return "too_restrictive"
        return "mismatch"
    if isinstance(cur, bool) and isinstance(rec, bool):
        return "too_permissive" if cur and not rec else "too_restrictive"
    return "mismatch"


def _env_snapshot(env: Dict[str, str]) -> Dict[str, str]:
    keys = list(dict.fromkeys(CORE_LIVE_KEYS + SCOPE_CAP_KEYS + ["PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"] + MUST_REMAIN_DISABLED_KEYS))
    return {key: str(env.get(key, "")) for key in keys}


def _orders(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    orders = raw.get("orders") if isinstance(raw, dict) else {}
    if isinstance(orders, dict):
        return [item for item in orders.values() if isinstance(item, dict)]
    if isinstance(orders, list):
        return [item for item in orders if isinstance(item, dict)]
    return []


def _positions(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    if not isinstance(raw, dict):
        return []
    return [dict(value, ticker=key) for key, value in raw.items() if isinstance(value, dict)]


def _open_order_count(raw: Dict[str, Any]) -> int:
    count = 0
    for order in _orders(raw):
        status = str(order.get("status") or order.get("order_status") or "").strip().lower()
        if status and status not in FINAL_ORDER_STATUSES:
            count += 1
    return count


def _open_position_count(raw: Dict[str, Any]) -> int:
    count = 0
    for pos in _positions(raw):
        status = str(pos.get("status") or "").strip().lower()
        base = _decimal(pos.get("position_size_base") or pos.get("bot_managed_base") or pos.get("size_base"))
        if status not in {"closed", "closed_tiny_residual"} and base > Decimal("0"):
            count += 1
    return count


def _open_d3_exit_count(raw: Dict[str, Any]) -> int:
    count = 0
    for order in _orders(raw):
        side = str(order.get("side") or "").upper()
        label = str(order.get("label") or order.get("exit_label") or order.get("order_role") or "").upper()
        client_order_id = str(order.get("client_order_id") or "").lower()
        status = str(order.get("status") or order.get("order_status") or "").lower()
        if side == "SELL" and ("TP" in label or "EXIT" in label or client_order_id.startswith(("phased3-", "phased4-"))) and status not in FINAL_ORDER_STATUSES:
            count += 1
    return count


def _latest_reports(root: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    patterns = {
        "workflow_completeness_audit": "full-bot-workflow-completeness-audit-*.json",
        "failure_determination_matrix": "full-bot-failure-determination-matrix-*.json",
        "maker_buy_adapter": "full-bot-maker-buy-live-adapter-*.json",
        "maker_buy_adapter_post_review": "full-bot-maker-buy-live-adapter-post-review-*.json",
        "near_miss_review": "full-bot-near-miss-phase-c-review-*.json",
        "orchestrator": "full-bot-orchestrator-*.json",
    }
    payloads: Dict[str, Dict[str, Any]] = {}
    paths: Dict[str, Dict[str, Any]] = {}
    for name, pattern in patterns.items():
        payload, path = load_latest_report(root, pattern)
        payloads[name] = payload
        paths[name] = {"pattern": f"reports/d6/{pattern}", "present": bool(path), "path": str(path) if path else ""}
    return payloads, paths


def _env_mismatches(current: Dict[str, str], recommended: Dict[str, str]) -> List[Dict[str, str]]:
    rows: List[Dict[str, str]] = []
    for key in CORE_LIVE_KEYS + SCOPE_CAP_KEYS + ["PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"] + MUST_REMAIN_DISABLED_KEYS:
        if key not in recommended and key not in current:
            continue
        cur = current.get(key, "")
        rec = recommended.get(key, "false" if key in MUST_REMAIN_DISABLED_KEYS else "")
        if _normalize_for_compare(key, cur) == _normalize_for_compare(key, rec):
            continue
        rows.append(
            {
                "key": key,
                "current": str(cur),
                "recommended": str(rec),
                "classification": _mismatch_direction(key, cur, rec),
            }
        )
    return rows


def _safety_env_blockers(current: Dict[str, str]) -> List[str]:
    blockers: List[str] = []
    for key in MUST_REMAIN_DISABLED_KEYS:
        if _as_bool(current.get(key)):
            blockers.append(f"{key.lower()}_enabled")
    if not _as_bool(current.get("PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "true")):
        blockers.append("phase_c_exit_limit_orders_not_disabled")
    return sorted(set(blockers))


def _p0_safety_gaps(open_orders: int, open_positions: int, open_d3_exit: int, safety_env_blockers: List[str]) -> List[str]:
    gaps: List[str] = []
    if open_orders:
        gaps.append("open_orders_nonzero")
    if open_d3_exit:
        gaps.append("open_d3_exit_nonzero")
    if open_positions:
        gaps.append("open_positions_nonzero")
    gaps.extend(safety_env_blockers)
    return sorted(set(gaps))


def _readiness_from_reports(payloads: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    failure = payloads.get("failure_determination_matrix") or {}
    failure_summary = failure.get("summary") if isinstance(failure.get("summary"), dict) else {}
    workflow = payloads.get("workflow_completeness_audit") or {}
    adapter = payloads.get("maker_buy_adapter_post_review") or payloads.get("maker_buy_adapter") or {}
    review = payloads.get("near_miss_review") or {}
    phase_c_ready = list(failure_summary.get("phase_c_ready_tickers") or workflow.get("phase_c_ready_tickers_now") or [])
    any_phase_c_ready = bool(failure_summary.get("any_ticker_phase_c_ready_now") or workflow.get("any_ticker_phase_c_ready_now") or phase_c_ready)
    fresh = list(failure_summary.get("top_all_ticker_fresh_judge_candidates") or [])
    risk = list(failure_summary.get("top_all_ticker_deterministic_risk_candidates") or [])
    refresh = list(failure_summary.get("top_all_ticker_refresh_candidates") or [])
    adapter_blockers = [str(x) for x in adapter.get("blockers") or []]
    review_blockers = [str(x) for x in review.get("blockers") or []]
    if "fresh_judge_buy_approval_missing" in review_blockers and not fresh:
        fresh = [str(x.get("ticker")) for x in review.get("fresh_review_results") or [] if isinstance(x, dict) and x.get("ticker")]
    if "deterministic_live_risk_approval_missing" in review_blockers and not risk:
        risk = [str(x.get("ticker")) for x in review.get("fresh_review_results") or [] if isinstance(x, dict) and x.get("ticker")]
    return {
        "phase_c_ready_tickers": sorted(set(str(x) for x in phase_c_ready if str(x))),
        "any_phase_c_ready": any_phase_c_ready,
        "fresh_judge_candidates": sorted(set(fresh)),
        "deterministic_risk_candidates": sorted(set(risk)),
        "refresh_candidates": sorted(set(refresh)),
        "adapter_blockers": sorted(set(adapter_blockers)),
        "review_blockers": sorted(set(review_blockers)),
        "failure_summary": failure_summary,
        "workflow_readiness_verdict": workflow.get("readiness_verdict", ""),
    }


def _process_local_overrides() -> Dict[str, str]:
    keys = CORE_LIVE_KEYS + SCOPE_CAP_KEYS + ["PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"] + MUST_REMAIN_DISABLED_KEYS
    return {key: RECOMMENDED_ENV_VALUES[key] for key in keys if key in RECOMMENDED_ENV_VALUES}


def _env_patch_lines(values: Dict[str, str]) -> str:
    return "\n".join(f"{key}={values[key]}" for key in sorted(values)) + "\n"


def build_full_live_parameter_readiness_gate(
    *,
    root: str | Path = ".",
    env_text: Optional[str] = None,
    ack: str = "",
    report_payloads: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    root_path = Path(root)
    env_path = root_path / ".env"
    parsed_env = parse_env_text(env_text if env_text is not None else (env_path.read_text(encoding="utf-8") if env_path.exists() else ""))
    current_env = _env_snapshot(parsed_env)
    recommended_env = {key: RECOMMENDED_ENV_VALUES.get(key, "false") for key in current_env}
    mismatches = _env_mismatches(current_env, recommended_env)

    payloads, report_paths = _latest_reports(root_path)
    payloads.update(report_payloads or {})
    readiness = _readiness_from_reports(payloads)

    open_orders_path = root_path / "state/open_orders.json"
    positions_path = root_path / "state/positions.json"
    before_hashes = {
        "state/open_orders.json": sha256_file(open_orders_path) if open_orders_path.exists() else "",
        "state/positions.json": sha256_file(positions_path) if positions_path.exists() else "",
    }
    open_orders_state = load_json_file(open_orders_path)
    positions_state = load_json_file(positions_path)
    open_orders = _open_order_count(open_orders_state)
    open_positions = _open_position_count(positions_state)
    open_d3_exit = _open_d3_exit_count(open_orders_state)

    exact_ack_present = str(ack or "").strip() == EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK
    safety_env_blockers = _safety_env_blockers(current_env)
    p0_safety_gaps = _p0_safety_gaps(open_orders, open_positions, open_d3_exit, safety_env_blockers)
    p1_live_start_blockers: List[str] = []
    if not readiness["any_phase_c_ready"]:
        p1_live_start_blockers.append("missing_phase_c_ready_candidate")
    if readiness["fresh_judge_candidates"]:
        p1_live_start_blockers.append("missing_fresh_phase_c_buy_judge_approval")
    if readiness["deterministic_risk_candidates"]:
        p1_live_start_blockers.append("missing_deterministic_live_risk_approval")
    if readiness["refresh_candidates"]:
        p1_live_start_blockers.append("stale_or_cap_hidden_d6_candidates_need_refresh")

    env_mismatch_blockers = [
        row["key"].lower() + "_mismatch"
        for row in mismatches
        if row["key"] in MUST_REMAIN_DISABLED_KEYS or row["key"] == "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS"
    ]
    if p0_safety_gaps:
        status = "blocked"
        classification = "unsafe_to_start" if safety_env_blockers else "blocked_by_safety_gap"
    elif env_mismatch_blockers:
        status = "blocked"
        classification = "blocked_by_env_mismatch"
    elif readiness["fresh_judge_candidates"] or readiness["deterministic_risk_candidates"]:
        status = "blocked"
        classification = "blocked_by_missing_fresh_judge_and_risk"
    elif not readiness["any_phase_c_ready"] or readiness["refresh_candidates"]:
        status = "blocked"
        classification = "blocked_by_missing_fresh_candidate_refresh"
    elif mismatches:
        status = "blocked"
        classification = "blocked_by_env_mismatch"
    elif exact_ack_present:
        status = "ready_for_ack_gated_maker_buy_actual_submit"
        classification = "ready_for_ack_gated_maker_buy_actual_submit"
    else:
        status = "ready_for_process_local_live_start"
        classification = "ready_for_process_local_live_start"

    first_real_submit_allowed = bool(
        readiness["any_phase_c_ready"] and not p0_safety_gaps and not env_mismatch_blockers and not mismatches and exact_ack_present
    )
    full_autonomous_start_allowed = bool(
        first_real_submit_allowed and not mismatches and classification == "ready_for_ack_gated_maker_buy_actual_submit"
    )

    blockers = sorted(set(p0_safety_gaps + p1_live_start_blockers + (env_mismatch_blockers if p0_safety_gaps else [])))
    warnings: List[str] = []
    if mismatches and not env_mismatch_blockers:
        warnings.append("env_has_restrictive_or_cap_mismatches_recommend_process_local_overrides_until_phase_c_ready")
    if not exact_ack_present:
        warnings.append("exact_ack_absent_required_only_for_actual_submit")

    exact_preview_command = (
        "python3 tools/build_d6_multi_order_intent_preview.py "
        "--json-out reports/d6/d6-multi-order-intent-preview-calibrated-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/d6-multi-order-intent-preview-calibrated-$(date -u +%Y%m%d).md && "
        "python3 tools/build_full_bot_orchestrator_report.py "
        "--d6-preview-json reports/d6/d6-multi-order-intent-preview-calibrated-$(date -u +%Y%m%d).json "
        "--json-out reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).md && "
        "python3 tools/build_full_bot_maker_buy_live_adapter_report.py "
        "--orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json "
        "--json-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).md && "
        "python3 tools/build_full_bot_near_miss_phase_c_review.py "
        "--adapter-report reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).json "
        "--json-out reports/d6/full-bot-near-miss-phase-c-review-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/full-bot-near-miss-phase-c-review-$(date -u +%Y%m%d).md && "
        "python3 tools/build_full_bot_failure_determination_matrix.py --all-configured-tickers "
        "--json-out reports/d6/full-bot-failure-determination-matrix-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/full-bot-failure-determination-matrix-$(date -u +%Y%m%d).md"
    )
    process_local_prefix = " ".join(f"{key}={value}" for key, value in _process_local_overrides().items())
    actual_submit_command = (
        "DO NOT RUN NOW. Only after Phase-C-ready candidate plus exact ACK: "
        f"{process_local_prefix} python3 tools/build_full_bot_maker_buy_live_adapter_report.py "
        f"--actual-submit --ack {EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK} "
        "--orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json "
        "--json-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).json "
        "--markdown-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).md"
    )
    full_start_command = (
        "DO NOT RUN NOW. Only after Phase-C-ready candidate, clean gate, and exact ACK: "
        f"{process_local_prefix} {EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK}=true python3 run_trader_loop.py"
    )

    after_hashes = {
        "state/open_orders.json": sha256_file(open_orders_path) if open_orders_path.exists() else "",
        "state/positions.json": sha256_file(positions_path) if positions_path.exists() else "",
    }
    env_patch_if_ready = _env_patch_lines(recommended_env) if classification == "ready_for_env_update_only" else ""

    report = {
        "generated_at": now_iso(),
        "phase": FULL_LIVE_PARAMETER_READINESS_GATE_PHASE,
        "status": status,
        "classification": classification,
        "report_only": True,
        "replication_enabled": _as_bool(current_env.get("REPLICATION_ENABLED")),
        "replication_publish_allowed": False,
        "follower_lifecycle_enabled": False,
        "env_mutation_performed": False,
        "bot_start_attempted": False,
        "live_order_submit_attempted": False,
        "coinbase_write_attempted": False,
        "state_write_performed": False,
        "current_env_values": current_env,
        "recommended_env_values": recommended_env,
        "env_mismatches": mismatches,
        "values_to_keep_disabled": {key: recommended_env.get(key, "false") for key in ["ENABLE_LIVE_EXIT_ORDERS", "AUTONOMOUS_ALLOW_EXITS", "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "REPLICATION_ENABLED", "LEARNING_TO_EXECUTION_READY", "LEARNING_TO_EXECUTION_ALLOWED", "LIVE_LEARNING_ALLOWED", "PARAMETER_CHANGE_ALLOWED", "MARKET_ORDER_ENABLED"]},
        "values_allowed_process_local_only": _process_local_overrides() if classification not in {"ready_for_env_update_only"} else {},
        "values_safe_for_permanent_env": {
            key: value
            for key, value in recommended_env.items()
            if key in {"ENABLE_LIVE_EXIT_ORDERS", "AUTONOMOUS_ALLOW_EXITS", "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT", "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS", "REPLICATION_ENABLED", "LEARNING_TO_EXECUTION_READY", "LEARNING_TO_EXECUTION_ALLOWED", "LIVE_LEARNING_ALLOWED", "PARAMETER_CHANGE_ALLOWED", "MARKET_ORDER_ENABLED"}
        },
        "phase_c_ready_tickers": readiness["phase_c_ready_tickers"],
        "any_ticker_phase_c_ready_now": readiness["any_phase_c_ready"],
        "first_real_maker_buy_live_submit_allowed_now": first_real_submit_allowed,
        "full_autonomous_start_allowed_now": full_autonomous_start_allowed,
        "blockers": blockers,
        "warnings": sorted(set(warnings)),
        "p0_safety_gaps": p0_safety_gaps,
        "p1_live_start_blockers": sorted(set(p1_live_start_blockers)),
        "exact_next_codex_task": "Run report-only fresh candidate refresh plus fresh Phase-C judge and deterministic live-risk evidence for selected maker BUY candidates; rerun this readiness gate before any ACK-gated actual submit.",
        "exact_preview_command": exact_preview_command,
        "exact_actual_submit_command_if_ready": actual_submit_command if first_real_submit_allowed else "DO NOT RUN NOW. Blocked until Phase-C-ready candidate plus exact ACK.",
        "exact_full_start_command_if_ready": full_start_command if full_autonomous_start_allowed else "DO NOT RUN NOW. Blocked until Phase-C-ready candidate, clean gate, and exact ACK.",
        "exact_env_patch_if_ready": env_patch_if_ready,
        "do_not_run_commands": [
            "python3 run_trader_loop.py",
            "python3 tools/build_full_bot_maker_buy_live_adapter_report.py --actual-submit",
            "any Coinbase submit/cancel/replace command",
            "any SELL, market order, live exit, D3 actual exit submit, replication, learning-to-execution, or parameter mutation command",
        ],
        "ack_boundaries": {
            "exact_maker_buy_ack_required_for_actual_submit": EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
            "exact_ack_present": exact_ack_present,
            "ack_alone_is_insufficient": not readiness["any_phase_c_ready"],
        },
        "state_counts": {
            "open_orders": open_orders,
            "open_positions": open_positions,
            "open_d3_exit": open_d3_exit,
        },
        "state_hashes": {
            "before": before_hashes,
            "after": after_hashes,
            "unchanged": before_hashes == after_hashes,
        },
        "source_report_paths": report_paths,
        "source_report_summary": {
            "workflow_readiness_verdict": readiness["workflow_readiness_verdict"],
            "fresh_judge_candidates": readiness["fresh_judge_candidates"],
            "deterministic_risk_candidates": readiness["deterministic_risk_candidates"],
            "refresh_candidates": readiness["refresh_candidates"],
            "adapter_blockers": readiness["adapter_blockers"],
            "review_blockers": readiness["review_blockers"],
        },
    }
    return json_safe(report)


def render_full_live_parameter_readiness_gate_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Live Parameter Readiness & Start Gate v1",
        "",
        "Report-only gate. No env mutation, bot start, live submit, Coinbase write, or trading-state write is performed.",
        "",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- report_only: `{report.get('report_only')}`",
        f"- replication_enabled: `{report.get('replication_enabled')}`",
        f"- replication_publish_allowed: `{report.get('replication_publish_allowed')}`",
        f"- follower_lifecycle_enabled: `{report.get('follower_lifecycle_enabled')}`",
        f"- env_mutation_performed: `{report.get('env_mutation_performed')}`",
        f"- bot_start_attempted: `{report.get('bot_start_attempted')}`",
        f"- live_order_submit_attempted: `{report.get('live_order_submit_attempted')}`",
        f"- coinbase_write_attempted: `{report.get('coinbase_write_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- any_ticker_phase_c_ready_now: `{report.get('any_ticker_phase_c_ready_now')}`",
        f"- first_real_maker_buy_live_submit_allowed_now: `{report.get('first_real_maker_buy_live_submit_allowed_now')}`",
        f"- full_autonomous_start_allowed_now: `{report.get('full_autonomous_start_allowed_now')}`",
        "",
        "## Environment",
        "",
        "```json",
        json.dumps(
            {
                "current_env_values": report.get("current_env_values"),
                "recommended_env_values": report.get("recommended_env_values"),
                "env_mismatches": report.get("env_mismatches"),
                "values_to_keep_disabled": report.get("values_to_keep_disabled"),
                "values_allowed_process_local_only": report.get("values_allowed_process_local_only"),
                "values_safe_for_permanent_env": report.get("values_safe_for_permanent_env"),
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Readiness",
        "",
        "```json",
        json.dumps(
            {
                "phase_c_ready_tickers": report.get("phase_c_ready_tickers"),
                "blockers": report.get("blockers"),
                "warnings": report.get("warnings"),
                "p0_safety_gaps": report.get("p0_safety_gaps"),
                "p1_live_start_blockers": report.get("p1_live_start_blockers"),
                "state_counts": report.get("state_counts"),
                "ack_boundaries": report.get("ack_boundaries"),
            },
            indent=2,
            sort_keys=True,
        ),
        "```",
        "",
        "## Commands",
        "",
        f"- next Codex task: `{report.get('exact_next_codex_task')}`",
        f"- may run now: `{report.get('exact_preview_command')}`",
        f"- actual submit if ready: `{report.get('exact_actual_submit_command_if_ready')}`",
        f"- full start if ready: `{report.get('exact_full_start_command_if_ready')}`",
        "",
        "## State Hashes",
        "",
        "```json",
        json.dumps(report.get("state_hashes") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Do Not Run",
        "",
        "```json",
        json.dumps(report.get("do_not_run_commands") or [], indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK",
    "FULL_LIVE_PARAMETER_READINESS_GATE_PHASE",
    "RECOMMENDED_ENV_VALUES",
    "build_full_live_parameter_readiness_gate",
    "parse_env_text",
    "render_full_live_parameter_readiness_gate_markdown",
]
