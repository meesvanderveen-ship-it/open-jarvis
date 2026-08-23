from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, List, Optional

from bot.atomic_io import atomic_write_json

DEFAULT_PATH = Path("state/opportunity_memory.json")
ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value in (None, ""):
            return Decimal(default)
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _iso(value)
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe(v) for v in value]
    return value


def load_opportunity_memory(path: str | Path = DEFAULT_PATH) -> Dict[str, Any]:
    p = Path(path)
    if not p.exists():
        return {"version": 1, "opportunities": []}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"version": 1, "opportunities": []}
    if not isinstance(data, dict):
        return {"version": 1, "opportunities": []}
    items = data.get("opportunities")
    data["opportunities"] = [x for x in items if isinstance(x, dict)] if isinstance(items, list) else []
    data.setdefault("version", 1)
    return data


def save_opportunity_memory(data: Dict[str, Any], path: str | Path = DEFAULT_PATH) -> Path:
    return atomic_write_json(Path(path), _safe(data), sort_keys=True)


def build_opportunity_from_analysis(
    *,
    ticker: str,
    analysis: Dict[str, Any],
    source_decision_id: str = "",
    ttl_minutes: int = 240,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Create a report-only opportunity record from a wait/prepared setup.

    This does not submit or authorize orders. Promotion is objective only:
    current price must cross trigger_level without invalidating the setup first.
    """
    now_dt = now or _now()
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    setup_type = str(plan.get("setup_type") or judge.get("setup_type") or plan.get("plan_action") or "unknown").strip()
    trigger = _dec(plan.get("trigger_price") or judge.get("trigger_price") or plan.get("trigger_level"), "0")
    invalidation = _dec(
        plan.get("invalidation_level")
        or plan.get("invalidation_price")
        or plan.get("stop_loss")
        or judge.get("invalidation_level"),
        "0",
    )
    reason = str(judge.get("trigger_wait_reason") or plan.get("no_plan_reason") or plan.get("reason") or "stored_wait_setup")
    return {
        "ticker": _ticker(ticker),
        "setup_type": setup_type,
        "source_decision_id": str(source_decision_id or plan.get("decision_id") or judge.get("decision_id") or ""),
        "trigger_level": str(trigger) if trigger > ZERO else "",
        "invalidation_level": str(invalidation) if invalidation > ZERO else "",
        "created_at": _iso(now_dt),
        "last_seen_at": _iso(now_dt),
        "expires_at": _iso(now_dt + timedelta(minutes=max(1, int(ttl_minutes)))),
        "promoted_to_order_candidate_at": "",
        "expired_at": "",
        "reason": reason,
        "status": "watching",
        "live_order_authorized": False,
    }


def upsert_opportunity(
    opportunity: Dict[str, Any],
    *,
    path: str | Path = DEFAULT_PATH,
    max_opportunities: int = 100,
) -> Dict[str, Any]:
    data = load_opportunity_memory(path)
    items = data["opportunities"]
    key = (
        _ticker(opportunity.get("ticker")),
        str(opportunity.get("setup_type") or ""),
        str(opportunity.get("source_decision_id") or ""),
    )
    replaced = False
    for idx, item in enumerate(items):
        existing = (_ticker(item.get("ticker")), str(item.get("setup_type") or ""), str(item.get("source_decision_id") or ""))
        if existing == key:
            merged = {**item, **opportunity, "created_at": item.get("created_at") or opportunity.get("created_at")}
            items[idx] = merged
            replaced = True
            break
    if not replaced:
        items.append(dict(opportunity))
    data["opportunities"] = items[-max(1, int(max_opportunities)) :]
    save_opportunity_memory(data, path)
    return {"stored": True, "replaced": replaced, "count": len(data["opportunities"]), "path": str(path)}


def evaluate_opportunities(
    *,
    market_by_ticker: Dict[str, Any],
    path: str | Path = DEFAULT_PATH,
    now: Optional[datetime] = None,
    persist: bool = False,
) -> Dict[str, Any]:
    now_dt = now or _now()
    data = load_opportunity_memory(path)
    actions: List[Dict[str, Any]] = []
    changed = False
    for item in data["opportunities"]:
        ticker = _ticker(item.get("ticker"))
        market = market_by_ticker.get(ticker) if isinstance(market_by_ticker, dict) else {}
        market = market if isinstance(market, dict) else {}
        current = _dec(market.get("mid_price") or market.get("current_price") or market.get("last_price"), "0")
        trigger = _dec(item.get("trigger_level"), "0")
        invalidation = _dec(item.get("invalidation_level"), "0")
        expires_at = _parse_time(item.get("expires_at"))
        status = str(item.get("status") or "watching")
        action = "keep_watching"
        if expires_at and now_dt >= expires_at:
            status = "expired"
            action = "expire"
            item["expired_at"] = item.get("expired_at") or _iso(now_dt)
            changed = True
        elif current > ZERO and invalidation > ZERO and current <= invalidation:
            status = "invalidated"
            action = "remove_invalidated"
            changed = True
        elif current > ZERO and trigger > ZERO and current >= trigger:
            status = "trigger_ready"
            action = "promote_to_judge_orderbook"
            item["promoted_to_order_candidate_at"] = item.get("promoted_to_order_candidate_at") or _iso(now_dt)
            changed = True
        item["status"] = status
        actions.append({
            "ticker": ticker,
            "status": status,
            "action": action,
            "current_price": str(current) if current > ZERO else "",
            "trigger_level": str(trigger) if trigger > ZERO else "",
            "invalidation_level": str(invalidation) if invalidation > ZERO else "",
            "live_order_authorized": False,
        })
    if persist and changed:
        save_opportunity_memory(data, path)
    return {
        "generated_at": _iso(now_dt),
        "path": str(path),
        "count": len(data["opportunities"]),
        "actions": actions,
        "promotions": [a for a in actions if a["action"] == "promote_to_judge_orderbook"],
        "preview_only": True,
        "live_order_authorized": False,
        "state_write_performed": bool(persist and changed),
    }


__all__ = [
    "DEFAULT_PATH",
    "build_opportunity_from_analysis",
    "evaluate_opportunities",
    "load_opportunity_memory",
    "save_opportunity_memory",
    "upsert_opportunity",
]
