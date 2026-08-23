#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bot.llm_clients import FINAL_JUDGE_REQUIRED_KEYS, normalize_final_judge_schema_aliases


APPROVAL_OBJECTIVE_THRESHOLD = 0.15


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
    dt = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _since_to_dt(value: str) -> Optional[datetime]:
    raw = str(value or "").strip()
    text = raw.lower()
    if not text:
        return None
    m = re.match(r"^(\d+)\s+hours?\s+ago$", text)
    if m:
        return datetime.now(timezone.utc) - timedelta(hours=int(m.group(1)))
    m = re.match(r"^(\d+)\s+days?\s+ago$", text)
    if m:
        return datetime.now(timezone.utc) - timedelta(days=int(m.group(1)))
    return _parse_time(raw)


def _row_time(row: Dict[str, Any]) -> Optional[datetime]:
    return _parse_time(row.get("generated_at") or row.get("timestamp") or row.get("created_at") or row.get("decision_time"))


def _latest_jsonl_time(path: Path) -> Optional[datetime]:
    latest: Optional[datetime] = None
    for row in _iter_jsonl(path):
        ts = _row_time(row)
        if ts and (latest is None or ts > latest):
            latest = ts
    return latest


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


def _next_full_cycle_boundary(now: datetime, interval_hours: int = 4) -> datetime:
    boundary = now.replace(minute=0, second=0, microsecond=0)
    if boundary <= now:
        boundary += timedelta(hours=1)
    while boundary.hour % max(1, interval_hours) != 0:
        boundary += timedelta(hours=1)
    return boundary


def _iter_jsonl(path: Path, since: Optional[datetime] = None, source_breakdown: Optional[Dict[str, Dict[str, int]]] = None) -> Iterable[Dict[str, Any]]:
    source_key = str(path)
    stats = {"seen": 0, "included": 0, "excluded_before_since": 0, "without_timestamp_excluded": 0}
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        if source_breakdown is not None:
            source_breakdown[source_key] = stats
        return []
    out: List[Dict[str, Any]] = []
    for line in lines:
        try:
            row = json.loads(line)
        except Exception:
            continue
        if not isinstance(row, dict):
            continue
        stats["seen"] += 1
        if since:
            ts = _row_time(row)
            if ts is None:
                stats["without_timestamp_excluded"] += 1
                continue
            if ts < since:
                stats["excluded_before_since"] += 1
                continue
        stats["included"] += 1
        out.append(row)
    if source_breakdown is not None:
        source_breakdown[source_key] = stats
    return out


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else ([] if value is None else [value])


def _counter_dict(counter: Counter) -> Dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _objective_score(row: Dict[str, Any]) -> Optional[float]:
    judge = _as_dict(row.get("judge"))
    judge, _aliases = normalize_final_judge_schema_aliases(judge)
    plan = _as_dict(row.get("trade_plan"))
    for value in (judge.get("objective_score"), plan.get("objective_score")):
        try:
            if value is not None and value != "":
                return float(value)
        except Exception:
            pass
    text = " ".join(str(x) for x in _as_list(judge.get("reasons")) + _as_list(plan.get("reason")))
    m = re.search(r"objective_score\s*=\s*(-?\d+(?:\.\d+)?)", text)
    return float(m.group(1)) if m else None


def _reason_text(judge: Dict[str, Any], plan: Dict[str, Any]) -> str:
    parts = (
        _as_list(judge.get("reasons"))
        + _as_list(judge.get("judge_reasons"))
        + _as_list(judge.get("must_reject_if"))
        + _as_list(plan.get("reason"))
        + _as_list(plan.get("no_plan_reason"))
        + _as_list(plan.get("hard_blockers"))
        + _as_list(plan.get("planner_blockers"))
    )
    for key in ("trigger_wait_reason", "judge_skip_reason", "strategy"):
        if judge.get(key):
            parts.append(judge.get(key))
    deduped = list(dict.fromkeys(str(part) for part in parts))
    return " | ".join(deduped).lower()


def _missing_required_keys_from_text(text: str) -> List[str]:
    out: List[str] = []
    for match in re.finditer(r"missing_required_keys:\s*\[([^\]]*)\]", text):
        for item in re.findall(r"'([^']+)'|\"([^\"]+)\"", match.group(1)):
            key = item[0] or item[1]
            if key:
                out.append(key)
    return out


