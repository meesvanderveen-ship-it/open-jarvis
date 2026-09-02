#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.config import BotConfig, configured_ticker_universe, effective_phase_c_allowed_tickers
from bot.atomic_io import atomic_write_json, process_lock
from bot.credential_status import READY, collect_checks, overall_state
from bot.phase_c_live_guard import LIVE_ENTRY_GUARD_VERSION, LIVE_ENTRY_REQUIRED_GATES
from bot.pre_live_startup_gate import assess_pre_live_startup_gate, enforce_pre_live_startup_gate
from bot.resilience import RetryPolicy, describe_failure, is_transient, policies_snapshot
from bot.product_rules import PRODUCT_RULE_NORMALIZER_VERSION
from bot.run_cycle_guard import CycleBoundaryGuard
from bot.phase_live_tiny_btc_preflight import ACTUAL_SUBMIT_ACK, PROVEN_PRODUCT

try:
    from bot.phase_c43_lifecycle_service import build_phase_c43_lifecycle_service_report
except Exception:  # pragma: no cover - service hook must never block bot startup
    build_phase_c43_lifecycle_service_report = None  # type: ignore

try:
    from replication.publisher import ReplicaPublisher
except Exception:  # pragma: no cover
    ReplicaPublisher = None  # type: ignore


LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)
StrategyEngine = None


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(LOGS_DIR / "loop.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)


def _safe_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        return float(value)
    except Exception:
        return default


def _short_text(value: Any, limit: int = 220) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _write_jsonl(filename: str, payload: Dict[str, Any]) -> None:
    path = LOGS_DIR / filename
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _env_bool(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _env_present(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def _runtime_ticker_source() -> str:
    if _env_present("ALLOWED_TICKERS"):
        return "env:ALLOWED_TICKERS -> BotConfig.allowed_tickers"
    return "BotConfig.allowed_tickers default"


def _build_tiny_runtime_startup_diagnostic(cfg: BotConfig) -> Dict[str, Any]:
    ack_value = os.getenv("BTC_USDC_TINY_ACTUAL_SUBMIT_ACK", "").strip()
    ack_present = bool(ack_value)
    ack_exact = ack_value == ACTUAL_SUBMIT_ACK
    wrapper_mode_active = _env_bool("BTC_USDC_TINY_WRAPPER_MODE")
    tiny_mode_active = wrapper_mode_active or ack_present
    effective_tickers = list(getattr(cfg, "allowed_tickers", []) or [])
    phase_c_tickers = list(getattr(cfg, "phase_c_allowed_tickers", []) or [])
    configured_universe = configured_ticker_universe(cfg)
    effective_phase_c = effective_phase_c_allowed_tickers(cfg)

    mismatch_reasons: List[str] = []
    if tiny_mode_active and effective_tickers != [PROVEN_PRODUCT]:
        mismatch_reasons.append("effective_runtime_tickers_not_exact_btc_usdc")
    if tiny_mode_active and phase_c_tickers != [PROVEN_PRODUCT]:
        mismatch_reasons.append("phase_c_allowed_tickers_not_exact_btc_usdc")
    if ack_present and not ack_exact:
        mismatch_reasons.append("tiny_actual_submit_ack_invalid")

    return {
        "phase": "run_trader_loop_tiny_runtime_startup_guard_v1",
        "effective_runtime_tickers": effective_tickers,
        "phase_c_allowed_tickers": phase_c_tickers,
        "configured_ticker_universe": configured_universe,
        "effective_phase_c_allowed_tickers": effective_phase_c,
        "ticker_source": _runtime_ticker_source(),
        "env_sources": {
            "ALLOWED_TICKERS": os.getenv("ALLOWED_TICKERS", ""),
            "PHASE_C_ALLOWED_TICKERS": os.getenv("PHASE_C_ALLOWED_TICKERS", ""),
            "BOT_CONFIG_SKIP_DOTENV": os.getenv("BOT_CONFIG_SKIP_DOTENV", ""),
            "BTC_USDC_TINY_WRAPPER_MODE": os.getenv("BTC_USDC_TINY_WRAPPER_MODE", ""),
            "BTC_USDC_TINY_ACTUAL_SUBMIT_ACK_present": ack_present,
            "BTC_USDC_TINY_ACTUAL_SUBMIT_ACK_exact": ack_exact,
        },
        "tiny_mode_active": tiny_mode_active,
        "ack_present": ack_present,
        "ack_exact": ack_exact,
        "fail_closed": bool(mismatch_reasons),
        "fail_closed_reason": ",".join(mismatch_reasons),
        "no_cycle_started": True,
        "no_llm_call": True,
        "no_coinbase_call": True,
        "state_write_performed": False,
    }


def _build_full_workflow_runtime_diagnostic(cfg: BotConfig) -> Dict[str, Any]:
    enabled = bool(getattr(cfg, "enable_full_workflow_live_mode", False))
    replication_enabled = _env_bool("REPLICATION_ENABLED")
    market_orders_enabled = (
        _env_bool("MARKET_ORDER_ENABLED")
        or _env_bool("ENABLE_MARKET_ORDERS")
        or _env_bool("ALLOW_MARKET_ORDERS")
    )
    learning_to_execution_enabled = (
        _env_bool("LEARNING_TO_EXECUTION_READY")
        or _env_bool("LEARNING_TO_EXECUTION_ALLOWED")
        or _env_bool("LIVE_LEARNING_ALLOWED")
    )
    return {
        "phase": "run_trader_loop_full_workflow_live_mode_bridge_v1",
        "enabled": enabled,
        "replication_enabled": replication_enabled,
        "replication_publish_allowed": False,
        "follower_lifecycle_enabled": False,
        "service_entrypoint": "run_trader_loop.py",
        "host_env_source": "BotConfig loads project .env unless BOT_CONFIG_SKIP_DOTENV=true",
        "strategy_engine_cycle_reachable": True,
        "configured_ticker_universe": configured_ticker_universe(cfg),
        "effective_phase_c_allowed_tickers": effective_phase_c_allowed_tickers(cfg),
        "phase_c43_entry_submitter_reachable": bool(getattr(cfg, "enable_phase_c43_autonomous_entry_submitter", True)),
        "lifecycle_hook_reachable": build_phase_c43_lifecycle_service_report is not None
        and bool(getattr(cfg, "enable_phase_c43_lifecycle_orchestrator", True)),
        "workflow_lane": "full_workflow_live" if enabled else "legacy_4h_cycle_with_lifecycle_hook",
        "caps": {
            "max_open_positions": getattr(cfg, "max_open_positions", None),
            "autonomous_max_open_orders": getattr(cfg, "autonomous_max_open_orders", None),
            "phase_c_max_open_entry_orders": getattr(cfg, "phase_c_max_open_entry_orders", None),
            "max_new_orders_per_cycle": getattr(cfg, "max_new_orders_per_cycle", None),
            "autonomous_max_new_orders_per_cycle": getattr(cfg, "autonomous_max_new_orders_per_cycle", None),
            "phase_c_max_new_orders_per_cycle": getattr(cfg, "phase_c_max_new_orders_per_cycle", None),
            "default_quote_size_usdc": str(getattr(cfg, "default_quote_size_usdc", "")),
            "max_notional_usd": str(getattr(cfg, "max_notional_usd", "")),
            "phase_c_max_order_quote": str(getattr(cfg, "phase_c_max_order_quote", "")),
            "autonomous_max_order_quote": str(getattr(cfg, "autonomous_max_order_quote", "")),
        },
        "live_flags": {
            "execution_mode": getattr(cfg, "execution_mode", ""),
            "enable_live_entry_orders": bool(getattr(cfg, "enable_live_entry_orders", False)),
            "enable_live_limit_orders": bool(getattr(cfg, "enable_live_limit_orders", False)),
            "enable_phase_c_live_small_limit_orders": bool(getattr(cfg, "enable_phase_c_live_small_limit_orders", False)),
            "enable_phase_c_actual_coinbase_submit": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
            "enable_live_exit_orders": bool(getattr(cfg, "enable_live_exit_orders", False)),
            "autonomous_allow_exits": bool(getattr(cfg, "autonomous_allow_exits", False)),
            "enable_phase_d3_actual_exit_submit": bool(getattr(cfg, "enable_phase_d3_actual_exit_submit", False)),
            "phase_c43_lifecycle_allow_coinbase_poll": bool(getattr(cfg, "phase_c43_lifecycle_allow_coinbase_poll", False)),
            "phase_c43_lifecycle_apply_local": bool(getattr(cfg, "phase_c43_lifecycle_apply_local", False)),
            "phase_c43_lifecycle_build_d2_plan": bool(getattr(cfg, "phase_c43_lifecycle_build_d2_plan", False)),
            "phase_c43_lifecycle_build_d3_preview": bool(getattr(cfg, "phase_c43_lifecycle_build_d3_preview", False)),
        },
        "forbidden_flags": {
            "replication_enabled": replication_enabled,
            "market_order_enabled": _env_bool("MARKET_ORDER_ENABLED"),
            "enable_market_orders": _env_bool("ENABLE_MARKET_ORDERS"),
            "allow_market_orders": _env_bool("ALLOW_MARKET_ORDERS"),
            "learning_to_execution_ready": _env_bool("LEARNING_TO_EXECUTION_READY"),
            "learning_to_execution_allowed": _env_bool("LEARNING_TO_EXECUTION_ALLOWED"),
            "live_learning_allowed": _env_bool("LIVE_LEARNING_ALLOWED"),
            "parameter_change_allowed": _env_bool("PARAMETER_CHANGE_ALLOWED"),
        },
        "safety_policy": {
            "uses_strategy_engine_for_entries": True,
            "uses_phase_c43_guard_and_submitter": True,
            "uses_lifecycle_hook_for_fill_apply_d2_d3": True,
            "does_not_bypass_judge_risk_or_phase_c": True,
            "does_not_bypass_d3_reduce_only_guards": True,
            "market_orders_disabled": not market_orders_enabled,
            "replication_disabled": not replication_enabled,
            "replication_publish_allowed": False,
            "follower_lifecycle_enabled": False,
            "learning_to_execution_disabled": not learning_to_execution_enabled,
            "parameter_mutation_disabled": not _env_bool("PARAMETER_CHANGE_ALLOWED"),
        },
    }


def _build_runtime_guard_version_context(cfg: BotConfig, *, source: str) -> Dict[str, Any]:
    return {
        "generated_at": _utc_now().isoformat(),
        "phase": "runtime_guard_version_context_v1",
        "source": source,
        "LIVE_ENTRY_GUARD_VERSION": LIVE_ENTRY_GUARD_VERSION,
        "PRODUCT_RULE_NORMALIZER_VERSION": PRODUCT_RULE_NORMALIZER_VERSION,
        "APPROVED_PROFILE_EFFECTIVE_DEFAULT_QUOTE": str(getattr(cfg, "default_quote_size_usdc", "50.00")),
        "LIVE_ENTRY_REQUIRED_GATES": ",".join(LIVE_ENTRY_REQUIRED_GATES),
        "live_entry_guard_version": LIVE_ENTRY_GUARD_VERSION,
        "product_rule_normalizer_version": PRODUCT_RULE_NORMALIZER_VERSION,
        "approved_profile_effective_default_quote": str(getattr(cfg, "default_quote_size_usdc", "50.00")),
        "live_entry_required_gates": list(LIVE_ENTRY_REQUIRED_GATES),
        "safety_policy": {
            "startup_and_full_cycle_runtime_proof": True,
            "wait_preview_valid_plan_false_block_version": True,
        },
    }


def _log_runtime_guard_version_context(cfg: BotConfig, *, source: str) -> Dict[str, Any]:
    context = _build_runtime_guard_version_context(cfg, source=source)
    logging.info(
        "LIVE_ENTRY_GUARD_VERSION=%s | PRODUCT_RULE_NORMALIZER_VERSION=%s | "
        "APPROVED_PROFILE_EFFECTIVE_DEFAULT_QUOTE=%s | LIVE_ENTRY_REQUIRED_GATES=%s",
        context["LIVE_ENTRY_GUARD_VERSION"],
        context["PRODUCT_RULE_NORMALIZER_VERSION"],
        context["APPROVED_PROFILE_EFFECTIVE_DEFAULT_QUOTE"],
        context["LIVE_ENTRY_REQUIRED_GATES"],
    )
    _write_jsonl("runtime_guard_version.jsonl", context)
    return context


def _log_tiny_runtime_startup_diagnostic(diagnostic: Dict[str, Any]) -> None:
    logging.info(
        "Tiny runtime diagnostic | effective_runtime_tickers=%s | phase_c_allowed_tickers=%s | "
        "ticker_source=%s | tiny_mode_active=%s | ack_present=%s | ack_exact=%s",
        ",".join(diagnostic["effective_runtime_tickers"]),
        ",".join(diagnostic["phase_c_allowed_tickers"]),
        diagnostic["ticker_source"],
        diagnostic["tiny_mode_active"],
        diagnostic["ack_present"],
        diagnostic["ack_exact"],
    )
    if diagnostic["fail_closed"]:
        logging.error(
            "Tiny runtime fail-closed | reason=%s | env_sources=%s",
            diagnostic["fail_closed_reason"],
            json.dumps(diagnostic["env_sources"], sort_keys=True),
        )


def _enforce_tiny_runtime_startup_guard(cfg: BotConfig) -> Dict[str, Any]:
    diagnostic = _build_tiny_runtime_startup_diagnostic(cfg)
    _log_tiny_runtime_startup_diagnostic(diagnostic)
    if diagnostic["fail_closed"]:
        raise SystemExit(2)
    return diagnostic


def _write_runtime_ticker_universe_state(cfg: BotConfig) -> None:
    """Write the current process' ticker universe to a small state file.

    The dashboard backend deliberately never imports bot.config or reads
    .env (see dashboard/backend/config.py), so this is the one safe,
    no-secrets channel for it to learn which tickers this run of the bot
    actually follows -- used to hide stale tickers (e.g. from a previously
    larger ALLOWED_TICKERS list) out of positions/opportunities/thesis views.
    """
    payload = {
        "generated_at": _utc_now().isoformat(),
        "allowed_tickers": list(getattr(cfg, "allowed_tickers", []) or []),
        "phase_c_allowed_tickers": list(getattr(cfg, "phase_c_allowed_tickers", []) or []),
        "configured_ticker_universe": configured_ticker_universe(cfg),
    }
    atomic_write_json("state/runtime_ticker_universe.json", payload)


def _log_full_workflow_runtime_diagnostic(diagnostic: Dict[str, Any]) -> None:
    if not diagnostic.get("enabled"):
        logging.info(
            "Full workflow live bridge disabled | workflow_lane=%s",
            diagnostic.get("workflow_lane"),
        )
        return
    caps = _safe_dict(diagnostic.get("caps"))
    flags = _safe_dict(diagnostic.get("live_flags"))
    logging.info(
        "Full workflow live bridge enabled | entries=%s | exits=%s/%s/%s | max_open_orders=%s | max_positions=%s | max_quote=%s | lifecycle_poll_apply=%s/%s | d2_d3=%s/%s",
        flags.get("enable_phase_c_actual_coinbase_submit"),
        flags.get("enable_live_exit_orders"),
        flags.get("autonomous_allow_exits"),
        flags.get("enable_phase_d3_actual_exit_submit"),
        caps.get("autonomous_max_open_orders"),
        caps.get("max_open_positions"),
        caps.get("phase_c_max_order_quote"),
        flags.get("phase_c43_lifecycle_allow_coinbase_poll"),
        flags.get("phase_c43_lifecycle_apply_local"),
        flags.get("phase_c43_lifecycle_build_d2_plan"),
        flags.get("phase_c43_lifecycle_build_d3_preview"),
    )


def _is_full_cycle_boundary(now_utc: datetime, interval_hours: int) -> bool:
    return (now_utc.minute == 0) and (now_utc.hour % interval_hours == 0)


def _sleep_until_next_hour_boundary() -> None:
    now = _utc_now()
    next_hour = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    sleep_seconds = max(1.0, (next_hour - now).total_seconds())
    logging.info(
        "Waiting until next hour boundary at %s UTC (%.0f sec).",
        next_hour.isoformat(),
        sleep_seconds,
    )
    time.sleep(sleep_seconds)


def _extract_result_fields(res: Dict[str, Any]) -> Dict[str, Any]:
    ticker = res.get("ticker", "Unknown")

    analysis = _safe_dict(res.get("analysis"))
    execution = _safe_dict(res.get("execution"))
    position_execution = _safe_dict(res.get("position_execution"))
    entry_gate = _safe_dict(res.get("entry_gate"))
    synthesis = _safe_dict(res.get("synthesis"))

    nested_position_execution = _safe_dict(execution.get("position_execution")) if execution else {}
    active_exec = nested_position_execution or execution or position_execution

    decision = analysis.get("decision", "unknown")
    confidence = analysis.get("confidence", 0)
    strategy = analysis.get("strategy", "unknown")
    side = analysis.get("side", "NONE")
    size_quote = analysis.get("size_quote", 0)

    action = str(_safe_dict(active_exec.get("position_action")).get("action", "")).strip().lower()
    if action == "close":
        decision = "close_position"
        side = "SELL"
        size_quote = _safe_dict(active_exec.get("position_action")).get("size_quote", size_quote)
    elif action == "reduce":
        decision = "reduce_size"
        side = "SELL"
        size_quote = _safe_dict(active_exec.get("position_action")).get("size_quote", size_quote)

    execution_status = active_exec.get("status", "unknown")
    executed = active_exec.get("executed", False)

    setup_type = (
        entry_gate.get("setup_type")
        or analysis.get("setup_type")
        or synthesis.get("setup_type")
        or "unknown"
    )
    gate_decision = entry_gate.get("decision", "n/a")
    gate_priority = entry_gate.get("priority", "n/a")

    return {
        "ticker": ticker,
        "decision": decision,
        "confidence": confidence,
        "strategy": strategy,
        "side": side,
        "size_quote": size_quote,
        "execution_status": execution_status,
        "executed": executed,
        "setup_type": setup_type,
        "gate_decision": gate_decision,
        "gate_priority": gate_priority,
        "analysis": analysis,
        "entry_gate": entry_gate,
        "active_exec": active_exec,
        "deepseek_pack": _safe_dict(res.get("deepseek_pack")),
        "regime": _safe_dict(res.get("regime")),
        "trend": _safe_dict(res.get("trend")),
        "breakout": _safe_dict(res.get("breakout")),
        "meanrev": _safe_dict(res.get("meanrev")),
        "bull": _safe_dict(res.get("bull")),
        "bear": _safe_dict(res.get("bear")),
        "synth": _safe_dict(res.get("synth")),
        "heartbeat": _safe_dict(res.get("heartbeat")),
        "position_watch": _safe_dict(res.get("position_watch")),
        "risk_context": _safe_dict(res.get("risk_context")),
        "position_context": _safe_dict(res.get("position_context")),
        "status": res.get("status", ""),
        "raw_result": res,
    }


def _count_fallbacks(row: Dict[str, Any]) -> int:
    count = 0

    if row["deepseek_pack"].get("fallback"):
        count += 1

    for key in ("regime", "trend", "breakout", "meanrev", "bull", "bear", "synth"):
        if _safe_dict(row.get(key)).get("fallback"):
            count += 1

    return count


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _log_result_details(row: Dict[str, Any]) -> None:
    logging.info(
        "Ticker %s | gate=%s/%s | decision=%s | side=%s | size_quote=%s | confidence=%s | "
        "strategy=%s | setup_type=%s | execution_status=%s | executed=%s",
        row["ticker"],
        row["gate_decision"],
        row["gate_priority"],
        row["decision"],
        row["side"],
        row["size_quote"],
        row["confidence"],
        row["strategy"],
        row["setup_type"],
        row["execution_status"],
        row["executed"],
    )

    gate_reasons = _safe_list(row["entry_gate"].get("reasons"))
    if gate_reasons:
        logging.info(
            "Ticker %s | gate_reasons=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in gate_reasons[:3]),
        )

    judge_reasons = _safe_list(row["analysis"].get("reasons"))
    if judge_reasons:
        logging.info(
            "Ticker %s | judge_reasons=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in judge_reasons[:4]),
        )

    gate_warnings = _safe_list(row["entry_gate"].get("warnings"))
    if gate_warnings:
        logging.warning(
            "Ticker %s | gate_warnings=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in gate_warnings[:3]),
        )

    must_reject_if = _safe_list(row["analysis"].get("must_reject_if"))
    if must_reject_if:
        logging.info(
            "Ticker %s | must_reject_if=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in must_reject_if[:3]),
        )

    exec_reason = row["active_exec"].get("reason") or row["active_exec"].get("details")
    if exec_reason:
        logging.info(
            "Ticker %s | execution_note=%s",
            row["ticker"],
            _short_text(exec_reason, 180),
        )

    trade_plan = _safe_dict(row["raw_result"].get("trade_plan") or row["analysis"].get("trade_plan"))
    orderbook_preview = _safe_dict(
        row["active_exec"].get("orderbook_entry_preview")
        or row["analysis"].get("orderbook_entry_preview")
        or _safe_dict(row["raw_result"].get("phase_c43_live_entry")).get("orderbook_entry_preview")
    )
    phase_c43 = _safe_dict(row["raw_result"].get("phase_c43_live_entry") or row["analysis"].get("phase_c43_live_entry"))
    dynamic_sizing = _safe_dict(
        phase_c43.get("dynamic_entry_sizing")
        or _safe_dict(phase_c43.get("risk_snapshot")).get("dynamic_entry_sizing")
        or row["analysis"].get("dynamic_entry_sizing")
    )
    if trade_plan or orderbook_preview or phase_c43:
        logging.info(
            "Ticker %s | plan_action=%s | valid_trade_plan=%s | orderbook_entry_candidate=%s | "
            "resting_entry_eligible=%s | prepare_resting_limit_entry=%s | live_submit_attempted=%s | "
            "live_order_submitted=%s",
            row["ticker"],
            trade_plan.get("plan_action", row["analysis"].get("plan_action", "n/a")),
            trade_plan.get("valid_trade_plan", row["analysis"].get("valid_trade_plan", False)),
            _truthy(row["active_exec"].get("orderbook_entry_candidate") or orderbook_preview.get("orderbook_entry_candidate")),
            _truthy(row["active_exec"].get("resting_entry_eligible") or orderbook_preview.get("eligible")),
            str(trade_plan.get("plan_action") or row["active_exec"].get("plan_action") or "").lower()
            in {"prepare_resting_limit_entry", "prepare_retest_limit_entry", "prepare_reclaim_retest_limit_entry", "prepare_breakout_retest_limit_entry"},
            _truthy(phase_c43.get("live_submission_attempted") or row["active_exec"].get("live_submission_attempted")),
            _truthy(phase_c43.get("live_order_submitted") or row["active_exec"].get("live_order_submitted")),
        )
    if dynamic_sizing:
        logging.info(
            "Ticker %s | dynamic_entry_quote=%s | dynamic_entry_range=%s-%s | sizing_reason=%s",
            row["ticker"],
            dynamic_sizing.get("clamped_quote"),
            dynamic_sizing.get("min_quote"),
            dynamic_sizing.get("max_quote"),
            _short_text(dynamic_sizing.get("final_reason"), 220),
        )

    fallback_notes: List[str] = []

    if row["deepseek_pack"].get("fallback"):
        fallback_notes.append(
            f"deepseek_preprocess={_short_text(row['deepseek_pack'].get('fallback_reason', 'unknown'), 120)}"
        )

    for key in ("regime", "trend", "breakout", "meanrev", "bull", "bear", "synth"):
        payload = _safe_dict(row.get(key))
        if payload.get("fallback"):
            fallback_notes.append(
                f"{key}={_short_text(payload.get('fallback_reason', 'unknown'), 120)}"
            )

    if fallback_notes:
        logging.warning(
            "Ticker %s | module_fallbacks=%s",
            row["ticker"],
            " | ".join(fallback_notes[:6]),
        )


def _extract_heartbeat_fields(res: Dict[str, Any]) -> Dict[str, Any]:
    ticker = res.get("ticker", "Unknown")
    heartbeat = _safe_dict(res.get("heartbeat"))
    position_watch = _safe_dict(res.get("position_watch"))
    status = str(res.get("status", "unknown"))

    return {
        "ticker": ticker,
        "status": status,
        "heartbeat_decision": heartbeat.get("decision", "unknown"),
        "heartbeat_reasons": _safe_list(heartbeat.get("reasons")),
        "position_watch_decision": position_watch.get("decision", "n/a"),
        "position_watch_reasons": _safe_list(position_watch.get("reasons")),
        "position_watch_warnings": _safe_list(position_watch.get("warnings")),
        "execution": _safe_dict(res.get("execution")),
        "position_execution": _safe_dict(res.get("position_execution")),
        "heartbeat": heartbeat,
        "position_watch": position_watch,
        "raw_result": res,
    }


def _resolve_management_decision(execution: Dict[str, Any]) -> str:
    if not execution:
        return "hold"

    position_action = _safe_dict(execution.get("position_action"))
    action = str(position_action.get("action", "")).strip().lower()
    if action == "close":
        return "close_position"
    if action == "reduce":
        return "reduce_size"

    status = str(execution.get("status", "")).strip().lower()
    if status in {
        "live_position_exit",
        "paper_position_exit",
        "position_closed_locally_dust_below_min_notional",
        "position_closed_locally_tiny_sell_size",
        "position_closed_locally_unexecutable_tiny_residual",
        "position_synced_no_live_base",
    }:
        return "close_position"

    reason = str(execution.get("reason", "")).strip().lower()
    if "close" in reason:
        return "close_position"
    if "reduce" in reason:
        return "reduce_size"

    return "hold"


def _log_heartbeat_result_details(row: Dict[str, Any]) -> None:
    logging.info(
        "Heartbeat | ticker=%s | status=%s | heartbeat_decision=%s | position_watch=%s",
        row["ticker"],
        row["status"],
        row["heartbeat_decision"],
        row["position_watch_decision"],
    )

    if row["heartbeat_reasons"]:
        logging.info(
            "Heartbeat | ticker=%s | reasons=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in row["heartbeat_reasons"][:4]),
        )

    if row["position_watch_reasons"]:
        logging.info(
            "Heartbeat | ticker=%s | deepseek_reasons=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in row["position_watch_reasons"][:4]),
        )

    if row["position_watch_warnings"]:
        logging.warning(
            "Heartbeat | ticker=%s | deepseek_warnings=%s",
            row["ticker"],
            " | ".join(_short_text(x, 140) for x in row["position_watch_warnings"][:3]),
        )

    execution = row["execution"] if row["execution"] else row["position_execution"]
    if execution:
        logging.info(
            "Heartbeat | ticker=%s | execution_status=%s | resolved_decision=%s | executed=%s",
            row["ticker"],
            execution.get("status", "unknown"),
            _resolve_management_decision(execution),
            bool(execution.get("executed", False)),
        )


def _log_cycle_summary(results: Dict[str, Any]) -> None:
    rows = _safe_list(results.get("results"))

    total = 0
    errors = 0
    approve_trade = 0
    wait_count = 0
    reject_count = 0
    reduce_size = 0
    close_position = 0

    gate_priority = 0
    gate_analyze = 0
    gate_watch = 0
    gate_skip = 0

    executed_count = 0
    fallback_hits = 0
    valid_trade_plans = 0
    orderbook_entry_candidates = 0
    resting_entry_eligible = 0
    prepare_resting_limit_entry = 0
    live_submit_attempted = 0

    for res in rows:
        if not isinstance(res, dict):
            continue

        total += 1

        if "error" in res:
            errors += 1
            continue

        row = _extract_result_fields(res)
        trade_plan = _safe_dict(res.get("trade_plan") or row["analysis"].get("trade_plan"))
        orderbook_preview = _safe_dict(
            row["active_exec"].get("orderbook_entry_preview")
            or row["analysis"].get("orderbook_entry_preview")
            or _safe_dict(res.get("phase_c43_live_entry")).get("orderbook_entry_preview")
        )
        phase_c43 = _safe_dict(res.get("phase_c43_live_entry") or row["analysis"].get("phase_c43_live_entry"))

        gate_decision = str(row["gate_decision"]).lower()
        decision = str(row["decision"]).lower()

        if gate_decision == "priority_analyze":
            gate_priority += 1
        elif gate_decision == "analyze":
            gate_analyze += 1
        elif gate_decision == "watch":
            gate_watch += 1
        elif gate_decision == "skip":
            gate_skip += 1

        if decision == "approve_trade":
            approve_trade += 1
        elif decision == "wait":
            wait_count += 1
        elif decision == "reject":
            reject_count += 1
        elif decision == "reduce_size":
            reduce_size += 1
        elif decision == "close_position":
            close_position += 1

        if row["executed"]:
            executed_count += 1

        fallback_hits += _count_fallbacks(row)
        valid_trade_plans += int(_truthy(trade_plan.get("valid_trade_plan") or row["analysis"].get("valid_trade_plan")))
        orderbook_entry_candidates += int(
            _truthy(row["active_exec"].get("orderbook_entry_candidate") or orderbook_preview.get("orderbook_entry_candidate"))
        )
        resting_entry_eligible += int(_truthy(row["active_exec"].get("resting_entry_eligible") or orderbook_preview.get("eligible")))
        prepare_resting_limit_entry += int(
            str(trade_plan.get("plan_action") or row["active_exec"].get("plan_action") or "").lower()
            in {"prepare_resting_limit_entry", "prepare_retest_limit_entry", "prepare_reclaim_retest_limit_entry", "prepare_breakout_retest_limit_entry"}
        )
        live_submit_attempted += int(_truthy(phase_c43.get("live_submission_attempted") or row["active_exec"].get("live_submission_attempted")))

    logging.info(
        "Cycle summary | total=%s | errors=%s | approve_trade=%s | wait=%s | reject=%s | "
        "reduce_size=%s | close_position=%s | executed=%s",
        total,
        errors,
        approve_trade,
        wait_count,
        reject_count,
        reduce_size,
        close_position,
        executed_count,
    )

    logging.info(
        "Gate summary | priority_analyze=%s | analyze=%s | watch=%s | skip=%s | fallback_hits=%s",
        gate_priority,
        gate_analyze,
        gate_watch,
        gate_skip,
        fallback_hits,
    )
    logging.info(
        "Workflow visibility | valid_trade_plans=%s | orderbook_entry_candidates=%s | "
        "resting_entry_eligible=%s | prepare_resting_limit_entry=%s | live_submit_attempted=%s",
        valid_trade_plans,
        orderbook_entry_candidates,
        resting_entry_eligible,
        prepare_resting_limit_entry,
        live_submit_attempted,
    )

    _write_jsonl(
        "cycle_summary.jsonl",
        {
            "generated_at": _utc_now().isoformat(),
            "total": total,
            "errors": errors,
            "approve_trade": approve_trade,
            "wait": wait_count,
            "reject": reject_count,
            "reduce_size": reduce_size,
            "close_position": close_position,
            "executed": executed_count,
            "gate_priority_analyze": gate_priority,
            "gate_analyze": gate_analyze,
            "gate_watch": gate_watch,
            "gate_skip": gate_skip,
            "fallback_hits": fallback_hits,
            "valid_trade_plans": valid_trade_plans,
            "orderbook_entry_candidates": orderbook_entry_candidates,
            "resting_entry_eligible": resting_entry_eligible,
            "prepare_resting_limit_entry": prepare_resting_limit_entry,
            "live_submit_attempted": live_submit_attempted,
        },
    )


def _log_heartbeat_summary(results: Dict[str, Any]) -> None:
    rows = _safe_list(results.get("results"))

    total = 0
    errors = 0
    heartbeat_ok = 0
    deepseek_hold_ok = 0
    full_reviews = 0
    paused = 0
    skipped = 0
    executed_count = 0

    for res in rows:
        if not isinstance(res, dict):
            continue

        total += 1

        if "error" in res:
            errors += 1
            continue

        status = str(res.get("status", "unknown")).lower()
        if status == "heartbeat_ok":
            heartbeat_ok += 1
        elif status == "deepseek_hold_ok":
            deepseek_hold_ok += 1
        elif status in {"deepseek_escalated_full_review", "heartbeat_full_review", "risk_management_override"}:
            full_reviews += 1
        elif status == "heartbeat_paused":
            paused += 1
        elif status == "heartbeat_skipped":
            skipped += 1

        execution = _safe_dict(res.get("execution"))
        position_execution = _safe_dict(res.get("position_execution"))
        active_exec = execution if execution else position_execution
        if bool(active_exec.get("executed", False)):
            executed_count += 1

    logging.info(
        "Heartbeat summary | total=%s | errors=%s | heartbeat_ok=%s | deepseek_hold_ok=%s | "
        "full_reviews=%s | paused=%s | skipped=%s | executed=%s",
        total,
        errors,
        heartbeat_ok,
        deepseek_hold_ok,
        full_reviews,
        paused,
        skipped,
        executed_count,
    )

    _write_jsonl(
        "heartbeat_summary.jsonl",
        {
            "generated_at": _utc_now().isoformat(),
            "total": total,
            "errors": errors,
            "heartbeat_ok": heartbeat_ok,
            "deepseek_hold_ok": deepseek_hold_ok,
            "full_reviews": full_reviews,
            "paused": paused,
            "skipped": skipped,
            "executed": executed_count,
        },
    )



def _init_replica_publisher() -> Optional["ReplicaPublisher"]:
    if ReplicaPublisher is None:
        logging.warning("Replication publisher import failed; replication will be skipped.")
        return None

    try:
        publisher = ReplicaPublisher()
        logging.info(
            "Replication publisher initialized | enabled=%s",
            getattr(getattr(publisher, "config", None), "enabled", "unknown"),
        )
        return publisher
    except Exception as e:
        logging.error("Replication publisher initialization failed: %s", e, exc_info=True)
        return None


def _publish_replication_decision(
    publisher: Optional["ReplicaPublisher"],
    *,
    cycle_type: str,
    ticker: str,
    decision: str,
    side: str,
    strategy: str,
    setup_type: str,
    confidence: int,
    requested_size_quote: float,
    requested_size_base: float,
    reason_summary: List[str],
    must_reject_if: List[str],
    analysis: Dict[str, Any],
    entry_gate: Dict[str, Any],
    risk_context: Dict[str, Any],
    position_context: Dict[str, Any],
    metadata: Dict[str, Any],
    event_id: Optional[str] = None,
) -> None:
    if publisher is None:
        return

    try:
        result = publisher.publish_decision_best_effort(
            ticker=ticker,
            decision=decision,
            side=side,
            strategy=strategy,
            setup_type=setup_type,
            confidence=confidence,
            requested_size_quote=requested_size_quote,
            requested_size_base=requested_size_base,
            reason_summary=reason_summary,
            must_reject_if=must_reject_if,
            analysis=analysis,
            entry_gate=entry_gate,
            risk_context=risk_context,
            position_context=position_context,
            metadata=metadata,
            event_id=event_id,
        )

        logging.info(
            "Replication | cycle=%s | ticker=%s | decision=%s | ok=%s | skipped=%s | reason=%s | status_code=%s",
            cycle_type,
            ticker,
            decision,
            result.get("ok"),
            result.get("skipped"),
            result.get("reason"),
            result.get("status_code", "n/a"),
        )

        _write_jsonl(
            "replication_publish.jsonl",
            {
                "generated_at": _utc_now().isoformat(),
                "cycle_type": cycle_type,
                "ticker": ticker,
                "decision": decision,
                "event_id": event_id,
                "publish_result": result,
            },
        )
    except Exception as e:
        logging.error(
            "Replication publish error | cycle=%s | ticker=%s | decision=%s | error=%s",
            cycle_type,
            ticker,
            decision,
            e,
            exc_info=True,
        )
        _write_jsonl(
            "replication_publish_errors.jsonl",
            {
                "generated_at": _utc_now().isoformat(),
                "cycle_type": cycle_type,
                "ticker": ticker,
                "decision": decision,
                "event_id": event_id,
                "error": str(e),
            },
        )


def _replicate_full_cycle_results(
    publisher: Optional["ReplicaPublisher"],
    results: Dict[str, Any],
) -> None:
    if publisher is None:
        return

    allowed_decisions = {"approve_trade", "close_position", "reduce_size", "wait", "reject", "hold"}

    for res in _safe_list(results.get("results")):
        if not isinstance(res, dict):
            continue
        if "error" in res:
            continue

        row = _extract_result_fields(res)
        decision = str(row["decision"] or "unknown").strip().lower()
        if decision not in allowed_decisions:
            continue

        analysis = row["analysis"]
        active_exec = row["active_exec"]
        position_action = _safe_dict(active_exec.get("position_action"))

        requested_size_quote = _safe_float(
            position_action.get("size_quote", analysis.get("size_quote", row.get("size_quote", 0)))
        )

        requested_size_base = _safe_float(position_action.get("size_base", analysis.get("size_base", 0)))
        if requested_size_base <= 0 and str(row.get("side", "")).upper() == "SELL":
            requested_size_base = _safe_float(
                active_exec.get("requested_base_size", active_exec.get("requested_amount", 0))
            )

        reason_summary = _safe_list(analysis.get("reasons"))
        if not reason_summary:
            reason_summary = _safe_list(row["entry_gate"].get("reasons"))

        event_id = (
            str(active_exec.get("event_id", "")).strip()
            or str(analysis.get("event_id", "")).strip()
            or ""
        ) or None

        metadata = {
            "origin": "run_trader_loop_full_cycle",
            "execution_status": row["execution_status"],
            "executed_on_master": bool(row["executed"]),
            "gate_decision": row["gate_decision"],
            "gate_priority": row["gate_priority"],
            "status": row["status"],
        }

        if requested_size_quote > 0 and "quote_size" not in metadata:
            metadata["quote_size"] = f"{requested_size_quote:.2f}"
        if requested_size_base > 0 and "base_size" not in metadata:
            metadata["base_size"] = f"{requested_size_base:.8f}"

        _publish_replication_decision(
            publisher,
            cycle_type="full",
            ticker=row["ticker"],
            decision=decision,
            side=str(row["side"] or "NONE").upper(),
            strategy=str(row["strategy"] or "unknown"),
            setup_type=str(row["setup_type"] or "unknown"),
            confidence=int(row["confidence"] or 0),
            requested_size_quote=requested_size_quote,
            requested_size_base=requested_size_base,
            reason_summary=[str(x) for x in reason_summary[:8]],
            must_reject_if=[str(x) for x in _safe_list(analysis.get("must_reject_if"))[:8]],
            analysis=analysis,
            entry_gate=row["entry_gate"],
            risk_context=row["risk_context"],
            position_context=row["position_context"],
            metadata=metadata,
            event_id=event_id,
        )


def _replicate_heartbeat_results(
    publisher: Optional["ReplicaPublisher"],
    results: Dict[str, Any],
) -> None:
    if publisher is None:
        return

    for res in _safe_list(results.get("results")):
        if not isinstance(res, dict):
            continue
        if "error" in res:
            continue

        row = _extract_heartbeat_fields(res)
        reasons: List[str] = []
        reasons.extend(str(x) for x in row["heartbeat_reasons"][:4])
        reasons.extend(str(x) for x in row["position_watch_reasons"][:4])

        execution = row["execution"] if row["execution"] else row["position_execution"]
        position_action = _safe_dict(execution.get("position_action")) if execution else {}
        side = str(position_action.get("side") or execution.get("side", "NONE")).upper() if execution else "NONE"
        event_id = str(execution.get("event_id", "")).strip() or None if execution else None
        resolved_decision = _resolve_management_decision(execution)
        requested_size_quote = _safe_float(position_action.get("size_quote", execution.get("size_quote", 0.0))) if execution else 0.0
        requested_size_base = _safe_float(position_action.get("size_base", execution.get("requested_size_base", 0.0))) if execution else 0.0

        metadata = {
            "origin": "run_trader_loop_heartbeat",
            "status": row["status"],
            "position_watch_decision": row["position_watch_decision"],
            "heartbeat_decision": row["heartbeat_decision"],
            "resolved_decision": resolved_decision,
            "executed_on_master": bool(execution.get("executed", False)) if execution else False,
            "execution_status": execution.get("status", "n/a") if execution else "n/a",
        }

        _publish_replication_decision(
            publisher,
            cycle_type="heartbeat",
            ticker=row["ticker"],
            decision=resolved_decision,
            side=side if side in {"BUY", "SELL"} else "NONE",
            strategy="position_heartbeat",
            setup_type="position_heartbeat",
            confidence=100 if resolved_decision in {"close_position", "reduce_size"} else 0,
            requested_size_quote=requested_size_quote,
            requested_size_base=requested_size_base,
            reason_summary=reasons[:8],
            must_reject_if=[],
            analysis={},
            entry_gate={},
            risk_context={},
            position_context={
                "heartbeat": row["heartbeat"],
                "position_watch": row["position_watch"],
                "execution": execution,
            },
            metadata=metadata,
            event_id=event_id,
        )



def _run_lifecycle_orchestrator_service_hook(cfg: BotConfig, *, cycle_type: str) -> None:
    """Run C.4.4.1 lifecycle maintenance after a bot cycle.

    This hook is deliberately best-effort and safety-first. It never submits or
    cancels Coinbase orders itself; the underlying orchestrator defaults to
    preview mode and only performs local reconciliation when explicitly enabled
    by config flags. Any hook error is logged but must not crash the trading loop.
    """
    if build_phase_c43_lifecycle_service_report is None:
        logging.warning("C.4.4.1 lifecycle service hook unavailable; import failed earlier.")
        return

    if not bool(getattr(cfg, "enable_phase_c43_lifecycle_orchestrator", True)):
        logging.info("C.4.4.1 lifecycle service hook disabled by config.")
        return

    try:
        report = build_phase_c43_lifecycle_service_report(
            cfg=cfg,
            ticker="",
            cycle_type=cycle_type,
            source="run_trader_loop",
        )
        summary = _safe_dict(report.get("summary"))
        governance = _safe_dict(report.get("governance_report"))
        logging.info(
            "C.4.4.1 lifecycle hook | cycle=%s | status=%s | governance=%s | open_c43=%s | "
            "open_d3_exit=%s | coinbase_call_attempted=%s | d3_coinbase_call_attempted=%s | "
            "proposed=%s | d3_proposed=%s | applied=%s | d3_applied=%s | d2=%s | d3=%s | "
            "errors=%s | d3_errors=%s",
            cycle_type,
            report.get("status"),
            governance.get("status", "n/a"),
            summary.get("local_c43_open_orders_seen", 0),
            summary.get("local_d3_open_exit_orders_seen", 0),
            summary.get("coinbase_call_attempted", False),
            summary.get("d3_coinbase_call_attempted", False),
            summary.get("proposed_actions", 0),
            len(summary.get("d3_proposed_actions") or []),
            summary.get("applied_actions", 0),
            summary.get("d3_applied_actions", 0),
            summary.get("d2_reports", 0),
            summary.get("d3_previews", 0),
            summary.get("errors", 0),
            len(report.get("d3_open_exit_lifecycle_errors") or []),
        )
        _write_jsonl("phase_c43_lifecycle_service.jsonl", report)
    except Exception as exc:
        logging.error("C.4.4.1 lifecycle service hook failed: %s", exc, exc_info=True)
        _write_jsonl(
            "phase_c43_lifecycle_service_errors.jsonl",
            {
                "generated_at": _utc_now().isoformat(),
                "phase": "C4.4.1_lifecycle_orchestrator_service_hook",
                "cycle_type": cycle_type,
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )

def _run_and_log_full_cycle(engine: StrategyEngine, publisher: Optional["ReplicaPublisher"], cfg: BotConfig) -> None:
    _log_runtime_guard_version_context(cfg, source="full_cycle")
    logging.info(
        "Starting new FULL trading cycle | allowed_tickers=%s | ranking_enabled=%s | max_new_orders_per_cycle=%s | "
        "max_open_orders=%s | max_positions=%s",
        ",".join(getattr(cfg, "allowed_tickers", []) or []),
        bool(getattr(cfg, "enable_candidate_ranking", False)),
        getattr(cfg, "autonomous_max_new_orders_per_cycle", "n/a"),
        getattr(cfg, "autonomous_max_open_orders", "n/a"),
        getattr(cfg, "max_open_positions", "n/a"),
    )
    results = engine.run_cycle()

    for res in results.get("results", []):
        if not isinstance(res, dict):
            logging.warning("Unexpected result type received: %r", res)
            continue

        if "error" in res:
            logging.error(
                "Ticker %s | error=%s",
                res.get("ticker", "Unknown"),
                res.get("error"),
            )
            continue

        row = _extract_result_fields(res)
        _log_result_details(row)

    _log_cycle_summary(results)
    _replicate_full_cycle_results(publisher, results)
    # Use engine.cfg (not the separately-constructed top-level cfg): portfolio-based
    # entry sizing mutates engine.cfg.phase_c_max_order_quote (and related caps) every
    # cycle, while the standalone cfg never receives those updates. Passing the stale
    # cfg here made the lifecycle governance re-check compare a portfolio-scaled order
    # against the old static .env cap, permanently blocking poll/D2/D3 for any order
    # sized above that static cap even though it was within the live policy that
    # approved it.
    _run_lifecycle_orchestrator_service_hook(engine.cfg, cycle_type="full")


def _run_and_log_heartbeat_cycle(engine: StrategyEngine, publisher: Optional["ReplicaPublisher"], cfg: BotConfig) -> None:
    logging.info("Starting hourly open-position heartbeat cycle...")
    results = engine.run_position_heartbeat_cycle()

    for res in results.get("results", []):
        if not isinstance(res, dict):
            logging.warning("Unexpected heartbeat result type received: %r", res)
            continue

        if "error" in res:
            logging.error(
                "Heartbeat | ticker %s | error=%s",
                res.get("ticker", "Unknown"),
                res.get("error"),
            )
            continue

        row = _extract_heartbeat_fields(res)
        _log_heartbeat_result_details(row)

    _log_heartbeat_summary(results)
    _replicate_heartbeat_results(publisher, results)
    # See matching comment in _run_and_log_full_cycle: use engine.cfg so the
    # governance re-check sees the same portfolio-scaled caps entry sizing used.
    _run_lifecycle_orchestrator_service_hook(engine.cfg, cycle_type="heartbeat")


def _run_guarded_cycle(
    *,
    guard: CycleBoundaryGuard,
    cycle_type: str,
    engine: StrategyEngine,
    publisher: Optional["ReplicaPublisher"],
    cfg: BotConfig,
    now_utc: Optional[datetime] = None,
) -> bool:
    now = now_utc or _utc_now()
    if not guard.should_run(cycle_type, now):
        logging.warning("Skipping duplicate %s cycle boundary at %s", cycle_type, now.replace(minute=0, second=0, microsecond=0).isoformat())
        return False
    if cycle_type == "full":
        _run_and_log_full_cycle(engine, publisher, cfg)
    else:
        _run_and_log_heartbeat_cycle(engine, publisher, cfg)
    return True


def _preflight_credentials(*, blocking: bool = True) -> str:
    """Controleer of OpenAI/Coinbase bruikbaar geconfigureerd zijn.

    Draait vóór BotConfig(), zodat een ontbrekende sleutel een leesbare
    instructie oplevert in plaats van een dataclass-traceback, en zodat een
    onbruikbare Coinbase-sleutel niet pas uren later midden in een cyclus
    opduikt. Alleen offline controles: geen netwerk, geen API-kosten.

    `blocking=False` rapporteert wel maar stopt niet. Dat is de modus voor
    `--startup-diagnostic`: juist wanneer de configuratie stuk is wil je die
    diagnose kunnen draaien, dus die mag er niet zelf op stuklopen.

    De credentials komen uit .env: `bot.config` laadt dat bestand bij import,
    dus vóór deze functie draait. Retourneert de vastgestelde toestand.
    """
    checks = collect_checks(online=False)
    state = overall_state(checks)
    if state == READY:
        for check in checks:
            logging.info("Credentials | %s: %s", check.provider, check.summary)
        return state

    logging.error("=" * 68)
    logging.error("%s — de bot start niet.", state.replace("_", " "))
    for check in checks:
        if check.ok:
            continue
        logging.error("  %s: %s", check.provider, check.summary)
        if check.detail:
            logging.error("      %s", check.detail)
    logging.error("")
    logging.error("  Stel de credentials in met:  python -m tools.setup_wizard")
    logging.error("=" * 68)
    if blocking:
        raise SystemExit(4)
    return state


def main() -> None:
    startup_diagnostic_only = "--startup-diagnostic" in sys.argv[1:]
    _preflight_credentials(blocking=not startup_diagnostic_only)
    cfg = BotConfig()
    cfg.validate()

    logging.getLogger().setLevel(getattr(logging, cfg.log_level, logging.INFO))
    diagnostic = _enforce_tiny_runtime_startup_guard(cfg)
    pre_live_startup_gate = assess_pre_live_startup_gate(cfg)
    if startup_diagnostic_only:
        diagnostic["pre_live_startup_gate"] = pre_live_startup_gate
    else:
        enforce_pre_live_startup_gate(cfg)

    logging.info(
        "=== Coinbase Swing-Trader Bot Started (%sH main interval + 1H heartbeat) ===",
        cfg.primary_interval_hours,
    )
    full_workflow_diagnostic = _build_full_workflow_runtime_diagnostic(cfg)
    _log_full_workflow_runtime_diagnostic(full_workflow_diagnostic)
    runtime_guard_version = _log_runtime_guard_version_context(cfg, source="startup")
    if startup_diagnostic_only:
        diagnostic["full_workflow"] = full_workflow_diagnostic
        diagnostic["runtime_guard_version"] = runtime_guard_version
        print(json.dumps(diagnostic, indent=2, sort_keys=True, ensure_ascii=True))
        return
    logging.info(
        "Execution mode=%s | tickers=%s",
        cfg.execution_mode,
        ",".join(cfg.allowed_tickers),
    )
    _write_runtime_ticker_universe_state(cfg)

    if hasattr(cfg, "enable_candidate_ranking"):
        logging.info(
            "Flow flags | ranking=%s | strict_meanrev_postfilter=%s | raw_llm_logging=%s | corrupt_llm_logging=%s",
            getattr(cfg, "enable_candidate_ranking", False),
            getattr(cfg, "enable_strict_meanrev_postfilter", False),
            getattr(cfg, "llm_raw_logging_enabled", False),
            getattr(cfg, "llm_corrupt_logging_enabled", False),
        )

    publisher = _init_replica_publisher()
    engine_cls = StrategyEngine
    if engine_cls is None:
        from bot.strategy_engine import StrategyEngine as engine_cls

    engine = engine_cls()
    cycle_guard = CycleBoundaryGuard()
    first_run = True

    # Herstelbeleid voor de hoofdlus. Instelbaar via JARVIS_RECOVERY_* in .env;
    # de standaard is 5 pogingen met 30s, 60s, 120s, 240s ertussen en daarna
    # een afkoelperiode van 5 minuten.
    recovery_policy = RetryPolicy.from_env(
        "JARVIS_RECOVERY",
        max_attempts=5,
        base_delay=30.0,
        max_delay=300.0,
        cooldown_seconds=300.0,
    )
    consecutive_errors = 0
    logging.info("Herstelbeleid | %s", json.dumps(policies_snapshot(recovery_policy), sort_keys=True))

    try:
        lock_path = os.getenv("RUN_TRADER_LOOP_LOCK_PATH", "state/runtime_mutation.lock")
        with process_lock(lock_path) as lock_info:
            logging.info("Runner process lock acquired | path=%s | pid=%s", lock_info["path"], lock_info["pid"])
            while True:
                try:
                    if first_run:
                        _run_guarded_cycle(guard=cycle_guard, cycle_type="full", engine=engine, publisher=publisher, cfg=cfg)
                        first_run = False
                    else:
                        now = _utc_now()
                        if _is_full_cycle_boundary(now, cfg.primary_interval_hours):
                            logging.info(
                                "Hour boundary %s UTC falls on the %sH main interval -> full cycle.",
                                now.isoformat(),
                                cfg.primary_interval_hours,
                            )
                            _run_guarded_cycle(guard=cycle_guard, cycle_type="full", engine=engine, publisher=publisher, cfg=cfg, now_utc=now)
                        else:
                            logging.info(
                                "Hour boundary %s UTC falls between main cycles -> heartbeat only.",
                                now.isoformat(),
                            )
                            _run_guarded_cycle(guard=cycle_guard, cycle_type="heartbeat", engine=engine, publisher=publisher, cfg=cfg, now_utc=now)

                    # De cyclus is helemaal doorgelopen: eerdere storingen
                    # tellen niet meer mee voor de wachttijd.
                    if consecutive_errors:
                        logging.info(
                            "Cyclus weer normaal doorlopen na %s storing(en); herstelteller op nul.",
                            consecutive_errors,
                        )
                        consecutive_errors = 0

                    logging.info("Waiting for next hour boundary...")
                    _sleep_until_next_hour_boundary()

                except KeyboardInterrupt:
                    logging.info("Bot stopped manually (Ctrl+C).")
                    break

                except Exception as e:
                    # Herstel met oplopende wachttijd in plaats van een vaste
                    # minuut. Een korte netwerkhapering hoefde nooit 60 seconden
                    # te kosten, en een provider die plat ligt werd elke minuut
                    # opnieuw bestookt -- precies het gedrag dat een rate limit
                    # uitlokt. De teller gaat terug op nul zodra er weer een
                    # cyclus goed gaat, zodat losse storingen niet opstapelen.
                    consecutive_errors += 1
                    logging.error("Error in loop: %s", e, exc_info=True)
                    logging.error("Uitleg: %s", describe_failure(e))
                    _write_jsonl(
                        "loop_errors.jsonl",
                        {
                            "generated_at": _utc_now().isoformat(),
                            "error": str(e),
                            "error_type": type(e).__name__,
                            "consecutive_errors": consecutive_errors,
                            "transient": is_transient(e),
                        },
                    )

                    pause = recovery_policy.delay_for(min(consecutive_errors + 1, recovery_policy.max_attempts))
                    if consecutive_errors >= recovery_policy.max_attempts:
                        # Blijven falen is geen tijdelijke storing meer. Langer
                        # rusten en dat ook zo benoemen, in plaats van in
                        # hetzelfde tempo doorgaan.
                        pause = max(pause, recovery_policy.cooldown_seconds)
                        logging.error(
                            "%s cycli achter elkaar mislukt. Langere afkoelperiode van %.0f seconden.",
                            consecutive_errors,
                            pause,
                        )
                    logging.info(
                        "Herstelpauze van %.0f seconden (storing %s); daarna wordt de engine opnieuw opgebouwd.",
                        pause,
                        consecutive_errors,
                    )
                    time.sleep(pause)
                    try:
                        publisher = _init_replica_publisher()
                        engine = StrategyEngine()
                    except Exception as rebuild_error:
                        logging.error("StrategyEngine rebuild failed: %s", rebuild_error, exc_info=True)
                        logging.error("Uitleg: %s", describe_failure(rebuild_error))
                        time.sleep(recovery_policy.base_delay)
    except RuntimeError as exc:
        logging.error("Runner process lock blocked startup: %s", exc)
        raise SystemExit(3) from exc


if __name__ == "__main__":
    main()
