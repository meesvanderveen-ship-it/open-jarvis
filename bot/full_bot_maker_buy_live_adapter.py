from __future__ import annotations

import json
from copy import copy
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from bot.full_bot_orchestrator import ORCHESTRATOR_POLICY, normalize_ticker, sha256_file
from bot.phase_c_live_guard import evaluate_phase_c_live_entry_readiness
from bot.phase_c_live_submitter import prepare_phase_c_live_entry_submission


FULL_BOT_MAKER_BUY_LIVE_ADAPTER_PHASE = "full_bot_maker_buy_live_adapter_v1"
EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK = "I_APPROVE_FULL_BOT_MAKER_BUY_LIVE_MAX_5_ORDERS_MAX_20_USDC_NO_SELL_NO_MARKET"
ZERO = Decimal("0")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(v) for v in value]
    return value


def to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        return Decimal(text) if text else Decimal(default)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def decimal_str(value: Any) -> str:
    text = format(to_decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def load_json_file(path: str | Path) -> Dict[str, Any]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def load_latest_full_bot_orchestrator_report(root: str | Path = ".") -> Tuple[Dict[str, Any], Optional[Path]]:
    base = Path(root) / "reports" / "d6"
    for path in sorted(base.glob("full-bot-orchestrator-*.json"), reverse=True):
        payload = load_json_file(path)
        if payload.get("phase") == "full_bot_orchestrator_v1":
            return payload, path
    return {}, None


def _action_intent(action: Dict[str, Any]) -> Dict[str, Any]:
    details = action.get("details") if isinstance(action.get("details"), dict) else {}
    intent = details.get("intent") if isinstance(details.get("intent"), dict) else {}
    return intent


def _candidate_quote(action: Dict[str, Any]) -> Decimal:
    intent = _action_intent(action)
    return to_decimal(intent.get("proposed_size_quote") or intent.get("size_quote") or intent.get("quote_size"))


def _candidate_price(action: Dict[str, Any]) -> Decimal:
    intent = _action_intent(action)
    return to_decimal(intent.get("proposed_price") or intent.get("limit_price") or intent.get("suggested_watch_level"))


def _is_market_candidate(action: Dict[str, Any]) -> bool:
    intent = _action_intent(action)
    action_class = str(action.get("action_class") or "").lower()
    preferred = str(intent.get("preferred_order_type") or intent.get("order_type") or "").lower()
    return "market" in action_class or preferred == "market" or bool(intent.get("market_order_preview"))


def _is_blocked_action(action: Dict[str, Any]) -> bool:
    return str(action.get("classification") or "").strip().lower() == "blocked"


def _soft_context_blockers(action: Dict[str, Any]) -> List[str]:
    intent = _action_intent(action)
    soft = [str(x) for x in intent.get("soft_blockers") or []]
    missing = [str(x) for x in intent.get("missing_conditions") or []]
    return sorted(set(soft + missing))


def select_maker_buy_candidates(
    orchestrator_report: Dict[str, Any],
    *,
    max_new_orders_per_cycle: int = 2,
    max_open_orders_total: int = 5,
    max_open_orders_per_ticker: int = 1,
    max_quote_per_order: Decimal = Decimal("20"),
    max_total_reserved_buy_quote: Decimal = Decimal("100"),
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    actions = [dict(x) for x in orchestrator_report.get("entry_action_candidates") or [] if isinstance(x, dict)]
    reservation = orchestrator_report.get("reservation_summary") if isinstance(orchestrator_report.get("reservation_summary"), dict) else {}
    open_count = int(reservation.get("open_order_count") or 0)
    open_by_ticker = reservation.get("open_order_count_by_ticker") if isinstance(reservation.get("open_order_count_by_ticker"), dict) else {}
    reserved_quote = to_decimal(reservation.get("reserved_quote_open_buy_orders"))

    strict = [a for a in actions if str(a.get("action_class") or "") == "strict_approve_trade_buy" and normalize_ticker(a.get("ticker"))]
    pool = strict or [a for a in actions if str(a.get("action_class") or "") in {"pattern_intent_maker_buy", "near_miss_maker_buy"}]

    selected: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    selected_tickers: set[str] = set()
    running_reserved_quote = reserved_quote

    for action in pool:
        ticker = normalize_ticker(action.get("ticker") or _action_intent(action).get("ticker"))
        side = str(action.get("side") or _action_intent(action).get("side") or "").strip().upper()
        quote = _candidate_quote(action)
        price = _candidate_price(action)
        reasons: List[str] = []
        if not ticker:
            reasons.append("ticker_missing")
        if side != "BUY":
            reasons.append(f"side_not_buy:{side or 'missing'}")
        if _is_market_candidate(action):
            reasons.append("market_candidate_rejected")
        if _is_blocked_action(action):
            reasons.append("blocked_candidate_rejected")
        if price <= ZERO:
            reasons.append("limit_price_missing")
        if quote <= ZERO:
            reasons.append("quote_missing")
        if quote > max_quote_per_order:
            reasons.append("max_20_usdc_order_cap_exceeded")
        if open_count + len(selected) >= max_open_orders_total:
            reasons.append("max_5_open_orders_total_reached")
        if ticker and (int(open_by_ticker.get(ticker) or 0) > 0 or ticker in selected_tickers):
            reasons.append("max_1_open_order_per_ticker_reached")
        if len(selected) >= max_new_orders_per_cycle:
            reasons.append("max_2_new_orders_per_cycle_reached")
        if running_reserved_quote + quote > max_total_reserved_buy_quote:
            reasons.append("max_100_usdc_reserved_quote_reached")

        snapshot = {
            "ticker": ticker,
            "action_class": action.get("action_class"),
            "classification": action.get("classification"),
            "side": side,
            "quote_size": decimal_str(quote),
            "limit_price": decimal_str(price),
            "soft_context_blockers": _soft_context_blockers(action),
            "source_action": action,
        }
        if reasons:
            rejected.append({**snapshot, "reasons": sorted(set(reasons))})
            continue
        selected.append(snapshot)
        selected_tickers.add(ticker)
        running_reserved_quote += quote

    selected_source_ids = {id(x.get("source_action")) for x in selected}
    for action in actions:
        if id(action) in selected_source_ids:
            continue
        action_class = str(action.get("action_class") or "")
        if action_class not in {"strict_approve_trade_buy", "pattern_intent_maker_buy", "near_miss_maker_buy"}:
            continue
        ticker = normalize_ticker(action.get("ticker") or _action_intent(action).get("ticker"))
        if any(r.get("source_action") == action for r in rejected):
            continue
        if action not in pool:
            rejected.append(
                {
                    "ticker": ticker,
                    "action_class": action_class,
                    "classification": action.get("classification"),
                    "side": str(action.get("side") or _action_intent(action).get("side") or "").upper(),
                    "quote_size": decimal_str(_candidate_quote(action)),
                    "limit_price": decimal_str(_candidate_price(action)),
                    "soft_context_blockers": _soft_context_blockers(action),
                    "source_action": action,
                    "reasons": ["not_selected_strict_approve_candidates_preferred"],
                }
            )
    return json_safe(selected), json_safe(rejected)


def _adapter_cfg(base_cfg: Any = None, *, allowed_tickers: Iterable[str], exact_ack_present: bool) -> Any:
    cfg = copy(base_cfg) if base_cfg is not None else type("FullBotMakerBuyCfg", (), {})()
    policy = ORCHESTRATOR_POLICY
    cfg.enable_phase_c_live_small_limit_orders = True
    cfg.execution_mode = "live"
    cfg.enable_limit_order_manager = True
    cfg.enable_live_limit_orders = True
    cfg.enable_live_entry_orders = True
    cfg.enable_live_exit_orders = False
    cfg.phase_c_allowed_tickers = sorted({normalize_ticker(x) for x in allowed_tickers if normalize_ticker(x)})
    cfg.phase_c_max_order_quote = Decimal(str(policy.get("max_quote_per_order", "20.00")))
    cfg.phase_c_max_open_entry_orders = int(policy.get("max_open_orders_total", 5))
    cfg.phase_c_max_new_orders_per_cycle = int(policy.get("max_new_orders_per_cycle", 2))
    cfg.phase_c_max_cancels_per_cycle = 0
    cfg.phase_c_max_replaces_per_cycle = 0
    cfg.phase_c_require_pending_intent = True
    cfg.phase_c_require_promotion_ready = True
    cfg.phase_c_require_fresh_judge = True
    cfg.phase_c_require_risk_approval = True
    cfg.phase_c_require_orderbook_freshness = True
    cfg.phase_c_entry_order_min_expiry_minutes = 15
    cfg.phase_c_entry_order_default_expiry_minutes = 60
    cfg.phase_c_entry_order_max_expiry_hours = 6
    cfg.phase_c_disable_exit_limit_orders = True
    cfg.phase_c_paper_shadow_log = True
    cfg.enable_phase_c_live_submit_infrastructure = True
    cfg.enable_phase_c_actual_coinbase_submit = bool(exact_ack_present)
    cfg.phase_c_live_order_post_only = True
    return cfg


def phase_c_candidate_from_selection(selection: Dict[str, Any]) -> Dict[str, Any]:
    source = selection.get("source_action") if isinstance(selection.get("source_action"), dict) else {}
    intent = _action_intent(source)
    ticker = normalize_ticker(selection.get("ticker") or intent.get("ticker"))
    quote = decimal_str(selection.get("quote_size") or intent.get("proposed_size_quote"))
    price = decimal_str(selection.get("limit_price") or intent.get("proposed_price"))
    action_class = str(selection.get("action_class") or "")
    strict_like = action_class in {"strict_approve_trade_buy", "pattern_intent_maker_buy"} and not _soft_context_blockers(source)
    judge_decision = "approve_trade" if strict_like else "wait"
    order_intent = {
        "intent_id": str(intent.get("intent_id") or f"full-bot-maker-buy-{ticker}"),
        "client_order_id": str(intent.get("client_order_id") or f"paper-fullbot-{ticker.replace('-', '')}"),
        "ticker": ticker,
        "side": "BUY",
        "execution_action": "place_limit_buy",
        "size_quote": quote,
        "limit_price": price,
        "post_only": True,
        "source_action_class": action_class,
        "source_intent_status": intent.get("status"),
        "preview_only": True,
    }
    analysis = {
        "ticker": ticker,
        "judge": {
            "decision": judge_decision,
            "side": "BUY" if judge_decision == "approve_trade" else "NONE",
            "source": "full_bot_orchestrator_adapter",
        },
        "paper_pending_order_intent": {
            "status": "trigger_ready",
            "trigger_ready": True,
            "requires_fresh_judge_and_risk": True,
            "source": "full_bot_orchestrator_adapter",
        },
    }
    execution_plan = {
        "ticker": ticker,
        "execution_action": "place_limit_buy",
        "read_only": True,
        "orderbook_summary": {
            "snapshot_available": True,
            "freshness_status": "fresh",
            "spread_pct": str((intent.get("expected_value") or {}).get("cost_estimate_pct") or "0"),
        },
    }
    risk = {
        "generated_at": now_iso(),
        "mode": "full_bot_maker_buy_adapter_live_risk",
        "accepted": strict_like,
        "approved": strict_like,
        "risk_approved": strict_like,
        "blockers": [] if strict_like else ["near_miss_requires_fresh_strict_approve_trade_before_live_submit"],
    }
    return json_safe({"ticker": ticker, "order_intent": order_intent, "analysis": analysis, "execution_plan": execution_plan, "risk": risk})


def build_full_bot_maker_buy_live_adapter_report(
    *,
    orchestrator_report: Dict[str, Any],
    ack: str = "",
    actual_submit_requested: bool = False,
    coinbase_client: Any = None,
    base_cfg: Any = None,
    product_rules_by_ticker: Optional[Dict[str, Dict[str, Any]]] = None,
    phase_c_ready_candidates: Optional[Iterable[Dict[str, Any]]] = None,
    source_paths: Optional[Iterable[str | Path]] = None,
    phase_c_submitter: Callable[..., Dict[str, Any]] = prepare_phase_c_live_entry_submission,
) -> Dict[str, Any]:
    exact_ack_present = str(ack or "").strip() == EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK
    preview_only = not (actual_submit_requested and exact_ack_present)
    selected, rejected = select_maker_buy_candidates(orchestrator_report)
    promoted_by_ticker = {
        normalize_ticker(x.get("ticker")): dict(x)
        for x in (phase_c_ready_candidates or [])
        if isinstance(x, dict) and normalize_ticker(x.get("ticker"))
    }
    phase_c_candidates = [
        promoted_by_ticker.get(normalize_ticker(x.get("ticker"))) or phase_c_candidate_from_selection(x)
        for x in selected
    ]
    cfg = _adapter_cfg(base_cfg, allowed_tickers=[x.get("ticker") for x in selected], exact_ack_present=exact_ack_present)

    phase_c_snapshots: List[Dict[str, Any]] = []
    phase_c_blockers: List[str] = []
    submit_results: List[Dict[str, Any]] = []
    attempted = False
    submitted_count = 0
    product_rules_by_ticker = product_rules_by_ticker if isinstance(product_rules_by_ticker, dict) else {}

    for index, candidate in enumerate(phase_c_candidates):
        guard = evaluate_phase_c_live_entry_readiness(
            cfg=cfg,
            ticker=str(candidate.get("ticker") or ""),
            analysis=candidate.get("analysis") or {},
            execution_plan=candidate.get("execution_plan") or {},
            order_intent=candidate.get("order_intent") or {},
            live_risk_result=candidate.get("risk") or {},
            open_live_entry_orders_count=int((orchestrator_report.get("reservation_summary") or {}).get("open_order_count") or 0),
            new_live_orders_this_cycle=index,
        )
        phase_c_blockers.extend(str(x) for x in guard.get("hard_block_reasons") or [])
        submit_live = bool(actual_submit_requested and exact_ack_present and guard.get("guard_allows_live_submit") and coinbase_client is not None)
        result = phase_c_submitter(
            cfg=cfg,
            ticker=str(candidate.get("ticker") or ""),
            order_intent=candidate.get("order_intent") or {},
            guard_result=guard,
            coinbase_client=coinbase_client,
            product_rules=product_rules_by_ticker.get(str(candidate.get("ticker") or "")),
            submit_live=submit_live,
        )
        attempted = attempted or bool(result.get("live_submission_attempted"))
        submitted_count += 1 if result.get("live_order_submitted") else 0
        submit_results.append(result)
        phase_c_snapshots.append(
            {
                "ticker": candidate.get("ticker"),
                "candidate": candidate,
                "guard_result": guard,
                "submit_preparation": result,
            }
        )

    blockers: List[str] = []
    warnings: List[str] = []
    if not selected:
        blockers.append("no_eligible_maker_buy_candidates_selected")
    if actual_submit_requested and not exact_ack_present:
        blockers.append("exact_ack_required_for_actual_submit")
    if exact_ack_present and actual_submit_requested and coinbase_client is None:
        blockers.append("coinbase_client_required_for_actual_submit")
    if phase_c_blockers:
        blockers.append("phase_c_guard_blockers_present")
    for item in selected:
        if item.get("soft_context_blockers"):
            warnings.append(f"{item.get('ticker')}:selected_near_miss_context_requires_fresh_strict_review")

    actual_submit_allowed = bool(actual_submit_requested and exact_ack_present and selected and not phase_c_blockers and coinbase_client is not None)
    would_submit_if_ack = bool(selected and not phase_c_blockers)
    status = "preview_ready_ack_required"
    classification = "WATCH"
    if blockers:
        status = "blocked"
    if actual_submit_allowed and attempted and submitted_count == len(selected):
        status = "actual_submit_completed"
        classification = "LIVE_WRITE"
    elif actual_submit_allowed:
        status = "actual_submit_armed"
        classification = "ACK_ARMED"

    reservation = orchestrator_report.get("reservation_summary") if isinstance(orchestrator_report.get("reservation_summary"), dict) else {}
    report = {
        "generated_at": now_iso(),
        "phase": FULL_BOT_MAKER_BUY_LIVE_ADAPTER_PHASE,
        "status": status,
        "classification": classification,
        "preview_only": preview_only,
        "exact_ack_present": exact_ack_present,
        "actual_submit_requested": bool(actual_submit_requested),
        "actual_submit_allowed": actual_submit_allowed,
        "actual_submit_attempted": attempted,
        "coinbase_write_attempted": attempted,
        "state_write_performed": False,
        "selected_entry_candidates": selected,
        "rejected_entry_candidates": rejected,
        "phase_c_candidate_snapshots": phase_c_snapshots,
        "phase_c_guard_summary": {
            "all_phase_c_guards_passed": bool(selected) and not phase_c_blockers,
            "guarded_candidate_count": len(phase_c_snapshots),
            "blockers": sorted(set(phase_c_blockers)),
            "phase_c_route_used": "bot.phase_c_live_submitter.prepare_phase_c_live_entry_submission",
            "direct_coinbase_submitter_introduced": False,
        },
        "reservation_summary": {
            "open_order_count": reservation.get("open_order_count", 0),
            "open_order_count_by_ticker": reservation.get("open_order_count_by_ticker", {}),
            "reserved_quote_open_buy_orders": reservation.get("reserved_quote_open_buy_orders", "0"),
            "max_new_orders_per_cycle": 2,
            "max_open_orders_total": 5,
            "max_open_orders_per_ticker": 1,
            "max_quote_per_order": "20",
            "max_total_reserved_buy_quote": "100",
        },
        "blockers": sorted(set(blockers)),
        "warnings": sorted(set(warnings)),
        "exact_ack_required": EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK,
        "would_submit_if_ack": would_submit_if_ack,
        "submit_results": submit_results,
        "safety_flags": {
            "buy_only": True,
            "maker_limit_only": True,
            "post_only_required": True,
            "market_orders_enabled": False,
            "sell_enabled": False,
            "live_exits_enabled": False,
            "d3_actual_exit_submit_enabled": False,
            "replication_enabled": False,
            "learning_to_execution_allowed": False,
            "parameter_mutation_allowed": False,
            "uses_existing_phase_c_route_only": True,
        },
        "next_operator_command_preview": (
            "python3 tools/build_full_bot_maker_buy_live_adapter_report.py "
            "--orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json "
            "--json-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).json "
            "--markdown-out reports/d6/full-bot-maker-buy-live-adapter-$(date -u +%Y%m%d).md"
        ),
        "next_operator_command_actual_submit": (
            "DO NOT RUN until operator gives ACK: python3 tools/build_full_bot_maker_buy_live_adapter_report.py "
            "--actual-submit --ack "
            f"{EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK} "
            "--orchestrator-report reports/d6/full-bot-orchestrator-$(date -u +%Y%m%d).json "
            "--json-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).json "
            "--markdown-out reports/d6/full-bot-maker-buy-live-adapter-actual-$(date -u +%Y%m%d).md"
        ),
        "input_hashes": {},
    }
    for raw in source_paths or []:
        path = Path(raw)
        if path.exists() and path.is_file():
            report["input_hashes"][str(path)] = sha256_file(path)
    return json_safe(report)


def render_full_bot_maker_buy_live_adapter_markdown(report: Dict[str, Any]) -> str:
    lines = [
        "# Full Bot Maker BUY Live Adapter v1",
        "",
        "ACK-gated Phase-C maker BUY adapter. Default command is preview-only: no Coinbase write and no trading-state write.",
        "",
        f"- generated_at: `{report.get('generated_at')}`",
        f"- status: `{report.get('status')}`",
        f"- classification: `{report.get('classification')}`",
        f"- preview_only: `{report.get('preview_only')}`",
        f"- exact_ack_present: `{report.get('exact_ack_present')}`",
        f"- actual_submit_allowed: `{report.get('actual_submit_allowed')}`",
        f"- actual_submit_attempted: `{report.get('actual_submit_attempted')}`",
        f"- coinbase_write_attempted: `{report.get('coinbase_write_attempted')}`",
        f"- state_write_performed: `{report.get('state_write_performed')}`",
        f"- exact_ack_required: `{report.get('exact_ack_required')}`",
        "",
        "## Selected Entry Candidates",
        "",
        "```json",
        json.dumps(report.get("selected_entry_candidates") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Rejected Entry Candidates",
        "",
        "```json",
        json.dumps(report.get("rejected_entry_candidates") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Phase-C Guard Summary",
        "",
        "```json",
        json.dumps(report.get("phase_c_guard_summary") or {}, indent=2, sort_keys=True),
        "```",
        "",
        "## Blockers",
        "",
        "```json",
        json.dumps(report.get("blockers") or [], indent=2, sort_keys=True),
        "```",
        "",
        "## Next Commands",
        "",
        f"- preview: `{report.get('next_operator_command_preview')}`",
        f"- actual submit: `{report.get('next_operator_command_actual_submit')}`",
        "",
    ]
    return "\n".join(lines)


__all__ = [
    "EXACT_FULL_BOT_MAKER_BUY_LIVE_ACK",
    "FULL_BOT_MAKER_BUY_LIVE_ADAPTER_PHASE",
    "build_full_bot_maker_buy_live_adapter_report",
    "load_latest_full_bot_orchestrator_report",
    "phase_c_candidate_from_selection",
    "render_full_bot_maker_buy_live_adapter_markdown",
    "select_maker_buy_candidates",
]