def _has_required_judge_keys(judge: Dict[str, Any]) -> bool:
    normalized, _aliases = normalize_final_judge_schema_aliases(judge)
    return all(key in normalized and normalized.get(key) not in (None, "") for key in FINAL_JUDGE_REQUIRED_KEYS)


def _classify_wait(judge: Dict[str, Any], plan: Dict[str, Any], score: Optional[float]) -> str:
    text = _reason_text(judge, plan)
    if "trigger_not_ready" in text or "trigger not ready" in text or "1h close" in text or "confirmation close" in text:
        return "valid_wait_trigger_not_ready"
    if "do_not_chase" in text or "do not chase" in text or "chase" in text:
        return "valid_wait_do_not_chase"
    if "confirmation" in text or "confirm" in text or "volume confirmation" in text:
        return "valid_wait_insufficient_confirmation"
    if score is not None and score < APPROVAL_OBJECTIVE_THRESHOLD:
        return "valid_wait_objective_below_threshold"
    if score is not None and score >= APPROVAL_OBJECTIVE_THRESHOLD:
        return "judge_too_strict"
    return "valid_wait_insufficient_confirmation"


def _has_entry_zone(plan: Dict[str, Any], row: Dict[str, Any]) -> bool:
    if plan.get("entry_zone_low") not in (None, "") or plan.get("entry_zone_high") not in (None, ""):
        return True
    for key in ("trend", "meanrev"):
        item = _as_dict(row.get(key))
        if item.get("entry_zone_low") not in (None, "") or item.get("entry_zone_high") not in (None, ""):
            return True
    return False


def _has_invalidation(plan: Dict[str, Any], row: Dict[str, Any]) -> bool:
    if str(plan.get("invalidation") or plan.get("stop_loss") or "").strip():
        return True
    for key in ("synth", "breakout", "trend", "meanrev"):
        text = json.dumps(_as_dict(row.get(key)), sort_keys=True).lower()
        if "invalidation" in text or "stop" in text:
            return True
    return False


def _blocker_family(reason: str) -> str:
    text = reason.lower()
    if "spread" in text or "liquid" in text or "orderbook" in text:
        return "liquidity"
    if "invalidation" in text or "stop" in text:
        return "risk_defined"
    if "bull" in text or "bear" in text or "confidence" in text or "score" in text:
        return "preselection_score"
    if "plan" in text:
        return "planner"
    if "d2" in text or "edge" in text or "reward" in text:
        return "d2_risk"
    if "submit" in text or "phase_c" in text:
        return "execution"
    return "other"


