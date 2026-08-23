#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from bot.atomic_io import atomic_write_json
from bot.orderbook_entry_planner import build_resting_limit_entry_preview, classify_entry_decision


OPPORTUNITY_JSON_PATH = Path("reports/audits/orderbook-entry-opportunity-audit-latest.json")
OPPORTUNITY_MD_PATH = Path("reports/audits/orderbook-entry-opportunity-audit-latest.md")
WORKFLOW_JSON_PATH = Path("reports/audits/orderbook-entry-workflow-audit-latest.json")
WORKFLOW_MD_PATH = Path("reports/audits/orderbook-entry-workflow-audit-latest.md")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    if text.lower().endswith(" utc"):
        text = text[:-4].strip() + "+00:00"
    elif text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _since_to_dt(value: str) -> Optional[datetime]:
    text = str(value or "").strip()
    lower = text.lower()
    if not text:
        return None
    if lower.endswith(" hours ago"):
        try:
            return datetime.now(timezone.utc) - timedelta(hours=int(lower.split()[0]))
        except Exception:
            return None
    if lower.endswith(" days ago"):
        try:
            return datetime.now(timezone.utc) - timedelta(days=int(lower.split()[0]))
        except Exception:
            return None
    return _parse_time(text)


def _row_time(row: Dict[str, Any]) -> Optional[datetime]:
    return _parse_time(row.get("generated_at") or row.get("timestamp") or row.get("created_at") or row.get("decision_time"))


