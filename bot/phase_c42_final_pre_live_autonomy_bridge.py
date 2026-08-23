from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from bot.phase_c41_pre_live_readiness import build_phase_c41_pre_live_readiness_report

ZERO = Decimal("0")
C42_DEFAULT_MAX_ORDER_QUOTE = Decimal("25.00")
C42_DEFAULT_MAX_OPEN_ORDERS = 4
C42_DEFAULT_MAX_NEW_ORDERS_PER_CYCLE = 1
C42_DEFAULT_MAX_CANCELS_PER_CYCLE = 2
C42_DEFAULT_MAX_REPLACES_PER_CYCLE = 1
C42_AUTONOMOUS_MODE_NAME = "autonomous_small_live_orderbook"
C42_FINAL_ARM_ACK = "I_UNDERSTAND_AND_APPROVE_C42_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, set):
        return list(value)
    return [value]


def _bool_cfg(cfg: Any, name: str, default: bool = False) -> bool:
    return bool(getattr(cfg, name, default))


def _int_cfg(cfg: Any, name: str, default: int) -> int:
    try:
        return int(getattr(cfg, name, default))
    except Exception:
        return int(default)


def _dec_cfg(cfg: Any, name: str, default: Decimal) -> Decimal:
    return _to_decimal(getattr(cfg, name, default), str(default))


def _allowed_phase_tickers(cfg: Any) -> List[str]:
    return [_normalize_ticker(x) for x in _as_list(getattr(cfg, "phase_c_allowed_tickers", [])) if _normalize_ticker(x)]


def build_c42_autonomous_env_preview(*, ticker: str = "BTC-USDC", max_order_quote: Decimal | str = C42_DEFAULT_MAX_ORDER_QUOTE) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker) or "BTC-USDC"
    max_quote = _to_decimal(max_order_quote, str(C42_DEFAULT_MAX_ORDER_QUOTE))
    staged_lines = [
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE=true",
        "AUTONOMOUS_MAX_ORDER_QUOTE=25.00",
        "AUTONOMOUS_MAX_OPEN_ORDERS=4",
        "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE=1",
        "AUTONOMOUS_MAX_CANCELS_PER_CYCLE=2",
        "AUTONOMOUS_MAX_REPLACES_PER_CYCLE=1",
        "AUTONOMOUS_REQUIRE_POST_ONLY=true",
        "AUTONOMOUS_ENTRY_ONLY_FIRST=true",
        "AUTONOMOUS_ALLOW_EXITS=false",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=true",
        "ENABLE_LIVE_LIMIT_ORDERS=true",
        "ENABLE_LIVE_ENTRY_ORDERS=true",
        "ENABLE_LIVE_EXIT_ORDERS=false",
        "ENABLE_PHASE_C_LIVE_SUBMIT_INFRASTRUCTURE=true",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=true",
        f"PHASE_C_ALLOWED_TICKERS={selected}",
        f"PHASE_C_MAX_ORDER_QUOTE={max_quote:.2f}",
        "PHASE_C_MAX_OPEN_ENTRY_ORDERS=4",
        "PHASE_C_MAX_NEW_ORDERS_PER_CYCLE=1",
        "PHASE_C_MAX_CANCELS_PER_CYCLE=2",
        "PHASE_C_MAX_REPLACES_PER_CYCLE=1",
        "PHASE_C_DISABLE_EXIT_LIMIT_ORDERS=true",
        "PHASE_C_LIVE_ORDER_POST_ONLY=true",
    ]
    rollback_lines = [
        "ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE=false",
        "ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false",
        "ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS=false",
        "ENABLE_LIVE_LIMIT_ORDERS=false",
        "ENABLE_LIVE_ENTRY_ORDERS=false",
        "ENABLE_LIVE_EXIT_ORDERS=false",
        "PHASE_C_ALLOWED_TICKERS=",
        "PHASE_C_MAX_ORDER_QUOTE=10.00",
    ]
    return {
        "mode_name": C42_AUTONOMOUS_MODE_NAME,
        "safety_note": "C.4.2 toont alleen de finale autonomy bridge en env-preview; deze module wijzigt geen .env, submit niet en cancelt niet.",
        "staged_autonomous_env_lines": staged_lines,
        "rollback_env_lines": rollback_lines,
        "human_arm_ack_required_for_later": C42_FINAL_ARM_ACK,
    }