def build_judge_funnel_audit(*, root: str | Path = ".", since: str = "") -> Dict[str, Any]:
    project_root = Path(root)
    since_dt = _since_to_dt(since)
    data_sources_checked = [
        "logs/analysis.jsonl",
        "logs/execution.jsonl",
        "logs/phase_c_guard.jsonl",
        "logs/phase_c43_live_entry_submitter.jsonl",
        "logs/phase_c_live_submit.jsonl",
        "logs/phase_c43_lifecycle_service.jsonl",
    ]
    source_breakdown: Dict[str, Dict[str, int]] = {}
    rows = list(_iter_jsonl(project_root / "logs/analysis.jsonl", since_dt, source_breakdown))
    execution_rows = list(_iter_jsonl(project_root / "logs/execution.jsonl", since_dt, source_breakdown))
    phase_c_rows = (
        list(_iter_jsonl(project_root / "logs/phase_c_guard.jsonl", since_dt, source_breakdown))
        + list(_iter_jsonl(project_root / "logs/phase_c43_live_entry_submitter.jsonl", since_dt, source_breakdown))
        + list(_iter_jsonl(project_root / "logs/phase_c_live_submit.jsonl", since_dt, source_breakdown))
    )
    lifecycle_rows = list(_iter_jsonl(project_root / "logs/phase_c43_lifecycle_service.jsonl", since_dt, source_breakdown))
    rows_seen_total = sum(item["seen"] for item in source_breakdown.values())
    rows_in_window = sum(item["included"] for item in source_breakdown.values())
    rows_excluded_before_since = sum(item["excluded_before_since"] for item in source_breakdown.values())
    rows_without_timestamp_excluded = sum(item["without_timestamp_excluded"] for item in source_breakdown.values())

    gate_counts = Counter()
    judge_skip = Counter()
    no_plan_reasons = Counter()
    no_plan_hard_blockers = Counter()
    d2_blockers = Counter()
    blocker_families = Counter()
    grouped: Dict[str, Dict[str, Dict[str, int]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(int)))
    expensive_called = 0
    expensive_not_called = 0
    no_plan = 0
    valid_plan = 0
    objective_present = 0
    objective_missing = 0
    final_decisions = Counter()
    audit_classifications = Counter()
    missing_required_keys = Counter()
    normalized_aliases = Counter()
    schema_failure_count = 0
    provider_fallback_count = 0
    valid_judge_response_count = 0
    invalid_judge_response_count = 0
    objective_present_after_normalization = 0
    objective_missing_after_normalization = 0
    post_trigger_objective_score_count = 0
    waits_high_objective_no_approve = 0
    waits_below_threshold = 0
    waits_trigger_not_ready_or_do_not_chase = 0
    raw_tickers = set()
    latest_cycle_tickers = set()
    bullish = bearish = entry_zone = invalidation = liquid = pending = trigger_true = trigger_false = 0
    planner_context_product_rules = planner_context_recent_rejections = planner_context_execution_feasibility = 0
    passed_to_mini = filtered_deepseek = sent_final = 0

    event_times = [ts for ts in (_row_time(row) for row in rows + execution_rows + phase_c_rows + lifecycle_rows) if ts is not None]
    first_event_time = min(event_times) if event_times else None
    last_event_time = max(event_times) if event_times else None
    latest_ts = max((_row_time(row) for row in rows), default=None)
    for row in rows:
        ticker = str(row.get("ticker") or _as_dict(row.get("feature_pack")).get("ticker") or "UNKNOWN")
        raw_tickers.add(ticker)
        row_ts = _row_time(row)
        if latest_ts and row_ts and row_ts == latest_ts:
            latest_cycle_tickers.add(ticker)
        gate = _as_dict(row.get("entry_gate") or _as_dict(row.get("feature_pack")).get("entry_gate"))
        decision = str(gate.get("decision") or "unknown").lower()
        gate_counts[decision] += 1
        plan = _as_dict(row.get("trade_plan"))
        judge = _as_dict(row.get("judge"))
        normalized_judge, row_aliases = normalize_final_judge_schema_aliases(judge)
        for alias in row_aliases + [str(a) for a in _as_list(judge.get("normalized_aliases"))]:
            normalized_aliases[alias] += 1
        setup = str(judge.get("setup_type") or gate.get("setup_type") or plan.get("setup_type") or "unknown")
        regime = str(_as_dict(row.get("regime")).get("regime_label") or "unknown")
        grouped[ticker][setup][regime] += 1
        bull_score = int(float(_as_dict(row.get("bull")).get("bull_case_score") or 0))
        bear_score = int(float(_as_dict(row.get("bear")).get("bear_case_score") or 0))
        bullish += int(bull_score > 0)
        bearish += int(bear_score >= bull_score and bear_score > 0)
        entry_zone += int(_has_entry_zone(plan, row))
        invalidation += int(_has_invalidation(plan, row))
        spread = _as_dict(_as_dict(row.get("feature_pack")).get("market")).get("spread_pct")
        try:
            liquid += int(spread is not None and float(spread) <= 0.006)
        except Exception:
            pass
        pending_ctx = _as_dict(row.get("pending_trade_plan") or _as_dict(_as_dict(row.get("feature_pack")).get("decision_context")).get("pending_trade_plan"))
        dc = _as_dict(_as_dict(row.get("feature_pack")).get("decision_context"))
        planner_context_product_rules += int(bool(dc.get("product_rules") or _as_dict(row.get("feature_pack")).get("product_rules") or _as_dict(row.get("feature_pack")).get("exchange_rules")))
        planner_context_recent_rejections += int(bool(dc.get("recent_exchange_rejections")))
        planner_context_execution_feasibility += int(bool(dc.get("execution_feasibility") or _as_dict(row.get("feature_pack")).get("execution_feasibility")))
        pending += int(bool(pending_ctx))
        trigger = bool(pending_ctx.get("trigger_ready") or pending_ctx.get("should_force_full_analysis"))
        trigger_true += int(trigger)
        trigger_false += int(not trigger)
        if decision in {"analyze", "priority_analyze", "watch"}:
            passed_to_mini += 1
        if decision in {"skip", "watch"}:
            filtered_deepseek += 1
        called = bool(judge.get("expensive_judge_called"))
        if not called and str(judge.get("strategy") or "") != "mini_analysis_screened_no_expensive_judge" and plan.get("source") != "trade_planner_skipped_by_expensive_judge_gate":
            called = bool(judge and str(judge.get("strategy") or "") not in {"", "mini_analysis_screened_no_expensive_judge"})
        expensive_called += int(called)
        expensive_not_called += int(not called)
        sent_final += int(called)
        action = str(plan.get("plan_action") or "no_plan").lower()
        no_plan += int(action == "no_plan")
        valid_plan += int(action != "no_plan")
        if action == "no_plan":
            reason = str(plan.get("no_plan_reason") or plan.get("reason") or "no_plan_reason_missing").strip() or "no_plan_reason_missing"
            no_plan_reasons[reason[:160]] += 1
            for blocker in _as_list(plan.get("hard_blockers")) or _as_list(plan.get("planner_blockers")):
                no_plan_hard_blockers[str(blocker)[:160]] += 1
        score = _objective_score({**row, "judge": normalized_judge})
        objective_present += int(score is not None)
        objective_missing += int(score is None)
        objective_present_after_normalization += int(score is not None)
        objective_missing_after_normalization += int(score is None)
        post_trigger_objective_score_count += int(normalized_judge.get("post_trigger_objective_score") not in (None, ""))
        final_decisions[str(normalized_judge.get("decision") or "unknown").lower()] += 1
        reasons = [str(x) for x in _as_list(judge.get("reasons")) + _as_list(judge.get("judge_reasons"))]
        reason_text = _reason_text(normalized_judge, plan)
        row_missing = _missing_required_keys_from_text(reason_text)
        for key in row_missing:
            missing_required_keys[key] += 1
        provider_failure = any(token in reason_text for token in (
            "judge providers failed",
            "provider unavailable",
            "anthropic_fallback_disabled",
            "fallback_disabled",
            "openai_gpt_5_5_failed",
            "anthropic_fallback_failed",
        ))
        schema_failure = "missing_required_keys" in reason_text or "judge_schema_failure" in reason_text or "json_response mislukt" in reason_text
        provider_fallback_count += int(provider_failure)
        schema_failure_count += int(schema_failure)
        valid_judge_response = bool(called and not provider_failure and not schema_failure and _has_required_judge_keys(normalized_judge))
        valid_judge_response_count += int(valid_judge_response)
        invalid_judge_response_count += int(called and not valid_judge_response)
        if called and schema_failure:
            audit_classifications["judge_schema_failure"] += 1
        elif called and provider_failure:
            audit_classifications["judge_provider_unavailable"] += 1
        elif called and str(normalized_judge.get("decision") or "").lower() == "wait" and valid_judge_response:
            wait_class = _classify_wait(normalized_judge, plan, score)
            audit_classifications[wait_class] += 1
            waits_high_objective_no_approve += int(score is not None and score >= APPROVAL_OBJECTIVE_THRESHOLD)
            waits_below_threshold += int(score is not None and score < APPROVAL_OBJECTIVE_THRESHOLD)
            waits_trigger_not_ready_or_do_not_chase += int(wait_class in {"valid_wait_trigger_not_ready", "valid_wait_do_not_chase"})
        skip_reason = str(judge.get("judge_skip_reason") or "")
        if not called and not skip_reason:
            skip_reason = next((r for r in reasons if "not_called" in r or "skipped" in r or "threshold" in r), "expensive_judge_not_called_reason_unknown")
        if not called:
            judge_skip[skip_reason] += 1
            blocker_families[_blocker_family(skip_reason)] += 1
        for reason in reasons + _as_list(plan.get("reason")):
            text = str(reason)
            if "d2" in text.lower() or "reward" in text.lower() or "edge" in text.lower():
                d2_blockers[text[:120]] += 1

    approve = final_decisions.get("approve_trade", 0)
    executed = sum(1 for row in execution_rows if bool(row.get("executed")) or str(row.get("status") or "").lower() in {"submitted", "filled"})
    phase_c_attempted = len(phase_c_rows)
    live_submitted = sum(
        1
        for row in phase_c_rows
        if bool(row.get("submitted"))
        or bool(row.get("live_order_submitted"))
        or str(row.get("status") or "").lower() in {"submitted", "accepted", "c43_autonomous_live_entry_submitted"}
    )
    live_submit_attempted = sum(1 for row in phase_c_rows if bool(row.get("live_submission_attempted")))
    fill_apply = sum(1 for row in lifecycle_rows if "apply" in json.dumps(row).lower() and ("filled" in json.dumps(row).lower() or "terminal" in json.dumps(row).lower()))

    unique_tickers = len(raw_tickers)
    latest_cycle_ticker_count = len(latest_cycle_tickers)
    decision_rows_total = len(rows)
    entry_candidate_rows = len(rows)
    planner_rows = len(rows)
    final_judge_event_rows = expensive_called + expensive_not_called
    preselection_drop_rate = expensive_not_called / max(1, entry_candidate_rows)
    final_reach = expensive_called / max(1, final_judge_event_rows)
    valid_rate = valid_plan / max(1, planner_rows)
    approve_rate = approve / max(1, expensive_called)
    raw_execution_rate = 0.0 if approve <= 0 else executed / approve
    execution_rate = min(1.0, raw_execution_rate)
    no_plan_drop = no_plan / max(1, planner_rows)
    audit_invariant_warnings: List[str] = []
    if raw_execution_rate > 1.0:
        audit_invariant_warnings.append(f"execution_rate_after_approve_clipped: executed={executed} approve_trade={approve}")
    if expensive_called > final_judge_event_rows:
        audit_invariant_warnings.append("final_judge_called_exceeds_final_judge_event_rows")
    if valid_plan > planner_rows:
        audit_invariant_warnings.append("valid_trade_plans_exceeds_planner_rows")
    if approve > expensive_called:
        audit_invariant_warnings.append("approve_trade_exceeds_final_judge_called")

    if since and since_dt and not rows:
        recommendation = "insufficient_new_data"
    else:
        substantial_schema_provider_failures = (schema_failure_count + provider_fallback_count) >= max(1, expensive_called // 3) and expensive_called > 0
    if since and since_dt and not rows:
        recommendation = "insufficient_new_data"
    elif substantial_schema_provider_failures:
        recommendation = "judge_schema_contract_failure"
    elif audit_classifications.get("valid_wait_trigger_not_ready", 0) or audit_classifications.get("valid_wait_do_not_chase", 0):
        recommendation = "market_wait_trigger_not_ready"
    elif audit_classifications.get("judge_too_strict", 0):
        recommendation = "judge_too_strict"
    elif audit_classifications.get("valid_wait_objective_below_threshold", 0):
        recommendation = "valid_wait_objective_below_threshold"
    elif final_reach < 0.20 and len(rows) >= 4:
        recommendation = "preselection_too_strict"
    elif no_plan_drop > 0.50:
        recommendation = "planner_handoff_too_strict"
    elif d2_blockers:
        recommendation = "d2_risk_too_strict"
    elif len(rows) and approve == 0 and bullish < max(1, len(rows) // 4):
        recommendation = "market_weak_correct_wait"
    else:
        recommendation = "insufficient_evidence" if len(rows) < 4 else "market_weak_correct_wait"

    last_full_cycle_completed_at = _latest_jsonl_time(project_root / "logs/cycle_summary.jsonl")
    now = datetime.now(timezone.utc)
    no_data_reason = ""
    if not rows:
        if since_dt and (last_full_cycle_completed_at is None or last_full_cycle_completed_at < since_dt):
            no_data_reason = "no_full_cycle_since_since_time"
            recommendation = "no_recent_full_cycle"
        elif since and since_dt is None:
            no_data_reason = "invalid_since_time"
        else:
            no_data_reason = "no_decision_rows_in_checked_sources"

    phase_c_windows = {
        "requested_window": _phase_c_submit_window(phase_c_rows),
        "since_last_full_cycle_completed": _phase_c_submit_window(phase_c_rows, last_full_cycle_completed_at),
    }
    precision_reject_counts = Counter(_phase_c_failure_reason(row) for row in phase_c_rows if _phase_c_failure_reason(row) in {"INVALID_PRICE_PRECISION", "INVALID_SIZE_PRECISION"})
    precision_normalized_attempts = 0
    precision_context_missing_attempts = 0
    precision_tickers = Counter()
    for row in phase_c_rows:
        submit = _as_dict(row.get("submit_result"))
        payload = _as_dict(submit.get("payload") or row.get("payload"))
        if payload.get("precision_normalization"):
            precision_normalized_attempts += 1
        product_rules = _as_dict(payload.get("product_rules") or payload.get("product_rules_used"))
        if not product_rules.get("precision_context_available"):
            precision_context_missing_attempts += 1
        reason = _phase_c_failure_reason(row)
        if reason in {"INVALID_PRICE_PRECISION", "INVALID_SIZE_PRECISION"}:
            precision_tickers[str(row.get("ticker") or submit.get("ticker") or payload.get("ticker") or "UNKNOWN")] += 1

    return {
        "phase": "judge_funnel_audit_v1",
        "generated_at": _now_iso(),
        "read_only": True,
        "coinbase_call_attempted": False,
        "since": since,
        "since_requested": since,
        "since_parsed_utc": since_dt.replace(microsecond=0).isoformat().replace("+00:00", "Z") if since_dt else "",
        "first_event_time_utc": first_event_time.replace(microsecond=0).isoformat().replace("+00:00", "Z") if first_event_time else "",
        "last_event_time_utc": last_event_time.replace(microsecond=0).isoformat().replace("+00:00", "Z") if last_event_time else "",
        "rows_seen_total": rows_seen_total,
        "rows_in_window": rows_in_window,
        "rows_excluded_before_since": rows_excluded_before_since,
        "rows_without_timestamp_excluded": rows_without_timestamp_excluded,
        "rows": decision_rows_total,
        "stdout_valid": True,
        "data_sources_checked": data_sources_checked,
        "source_type": "structured_jsonl",
        "journalctl_processed": False,
        "no_data_reason": no_data_reason,
        "reason": no_data_reason,
        "last_full_cycle_completed_at": last_full_cycle_completed_at.replace(microsecond=0).isoformat().replace("+00:00", "Z") if last_full_cycle_completed_at else "",
        "next_full_cycle_expected_at": _next_full_cycle_boundary(now).isoformat().replace("+00:00", "Z"),
        "source_breakdown": source_breakdown,
        "audit_window_valid": bool(not since or since_dt is not None),
        "audit_invariant_warnings": audit_invariant_warnings,
        "unique_tickers": unique_tickers,
        "latest_cycle_tickers": latest_cycle_ticker_count,
        "decision_rows_total": decision_rows_total,
        "entry_candidate_rows": entry_candidate_rows,
        "planner_rows": planner_rows,
        "final_judge_event_rows": final_judge_event_rows,
        "final_judge_called": expensive_called,
        "final_judge_not_called": expensive_not_called,
        "valid_trade_plans": valid_plan,
        "no_plan": no_plan,
        "objective_score_extracted": objective_present,
        "objective_score_missing": objective_missing,
        "schema_failure_count": schema_failure_count,
        "provider_fallback_count": provider_fallback_count,
        "missing_required_keys_count_by_key": _counter_dict(missing_required_keys),
        "normalized_alias_count_by_alias": _counter_dict(normalized_aliases),
        "valid_judge_response_count": valid_judge_response_count,
        "invalid_judge_response_count": invalid_judge_response_count,
        "objective_score_present_after_normalization": objective_present_after_normalization,
        "objective_score_missing_after_normalization": objective_missing_after_normalization,
        "post_trigger_objective_score_count": post_trigger_objective_score_count,
        "waits_with_objective_score_gte_approval_threshold_no_approve": waits_high_objective_no_approve,
        "waits_with_objective_score_below_threshold": waits_below_threshold,
        "waits_caused_by_trigger_not_ready_or_do_not_chase": waits_trigger_not_ready_or_do_not_chase,
        "audit_classification_counts": _counter_dict(audit_classifications),
        "raw_ticker_candidates": unique_tickers,
        "gate_counts": _counter_dict(gate_counts),
        "candidates_with_bullish_evidence": bullish,
        "candidates_with_bearish_warning": bearish,
        "candidates_with_valid_entry_zone": entry_zone,
        "candidates_with_defined_invalidation": invalidation,
        "candidates_with_acceptable_spread_liquidity": liquid,
        "candidates_with_pending_intent": pending,
        "trigger_ready_true": trigger_true,
        "trigger_ready_false": trigger_false,
        "candidates_passed_to_mini_analysis": passed_to_mini,
        "candidates_filtered_by_deepseek_pre_gate": filtered_deepseek,
        "candidates_sent_to_final_expensive_judge": sent_final,
        "expensive_judge_called_count": expensive_called,
        "expensive_judge_not_called_count": expensive_not_called,
        "judge_skip_reason_counts": _counter_dict(judge_skip),
        "no_plan_reason_counts": _counter_dict(no_plan_reasons),
        "no_plan_hard_blocker_counts": _counter_dict(no_plan_hard_blockers),
        "no_plan_count": no_plan,
        "valid_trade_plan_count": valid_plan,
        "objective_score_extracted_count": objective_present,
        "objective_score_missing_count": objective_missing,
        "final_judge_decision_counts": _counter_dict(final_decisions),
        "d2_plan_built_count": sum(1 for row in rows if "d2" in json.dumps(row).lower() and "plan" in json.dumps(row).lower()),
        "d2_blocker_counts": _counter_dict(d2_blockers),
        "phase_c_submit_attempted_count": phase_c_attempted,
        "phase_c_live_submission_attempted_count": live_submit_attempted,
        "phase_c_live_order_submitted_count": live_submitted,
        "phase_c_submit_windows": phase_c_windows,
        "precision_context_audit": {
            "planner_judge_rows_with_product_rules": planner_context_product_rules,
            "planner_judge_rows_with_recent_exchange_rejections": planner_context_recent_rejections,
            "planner_judge_rows_with_execution_feasibility": planner_context_execution_feasibility,
            "precision_normalized_attempt_count": precision_normalized_attempts,
            "precision_context_missing_attempt_count": precision_context_missing_attempts,
            "invalid_price_precision_reject_count": precision_reject_counts.get("INVALID_PRICE_PRECISION", 0),
            "invalid_size_precision_reject_count": precision_reject_counts.get("INVALID_SIZE_PRECISION", 0),
            "precision_reject_tickers": _counter_dict(precision_tickers),
            "p0_missing_context": bool(decision_rows_total and (planner_context_product_rules < decision_rows_total or planner_context_execution_feasibility < decision_rows_total)),
        },
        "fill_apply_count": fill_apply,
        "blocker_family_counts": _counter_dict(blocker_families),
        "grouped_by_ticker_setup_regime": grouped,
        "ratios": {
            "final_judge_reach_rate": final_reach,
            "valid_plan_rate": valid_rate,
            "approve_rate_after_judge": approve_rate,
            "execution_rate_after_approve": execution_rate,
            "preselection_drop_rate": preselection_drop_rate,
            "no_plan_drop_rate": no_plan_drop,
        },
        "ratio_denominators": {
            "final_judge_reach_rate": "final_judge_event_rows",
            "valid_plan_rate": "planner_rows",
            "approve_rate_after_judge": "final_judge_called",
            "execution_rate_after_approve": "approve",
            "preselection_drop_rate": "entry_candidate_rows",
            "no_plan_drop_rate": "planner_rows",
        },
        "recommendation": recommendation,
    }


def render_markdown(report: Dict[str, Any]) -> str:
    ratios = report.get("ratios") if isinstance(report.get("ratios"), dict) else {}
    denominators = report.get("ratio_denominators") if isinstance(report.get("ratio_denominators"), dict) else {}
    lines = [
        "# Judge Funnel Audit",
        "",
        f"Generated: `{report.get('generated_at')}`",
        f"Recommendation: `{report.get('recommendation')}`",
        "",
        "## Window",
        f"- since_requested: `{report.get('since_requested')}`",
        f"- since_parsed_utc: `{report.get('since_parsed_utc')}`",
        f"- rows_seen_total: {report.get('rows_seen_total')}",
        f"- rows_in_window: {report.get('rows_in_window')}",
        f"- rows_excluded_before_since: {report.get('rows_excluded_before_since')}",
        f"- rows_without_timestamp_excluded: {report.get('rows_without_timestamp_excluded')}",
        f"- audit_window_valid: {report.get('audit_window_valid')}",
        "",
        *([f"WARNING: no rows were found after `{report.get('since_requested')}`; recommendation is `insufficient_new_data`."] if report.get("recommendation") == "insufficient_new_data" else []),
        *([f"WARNING: {warning}" for warning in report.get("audit_invariant_warnings") or []]),
        "",
        "## Counts",
        f"- unique_tickers: {report.get('unique_tickers')}",
        f"- latest_cycle_tickers: {report.get('latest_cycle_tickers')}",
        f"- decision_rows_total: {report.get('decision_rows_total')}",
        f"- entry_candidate_rows: {report.get('entry_candidate_rows')}",
        f"- planner_rows: {report.get('planner_rows')}",
        f"- final_judge_event_rows: {report.get('final_judge_event_rows')}",
        f"- final_judge_called: {report.get('final_judge_called')}",
        f"- final_judge_not_called: {report.get('final_judge_not_called')}",
        f"- valid_trade_plans: {report.get('valid_trade_plans')}",
        f"- no_plan: {report.get('no_plan')}",
        f"- objective_score_extracted: {report.get('objective_score_extracted')}",
        f"- objective_score_missing: {report.get('objective_score_missing')}",
        f"- schema_failure_count: {report.get('schema_failure_count')}",
        f"- provider_fallback_count: {report.get('provider_fallback_count')}",
        f"- valid_judge_response_count: {report.get('valid_judge_response_count')}",
        f"- invalid_judge_response_count: {report.get('invalid_judge_response_count')}",
        f"- objective_score_present_after_normalization: {report.get('objective_score_present_after_normalization')}",
        f"- objective_score_missing_after_normalization: {report.get('objective_score_missing_after_normalization')}",
        f"- post_trigger_objective_score_count: {report.get('post_trigger_objective_score_count')}",
        "",
        "## Ratios",
    ]
    for key, value in ratios.items():
        lines.append(f"- `{key}`: {float(value):.4f} (denominator: `{denominators.get(key, 'unknown')}`)")
    lines.extend(["", "## Skip Reasons"])
    skips = report.get("judge_skip_reason_counts") or {}
    lines.extend([f"- `{k}`: {v}" for k, v in skips.items()] or ["- none"])
    lines.extend(["", "## No Plan Reasons"])
    no_plan_reasons = report.get("no_plan_reason_counts") or {}
    lines.extend([f"- `{k}`: {v}" for k, v in no_plan_reasons.items()] or ["- none"])
    lines.extend(["", "## Schema"])
    missing = report.get("missing_required_keys_count_by_key") or {}
    lines.extend(["Missing required keys:"] + ([f"- `{k}`: {v}" for k, v in missing.items()] or ["- none"]))
    aliases = report.get("normalized_alias_count_by_alias") or {}
    lines.extend(["", "Normalized aliases:"] + ([f"- `{k}`: {v}" for k, v in aliases.items()] or ["- none"]))
    classes = report.get("audit_classification_counts") or {}
    lines.extend(["", "Audit classifications:"] + ([f"- `{k}`: {v}" for k, v in classes.items()] or ["- none"]))
    return "\n".join(lines) + "\n"


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build read-only judge funnel audit from local logs.")
    parser.add_argument("--root", default=".")
    parser.add_argument("--since", default="")
    parser.add_argument("--json-out")
    parser.add_argument("--md-out")
    parser.add_argument("--json", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    report = build_judge_funnel_audit(root=args.root, since=args.since)
    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.md_out:
        path = Path(args.md_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(render_markdown(report), encoding="utf-8")
    if args.json or not (args.json_out or args.md_out):
        print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
