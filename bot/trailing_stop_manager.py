from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Optional

ZERO = Decimal("0")


def _dec(value: Any, default: str = "0") -> Decimal:
    try:
        if value in (None, ""):
            return Decimal(default)
        return value if isinstance(value, Decimal) else Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return Decimal(default)


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _safe(v) for k, v in value.items()}
    return value


def build_trailing_stop_status(
    *,
    position: Dict[str, Any],
    market: Dict[str, Any],
    policy: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Report-only trailing stop state.

    The stop only ratchets upward. It never emits a live cancel/replace/apply
    instruction; callers must route through existing ACK-gated D.4/stop paths.
    """
    policy = dict(policy or {})
    entry = _dec(position.get("entry_price") or position.get("avg_fill_price"), "0")
    current = _dec(market.get("mid_price") or market.get("current_price"), "0")
    previous_peak = _dec(position.get("highest_price_since_entry") or policy.get("prior_peak_price"), "0")
    previous_stop = _dec(position.get("trailing_stop_price") or policy.get("prior_stop_price"), "0")
    activation_pct = _dec(policy.get("activation_profit_pct") or position.get("trailing_trigger_pct"), "0.025")
    distance_pct = _dec(policy.get("trailing_distance_pct") or position.get("trailing_distance_pct"), "0.018")
    activation_price = entry * (Decimal("1") + activation_pct) if entry > ZERO else ZERO
    peak = max(previous_peak, current)
    candidate_stop = peak * (Decimal("1") - distance_pct) if peak > ZERO and distance_pct > ZERO else ZERO
    ratcheted_stop = max(previous_stop, candidate_stop)
    active = bool(entry > ZERO and current > ZERO and current >= activation_price)
    triggered = bool(active and ratcheted_stop > ZERO and current <= ratcheted_stop)
    blockers = []
    if entry <= ZERO:
        blockers.append("entry_price_missing")
    if current <= ZERO:
        blockers.append("current_price_missing")
    if distance_pct <= ZERO:
        blockers.append("trailing_distance_pct_missing")
    if ratcheted_stop < previous_stop:
        blockers.append("trailing_stop_would_move_down")
    return _safe({
        "generated_at": _now_iso(),
        "phase": "trailing_stop_manager_report_only_v1",
        "status": "triggered_preview" if triggered else ("active" if active else "inactive"),
        "entry_price": entry,
        "current_price": current,
        "activation_price": activation_price,
        "highest_price_since_entry": peak,
        "previous_trailing_stop_price": previous_stop,
        "candidate_trailing_stop_price": candidate_stop,
        "trailing_stop_price": ratcheted_stop,
        "stop_moved_down": False,
        "triggered": triggered,
        "proposed_action": "route_to_controlled_stop_preview" if triggered else "keep_open",
        "blockers": blockers,
        "preview_only": True,
        "live_action_attempted": False,
        "state_write_performed": False,
    })


__all__ = ["build_trailing_stop_status"]