def assess_phase_c42_final_autonomy_bridge(
    *,
    cfg: Any,
    ticker: str,
    c41_report: Dict[str, Any],
    arm_ack: str = "",
    autonomous_mode: str = "dry_run",
    max_order_quote: Decimal | str = C42_DEFAULT_MAX_ORDER_QUOTE,
    max_open_orders: int = C42_DEFAULT_MAX_OPEN_ORDERS,
    max_new_orders_per_cycle: int = C42_DEFAULT_MAX_NEW_ORDERS_PER_CYCLE,
    max_cancels_per_cycle: int = C42_DEFAULT_MAX_CANCELS_PER_CYCLE,
    max_replaces_per_cycle: int = C42_DEFAULT_MAX_REPLACES_PER_CYCLE,
) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker)
    max_quote = _to_decimal(max_order_quote, str(C42_DEFAULT_MAX_ORDER_QUOTE))
    max_open = int(max_open_orders)
    max_new = int(max_new_orders_per_cycle)
    max_cancels = int(max_cancels_per_cycle)
    max_replaces = int(max_replaces_per_cycle)
    blockers: List[str] = []
    warnings: List[str] = []
    passed: List[str] = []

    actual_submit = _bool_cfg(cfg, "enable_phase_c_actual_coinbase_submit", False)
    live_limit = _bool_cfg(cfg, "enable_live_limit_orders", False)
    live_entry = _bool_cfg(cfg, "enable_live_entry_orders", False)
    live_exit = _bool_cfg(cfg, "enable_live_exit_orders", False)
    phase_c_small_live = _bool_cfg(cfg, "enable_phase_c_live_small_limit_orders", False)
    autonomous_enabled = _bool_cfg(cfg, "enable_autonomous_small_live_orderbook_mode", False)
    cfg_max_quote = _dec_cfg(cfg, "autonomous_max_order_quote", max_quote)
    cfg_max_open = _int_cfg(cfg, "autonomous_max_open_orders", max_open)
    cfg_max_new = _int_cfg(cfg, "autonomous_max_new_orders_per_cycle", max_new)
    cfg_max_cancels = _int_cfg(cfg, "autonomous_max_cancels_per_cycle", max_cancels)
    cfg_max_replaces = _int_cfg(cfg, "autonomous_max_replaces_per_cycle", max_replaces)
    require_post_only = _bool_cfg(cfg, "autonomous_require_post_only", True)
    entry_only_first = _bool_cfg(cfg, "autonomous_entry_only_first", True)
    allow_exits = _bool_cfg(cfg, "autonomous_allow_exits", False)
    allowed_tickers = _allowed_phase_tickers(cfg)

    c41_ready = bool(c41_report.get("pre_live_ready_no_submit"))
    c41_status = str(c41_report.get("status") or "")
    readiness = _as_dict(c41_report.get("readiness"))
    readiness_summary = _as_dict(readiness.get("readiness_summary"))
    c40_summary = _as_dict(c41_report.get("c40_summary"))
    c40_counts = _as_dict(c40_summary.get("counts"))
    c38_summary = _as_dict(c41_report.get("c38_summary"))
    payload = _as_dict(c38_summary.get("payload_preview_summary"))
    payload_quote = _to_decimal(payload.get("size_quote_normalized") or payload.get("size_quote_requested"), "0")
    payload_accepted = bool(payload.get("accepted"))
    payload_post_only = bool(payload.get("post_only"))
    payload_side_buy = str(payload.get("side") or "").upper() == "BUY"

    def require(condition: bool, ok: str, bad: str) -> None:
        if condition:
            passed.append(ok)
        else:
            blockers.append(bad)

    require(bool(selected), "selected_ticker_present", "selected_ticker_missing")
    require(c41_ready, "c41_pre_live_ready_no_submit", "c41_pre_live_not_ready")
    require(c41_status in {"pre_live_ready_no_submit", "pre_live_readiness_ready_no_submit"} or c41_ready, "c41_status_ready", "c41_status_not_ready")
    require(not bool(c41_report.get("live_submission_attempted_by_this_tool")), "c41_made_no_live_attempt", "c41_attempted_live_submit_forbidden")
    require(not bool(c41_report.get("live_order_submitted")), "c41_submitted_no_live_order", "c41_submitted_live_order_forbidden")
    require(not bool(c41_report.get("cancel_attempted_by_this_tool")), "c41_made_no_cancel_attempt", "c41_attempted_cancel_forbidden")
    require(not bool(c41_report.get("cancel_submitted")), "c41_submitted_no_cancel", "c41_submitted_cancel_forbidden")
    require(not actual_submit or autonomous_enabled, "actual_submit_not_enabled_without_autonomous_mode", "actual_submit_enabled_while_autonomous_mode_disabled")
    require(not live_exit, "live_exit_orders_disabled", "live_exit_orders_enabled_forbidden_for_first_autonomous_phase")
    require(not allow_exits, "autonomous_allow_exits_false", "autonomous_allow_exits_true_forbidden_for_first_phase")
    require(entry_only_first, "autonomous_entry_only_first_true", "autonomous_entry_only_first_not_true")
    require(require_post_only, "autonomous_post_only_required", "autonomous_post_only_not_required")
    require(max_quote > ZERO and max_quote <= C42_DEFAULT_MAX_ORDER_QUOTE, "max_order_quote_within_25_usdc_cap", "max_order_quote_invalid_or_above_25")
    require(cfg_max_quote <= C42_DEFAULT_MAX_ORDER_QUOTE and cfg_max_quote > ZERO, "configured_max_order_quote_within_25_usdc_cap", "configured_max_order_quote_invalid_or_above_25")
    require(max_open >= 1 and max_open <= C42_DEFAULT_MAX_OPEN_ORDERS, "max_open_orders_within_4_cap", "max_open_orders_invalid_or_above_4")
    require(cfg_max_open >= 1 and cfg_max_open <= C42_DEFAULT_MAX_OPEN_ORDERS, "configured_max_open_orders_within_4_cap", "configured_max_open_orders_invalid_or_above_4")
    require(max_new >= 1 and max_new <= C42_DEFAULT_MAX_NEW_ORDERS_PER_CYCLE, "max_new_orders_per_cycle_within_cap", "max_new_orders_per_cycle_invalid_or_above_cap")
    require(max_cancels >= 0 and max_cancels <= C42_DEFAULT_MAX_CANCELS_PER_CYCLE, "max_cancels_per_cycle_within_cap", "max_cancels_per_cycle_invalid_or_above_cap")
    require(max_replaces >= 0 and max_replaces <= C42_DEFAULT_MAX_REPLACES_PER_CYCLE, "max_replaces_per_cycle_within_cap", "max_replaces_per_cycle_invalid_or_above_cap")
    require(int(c40_counts.get("live_unmanaged_orders") or 0) == 0, "no_unmanaged_live_orders", "unmanaged_live_orders_present")
    require(int(c40_counts.get("partial_fill_like_orders") or 0) == 0, "no_partial_fill_like_orders_before_autonomy", "partial_fill_like_orders_present_before_autonomy")
    require(int(c40_counts.get("live_open_orders") or 0) <= max_open, "live_open_orders_within_cap", "live_open_orders_above_cap")
    require(payload_accepted, "payload_accepted", "payload_not_accepted")
    require(payload_side_buy, "payload_side_buy", "payload_side_not_buy")
    require(payload_post_only, "payload_post_only", "payload_not_post_only")
    require(payload_quote > ZERO and payload_quote <= max_quote, "payload_quote_within_autonomous_cap", "payload_quote_missing_or_above_autonomous_cap")

    # Arming locks: these are expected to remain false until the final live window.
    arm_ack_ok = arm_ack == C42_FINAL_ARM_ACK
    final_mode = autonomous_mode == C42_AUTONOMOUS_MODE_NAME
    can_arm_autonomous_now = not blockers and final_mode and arm_ack_ok and autonomous_enabled and actual_submit and live_limit and live_entry and phase_c_small_live

    if autonomous_enabled and not final_mode:
        warnings.append("autonomous_flag_enabled_but_tool_not_in_autonomous_mode; no live order should be attempted")
    if actual_submit and not arm_ack_ok:
        warnings.append("actual_submit_enabled_without_c42_human_ack; rollback immediately")
    if live_limit or live_entry or phase_c_small_live:
        if selected and allowed_tickers and selected not in allowed_tickers:
            blockers.append("selected_ticker_not_in_phase_c_allowed_tickers")

    ready_to_arm = not blockers and not actual_submit and not autonomous_enabled
    status = "autonomous_small_live_armed" if can_arm_autonomous_now else ("ready_to_arm_autonomous_small_live" if ready_to_arm else "autonomous_small_live_precheck_blocked")
    return _json_safe({
        "status": status,
        "ready_to_arm_autonomous_small_live": ready_to_arm,
        "can_arm_autonomous_now": can_arm_autonomous_now,
        "blockers": blockers,
        "warnings": warnings,
        "passed_checks": passed,
        "limits": {
            "max_order_quote": str(max_quote),
            "max_open_orders": max_open,
            "max_new_orders_per_cycle": max_new,
            "max_cancels_per_cycle": max_cancels,
            "max_replaces_per_cycle": max_replaces,
            "entry_only_first": entry_only_first,
            "allow_exits": allow_exits,
            "require_post_only": require_post_only,
        },
        "current_config": {
            "enable_autonomous_small_live_orderbook_mode": autonomous_enabled,
            "enable_phase_c_actual_coinbase_submit": actual_submit,
            "enable_phase_c_live_small_limit_orders": phase_c_small_live,
            "enable_live_limit_orders": live_limit,
            "enable_live_entry_orders": live_entry,
            "enable_live_exit_orders": live_exit,
            "phase_c_allowed_tickers": allowed_tickers,
            "autonomous_max_order_quote": str(cfg_max_quote),
            "autonomous_max_open_orders": cfg_max_open,
            "autonomous_max_new_orders_per_cycle": cfg_max_new,
            "autonomous_max_cancels_per_cycle": cfg_max_cancels,
            "autonomous_max_replaces_per_cycle": cfg_max_replaces,
            "autonomous_require_post_only": require_post_only,
            "autonomous_entry_only_first": entry_only_first,
            "autonomous_allow_exits": allow_exits,
        },
        "arming_locks": {
            "autonomous_mode_required": C42_AUTONOMOUS_MODE_NAME,
            "autonomous_mode_provided": autonomous_mode,
            "final_mode_ok": final_mode,
            "human_ack_required": C42_FINAL_ARM_ACK,
            "human_ack_ok": arm_ack_ok,
            "autonomous_flag_enabled": autonomous_enabled,
            "actual_submit_enabled": actual_submit,
            "live_limit_orders_enabled": live_limit,
            "live_entry_orders_enabled": live_entry,
            "phase_c_small_live_enabled": phase_c_small_live,
        },
        "runtime_readiness_summary": {
            "selected_ticker": selected,
            "c41_status": c41_status,
            "c41_pre_live_ready_no_submit": c41_ready,
            "payload_accepted": payload_accepted,
            "payload_side_buy": payload_side_buy,
            "payload_post_only": payload_post_only,
            "payload_quote": str(payload_quote),
            "live_open_orders": int(c40_counts.get("live_open_orders") or 0),
            "live_unmanaged_orders": int(c40_counts.get("live_unmanaged_orders") or 0),
            "partial_fill_like_orders": int(c40_counts.get("partial_fill_like_orders") or 0),
            "deterministic_live_risk_accepted": bool(readiness_summary.get("deterministic_live_risk_accepted")),
            "controlled_coinbase_poll_succeeded": bool(readiness_summary.get("controlled_coinbase_poll_succeeded")),
        },
        "safety_policy": {
            "c42_does_not_submit": True,
            "c42_does_not_cancel": True,
            "c42_does_not_modify_env": True,
            "max_order_quote_hard_cap_usdc": str(C42_DEFAULT_MAX_ORDER_QUOTE),
            "max_open_orders_hard_cap": C42_DEFAULT_MAX_OPEN_ORDERS,
            "first_autonomous_phase_entry_only": True,
            "live_exits_forbidden_initially": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


def build_phase_c42_final_pre_live_autonomy_bridge_report(
    *,
    cfg: Any,
    ticker: str = "BTC-USDC",
    live_orders_snapshot: Optional[Sequence[Dict[str, Any]]] = None,
    allow_coinbase_poll: bool = False,
    coinbase_client: Any = None,
    risk_dir: str | Path | None = None,
    order_store_path: str | Path = "state/open_orders.json",
    order_events_path: str | Path = "logs/order_events.jsonl",
    require_controlled_coinbase_poll: bool = True,
    arm_ack: str = "",
    autonomous_mode: str = "dry_run",
    max_order_quote: Decimal | str = C42_DEFAULT_MAX_ORDER_QUOTE,
    max_open_orders: int = C42_DEFAULT_MAX_OPEN_ORDERS,
    max_new_orders_per_cycle: int = C42_DEFAULT_MAX_NEW_ORDERS_PER_CYCLE,
    max_cancels_per_cycle: int = C42_DEFAULT_MAX_CANCELS_PER_CYCLE,
    max_replaces_per_cycle: int = C42_DEFAULT_MAX_REPLACES_PER_CYCLE,
) -> Dict[str, Any]:
    selected = _normalize_ticker(ticker) or "BTC-USDC"
    c41 = build_phase_c41_pre_live_readiness_report(
        cfg=cfg,
        ticker=selected,
        live_orders_snapshot=live_orders_snapshot,
        allow_coinbase_poll=allow_coinbase_poll,
        coinbase_client=coinbase_client,
        risk_dir=risk_dir,
        order_store_path=order_store_path,
        order_events_path=order_events_path,
        require_controlled_coinbase_poll=require_controlled_coinbase_poll,
        emergency_cancel_mode="dry_run",
        human_cancel_ack="",
        cancel_live=False,
        cancel_order_ids=[],
        cancel_coinbase_client=None,
    )
    assessment = assess_phase_c42_final_autonomy_bridge(
        cfg=cfg,
        ticker=selected,
        c41_report=c41,
        arm_ack=arm_ack,
        autonomous_mode=autonomous_mode,
        max_order_quote=max_order_quote,
        max_open_orders=max_open_orders,
        max_new_orders_per_cycle=max_new_orders_per_cycle,
        max_cancels_per_cycle=max_cancels_per_cycle,
        max_replaces_per_cycle=max_replaces_per_cycle,
    )
    c41_readiness = _as_dict(c41.get("readiness"))
    return _json_safe({
        "phase": "C4.2_final_pre_live_autonomy_bridge",
        "generated_at": _now_iso(),
        "config_ok": True,
        "selected_ticker": selected,
        "status": assessment.get("status"),
        "ready_to_arm_autonomous_small_live": bool(assessment.get("ready_to_arm_autonomous_small_live")),
        "can_arm_autonomous_now": bool(assessment.get("can_arm_autonomous_now")),
        "actual_coinbase_submit_currently_enabled": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "live_submission_attempted_by_this_tool": False,
        "live_order_submitted": False,
        "cancel_attempted_by_this_tool": False,
        "cancel_submitted": False,
        "assessment": assessment,
        "c41_summary": {
            "status": c41.get("status"),
            "pre_live_ready_no_submit": c41.get("pre_live_ready_no_submit"),
            "blockers": c41_readiness.get("blockers", []),
            "readiness_summary": c41_readiness.get("readiness_summary", {}),
        },
        "env_preview": build_c42_autonomous_env_preview(ticker=selected, max_order_quote=max_order_quote),
        "final_live_instructions": [
            "Niet armeren zolang status niet ready_to_arm_autonomous_small_live is.",
            "Autonomous small-live mag maximaal 25 USDC per order gebruiken en maximaal 4 open orders beheren.",
            "Start entry-only; live exits blijven uit in de eerste autonome fase.",
            "Laat C.4.1 met echte Coinbase open-order poll en echte deterministic live-risk snapshot groen worden.",
            "Activeer final-live flags alleen in een expliciet venster en draai direct daarna C.4.2/C.4.1/C.4.0 opnieuw.",
            "Bij unmanaged order, partial fill of unexpected submit: rollback uitvoeren en troubleshooten.",
        ],
        "rollback_commands": [
            "python3 - <<'PY'\nfrom pathlib import Path\nimport re\np=Path('.env')\ns=p.read_text()\nfor k,v in {\n 'ENABLE_AUTONOMOUS_SMALL_LIVE_ORDERBOOK_MODE':'false',\n 'ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT':'false',\n 'ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_ENTRY_ORDERS':'false',\n 'ENABLE_LIVE_EXIT_ORDERS':'false',\n}.items():\n    line=f'{k}={v}'\n    if re.search(rf'^{k}=.*$', s, re.M):\n        s=re.sub(rf'^{k}=.*$', line, s, flags=re.M)\n    else:\n        s += '\\n' + line\nif re.search(r'^PHASE_C_ALLOWED_TICKERS=.*$', s, re.M):\n    s=re.sub(r'^PHASE_C_ALLOWED_TICKERS=.*$', 'PHASE_C_ALLOWED_TICKERS=', s, flags=re.M)\np.write_text(s)\nPY",
            "sudo systemctl restart coinbase-bot",
            "python3 tools/show_phase_c42_final_pre_live_autonomy_bridge.py --ticker BTC-USDC --json",
            "python3 tools/show_phase_c41_pre_live_readiness.py --ticker BTC-USDC --json",
            "python3 tools/show_phase_c40_live_order_safety.py --ticker BTC-USDC --json",
        ],
        "safety_policy": {
            "c42_is_final_pre_live_bridge_only": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_modify_env": True,
            "hard_cap_max_quote_usdc": str(C42_DEFAULT_MAX_ORDER_QUOTE),
            "hard_cap_max_open_orders": C42_DEFAULT_MAX_OPEN_ORDERS,
            "entry_only_first": True,
            "live_exits_forbidden_initially": True,
            "followers_not_in_order_lifecycle": True,
        },
    })
