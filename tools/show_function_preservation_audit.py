#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

OPEN_ORDER_STATUSES = {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending"}
C43_PREFIXES = ("phasec-", "c43-", "phase-c43-")
D3_EXIT_PREFIX = "d3exit-"

REQUIRED_SAFE_FLAGS: Dict[str, str] = {
    "REPLICATION_ENABLED": "false",
    "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "false",
    "ENABLE_LIVE_EXIT_ORDERS": "false",
    "AUTONOMOUS_ALLOW_EXITS": "false",
    "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "true",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "false",
}

FULL_WORKFLOW_LIVE_FLAGS: Dict[str, str] = {
    "ENABLE_FULL_WORKFLOW_LIVE_MODE": "true",
    "EXECUTION_MODE": "live",
    "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT": "true",
    "ENABLE_LIVE_EXIT_ORDERS": "true",
    "AUTONOMOUS_ALLOW_EXITS": "true",
    "ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT": "true",
    "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS": "false",
    "AUTONOMOUS_ENTRY_ONLY_FIRST": "false",
    "MAX_OPEN_POSITIONS": "3",
    "AUTONOMOUS_MAX_OPEN_ORDERS": "3",
    "PHASE_C_MAX_OPEN_ENTRY_ORDERS": "3",
    "MAX_NEW_ORDERS_PER_CYCLE": "1",
    "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE": "1",
    "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE": "1",
    "DEFAULT_QUOTE_SIZE_USDC": "20.00",
    "MAX_NOTIONAL_USD": "20.00",
    "PHASE_C_MAX_ORDER_QUOTE": "20.00",
    "AUTONOMOUS_MAX_ORDER_QUOTE": "20.00",
    "PHASE_D3_MAX_EXIT_ORDER_QUOTE": "20.00",
    "PHASE_D3_MAX_OPEN_EXIT_ORDERS": "3",
    "PHASE_D3_MAX_NEW_EXIT_ORDERS_PER_CYCLE": "1",
    "REPLICATION_ENABLED": "false",
    "MARKET_ORDER_ENABLED": "false",
    "ENABLE_MARKET_ORDERS": "false",
    "ALLOW_MARKET_ORDERS": "false",
    "LEARNING_TO_EXECUTION_READY": "false",
    "LEARNING_TO_EXECUTION_ALLOWED": "false",
    "LIVE_LEARNING_ALLOWED": "false",
    "PARAMETER_CHANGE_ALLOWED": "false",
}

EXPECTED_READY_FLAGS: Dict[str, str] = {
    "ENABLE_LIVE_LIMIT_ORDERS": "true",
    "ENABLE_LIVE_ENTRY_ORDERS": "true",
    "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS": "true",
}

@dataclass(frozen=True)
class StaticCheck:
    key: str
    label: str
    files: Tuple[str, ...]
    all_patterns: Tuple[str, ...] = ()
    any_patterns: Tuple[str, ...] = ()
    tests: Tuple[str, ...] = ()
    required: bool = True
    category: str = "core"
    notes: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_root() -> Path:
    here = Path(__file__).resolve()
    # tools/show_function_preservation_audit.py -> project root is parent[1]
    if here.parent.name == "tools":
        return here.parents[1]
    return Path.cwd()


def _read_text(path: Path, max_chars: int = 2_000_000) -> str:
    try:
        if not path.exists() or not path.is_file():
            return ""
        return path.read_text(encoding="utf-8", errors="replace")[:max_chars]
    except Exception:
        return ""


def _load_json(path: Path) -> Any:
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            return None
        return json.loads(text)
    except Exception as exc:
        return {"_error": f"json_load_failed:{type(exc).__name__}:{exc}"}


def _iter_jsonl(path: Path, limit_tail: int = 5000) -> List[Dict[str, Any]]:
    if not path.exists() or not path.is_file():
        return []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines[-limit_tail:]:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            if isinstance(obj, dict):
                rows.append(obj)
        except Exception:
            rows.append({"_parse_error": True, "raw_prefix": line[:200]})
    return rows


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _env_parse(path: Path) -> Dict[str, Any]:
    entries: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    malformed: List[Dict[str, Any]] = []
    if not path.exists():
        return {"path": str(path), "exists": False, "entries": {}, "effective": {}, "duplicates": {}, "malformed": []}
    for lineno, raw in enumerate(_read_text(path, max_chars=1_000_000).splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            malformed.append({"line": lineno, "raw": raw})
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", key):
            malformed.append({"line": lineno, "raw": raw, "reason": "invalid_key"})
            continue
        entries[key].append({"line": lineno, "value": value, "raw": raw})
    effective = {k: v[-1]["value"] for k, v in entries.items() if v}
    duplicates = {k: v for k, v in entries.items() if len(v) > 1}
    return {
        "path": str(path),
        "exists": True,
        "entries": entries,
        "effective": effective,
        "duplicates": duplicates,
        "malformed": malformed,
    }


def _norm_bool(value: Any) -> Optional[bool]:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return None


def _check_env_safety(env: Dict[str, Any]) -> Dict[str, Any]:
    effective = env.get("effective", {}) if isinstance(env, dict) else {}
    duplicates = env.get("duplicates", {}) if isinstance(env, dict) else {}
    malformed = env.get("malformed", []) if isinstance(env, dict) else []
    flags: Dict[str, Any] = {}
    blockers: List[str] = []
    warnings: List[str] = []

    full_workflow_requested = str(effective.get("ENABLE_FULL_WORKFLOW_LIVE_MODE", "")).strip().lower() == "true"
    if full_workflow_requested:
        for key, expected in FULL_WORKFLOW_LIVE_FLAGS.items():
            value = effective.get(key)
            ok = str(value).strip().lower() == expected.lower()
            flags[key] = {"value": value, "expected_full_workflow_live_max3x20": expected, "ok": ok, "line": (env.get("entries", {}).get(key, [{}])[-1].get("line") if env.get("entries", {}).get(key) else None)}
            if not ok:
                blockers.append(f"{key}_not_{expected}")
    else:
        for key, expected in REQUIRED_SAFE_FLAGS.items():
            value = effective.get(key)
            ok = str(value).strip().lower() == expected
            flags[key] = {"value": value, "expected_observe_only": expected, "ok": ok, "line": (env.get("entries", {}).get(key, [{}])[-1].get("line") if env.get("entries", {}).get(key) else None)}
            if not ok:
                blockers.append(f"{key}_not_{expected}")

    if not full_workflow_requested:
        required_keys_for_duplicates = set(REQUIRED_SAFE_FLAGS)
    else:
        required_keys_for_duplicates = set(FULL_WORKFLOW_LIVE_FLAGS)

    for key, expected in EXPECTED_READY_FLAGS.items():
        value = effective.get(key)
        flags[key] = {"value": value, "expected_for_entry_infra_ready": expected, "ok": str(value).strip().lower() == expected if value is not None else False, "line": (env.get("entries", {}).get(key, [{}])[-1].get("line") if env.get("entries", {}).get(key) else None)}
        if value is None:
            warnings.append(f"{key}_missing")

    for key in sorted(required_keys_for_duplicates | set(EXPECTED_READY_FLAGS)):
        if key in duplicates:
            warnings.append(f"duplicate_env_key:{key}")
    for item in malformed:
        warnings.append(f"malformed_env_line:{item.get('line')}")

    # Specific safety interpretation.
    actual_submit = _norm_bool(effective.get("ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT"))
    live_exits = _norm_bool(effective.get("ENABLE_LIVE_EXIT_ORDERS"))
    d3_actual = _norm_bool(effective.get("ENABLE_PHASE_D3_ACTUAL_EXIT_SUBMIT"))
    replication = _norm_bool(effective.get("REPLICATION_ENABLED"))
    if full_workflow_requested and not blockers:
        mode = "full_workflow_live_max3x20"
    else:
        mode = "observe_only_no_submit" if actual_submit is False and live_exits is False and d3_actual is False and replication is False else "review_required"

    return {
        "mode": mode,
        "ready": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "flags": flags,
    }


def _file_exists(root: Path, rel: str) -> bool:
    return (root / rel).exists()


def _pattern_found(root: Path, rels: Iterable[str], pattern: str) -> bool:
    rx = re.compile(pattern, re.MULTILINE | re.DOTALL)
    for rel in rels:
        text = _read_text(root / rel)
        if text and rx.search(text):
            return True
    return False


def _ast_defs(root: Path, rel: str) -> Dict[str, List[str]]:
    text = _read_text(root / rel)
    if not text:
        return {"functions": [], "classes": []}
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return {"functions": [], "classes": [], "syntax_error": ["true"]}
    funcs: List[str] = []
    classes: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
    return {"functions": sorted(set(funcs)), "classes": sorted(set(classes))}


def _static_checks() -> List[StaticCheck]:
    return [
        StaticCheck("strategy_engine", "StrategyEngine core workflow", ("bot/strategy_engine.py",), (r"class\s+StrategyEngine\b", r"run_trader_loop|analyze|judge|approve_trade"), category="core"),
        StaticCheck("coinbase_client", "Coinbase client", ("bot/coinbase_client.py",), (r"class\s+CoinbaseClient\b", r"place_limit_order|get_order|accounts|product"), category="core"),
        StaticCheck("risk_firewall", "Deterministic risk firewall", ("risk_firewall.py",), (r"risk|approve|reject|position|size",), category="core"),
        StaticCheck("llm_clients", "LLM clients and hygiene", ("bot/llm_clients.py", "bot/llm_clients_resilient.py"), any_patterns=(r"llm_corrupt", r"provider_errors", r"openai", r"anthropic"), category="core"),
        StaticCheck("market_data", "Market data/candles/orderbook context", ("bot/market_data.py", "bot/orderbook_analyzer.py"), any_patterns=(r"orderbook", r"candles", r"best_bid", r"best_ask"), category="core"),

        StaticCheck("execution_planner", "Read-only execution planner", ("bot/execution_planner.py",), (r"class\s+ReadOnlyExecutionPlanner\b", r"no_order|limit|pending"), tests=("tests/test_execution_planner_read_only.py",), category="buy_entry"),
        StaticCheck("pending_order_intents", "Pending/watchlist order intents", ("bot/pending_order_intents.py",), (r"class\s+PendingOrderIntentStore\b", r"needs_fresh_analysis|promotion_ready|trigger_ready"), tests=("tests/test_phase_b6_pending_order_intents.py",), category="buy_entry"),
        StaticCheck("phase_c43_entry", "C.4.3 autonomous live entry guard/submit/fill bridge", ("bot/phase_c43_autonomous_entry_live.py",), (r"build_phase_c43_status_report", r"reconcile_phase_c43_fills_to_positions", r"build_phase_c43_guard_and_submit_preparation"), tests=("tests/test_phase_c43_autonomous_entry_live.py",), category="buy_entry"),
        StaticCheck("c43_strategy_bridge", "StrategyEngine direct C.4.3 bridge v2", ("bot/strategy_engine.py",), (r"strategy_engine_direct_c43_bridge", r"phase_c43_strategy_engine_direct_bridge"), tests=("tests/test_phase_c43_strategy_engine_direct_bridge.py",), category="buy_entry"),
        StaticCheck("phase_c40_safety", "Phase C.40 live order safety layer", ("bot/phase_c40_live_order_safety_layer.py",), (r"collect_live_open_orders_snapshot", r"unmanaged_order_requires_manual_review|C40_FINAL_STATUSES"), tests=("tests/test_phase_c40_live_order_safety_layer.py",), category="buy_entry"),
        StaticCheck("coinbase_order_snapshot", "Read-only Coinbase order/fill snapshot", ("bot/coinbase_order_snapshot.py",), (r"fetch_coinbase_order_snapshot", r"normalize_coinbase_order_snapshot", r"does_not_cancel"), tests=("tests/test_coinbase_order_snapshot.py",), category="buy_entry"),
        StaticCheck("controlled_entry_pilot", "C.4.4.3 controlled entry-only pilot runner", ("bot/phase_c43_controlled_entry_pilot.py", "tools/run_phase_c43_controlled_entry_pilot.py"), (r"build_controlled_entry_pilot_report", r"one_entry_order_only_requires_zero_open_before_submit", r"uses_existing_c43_smoke_submitter_only"), tests=("tests/test_phase_c43_controlled_entry_pilot.py",), category="buy_entry"),

        StaticCheck("d1_exit_scaffold", "D.1 exit orderbook scaffold", ("bot/phase_d1_exit_orderbook_scaffold.py",), (r"D1_exit_orderbook_scaffold", r"reduce_only|SELL|exit"), tests=("tests/test_phase_d1_exit_orderbook_scaffold.py",), category="sell_exit"),
        StaticCheck("d2_position_executor", "D.2 position executor plan", ("bot/phase_d2_position_executor.py",), (r"build_phase_d2_position_executor_report", r"TP1|TP2|RUNNER|minimum_net_edge"), tests=("tests/test_phase_d2_position_executor.py",), category="sell_exit"),
        StaticCheck("d3_controlled_exits", "D.3 controlled reduce-only exits", ("bot/phase_d3_controlled_live_exits.py",), (r"submit_phase_d3_controlled_exit", r"reduce_only|no_oversell|reserved"), tests=("tests/test_phase_d3_controlled_live_exits.py",), category="sell_exit"),
        StaticCheck("d31_readiness", "D.3.1 lifecycle readiness", ("bot/phase_d31_lifecycle_readiness.py",), (r"build_phase_d31_lifecycle_readiness_report", r"ready_for_controlled_entry_only_arming"), tests=("tests/test_phase_d31_lifecycle_readiness.py",), category="sell_exit"),
        StaticCheck("d32_llm_health", "D.3.2 LLM pre-live health", ("bot/phase_d32_llm_pre_live_health.py",), (r"build_phase_d32_llm_pre_live_health_report", r"recent_llm_corrupt_outputs|recent_provider"), tests=("tests/test_phase_d32_llm_pre_live_health.py",), category="safety"),

        StaticCheck("order_store", "OrderStore lifecycle/open/final/reservations", ("bot/order_store.py",), (r"OPEN_ORDER_STATUSES", r"FINAL_ORDER_STATUSES", r"def\s+update_order", r"reserved_quote_by_ticker"), category="cancel_lifecycle"),
        StaticCheck("manual_cancel_tool", "Manual C.4.3 cancel lifecycle repair tool", ("tools/mark_phase_c43_live_order_cancelled.py",), (r"local_order_marked_cancelled", r"does not call Coinbase|No Coinbase call", r"position_created"), tests=("tests/test_phase_c43_manual_cancel_tool.py",), category="cancel_lifecycle"),
        StaticCheck("repair_c43_record", "C.4.3 order-id/store repair tool", ("tools/repair_phase_c43_live_order_record.py",), (r"success_response", r"exchange_order_id", r"state/open_orders.json"), category="cancel_lifecycle"),
        StaticCheck("c43_lifecycle_orchestrator", "C.4.4/D.3.3 lifecycle orchestrator", ("bot/phase_c43_lifecycle_orchestrator.py", "tools/reconcile_phase_c43_live_orders.py"), (r"build_phase_c43_lifecycle_orchestrator_report", r"positions_opened_only_after_fill_evidence", r"d3_preview_forces_submit_live_false"), tests=("tests/test_phase_c43_lifecycle_orchestrator.py",), category="cancel_lifecycle"),
        StaticCheck("c43_lifecycle_service_hook", "C.4.4.1 lifecycle service hook", ("bot/phase_c43_lifecycle_service.py", "run_trader_loop.py"), (r"build_phase_c43_lifecycle_service_report", r"_run_lifecycle_orchestrator_service_hook", r"phase_c43_lifecycle_service.jsonl"), tests=("tests/test_phase_c43_lifecycle_service.py",), category="cancel_lifecycle"),
        StaticCheck("c43_lifecycle_governance", "C.4.4.2 lifecycle poll/apply governance", ("bot/phase_c43_lifecycle_governance.py", "bot/phase_c43_lifecycle_service.py", "tools/show_phase_c43_lifecycle_governance.py"), (r"build_phase_c43_lifecycle_governance_report", r"effective_flags", r"apply_local_requires_coinbase_poll"), tests=("tests/test_phase_c43_lifecycle_governance.py", "tests/test_phase_c43_lifecycle_service.py"), category="cancel_lifecycle"),
        StaticCheck("c44_poll_to_apply_closeout", "C.4.4.4 governed poll-to-apply closeout runner", ("bot/phase_c44_poll_to_apply_closeout.py", "tools/run_phase_c44_poll_to_apply_closeout.py"), (r"build_phase_c44_poll_to_apply_closeout_report", r"uses_governance_effective_flags", r"fill_apply_requires_explicit_allow_fill_apply"), tests=("tests/test_phase_c44_poll_to_apply_closeout.py",), category="cancel_lifecycle"),
        StaticCheck("c45_live_fill_pilot", "C.4.5 controlled live fill pilot", ("bot/phase_c45_live_fill_pilot.py", "tools/run_phase_c45_live_fill_pilot.py"), (r"build_phase_c45_live_fill_pilot_report", r"fill_apply_requires_explicit_c45_ack", r"never_submits_live_sell_orders"), tests=("tests/test_phase_c45_live_fill_pilot.py",), category="cancel_lifecycle"),

        StaticCheck("execution_learning", "Execution outcome learning / no-fill labels", ("bot/execution_outcome_tracker.py",), any_patterns=(r"missed_fill_opportunity", r"correct_no_fill", r"avoided_bad_entry", r"good_limit_execution"), tests=("tests/test_execution_outcome_tracker_phase_b.py", "tests/test_phase_b3_no_fill_analysis.py"), category="learning"),
        StaticCheck("decision_outcomes", "Decision outcome tracker", ("bot/decision_outcome_tracker.py",), any_patterns=(r"resolved", r"expired", r"cancelled", r"outcome"), tests=("tests/test_decision_outcome_tracker.py",), category="learning"),
        StaticCheck("trade_reflection", "Post-trade reflection memory", ("bot/trade_reflection.py",), (r"class\s+TradeReflectionStore", r"summarize_recent_reflections", r"MFE|MAE|closed trade|reflection"), tests=("tests/test_trade_reflection_learning.py",), category="learning"),

        StaticCheck("chart_patterns", "Chart-pattern context", ("bot/chart_patterns.py",), any_patterns=(r"support_sweep", r"breakout_retest", r"failed_breakout", r"compression"), category="roadmap"),
        StaticCheck("trade_planner", "GPT trade planner schema/helpers", ("bot/trade_planner.py",), (r"normalize_trade_plan", r"plan_action", r"do_not_chase"), category="roadmap"),
        StaticCheck("pending_trade_plans", "Pending trade plans lifecycle", ("bot/pending_trade_plans.py",), (r"class\s+PendingTradePlanStore", r"evaluate|expire|cancel_plan|trigger"), tests=("tests/test_pending_trade_plan_observability.py",), category="roadmap"),
        StaticCheck("backtest_replay", "Replay/backtest harness", ("bot/replay_backtest.py", "replay_backtest.py", "tools/replay_backtest.py"), any_patterns=(r"replay", r"backtest", r"feature_snapshot"), required=False, category="roadmap", notes="Roadmap item; OK if still missing."),
        StaticCheck("social_fundamental_context", "Social/fundamental context adapters", ("bot/external_context/social_sentiment_service.py", "bot/external_context/fundamental_context_service.py"), any_patterns=(r"social", r"fundamental", r"tokenomics", r"event_risk"), required=False, category="roadmap", notes="Roadmap item; OK if disabled/missing."),
    ]


def _evaluate_static_checks(root: Path) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []
    by_category: Dict[str, Dict[str, int]] = defaultdict(lambda: {"total": 0, "present": 0, "missing_required": 0, "partial": 0, "tests_present": 0})
    missing_required: List[str] = []
    for chk in _static_checks():
        files_present = [rel for rel in chk.files if _file_exists(root, rel)]
        file_ok = bool(files_present)
        all_ok = all(_pattern_found(root, chk.files, pat) for pat in chk.all_patterns)
        any_ok = True if not chk.any_patterns else any(_pattern_found(root, chk.files, pat) for pat in chk.any_patterns)
        tests_present = [rel for rel in chk.tests if _file_exists(root, rel)]
        present = file_ok and all_ok and any_ok
        partial = file_ok and not present
        status = "present" if present else ("partial" if partial else ("missing" if chk.required else "roadmap_missing"))
        if chk.required and not present:
            missing_required.append(chk.key)
        by_category[chk.category]["total"] += 1
        if present:
            by_category[chk.category]["present"] += 1
        if partial:
            by_category[chk.category]["partial"] += 1
        if chk.required and not present:
            by_category[chk.category]["missing_required"] += 1
        if tests_present:
            by_category[chk.category]["tests_present"] += 1
        checks.append({
            "key": chk.key,
            "category": chk.category,
            "label": chk.label,
            "status": status,
            "required": chk.required,
            "files_present": files_present,
            "tests_present": tests_present,
            "notes": chk.notes,
        })
    return {
        "checks": checks,
        "summary_by_category": dict(by_category),
        "missing_required": missing_required,
        "ready": not missing_required,
    }


def _inspect_live_exit_gate_coverage(root: Path) -> Dict[str, Any]:
    required_patterns = {
        "coinbase_executor_execute_trade_gate": (
            "coinbase_executor.py",
            (r"def\s+execute_trade\(", r"assert_live_exit_allowed\("),
        ),
        "coinbase_executor_execute_close_gate": (
            "coinbase_executor.py",
            (r"def\s+execute_close_spot_position\(", r"assert_live_exit_allowed\("),
        ),
        "strategy_engine_legacy_exit_gate": (
            "bot/strategy_engine.py",
            (r"def\s+_handle_position_action\(", r"evaluate_live_exit_allowed\(", r"live_exit_blocked_by_policy"),
        ),
        "d3_submit_central_gate": (
            "bot/phase_d3_controlled_live_exits.py",
            (r"def\s+submit_phase_d3_controlled_exit\(", r"assert_live_exit_allowed\(", r"phase_d3_controlled_live_exit"),
        ),
    }
    checks: List[Dict[str, Any]] = []
    blockers: List[str] = []
    for key, (rel, patterns) in required_patterns.items():
        missing = [pat for pat in patterns if not _pattern_found(root, (rel,), pat)]
        checks.append({
            "key": key,
            "file": rel,
            "missing_patterns": missing,
            "ready": not missing,
        })
        if missing:
            blockers.append(f"ungated_live_sell_sink:{key}")
    return {
        "checks": checks,
        "blockers": blockers,
        "ready": not blockers,
    }


def _orders_from_state(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, dict):
        orders = data.get("orders")
        if isinstance(orders, dict):
            return [dict(v) for v in orders.values() if isinstance(v, dict)]
        if isinstance(orders, list):
            return [dict(v) for v in orders if isinstance(v, dict)]
        open_orders = data.get("open_orders")
        if isinstance(open_orders, list):
            return [dict(v) for v in open_orders if isinstance(v, dict)]
    if isinstance(data, list):
        return [dict(v) for v in data if isinstance(v, dict)]
    return []


def _is_c43_entry(order: Dict[str, Any]) -> bool:
    cid = str(order.get("client_order_id") or "").lower()
    mode = str(order.get("mode") or order.get("source_mode") or "").lower()
    phase = str(order.get("phase") or "").lower()
    side = str(order.get("side") or "").upper()
    return side == "BUY" and (cid.startswith(C43_PREFIXES) or mode in {"live", "phase_c_live", "autonomous_small_live"} or "c4.3" in phase)


def _is_d3_exit(order: Dict[str, Any]) -> bool:
    cid = str(order.get("client_order_id") or "").lower()
    mode = str(order.get("mode") or order.get("source_mode") or "").lower()
    phase = str(order.get("phase") or "").lower()
    side = str(order.get("side") or "").upper()
    return side == "SELL" and (cid.startswith(D3_EXIT_PREFIX) or "d3" in phase or mode == "phase_d3_live_exit")


def _position_index(root: Path) -> Dict[str, Dict[str, Any]]:
    data = _load_json(root / "state/positions.json")
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(data, dict):
        return out
    for value in data.values():
        if not isinstance(value, dict):
            continue
        for key in (
            value.get("order_id"),
            value.get("client_order_id"),
            value.get("source_order_id"),
            value.get("phase_c43_client_order_id"),
            value.get("phase_c43_exchange_order_id"),
        ):
            text = str(key or "").strip()
            if text:
                out[text] = value
    return out


def _filled_c43_has_position(order: Dict[str, Any], position_index: Dict[str, Dict[str, Any]]) -> bool:
    if order.get("position_created"):
        return True
    for key in (
        order.get("client_order_id"),
        order.get("exchange_order_id"),
        order.get("order_id"),
        order.get("linked_position_id"),
        order.get("position_id"),
    ):
        text = str(key or "").strip()
        if text and text in position_index:
            return True
    return False


def _inspect_order_store(root: Path, path: Path) -> Dict[str, Any]:
    data = _load_json(path)
    orders = _orders_from_state(data)
    position_index = _position_index(root)
    by_status = Counter(str(o.get("status") or "unknown").lower() for o in orders)
    open_orders = [o for o in orders if str(o.get("status") or "").lower() in OPEN_ORDER_STATUSES]
    c43_open = [o for o in open_orders if _is_c43_entry(o)]
    d3_open = [o for o in open_orders if _is_d3_exit(o)]
    cancelled_c43 = [o for o in orders if _is_c43_entry(o) and str(o.get("status") or "").lower() in {"cancelled", "canceled"}]
    filled_c43 = [o for o in orders if _is_c43_entry(o) and str(o.get("status") or "").lower() == "filled"]
    warnings: List[str] = []
    blockers: List[str] = []
    if c43_open:
        warnings.append(f"open_c43_entry_orders:{len(c43_open)}")
    if d3_open:
        warnings.append(f"open_d3_exit_orders:{len(d3_open)}")
    # A filled C.4.3 entry is coherent when a position links through any canonical
    # order/position id. Older fills may not have order.position_created=True yet.
    for order in filled_c43:
        if not _filled_c43_has_position(order, position_index):
            warnings.append(f"filled_c43_without_position_created:{order.get('client_order_id')}")
    return {
        "path": str(path),
        "exists": path.exists(),
        "total_records": len(orders),
        "by_status": dict(by_status),
        "total_open_orders": len(open_orders),
        "open_c43_entry_orders": len(c43_open),
        "open_d3_exit_orders": len(d3_open),
        "cancelled_c43_records": len(cancelled_c43),
        "filled_c43_records": len(filled_c43),
        "sample_open_orders": [{"client_order_id": o.get("client_order_id"), "ticker": o.get("ticker"), "side": o.get("side"), "status": o.get("status")} for o in open_orders[:10]],
        "warnings": warnings,
        "blockers": blockers,
        "ready": not blockers,
    }


def _inspect_logs(root: Path, window_minutes: int = 240) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    since = now - timedelta(minutes=window_minutes)
    llm_corrupt = _iter_jsonl(root / "logs/llm_corrupt.jsonl")
    provider_errors = _iter_jsonl(root / "logs/llm_provider_errors.jsonl")
    order_events = _iter_jsonl(root / "logs/order_events.jsonl")
    phase_c_submit = _iter_jsonl(root / "logs/phase_c_live_submit.jsonl")

    def recent(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        out = []
        for row in rows:
            dt = _parse_ts(row.get("generated_at") or row.get("timestamp") or row.get("time"))
            if dt and dt >= since:
                out.append(row)
        return out

    recent_corrupt = recent(llm_corrupt)
    recent_provider = recent(provider_errors)
    live_submits = [r for r in phase_c_submit + order_events if str(r).find("live_order_submitted") >= 0 or str(r.get("event_type") or "").find("live_entry_order_submitted") >= 0]
    manual_cancels = [r for r in order_events if str(r.get("event_type") or "") == "phase_c43_live_entry_order_manually_cancelled"]
    return {
        "window_minutes": window_minutes,
        "since": since.isoformat(),
        "llm_corrupt_recent": len(recent_corrupt),
        "provider_errors_recent": len(recent_provider),
        "order_events_rows_sampled": len(order_events),
        "phase_c_submit_rows_sampled": len(phase_c_submit),
        "manual_c43_cancel_events": len(manual_cancels),
        "live_submit_related_rows_sampled": len(live_submits),
        "recent_corrupt_sample": [{k: row.get(k) for k in ("generated_at", "ticker", "stage", "model", "error", "error_type")} for row in recent_corrupt[:5]],
        "recent_provider_error_sample": [{k: row.get(k) for k in ("generated_at", "ticker", "stage", "provider", "error", "error_type")} for row in recent_provider[:5]],
        "ready": len(recent_corrupt) == 0 and len(recent_provider) == 0,
        "warnings": ([f"recent_llm_corrupt_outputs:{len(recent_corrupt)}"] if recent_corrupt else []) + ([f"recent_provider_errors:{len(recent_provider)}"] if recent_provider else []),
    }


def _tests_overview(root: Path) -> Dict[str, Any]:
    tests = sorted(str(p.relative_to(root)) for p in (root / "tests").glob("test_*.py")) if (root / "tests").exists() else []
    key_groups = {
        "c43": [t for t in tests if "phase_c43" in t],
        "d3": [t for t in tests if "phase_d3" in t or "phase_d31" in t or "phase_d32" in t],
        "learning": [t for t in tests if "reflection" in t or "outcome" in t or "no_fill" in t],
        "planner_patterns": [t for t in tests if "planner" in t or "pattern" in t or "pending_trade_plan" in t],
    }
    return {"total_test_files": len(tests), "key_groups": key_groups}


def build_audit_report(root: Path, *, env_path: Optional[Path] = None, order_store_path: Optional[Path] = None, window_minutes: int = 240) -> Dict[str, Any]:
    root = root.resolve()
    env_path = env_path or root / ".env"
    order_store_path = order_store_path or root / "state/open_orders.json"
    env = _env_parse(env_path)
    env_safety = _check_env_safety(env)
    static = _evaluate_static_checks(root)
    live_exit_gate_coverage = _inspect_live_exit_gate_coverage(root)
    orders = _inspect_order_store(root, order_store_path)
    logs = _inspect_logs(root, window_minutes=window_minutes)
    tests = _tests_overview(root)

    blockers: List[str] = []
    warnings: List[str] = []
    if not env_safety["ready"]:
        blockers.extend(env_safety["blockers"])
    blockers.extend(live_exit_gate_coverage["blockers"])
    # Static missing required modules is a warning rather than blocker for runtime safety, but a blocker for preservation.
    preservation_blockers = list(static["missing_required"])
    warnings.extend(env_safety["warnings"])
    warnings.extend(orders["warnings"])
    warnings.extend(logs["warnings"])

    overall_status = "ok_observe_only" if not blockers and not preservation_blockers else "review_required"
    if blockers:
        overall_status = "safety_blocked"
    elif preservation_blockers:
        overall_status = "preservation_review_required"

    return {
        "generated_at": _now_iso(),
        "tool": "show_function_preservation_audit",
        "version": "2026-05-18.lifecycle-service-hook-v3",
        "root": str(root),
        "safety_policy": {
            "read_only": True,
            "does_not_call_coinbase": True,
            "does_not_call_llm": True,
            "does_not_submit_orders": True,
            "does_not_cancel_orders": True,
            "does_not_modify_files": True,
        },
        "overall_status": overall_status,
        "blockers": blockers,
        "preservation_blockers": preservation_blockers,
        "warnings": warnings,
        "env_safety": env_safety,
        "static_function_preservation": static,
        "live_exit_gate_coverage": live_exit_gate_coverage,
        "order_store": orders,
        "logs": logs,
        "tests_overview": tests,
        "next_steps": _next_steps(overall_status, env_safety, static, orders, logs),
    }


def _next_steps(overall_status: str, env_safety: Dict[str, Any], static: Dict[str, Any], orders: Dict[str, Any], logs: Dict[str, Any]) -> List[str]:
    steps: List[str] = []
    if env_safety.get("blockers"):
        steps.append("Fix .env safety flags before restarting or arming live submit.")
    if static.get("missing_required"):
        steps.append("Review missing required modules/patterns; do not proceed with D.3.3/D.4 patches until preservation blockers are understood.")
    if orders.get("open_c43_entry_orders"):
        steps.append("Reconcile open C.4.3 entry orders before placing any new order.")
    if orders.get("open_d3_exit_orders"):
        steps.append("Review open D.3 exit orders; live SELL/exits must remain disabled unless separately armed.")
    if logs.get("llm_corrupt_recent") or logs.get("provider_errors_recent"):
        steps.append("Inspect recent LLM/provider errors before live-entry arming.")
    if not steps:
        steps.append("Observe-only state looks coherent. Run py_compile/pytest and monitor service logs before any controlled live arming.")
    return steps


def _print_human(report: Dict[str, Any]) -> None:
    print("Function preservation audit")
    print("===========================")
    print(f"Generated: {report['generated_at']}")
    print(f"Root:      {report['root']}")
    print(f"Status:    {report['overall_status']}")
    print()
    print("Safety flags:")
    for key, item in report["env_safety"]["flags"].items():
        value = item.get("value")
        ok = item.get("ok")
        line = item.get("line")
        marker = "OK" if ok else "REVIEW"
        print(f"  {marker:6} {key}={value!s} (line {line})")
    print()
    print("Static preservation by category:")
    for cat, data in sorted(report["static_function_preservation"]["summary_by_category"].items()):
        print(f"  {cat:18} present={data['present']}/{data['total']} partial={data['partial']} missing_required={data['missing_required']} tests_present={data['tests_present']}")
    print()
    order_store = report["order_store"]
    print("Order store:")
    print(f"  total_records={order_store['total_records']} total_open_orders={order_store['total_open_orders']} open_c43_entry={order_store['open_c43_entry_orders']} open_d3_exit={order_store['open_d3_exit_orders']} cancelled_c43={order_store['cancelled_c43_records']}")
    print()
    logs = report["logs"]
    print("Recent log health:")
    print(f"  window_minutes={logs['window_minutes']} llm_corrupt_recent={logs['llm_corrupt_recent']} provider_errors_recent={logs['provider_errors_recent']} manual_c43_cancel_events={logs['manual_c43_cancel_events']}")
    if report["blockers"]:
        print("\nSafety blockers:")
        for b in report["blockers"]:
            print(f"  - {b}")
    if report["preservation_blockers"]:
        print("\nPreservation blockers:")
        for b in report["preservation_blockers"]:
            print(f"  - {b}")
    if report["warnings"]:
        print("\nWarnings:")
        for w in report["warnings"][:30]:
            print(f"  - {w}")
    print("\nNext steps:")
    for step in report["next_steps"]:
        print(f"  - {step}")


def main() -> int:
    p = argparse.ArgumentParser(description="Read-only function-preservation and safety audit for the Coinbase spot LLM tradingbot.")
    p.add_argument("--root", default=None, help="Project root. Defaults to parent of tools/ or current directory.")
    p.add_argument("--env-path", default=None, help="Path to .env. Defaults to <root>/.env")
    p.add_argument("--order-store", default=None, help="Path to open_orders.json. Defaults to <root>/state/open_orders.json")
    p.add_argument("--window-minutes", type=int, default=240, help="Recent LLM/provider log window.")
    p.add_argument("--json", action="store_true", help="Print full JSON report.")
    p.add_argument("--fail-on-review", action="store_true", help="Exit non-zero if safety or preservation review is required.")
    args = p.parse_args()

    root = Path(args.root).resolve() if args.root else _project_root().resolve()
    env_path = Path(args.env_path).resolve() if args.env_path else root / ".env"
    order_store = Path(args.order_store).resolve() if args.order_store else root / "state/open_orders.json"
    report = build_audit_report(root, env_path=env_path, order_store_path=order_store, window_minutes=args.window_minutes)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    else:
        _print_human(report)

    if args.fail_on_review and report.get("overall_status") != "ok_observe_only":
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