def _next_full_cycle_boundary(now: datetime, interval_hours: int = 4) -> datetime:
    boundary = now.replace(minute=0, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(hours=1)
    while boundary.hour % max(1, interval_hours) != 0:
        boundary += timedelta(hours=1)
    return boundary


def _iter_jsonl(
    path: Path,
    since_dt: Optional[datetime],
    source_breakdown: Optional[Dict[str, Dict[str, int]]] = None,
) -> Iterable[Dict[str, Any]]:
    stats = {"seen": 0, "included": 0, "excluded_before_since": 0, "without_timestamp_excluded": 0}
    if not path.exists():
        if source_breakdown is not None:
            source_breakdown[str(path)] = stats
        return []
    out: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        stats["seen"] += 1
        ts = _row_time(row)
        if since_dt:
            if ts is None:
                stats["without_timestamp_excluded"] += 1
                continue
            if ts < since_dt:
                stats["excluded_before_since"] += 1
                continue
        stats["included"] += 1
        out.append(row)
    if source_breakdown is not None:
        source_breakdown[str(path)] = stats
    return out


def _latest_jsonl_time(path: Path) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for row in _iter_jsonl(path, None):
        ts = _row_time(row)
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


def _counter_dict(counter: Counter) -> Dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _phase_c_failure_reason(row: Dict[str, Any]) -> str:
    submit_result = _as_dict(row.get("submit_result"))
    local_order = _as_dict(row.get("local_order_record"))
    response = _as_dict(row.get("coinbase_response") or local_order.get("coinbase_response") or submit_result.get("coinbase_response"))
    error_response = _as_dict(response.get("error_response"))
    return str(
        row.get("reject_reason")
        or submit_result.get("reject_reason")
        or local_order.get("reject_reason")
        or error_response.get("error")
        or row.get("preview_failure_reason")
        or submit_result.get("preview_failure_reason")
        or local_order.get("preview_failure_reason")
        or row.get("error_type")
        or row.get("error")
        or row.get("status")
        or "unknown"
    )


def _phase_c_submit_window(rows: Sequence[Dict[str, Any]], since_dt: Optional[datetime] = None) -> Dict[str, Any]:
    selected: List[Dict[str, Any]] = []
    for row in rows:
        ts = _row_time(row)
        if since_dt is not None and (ts is None or ts < since_dt):
            continue
        selected.append(row)
    attempted_rows = [row for row in selected if bool(row.get("live_submission_attempted"))]
    submitted_rows = [row for row in selected if bool(row.get("live_order_submitted"))]
    failures = Counter(_phase_c_failure_reason(row) for row in attempted_rows if not bool(row.get("live_order_submitted")))
    return {
        "rows_total": len(selected),
        "live_submission_attempted_count": len(attempted_rows),
        "live_order_submitted_count": len(submitted_rows),
        "failure_reasons": _counter_dict(failures),
    }


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _has_entry_level(row: Dict[str, Any]) -> bool:
    plan = _as_dict(row.get("trade_plan"))
    judge = _as_dict(row.get("judge"))
    return any(plan.get(k) not in (None, "") for k in ("preferred_limit_price", "entry_zone_low", "entry_zone_high", "entry_price")) or judge.get("preferred_limit_price") not in (None, "")


def _has_invalidation(row: Dict[str, Any]) -> bool:
    plan = _as_dict(row.get("trade_plan"))
    judge = _as_dict(row.get("judge"))
    return any((plan.get(k) not in (None, "")) for k in ("invalidation_price", "stop_loss_price", "stop_loss", "invalidation")) or judge.get("invalidation_price") not in (None, "")


def _has_target(row: Dict[str, Any]) -> bool:
    plan = _as_dict(row.get("trade_plan"))
    judge = _as_dict(row.get("judge"))
    return any((plan.get(k) not in (None, "")) for k in ("take_profit_1", "take_profit_2", "target_price_1", "target_price_2")) or any(judge.get(k) not in (None, "") for k in ("target_price_1", "target_price_2"))


def _ticker(row: Dict[str, Any]) -> str:
    return str(row.get("ticker") or _as_dict(row.get("feature_pack")).get("ticker") or _as_dict(row.get("trade_plan")).get("ticker") or "UNKNOWN")


def _setup(row: Dict[str, Any]) -> str:
    plan = _as_dict(row.get("trade_plan"))
    judge = _as_dict(row.get("judge"))
    gate = _as_dict(row.get("entry_gate") or _as_dict(row.get("feature_pack")).get("entry_gate"))
    return str(plan.get("setup_type") or judge.get("setup_type") or gate.get("setup_type") or "unknown")


def _order_counts(root: Path) -> Dict[str, int]:
    try:
        payload = json.loads((root / "state/open_orders.json").read_text(encoding="utf-8"))
    except Exception:
        payload = {}
    orders = payload.get("orders") if isinstance(payload, dict) and isinstance(payload.get("orders"), dict) else payload
    rows = list(orders.values()) if isinstance(orders, dict) else (orders if isinstance(orders, list) else [])
    active = {"planned", "pending", "submitted", "open", "active", "partially_filled", "cancel_pending", "replace_pending"}
    return {"open_orders": sum(1 for row in rows if isinstance(row, dict) and str(row.get("status") or "").lower() in active)}


def build_orderbook_entry_opportunity_audit(*, root: Path = Path("."), since: str = "") -> Dict[str, Any]:
    since_dt = _since_to_dt(since)
    data_sources_checked = ["logs/analysis.jsonl", "logs/phase_c_live_submit.jsonl", "state/open_orders.json"]
    source_breakdown: Dict[str, Dict[str, int]] = {}
    rows = list(_iter_jsonl(root / "logs/analysis.jsonl", since_dt, source_breakdown))
    phase_c_submit_rows = list(_iter_jsonl(root / "logs/phase_c_live_submit.jsonl", since_dt, source_breakdown))
    order_counts = _order_counts(root)
    label_counts = Counter()
    setup_counts = Counter()
    ticker_counts = Counter()
    blocker_counts = Counter()
    near_miss: List[Dict[str, Any]] = []
    eligible = 0
    prepare_resting_limit_entry_would_be = 0
    valid_trade_plans = 0
    concrete_entry = 0
    inv_count = 0
    target_count = 0
    no_setup = trigger_not_ready = do_not_chase = 0
    product_rules_rows = recent_rejections_rows = execution_feasibility_rows = 0

    for row in rows:
        label = classify_entry_decision(row)
        preview = build_resting_limit_entry_preview(
            ticker=_ticker(row),
            analysis=row,
            open_orders_count=order_counts["open_orders"],
            max_open_orders=4,
            max_new_orders_per_cycle=1,
        )
        label_counts[label] += 1
        setup_counts[_setup(row)] += 1
        ticker_counts[_ticker(row)] += 1
        action = str(_as_dict(row.get("trade_plan")).get("plan_action") or "no_plan").lower()
        valid_trade_plans += int(action in {"prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion", "prepare_resting_limit_entry", "prepare_retest_limit_entry", "prepare_pullback_limit_entry", "prepare_reclaim_retest_limit_entry", "prepare_breakout_retest_limit_entry", "manage_existing", "reduce", "close"})
        concrete_entry += int(_has_entry_level(row))
        inv_count += int(_has_invalidation(row))
        target_count += int(_has_target(row))
        no_setup += int(label == "wait_no_setup")
        trigger_not_ready += int(label in {"wait_trigger_not_ready", "wait_trigger_not_ready_no_order"})
        do_not_chase += int(label in {"wait_do_not_chase", "wait_do_not_chase_no_order"})
        if preview["eligible"]:
            eligible += 1
            prepare_resting_limit_entry_would_be += 1
        else:
            for blocker in preview.get("blockers") or []:
                blocker_counts[str(blocker)] += 1
        if len(near_miss) < 20 and (not preview["eligible"]) and _has_entry_level(row) and _has_invalidation(row):
            near_miss.append({
                "ticker": _ticker(row),
                "setup_type": _setup(row),
                "entry_decision_label": label,
                "blockers": preview.get("blockers") or [],
                "entry_level": preview.get("entry_level"),
                "invalidation_level": preview.get("invalidation_level"),
                "target_levels": preview.get("target_levels"),
                "reason": preview.get("reason"),
            })
        fp = _as_dict(row.get("feature_pack"))
        dc = _as_dict(fp.get("decision_context"))
        product_rules_rows += int(bool(dc.get("product_rules") or fp.get("product_rules") or fp.get("exchange_rules")))
        recent_rejections_rows += int(bool(dc.get("recent_exchange_rejections")))
        execution_feasibility_rows += int(bool(dc.get("execution_feasibility") or fp.get("execution_feasibility") or preview.get("execution_feasibility")))

    last_full_cycle_completed_at = _latest_jsonl_time(root / "logs/cycle_summary.jsonl")
    no_data_reason = ""
    recommendation = "insufficient_evidence" if len(rows) < 4 else "review_near_misses"
    if not rows:
        if since_dt and (last_full_cycle_completed_at is None or last_full_cycle_completed_at < since_dt):
            no_data_reason = "no_full_cycle_since_since_time"
            recommendation = "no_recent_full_cycle"
        elif since and since_dt is None:
            no_data_reason = "invalid_since_time"
            recommendation = "insufficient_new_data"
        else:
            no_data_reason = "no_decision_rows_in_checked_sources"
            recommendation = "insufficient_new_data"

    phase_c_windows = {
        "requested_window": _phase_c_submit_window(phase_c_submit_rows),
        "since_last_full_cycle_completed": _phase_c_submit_window(phase_c_submit_rows, last_full_cycle_completed_at),
    }
    precision_rejects = Counter(_phase_c_failure_reason(row) for row in phase_c_submit_rows if _phase_c_failure_reason(row) in {"INVALID_PRICE_PRECISION", "INVALID_SIZE_PRECISION"})
    precision_normalized_attempts = 0
    precision_context_missing_attempts = 0
    precision_tickers = Counter()
    for row in phase_c_submit_rows:
        submit = _as_dict(row.get("submit_result"))
        payload = _as_dict(submit.get("payload") or row.get("payload"))
        precision_normalized_attempts += int(bool(payload.get("precision_normalization")))
        product_rules = _as_dict(payload.get("product_rules") or payload.get("product_rules_used"))
        precision_context_missing_attempts += int(not bool(product_rules.get("precision_context_available")))
        reason = _phase_c_failure_reason(row)
        if reason in {"INVALID_PRICE_PRECISION", "INVALID_SIZE_PRECISION"}:
            precision_tickers[str(row.get("ticker") or submit.get("ticker") or payload.get("ticker") or "UNKNOWN")] += 1

    return {
        "phase": "orderbook_entry_opportunity_audit_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "live_submission_attempted": False,
        "env_mutation_performed": False,
        "state_mutation_performed": False,
        "since_requested": since,
        "since_parsed_utc": since_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z") if since_dt else "",
        "audit_window_valid": bool(not since or since_dt is not None),
        "stdout_valid": True,
        "rows": len(rows),
        "reason": no_data_reason,
        "no_data_reason": no_data_reason,
        "recommendation": recommendation,
        "data_sources_checked": data_sources_checked,
        "source_breakdown": source_breakdown,
        "source_type": "structured_jsonl",
        "journalctl_processed": False,
        "last_full_cycle_completed_at": last_full_cycle_completed_at.replace(microsecond=0).isoformat().replace("+00:00", "Z") if last_full_cycle_completed_at else "",
        "next_full_cycle_expected_at": _next_full_cycle_boundary(datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
        "decision_rows_total": len(rows),
        "phase_c_submit_rows_total": len(phase_c_submit_rows),
        "live_submission_attempted_count": sum(1 for row in phase_c_submit_rows if bool(row.get("live_submission_attempted"))),
        "live_order_submitted_count": sum(1 for row in phase_c_submit_rows if bool(row.get("live_order_submitted"))),
        "phase_c_submit_windows": phase_c_windows,
        "precision_context_audit": {
            "planner_judge_rows_with_product_rules": product_rules_rows,
            "planner_judge_rows_with_recent_exchange_rejections": recent_rejections_rows,
            "planner_judge_rows_with_execution_feasibility": execution_feasibility_rows,
            "precision_normalized_attempt_count": precision_normalized_attempts,
            "precision_context_missing_attempt_count": precision_context_missing_attempts,
            "invalid_price_precision_reject_count": precision_rejects.get("INVALID_PRICE_PRECISION", 0),
            "invalid_size_precision_reject_count": precision_rejects.get("INVALID_SIZE_PRECISION", 0),
            "precision_reject_tickers": dict(precision_tickers),
            "p0_missing_context": bool(rows and (product_rules_rows < len(rows) or execution_feasibility_rows < len(rows))),
        },
        "wait_no_setup": no_setup,
        "wait_trigger_not_ready_no_order": trigger_not_ready,
        "wait_do_not_chase_no_order": do_not_chase,
        "wait_trigger_not_ready": trigger_not_ready,
        "wait_do_not_chase": do_not_chase,
        "valid_trade_plans": valid_trade_plans,
        "setups_with_concrete_entrylevel": concrete_entry,
        "setups_with_invalidation": inv_count,
        "setups_with_target_or_exit_thesis": target_count,
        "resting_limit_entry_qualified": eligible,
        "prepare_resting_limit_entry_would_be": prepare_resting_limit_entry_would_be,
        "entry_decision_label_counts": dict(sorted(label_counts.items())),
        "top_tickers": dict(ticker_counts.most_common(10)),
        "top_setup_types": dict(setup_counts.most_common(10)),
        "not_qualified_reason_counts": dict(blocker_counts.most_common(20)),
        "near_orderbook_worthy_samples": near_miss,
        "current_entry_decision_flow": [
            "entry_gate/preselection finds analyze/watch/skip candidates",
            "trade_planner builds prepare_buy/prepare_reclaim plans when trigger/invalidation/zone exist",
            "final_judge currently returns approve_trade only when trigger is ready; trigger_not_ready remains wait",
            "read-only execution planner now turns eligible wait/do_not_chase retest plans into prepared resting limit BUY previews",
            "C4.3 risk snapshot accepts judge_approve_trade or eligible resting_entry_preview, then still checks BUY side, quote caps, orderbook freshness and open-order capacity",
            "C4.3 fill reconciliation/D1 links filled BUY to position",
            "D2 builds position exit plan from filled position, invalidation and targets",
            "D3 submits/monitors guarded limit SELL exits only with base/reservation evidence",
        ],
        "where_wait_originates": {
            "trigger_not_ready": "final judge sets decision=wait with trigger_wait_reason despite conditional plan",
            "do_not_chase": "judge/planner must_not_trade_if or reasons block immediate entry above fair/retest level",
            "no_setup": "trade_plan no_plan or missing concrete setup/risk fields",
        },
        "pending_limit_entry_technically_possible": eligible > 0 or concrete_entry > 0,
        "missing_fields_summary": {
            "missing_entry_level": len(rows) - concrete_entry,
            "missing_invalidation": len(rows) - inv_count,
            "missing_target": len(rows) - target_count,
        },
        "risks": [
            "Do not convert every wait into an order; require technical level, invalidation, target and reward gates.",
            "Resting limit entries can become stale and must be cancelled if setup invalidates or price moves away.",
            "C4.3 preview can prepare resting entries without approve_trade, but live submit remains disabled unless ENABLE_RESTING_LIMIT_ENTRY_LIVE_SUBMIT is separately enabled.",
            "No market orders should be introduced for this mode.",
        ],
        "concrete_patch_proposals": [
            "Use orderbook_entry_preview to classify trigger_not_ready rows as pending-limit candidates only when complete.",
            "Keep live submit disabled until ENABLE_RESTING_LIMIT_ENTRY_LIVE_SUBMIT and existing C4.3 ACK/config gates are separately approved.",
            "Add pending-entry lifecycle states: preview, submitted, monitored, stale/cancel, bounded replace, filled, D2/D3 handoff.",
            "Persist only after operator enables the mode; current audit is report-only.",
        ],
    }


def build_workflow_audit(opportunity: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "phase": "orderbook_entry_workflow_audit_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "current_entry_decision_flow": opportunity["current_entry_decision_flow"],
        "where_wait_originates": opportunity["where_wait_originates"],
        "post_deploy_counts": {
            "decision_rows_total": opportunity["decision_rows_total"],
            "wait_trigger_not_ready": opportunity["wait_trigger_not_ready"],
            "wait_do_not_chase": opportunity["wait_do_not_chase"],
            "valid_trade_plans": opportunity["valid_trade_plans"],
            "resting_limit_entry_qualified": opportunity["resting_limit_entry_qualified"],
            "prepare_resting_limit_entry_would_be": opportunity.get("prepare_resting_limit_entry_would_be", 0),
        },
        "pending_limit_entry_technically_possible": opportunity["pending_limit_entry_technically_possible"],
        "missing_fields_summary": opportunity["missing_fields_summary"],
        "risks": opportunity["risks"],
        "concrete_patch_proposals": opportunity["concrete_patch_proposals"],
        "lifecycle_model": [
            "pending_entry_created_preview",
            "live_submit_only_if_env_ack_operator_later_allows",
            "open_entry_order_monitored_each_cycle",
            "cancel_if_stale_or_invalidated",
            "replace_once_if_bounded_and_same_thesis",
            "fill_detected_by_d1_c43_reconciliation",
            "position_opened",
            "d2_exit_plan_generated",
            "d3_limit_exit_orders_placed_with_base_reservation",
            "controlled_stop_exit_route_remains_separate",
        ],
    }


def render_markdown(report: Dict[str, Any], *, title: str) -> str:
    lines = [
        f"# {title}",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Rows: `{report.get('decision_rows_total', (report.get('post_deploy_counts') or {}).get('decision_rows_total'))}`",
        "",
    ]
    for key in (
        "wait_no_setup",
        "wait_trigger_not_ready",
        "wait_do_not_chase",
        "valid_trade_plans",
        "setups_with_concrete_entrylevel",
        "setups_with_invalidation",
        "setups_with_target_or_exit_thesis",
        "resting_limit_entry_qualified",
    ):
        if key in report:
            lines.append(f"- {key}: {report.get(key)}")
    if "post_deploy_counts" in report:
        lines.append(json.dumps(report["post_deploy_counts"], indent=2, sort_keys=True))
    lines.extend(["", "## Top Blockers", json.dumps(report.get("not_qualified_reason_counts") or {}, indent=2, sort_keys=True)])
    lines.extend(["", "## Safety", "- read-only", "- no Coinbase submit/cancel/replace", "- no env/state mutation"])
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build read-only orderbook entry opportunity audit.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--since", default="")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root)
    opportunity = build_orderbook_entry_opportunity_audit(root=root, since=args.since)
    workflow = build_workflow_audit(opportunity)
    atomic_write_json(root / OPPORTUNITY_JSON_PATH, opportunity)
    atomic_write_json(root / WORKFLOW_JSON_PATH, workflow)
    (root / OPPORTUNITY_MD_PATH).parent.mkdir(parents=True, exist_ok=True)
    (root / OPPORTUNITY_MD_PATH).write_text(render_markdown(opportunity, title="Orderbook Entry Opportunity Audit"), encoding="utf-8")
    (root / WORKFLOW_MD_PATH).write_text(render_markdown(workflow, title="Orderbook Entry Workflow Audit"), encoding="utf-8")
    if args.json:
        print(json.dumps(opportunity, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
