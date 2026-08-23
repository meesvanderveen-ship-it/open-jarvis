from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


ENTRY_PLAN_ACTIONS = {
    "prepare_buy",
    "prepare_reclaim",
    "prepare_breakout",
    "prepare_mean_reversion",
}

FINAL_STATUSES = {"expired", "invalidated", "cancelled", "executed", "replaced"}
ACTIVE_STATUSES = {"active", "waiting", "trigger_ready"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    if d.is_nan() or d.is_infinite():
        return None
    return d


def _to_float(value: Any) -> Optional[float]:
    d = _to_decimal(value)
    if d is None:
        return None
    return float(d)


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def extract_current_price(feature_pack: Dict[str, Any]) -> Optional[float]:
    if not isinstance(feature_pack, dict):
        return None

    candidates = [
        feature_pack.get("current_price"),
        feature_pack.get("price"),
        feature_pack.get("last_price"),
        feature_pack.get("mid_price"),
        (feature_pack.get("orderbook_context") or {}).get("mid_price"),
        ((feature_pack.get("indicators") or {}).get("1h") or {}).get("close"),
        ((feature_pack.get("indicators") or {}).get("4h") or {}).get("close"),
        ((feature_pack.get("raw_context") or {}).get("1h") or {}).get("latest_close"),
        ((feature_pack.get("raw_context") or {}).get("4h") or {}).get("latest_close"),
    ]
    for item in candidates:
        d = _to_decimal(item)
        if d is not None and d > 0:
            return float(d)
    return None


def _distance_pct(price: Optional[float], level: Any) -> Optional[float]:
    if price is None or price <= 0:
        return None
    level_d = _to_decimal(level)
    if level_d is None or level_d <= 0:
        return None
    try:
        return float(((Decimal(str(price)) - level_d) / Decimal(str(price))) * Decimal("100"))
    except Exception:
        return None


def _entry_action(action: Any) -> bool:
    return str(action or "").strip().lower() in ENTRY_PLAN_ACTIONS


def _safe_plan_snapshot(plan: Dict[str, Any]) -> Dict[str, Any]:
    keys = [
        "plan_action",
        "ticker",
        "setup_type",
        "entry_zone_low",
        "entry_zone_high",
        "trigger",
        "do_not_chase_above",
        "stop_loss",
        "take_profit_1",
        "take_profit_2",
        "invalidation",
        "max_size_quote",
        "monitoring_rules",
        "confidence",
        "must_not_trade_if",
        "reason",
        "source",
        "pattern_alignment",
    ]
    return {key: _json_safe(plan.get(key)) for key in keys if key in plan}


def build_default_pending_context(ticker: Optional[str] = None, reason: str = "no_active_pending_plan") -> Dict[str, Any]:
    return {
        "enabled": True,
        "ticker": _normalize_ticker(ticker),
        "has_active_plan": False,
        "status": "none",
        "trigger_ready": False,
        "should_force_full_analysis": False,
        "plan": {},
        "evaluation": {
            "status": "none",
            "reason": reason,
            "reasons": [reason],
            "current_price": None,
        },
        "safety_policy": (
            "Pending plans are monitoring context only. A trigger may promote a ticker to fresh analysis, "
            "but never authorizes execution without a new GPT-5.5 judge decision and deterministic risk checks."
        ),
    }


def normalize_pending_trade_plan(
    *,
    ticker: str,
    trade_plan: Dict[str, Any],
    judge: Optional[Dict[str, Any]] = None,
    chart_patterns: Optional[Dict[str, Any]] = None,
    recent_reflections: Optional[Dict[str, Any]] = None,
    ttl_hours: int = 24,
    source: str = "strategy_engine",
    now: Optional[datetime] = None,
) -> Optional[Dict[str, Any]]:
    if not isinstance(trade_plan, dict):
        return None

    action = str(trade_plan.get("plan_action", "no_plan")).strip().lower()
    if not _entry_action(action):
        return None

    normalized_ticker = _normalize_ticker(ticker or trade_plan.get("ticker"))
    if not normalized_ticker:
        return None

    created = now or _now_utc()
    ttl = max(1, int(ttl_hours or 24))
    expires = created + timedelta(hours=ttl)

    plan_id = f"{normalized_ticker}:{created.strftime('%Y%m%dT%H%M%SZ')}:{action}"
    best_pattern = {}
    if isinstance(chart_patterns, dict):
        patterns = chart_patterns.get("patterns")
        if isinstance(patterns, list) and patterns:
            best_pattern = deepcopy(patterns[0]) if isinstance(patterns[0], dict) else {}

    confidence = int(max(0, min(100, int(float(trade_plan.get("confidence") or 0)))))

    return {
        "plan_id": plan_id,
        "ticker": normalized_ticker,
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "status": "active",
        "source": source,
        "trade_plan": _safe_plan_snapshot(trade_plan),
        "judge_snapshot": _json_safe({
            "decision": (judge or {}).get("decision"),
            "confidence": (judge or {}).get("confidence"),
            "strategy": (judge or {}).get("strategy"),
            "reasons": _as_list((judge or {}).get("reasons"))[:8],
        }),
        "pattern_snapshot": _json_safe({
            "pattern_bias": (chart_patterns or {}).get("pattern_bias"),
            "best_pattern_score": (chart_patterns or {}).get("best_pattern_score"),
            "best_pattern": best_pattern,
            "market_structure": (chart_patterns or {}).get("market_structure", {}),
        }),
        "reflection_snapshot": _json_safe({
            "sample_strength": (recent_reflections or {}).get("sample_strength"),
            "overfit_warning": (recent_reflections or {}).get("overfit_warning"),
            "weighted_context_signals": (recent_reflections or {}).get("weighted_context_signals", [])[:3],
        }),
        "confidence": confidence,
        "evaluation_history": [],
        "safety_policy": (
            "Monitor only. Do not execute from this pending plan directly; trigger requires fresh analysis, "
            "fresh final judge approval, and deterministic risk/firewall checks."
        ),
    }


def evaluate_pending_plan(
    plan: Dict[str, Any],
    feature_pack: Dict[str, Any],
    *,
    now: Optional[datetime] = None,
    max_chase_distance_pct: Decimal = Decimal("0.0200"),
) -> Dict[str, Any]:
    current_dt = now or _now_utc()
    ticker = _normalize_ticker(plan.get("ticker"))
    tp = plan.get("trade_plan") or {}
    if not isinstance(tp, dict):
        tp = {}

    reasons: List[str] = []
    expires_at = _parse_dt(plan.get("expires_at"))
    current_price = extract_current_price(feature_pack)

    if str(plan.get("status", "active")).lower() in FINAL_STATUSES:
        return {
            "ticker": ticker,
            "status": str(plan.get("status")),
            "trigger_ready": False,
            "should_force_full_analysis": False,
            "current_price": current_price,
            "reason": "plan_already_final",
            "reasons": ["plan_already_final"],
        }

    if expires_at is not None and current_dt >= expires_at:
        return {
            "ticker": ticker,
            "status": "expired",
            "trigger_ready": False,
            "should_force_full_analysis": False,
            "current_price": current_price,
            "reason": "pending_plan_expired",
            "reasons": ["pending_plan_expired"],
        }

    if current_price is None:
        return {
            "ticker": ticker,
            "status": "waiting",
            "trigger_ready": False,
            "should_force_full_analysis": False,
            "current_price": None,
            "reason": "current_price_unavailable",
            "reasons": ["current_price_unavailable"],
        }

    price_d = Decimal(str(current_price))
    low = _to_decimal(tp.get("entry_zone_low"))
    high = _to_decimal(tp.get("entry_zone_high"))
    chase = _to_decimal(tp.get("do_not_chase_above"))
    stop = _to_decimal(tp.get("stop_loss"))

    if low is not None and high is not None and low > high:
        low, high = high, low

    if stop is not None and stop > 0 and price_d <= stop:
        return {
            "ticker": ticker,
            "status": "invalidated",
            "trigger_ready": False,
            "should_force_full_analysis": False,
            "current_price": current_price,
            "reason": "price_at_or_below_stop_loss_invalidation",
            "reasons": ["price_at_or_below_stop_loss_invalidation"],
        }

    if chase is not None and chase > 0 and price_d > chase:
        chase_distance = ((price_d - chase) / price_d) if price_d > 0 else Decimal("0")
        if chase_distance > max_chase_distance_pct:
            return {
                "ticker": ticker,
                "status": "invalidated",
                "trigger_ready": False,
                "should_force_full_analysis": False,
                "current_price": current_price,
                "reason": "price_moved_too_far_above_do_not_chase_level",
                "reasons": ["price_moved_too_far_above_do_not_chase_level"],
                "distance_above_do_not_chase_pct": float(chase_distance * Decimal("100")),
            }
        reasons.append("price_above_do_not_chase_level_requires_fresh_judge_review")

    in_entry_zone = False
    if low is not None and high is not None and low > 0 and high > 0:
        in_entry_zone = low <= price_d <= high
    elif low is not None and low > 0:
        in_entry_zone = price_d >= low
    elif high is not None and high > 0:
        in_entry_zone = price_d <= high

    if in_entry_zone:
        reasons.append("current_price_inside_pending_entry_zone")
        return {
            "ticker": ticker,
            "status": "trigger_ready",
            "trigger_ready": True,
            "should_force_full_analysis": True,
            "current_price": current_price,
            "reason": "pending_plan_trigger_ready_requires_fresh_analysis",
            "reasons": reasons,
            "distance_to_entry_low_pct": _distance_pct(current_price, low),
            "distance_to_entry_high_pct": _distance_pct(current_price, high),
        }

    if low is not None and price_d < low:
        reasons.append("current_price_below_entry_zone_waiting")
    elif high is not None and price_d > high:
        reasons.append("current_price_above_entry_zone_waiting_or_chasing_risk")
    else:
        reasons.append("entry_zone_not_numeric_waiting_for_llm_trigger_context")

    return {
        "ticker": ticker,
        "status": "waiting",
        "trigger_ready": False,
        "should_force_full_analysis": False,
        "current_price": current_price,
        "reason": reasons[0] if reasons else "pending_plan_waiting",
        "reasons": reasons or ["pending_plan_waiting"],
        "distance_to_entry_low_pct": _distance_pct(current_price, low),
        "distance_to_entry_high_pct": _distance_pct(current_price, high),
    }


def _status_sort_key(status: Any) -> int:
    order = {
        "trigger_ready": 0,
        "active": 1,
        "waiting": 2,
        "invalidated": 3,
        "expired": 4,
        "cancelled": 5,
        "replaced": 6,
        "executed": 7,
    }
    return order.get(str(status or "").strip().lower(), 99)


def _hours_until(value: Any, now: Optional[datetime] = None) -> Optional[float]:
    dt = _parse_dt(value)
    if dt is None:
        return None
    current = now or _now_utc()
    return round((dt - current).total_seconds() / 3600.0, 3)


def _last_evaluation(plan: Dict[str, Any]) -> Dict[str, Any]:
    history = plan.get("evaluation_history")
    if isinstance(history, list) and history:
        last = history[-1]
        if isinstance(last, dict):
            return deepcopy(last)
    return {}


def build_pending_plan_observability(
    plans: List[Dict[str, Any]],
    *,
    include_final: bool = True,
    now: Optional[datetime] = None,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    """Build a compact audit/observability summary for pending trade plans.

    This function is intentionally read-only and deterministic. It does not
    evaluate triggers, modify state, place orders, or call any exchange/LLM API.
    """
    current = now or _now_utc()
    clean_plans = [p for p in plans if isinstance(p, dict)]
    if not include_final:
        clean_plans = [p for p in clean_plans if str(p.get("status", "active")).lower() not in FINAL_STATUSES]

    status_counts: Dict[str, int] = {}
    ticker_counts: Dict[str, int] = {}
    actionable: List[Dict[str, Any]] = []
    active: List[Dict[str, Any]] = []
    final: List[Dict[str, Any]] = []

    for plan in clean_plans:
        status = str(plan.get("status", "active") or "active").strip().lower()
        ticker = _normalize_ticker(plan.get("ticker"))
        status_counts[status] = status_counts.get(status, 0) + 1
        if ticker:
            ticker_counts[ticker] = ticker_counts.get(ticker, 0) + 1

        tp = plan.get("trade_plan") if isinstance(plan.get("trade_plan"), dict) else {}
        last_eval = _last_evaluation(plan)
        item = {
            "plan_id": plan.get("plan_id"),
            "ticker": ticker,
            "status": status,
            "plan_action": tp.get("plan_action"),
            "setup_type": tp.get("setup_type"),
            "confidence": plan.get("confidence", tp.get("confidence")),
            "created_at": plan.get("created_at"),
            "updated_at": plan.get("updated_at"),
            "expires_at": plan.get("expires_at"),
            "hours_until_expiry": _hours_until(plan.get("expires_at"), current),
            "entry_zone_low": tp.get("entry_zone_low"),
            "entry_zone_high": tp.get("entry_zone_high"),
            "do_not_chase_above": tp.get("do_not_chase_above"),
            "stop_loss": tp.get("stop_loss"),
            "trigger": tp.get("trigger"),
            "invalidation": tp.get("invalidation"),
            "last_evaluation_status": last_eval.get("status"),
            "last_evaluation_reason": last_eval.get("reason"),
            "last_evaluated_at": last_eval.get("evaluated_at"),
            "current_price_at_last_eval": last_eval.get("current_price"),
            "requires_fresh_judge_and_risk": True,
            "safety_policy": plan.get("safety_policy"),
        }
        if status == "trigger_ready":
            actionable.append(item)
        elif status not in FINAL_STATUSES:
            active.append(item)
        else:
            final.append(item)

    actionable.sort(key=lambda x: (str(x.get("ticker") or ""), str(x.get("updated_at") or "")))
    active.sort(key=lambda x: (_status_sort_key(x.get("status")), x.get("hours_until_expiry") if x.get("hours_until_expiry") is not None else 999999, str(x.get("ticker") or "")))
    final.sort(key=lambda x: str(x.get("updated_at") or ""), reverse=True)

    if limit is not None and limit > 0:
        actionable = actionable[:limit]
        active = active[:limit]
        final = final[:limit]

    return {
        "generated_at": current.isoformat(),
        "total_plans": len(clean_plans),
        "active_count": len(active),
        "trigger_ready_count": len(actionable),
        "final_count": len(final),
        "status_counts": dict(sorted(status_counts.items())),
        "ticker_counts": dict(sorted(ticker_counts.items())),
        "actionable_trigger_ready": actionable,
        "active_or_waiting": active,
        "final_recent": final,
        "safety_policy": (
            "Observability only. Pending plans and trigger_ready states never authorize execution; "
            "they only explain why a ticker may be promoted to fresh GPT-5.5 planner/judge analysis."
        ),
    }


class PendingTradePlanStore:
    def __init__(
        self,
        path: str | Path = "state/pending_trade_plans.json",
        *,
        max_records: int = 200,
        ttl_hours: int = 24,
        enabled: bool = True,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_records = max(1, int(max_records))
        self.ttl_hours = max(1, int(ttl_hours))
        self.enabled = bool(enabled)

    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, dict):
            records = payload.get("plans", [])
        else:
            records = payload
        if not isinstance(records, list):
            return []
        return [r for r in records if isinstance(r, dict)]

    def _write_all(self, plans: List[Dict[str, Any]]) -> None:
        plans = plans[-self.max_records:]
        payload = {
            "updated_at": _now_iso(),
            "plans": _json_safe(plans),
        }
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)

    def list_plans(self, include_final: bool = True) -> List[Dict[str, Any]]:
        plans = self._read_all()
        if include_final:
            return plans
        return [p for p in plans if str(p.get("status", "active")).lower() not in FINAL_STATUSES]

    def get_active_plan(self, ticker: str) -> Optional[Dict[str, Any]]:
        t = _normalize_ticker(ticker)
        candidates = [
            p for p in self._read_all()
            if _normalize_ticker(p.get("ticker")) == t and str(p.get("status", "active")).lower() not in FINAL_STATUSES
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda p: str(p.get("created_at", "")), reverse=True)
        return candidates[0]

    def observability_summary(
        self,
        *,
        include_final: bool = True,
        limit: Optional[int] = None,
    ) -> Dict[str, Any]:
        return build_pending_plan_observability(
            self._read_all(),
            include_final=include_final,
            limit=limit,
        )

    def active_status_counts(self) -> Dict[str, int]:
        summary = self.observability_summary(include_final=False)
        return dict(summary.get("status_counts") or {})

    def store_plan(
        self,
        *,
        ticker: str,
        trade_plan: Dict[str, Any],
        judge: Optional[Dict[str, Any]] = None,
        chart_patterns: Optional[Dict[str, Any]] = None,
        recent_reflections: Optional[Dict[str, Any]] = None,
        source: str = "strategy_engine",
    ) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        plan = normalize_pending_trade_plan(
            ticker=ticker,
            trade_plan=trade_plan,
            judge=judge,
            chart_patterns=chart_patterns,
            recent_reflections=recent_reflections,
            ttl_hours=self.ttl_hours,
            source=source,
        )
        if plan is None:
            return None

        plans = self._read_all()
        # Keep one active pending entry plan per ticker. Replace older active plans;
        # this avoids contradictory triggers and stale duplicate monitoring.
        for existing in plans:
            if _normalize_ticker(existing.get("ticker")) == plan["ticker"] and str(existing.get("status", "active")).lower() not in FINAL_STATUSES:
                existing["status"] = "replaced"
                existing["updated_at"] = plan["created_at"]
                existing.setdefault("evaluation_history", []).append({
                    "evaluated_at": plan["created_at"],
                    "status": "replaced",
                    "reason": "replaced_by_newer_pending_plan_for_same_ticker",
                })
        plans.append(plan)
        self._write_all(plans)
        return deepcopy(plan)

    def update_plan_status(self, plan_id: str, status: str, reason: str, extra: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        if not plan_id:
            return None
        plans = self._read_all()
        found: Optional[Dict[str, Any]] = None
        now = _now_iso()
        for plan in plans:
            if str(plan.get("plan_id")) == str(plan_id):
                plan["status"] = status
                plan["updated_at"] = now
                event = {"evaluated_at": now, "status": status, "reason": reason}
                if extra:
                    event.update(_json_safe(extra))
                plan.setdefault("evaluation_history", []).append(event)
                found = deepcopy(plan)
                break
        self._write_all(plans)
        return found

    def cancel_plan(self, ticker: str, reason: str = "cancelled") -> Optional[Dict[str, Any]]:
        plan = self.get_active_plan(ticker)
        if not plan:
            return None
        return self.update_plan_status(str(plan.get("plan_id")), "cancelled", reason)

    def evaluate_ticker(
        self,
        ticker: str,
        feature_pack: Dict[str, Any],
        *,
        max_chase_distance_pct: Decimal = Decimal("0.0200"),
    ) -> Dict[str, Any]:
        if not self.enabled:
            ctx = build_default_pending_context(ticker, reason="pending_trade_plans_disabled")
            ctx["enabled"] = False
            return ctx

        plan = self.get_active_plan(ticker)
        if not plan:
            return build_default_pending_context(ticker)

        evaluation = evaluate_pending_plan(
            plan,
            feature_pack,
            max_chase_distance_pct=max_chase_distance_pct,
        )
        status = str(evaluation.get("status", "waiting"))
        if status in FINAL_STATUSES:
            self.update_plan_status(str(plan.get("plan_id")), status, str(evaluation.get("reason", status)), evaluation)
            plan = self.get_active_plan(ticker) or plan
        elif status == "trigger_ready":
            self.update_plan_status(str(plan.get("plan_id")), "trigger_ready", str(evaluation.get("reason", status)), evaluation)
            plan = self.get_active_plan(ticker) or plan
        elif status == "waiting":
            # Persist lightweight evaluation for audit, but keep the plan active.
            self.update_plan_status(str(plan.get("plan_id")), "waiting", str(evaluation.get("reason", status)), evaluation)
            plan = self.get_active_plan(ticker) or plan

        return {
            "enabled": True,
            "ticker": _normalize_ticker(ticker),
            "has_active_plan": status not in FINAL_STATUSES,
            "status": status,
            "trigger_ready": bool(evaluation.get("trigger_ready", False)),
            "should_force_full_analysis": bool(evaluation.get("should_force_full_analysis", False)),
            "plan": _json_safe(plan),
            "evaluation": _json_safe(evaluation),
            "safety_policy": build_default_pending_context(ticker)["safety_policy"],
        }
