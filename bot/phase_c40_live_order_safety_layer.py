from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.order_store import OrderStore

ZERO = Decimal("0")
C40_DEFAULT_MAX_PILOT_OPEN_ORDERS = 1
C40_MANAGED_CLIENT_PREFIXES = ("phasec-", "paper-phasec-")
C40_OPEN_STATUSES = {
    "open",
    "pending",
    "active",
    "submitted",
    "partially_filled",
    "cancel_pending",
    "replace_pending",
    "new",
    "queued",
}
C40_FINAL_STATUSES = {"filled", "cancelled", "canceled", "expired", "failed", "rejected", "done"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


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


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


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


def _read_jsonl_tail(path: str | Path, *, max_lines: int = 2000) -> List[Dict[str, Any]]:
    p = Path(path)
    if not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-int(max_lines):]
    except Exception:
        return []
    rows: List[Dict[str, Any]] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _client_order_id(order: Dict[str, Any]) -> str:
    return str(
        order.get("client_order_id")
        or order.get("client_order_id_preview")
        or order.get("client_order_id_previewed")
        or order.get("client_order_id_raw")
        or ""
    ).strip()


def _exchange_order_id(order: Dict[str, Any]) -> str:
    return str(order.get("order_id") or order.get("id") or order.get("exchange_order_id") or "").strip()


def _order_ticker(order: Dict[str, Any]) -> str:
    return _normalize_ticker(order.get("product_id") or order.get("ticker") or order.get("product") or order.get("productId"))


def _order_side(order: Dict[str, Any]) -> str:
    return str(order.get("side") or "").strip().upper()


def _order_status(order: Dict[str, Any]) -> str:
    status = str(order.get("status") or order.get("order_status") or order.get("completion_percentage_status") or "").strip().lower()
    if status in {"open", "pending", "active", "submitted", "partially_filled"}:
        return status
    if not status and _to_decimal(_filled_size(order), "0") > ZERO:
        return "partially_filled"
    return status or "unknown"


def _is_open_order(order: Dict[str, Any]) -> bool:
    status = _order_status(order)
    if status in C40_FINAL_STATUSES:
        return False
    if status in C40_OPEN_STATUSES or status == "unknown":
        return True
    return False


def _limit_price(order: Dict[str, Any]) -> str:
    cfg = _as_dict(order.get("order_configuration"))
    limit_gtc = _as_dict(cfg.get("limit_limit_gtc") or cfg.get("limit_limit_ioc") or cfg.get("limit_limit_fok"))
    return str(order.get("limit_price") or order.get("price") or limit_gtc.get("limit_price") or "").strip()


def _base_size(order: Dict[str, Any]) -> str:
    cfg = _as_dict(order.get("order_configuration"))
    limit_gtc = _as_dict(cfg.get("limit_limit_gtc") or cfg.get("limit_limit_ioc") or cfg.get("limit_limit_fok"))
    return str(order.get("base_size") or order.get("size_base") or order.get("size_base_normalized") or limit_gtc.get("base_size") or "0").strip()


def _quote_size(order: Dict[str, Any]) -> str:
    return str(order.get("quote_size") or order.get("size_quote") or order.get("size_quote_normalized") or order.get("size_quote_requested") or "0").strip()


def _filled_size(order: Dict[str, Any]) -> str:
    return str(order.get("filled_size") or order.get("filled_size_base") or order.get("filled_base") or order.get("completion_percentage_filled_size") or "0").strip()


def _created_at(order: Dict[str, Any]) -> Optional[datetime]:
    return _parse_dt(order.get("created_time") or order.get("created_at") or order.get("creation_time") or order.get("submitted_at"))


def _expires_at(order: Dict[str, Any]) -> Optional[datetime]:
    return _parse_dt(order.get("expires_at") or order.get("expiry_time") or order.get("cancel_after") or order.get("expiry_at"))


def normalize_live_order(order: Dict[str, Any], *, source: str = "snapshot") -> Dict[str, Any]:
    """Normalize a Coinbase/order snapshot without mutating or calling Coinbase."""
    raw = dict(order or {})
    cid = _client_order_id(raw)
    oid = _exchange_order_id(raw)
    ticker = _order_ticker(raw)
    side = _order_side(raw)
    status = _order_status(raw)
    created = _created_at(raw)
    expires = _expires_at(raw)
    filled = _to_decimal(_filled_size(raw), "0")
    base = _to_decimal(_base_size(raw), "0")
    quote = _to_decimal(_quote_size(raw), "0")
    is_partial = filled > ZERO and status not in C40_FINAL_STATUSES
    managed_prefix = cid.startswith(C40_MANAGED_CLIENT_PREFIXES)
    return _json_safe({
        "source": source,
        "ticker": ticker,
        "side": side,
        "status": status,
        "is_open": _is_open_order(raw),
        "is_partial_fill_like": is_partial or status == "partially_filled",
        "client_order_id": cid,
        "order_id": oid,
        "local_key": cid or oid,
        "managed_prefix": managed_prefix,
        "limit_price": _limit_price(raw),
        "base_size": str(base),
        "quote_size": str(quote),
        "filled_size_base": str(filled),
        "created_at": created.isoformat() if created else None,
        "expires_at": expires.isoformat() if expires else None,
        "raw_status": raw.get("status") or raw.get("order_status"),
        "raw": raw,
    })


def normalize_local_order(order: Dict[str, Any]) -> Dict[str, Any]:
    raw = dict(order or {})
    cid = _client_order_id(raw) or str(raw.get("client_order_id") or raw.get("order_id") or "").strip()
    ticker = _normalize_ticker(raw.get("ticker") or raw.get("product_id"))
    status = _order_status(raw)
    return _json_safe({
        "source": "local_order_store",
        "ticker": ticker,
        "side": _order_side(raw),
        "status": status,
        "is_open": status in {"planned", "pending", "submitted", "partially_filled", "cancel_pending", "replace_pending"} or _is_open_order(raw),
        "client_order_id": cid,
        "order_id": _exchange_order_id(raw),
        "local_key": cid or _exchange_order_id(raw),
        "managed_prefix": str(cid).startswith(C40_MANAGED_CLIENT_PREFIXES),
        "limit_price": _limit_price(raw),
        "base_size": _base_size(raw),
        "quote_size": _quote_size(raw),
        "filled_size_base": _filled_size(raw),
        "created_at": (_parse_dt(raw.get("created_at")) or _parse_dt(raw.get("submitted_at")) or None).isoformat() if (_parse_dt(raw.get("created_at")) or _parse_dt(raw.get("submitted_at"))) else None,
        "expires_at": _expires_at(raw).isoformat() if _expires_at(raw) else None,
        "raw": raw,
    })


def _collect_local_open_orders(order_store_path: str | Path = "state/open_orders.json", *, order_store: Optional[OrderStore] = None) -> List[Dict[str, Any]]:
    store = order_store or OrderStore(path=order_store_path)
    try:
        return [normalize_local_order(o) for o in store.open_orders()]
    except Exception:
        return []


def collect_live_open_orders_snapshot(
    *,
    live_orders_snapshot: Optional[Sequence[Dict[str, Any]]] = None,
    coinbase_client: Any = None,
    allow_coinbase_poll: bool = False,
    product_id: Optional[str] = None,
    order_status: str = "OPEN",
    limit: int = 100,
) -> Dict[str, Any]:
    """Collect open order data. Default is snapshot/no-client/no-Coinbase-call."""
    if live_orders_snapshot is not None:
        orders = [normalize_live_order(o, source="provided_snapshot") for o in live_orders_snapshot if isinstance(o, dict)]
        return {
            "source": "provided_snapshot",
            "coinbase_call_attempted": False,
            "coinbase_call_succeeded": False,
            "orders": [o for o in orders if bool(o.get("is_open"))],
            "errors": [],
        }
    if allow_coinbase_poll and coinbase_client is not None:
        try:
            response = coinbase_client.list_orders(product_id=product_id, order_status=order_status, limit=limit)
            raw_orders = response.get("orders") if isinstance(response, dict) else []
            orders = [normalize_live_order(o, source="coinbase_poll") for o in raw_orders if isinstance(o, dict)]
            return {
                "source": "coinbase_poll",
                "coinbase_call_attempted": True,
                "coinbase_call_succeeded": True,
                "orders": [o for o in orders if bool(o.get("is_open"))],
                "raw_response_keys": sorted(list(response.keys())) if isinstance(response, dict) else [],
                "errors": [],
            }
        except Exception as exc:
            return {
                "source": "coinbase_poll_error",
                "coinbase_call_attempted": True,
                "coinbase_call_succeeded": False,
                "orders": [],
                "errors": [str(exc)],
            }
    return {
        "source": "no_snapshot_no_coinbase_poll",
        "coinbase_call_attempted": False,
        "coinbase_call_succeeded": False,
        "orders": [],
        "errors": [],
    }


def _match_local_live(local_orders: Sequence[Dict[str, Any]], live_orders: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    local_keys = {str(o.get("local_key") or "").strip(): o for o in local_orders if str(o.get("local_key") or "").strip()}
    live_keys = {str(o.get("local_key") or "").strip(): o for o in live_orders if str(o.get("local_key") or "").strip()}
    matched = sorted(set(local_keys) & set(live_keys))
    live_unmanaged: List[Dict[str, Any]] = []
    for key, order in live_keys.items():
        if key in local_keys:
            continue
        if bool(order.get("managed_prefix")):
            # Managed-looking order not in local store is still concerning but not "foreign".
            item = dict(order)
            item["unmanaged_reason"] = "managed_prefix_but_missing_from_local_store"
            live_unmanaged.append(item)
        else:
            item = dict(order)
            item["unmanaged_reason"] = "live_order_missing_from_local_store_and_no_phasec_prefix"
            live_unmanaged.append(item)
    local_missing_live = [dict(local_keys[k], missing_reason="local_open_order_not_found_in_live_snapshot") for k in sorted(set(local_keys) - set(live_keys))]
    return {
        "matched_order_keys": matched,
        "live_unmanaged_orders": live_unmanaged,
        "local_open_orders_missing_live": local_missing_live,
        "counts": {
            "matched": len(matched),
            "live_unmanaged": len(live_unmanaged),
            "local_missing_live": len(local_missing_live),
        },
    }


def _age_seconds(order: Dict[str, Any], now: datetime) -> Optional[int]:
    created = _parse_dt(order.get("created_at"))
    if not created:
        return None
    return max(0, int((now - created).total_seconds()))


def assess_c40_order_safety(
    *,
    cfg: Any,
    live_orders: Sequence[Dict[str, Any]],
    local_orders: Sequence[Dict[str, Any]],
    max_pilot_open_orders: int = C40_DEFAULT_MAX_PILOT_OPEN_ORDERS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    now = now or _now()
    live_open = [dict(o) for o in live_orders if bool(o.get("is_open"))]
    local_open = [dict(o) for o in local_orders if bool(o.get("is_open"))]
    matching = _match_local_live(local_open, live_open)

    blockers: List[str] = []
    warnings: List[str] = []
    recommendations: List[Dict[str, Any]] = []

    if len(live_open) > int(max_pilot_open_orders):
        blockers.append("live_open_order_count_above_pilot_max")
    if matching["counts"]["live_unmanaged"] > 0:
        blockers.append("unmanaged_live_open_orders_detected")
    if matching["counts"]["local_missing_live"] > 0 and live_open:
        warnings.append("local_open_orders_missing_from_live_snapshot")

    actual_submit = bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False))
    if actual_submit:
        warnings.append("actual_submit_flag_enabled_during_c40_read_only_monitoring")
    if bool(getattr(cfg, "enable_live_exit_orders", False)):
        blockers.append("live_exit_orders_enabled_forbidden_in_c40")

    for order in live_open:
        rec_reasons: List[str] = []
        expires = _parse_dt(order.get("expires_at"))
        age = _age_seconds(order, now)
        if expires and expires <= now:
            rec_reasons.append("order_expired_but_still_open")
        if order.get("is_partial_fill_like"):
            rec_reasons.append("partial_fill_detected_prepare_reconciliation")
        if not bool(order.get("managed_prefix")):
            rec_reasons.append("unmanaged_order_requires_manual_review")
        if age is not None and age > 3600 and str(order.get("side") or "").upper() == "BUY":
            rec_reasons.append("open_entry_order_older_than_one_hour_review_expiry")
        if rec_reasons:
            recommendations.append({
                "ticker": order.get("ticker"),
                "client_order_id": order.get("client_order_id"),
                "order_id": order.get("order_id"),
                "side": order.get("side"),
                "status": order.get("status"),
                "recommendation": "cancel_or_reconcile_dry_run_only" if any("expired" in r or "unmanaged" in r for r in rec_reasons) else "monitor_and_reconcile_dry_run_only",
                "reasons": rec_reasons,
            })

    status = "live_order_safety_blocked" if blockers else "live_order_safety_review_required" if recommendations or warnings else "live_order_safety_clear_no_live_orders" if not live_open else "live_order_safety_clear_known_orders"
    return _json_safe({
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "recommendations": recommendations,
        "counts": {
            "live_open_orders": len(live_open),
            "local_open_orders": len(local_open),
            "live_unmanaged_orders": matching["counts"]["live_unmanaged"],
            "local_missing_live": matching["counts"]["local_missing_live"],
            "partial_fill_like_orders": sum(1 for o in live_open if bool(o.get("is_partial_fill_like"))),
            "cancel_recommendations": len(recommendations),
        },
        "matching": matching,
        "safety_policy": {
            "c40_is_read_only_monitoring_scaffold": True,
            "does_not_submit": True,
            "does_not_cancel_by_default": True,
            "does_not_modify_env": True,
            "max_one_pilot_order": True,
            "followers_not_in_order_lifecycle": True,
            "live_exits_forbidden": True,
        },
    })


def _summarize_audit_events(path: str | Path = "logs/order_events.jsonl", *, max_lines: int = 2000) -> Dict[str, Any]:
    rows = _read_jsonl_tail(path, max_lines=max_lines)
    by_type: Dict[str, int] = {}
    recent: List[Dict[str, Any]] = []
    for row in rows:
        et = str(row.get("event_type") or "unknown")
        by_type[et] = by_type.get(et, 0) + 1
        if len(recent) < 5:
            pass
    for row in rows[-5:]:
        recent.append({
            "generated_at": row.get("generated_at"),
            "event_type": row.get("event_type"),
            "ticker": _order_ticker(_as_dict(row.get("order")) or row),
            "client_order_id": _client_order_id(_as_dict(row.get("order")) or row),
        })
    return {"sample_size": len(rows), "by_event_type": by_type, "recent_events": recent}


def build_phase_c40_live_order_safety_report(
    *,
    cfg: Any,
    ticker: Optional[str] = None,
    live_orders_snapshot: Optional[Sequence[Dict[str, Any]]] = None,
    coinbase_client: Any = None,
    allow_coinbase_poll: bool = False,
    order_store_path: str | Path = "state/open_orders.json",
    order_events_path: str | Path = "logs/order_events.jsonl",
    max_lines: int = 2000,
    max_pilot_open_orders: int = C40_DEFAULT_MAX_PILOT_OPEN_ORDERS,
) -> Dict[str, Any]:
    selected_ticker = _normalize_ticker(ticker)
    live_collection = collect_live_open_orders_snapshot(
        live_orders_snapshot=live_orders_snapshot,
        coinbase_client=coinbase_client,
        allow_coinbase_poll=allow_coinbase_poll,
        product_id=selected_ticker or None,
    )
    live_orders_all = _as_list(live_collection.get("orders"))
    if selected_ticker:
        live_orders = [o for o in live_orders_all if _normalize_ticker(_as_dict(o).get("ticker")) == selected_ticker]
    else:
        live_orders = [o for o in live_orders_all if isinstance(o, dict)]

    local_all = _collect_local_open_orders(order_store_path)
    local_orders = [o for o in local_all if not selected_ticker or _normalize_ticker(o.get("ticker")) == selected_ticker]
    safety = assess_c40_order_safety(
        cfg=cfg,
        live_orders=live_orders,
        local_orders=local_orders,
        max_pilot_open_orders=max_pilot_open_orders,
    )
    audit = _summarize_audit_events(order_events_path, max_lines=max_lines)

    status = safety.get("status")
    if live_collection.get("coinbase_call_attempted") and not live_collection.get("coinbase_call_succeeded"):
        status = "live_order_safety_poll_error"

    return _json_safe({
        "generated_at": _now_iso(),
        "phase": "C4.0_live_order_safety_layer_monitor_cancel_expiry_scaffold",
        "status": status,
        "config_ok": True,
        "selected_ticker": selected_ticker or None,
        "actual_coinbase_submit_currently_enabled": bool(getattr(cfg, "enable_phase_c_actual_coinbase_submit", False)),
        "enable_live_limit_orders": bool(getattr(cfg, "enable_live_limit_orders", False)),
        "enable_live_entry_orders": bool(getattr(cfg, "enable_live_entry_orders", False)),
        "enable_live_exit_orders": bool(getattr(cfg, "enable_live_exit_orders", False)),
        "coinbase_poll": {
            "allow_coinbase_poll": bool(allow_coinbase_poll),
            "coinbase_client_provided": coinbase_client is not None,
            "coinbase_call_attempted": bool(live_collection.get("coinbase_call_attempted")),
            "coinbase_call_succeeded": bool(live_collection.get("coinbase_call_succeeded")),
            "source": live_collection.get("source"),
            "errors": live_collection.get("errors") or [],
        },
        "live_orders": live_orders,
        "local_open_orders": local_orders,
        "safety_assessment": safety,
        "audit_summary": audit,
        "dry_run_cancel_plan": {
            "cancel_allowed_by_default": False,
            "cancel_attempted_by_this_tool": False,
            "cancel_submitted": False,
            "recommendations": safety.get("recommendations") or [],
            "note": "C.4.0 doet alleen cancel/expiry aanbevelingen; geen echte cancel-call.",
        },
        "partial_fill_preparation": {
            "partial_fill_like_count": _as_dict(safety.get("counts")).get("partial_fill_like_orders", 0),
            "required_next_step_if_seen": "reconcile filled base/quote, update local order registry, then position state; do not place exits automatically in C.4.0",
        },
        "emergency_runbook": [
            "Controleer Coinbase UI/API op open orders voor de pilot ticker.",
            "Als unmanaged of expired order bestaat: niet submitten; voer later alleen een expliciete emergency-cancel tool uit.",
            "Zet ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT=false en herstart coinbase-bot.",
            "Draai python3 tools/show_phase_c40_live_order_safety.py --json opnieuw en bevestig live_open_orders=0 of alleen bekende pilot-order.",
            "Controleer logs/order_events.jsonl, logs/phase_c_live_submit.jsonl en logs/errors.jsonl.",
        ],
        "rollback_commands": [
            "python3 - <<'PY'\nfrom pathlib import Path\nimport re\np=Path('.env')\ns=p.read_text()\nfor k,v in {\n 'ENABLE_PHASE_C_ACTUAL_COINBASE_SUBMIT':'false',\n 'ENABLE_PHASE_C_LIVE_SMALL_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_LIMIT_ORDERS':'false',\n 'ENABLE_LIVE_ENTRY_ORDERS':'false',\n 'ENABLE_LIVE_EXIT_ORDERS':'false',\n}.items():\n    line=f'{k}={v}'\n    if re.search(rf'^{k}=.*$', s, re.M):\n        s=re.sub(rf'^{k}=.*$', line, s, flags=re.M)\n    else:\n        s += '\\n' + line\nif re.search(r'^PHASE_C_ALLOWED_TICKERS=.*$', s, re.M):\n    s=re.sub(r'^PHASE_C_ALLOWED_TICKERS=.*$', 'PHASE_C_ALLOWED_TICKERS=', s, flags=re.M)\np.write_text(s)\nPY",
            "sudo systemctl restart coinbase-bot",
            "python3 tools/show_phase_c40_live_order_safety.py --json",
            "python3 tools/show_phase_c_submit_readiness.py --json",
        ],
        "safety_policy": {
            "c40_is_read_only_safety_layer": True,
            "does_not_submit": True,
            "does_not_cancel_by_default": True,
            "does_not_modify_env": True,
            "default_does_not_call_coinbase": not bool(allow_coinbase_poll),
            "coinbase_poll_requires_explicit_allow_and_client": True,
            "max_one_pilot_open_order": True,
            "live_exits_forbidden": True,
            "followers_not_in_order_lifecycle": True,
        },
    })


__all__ = [
    "C40_DEFAULT_MAX_PILOT_OPEN_ORDERS",
    "build_phase_c40_live_order_safety_report",
    "assess_c40_order_safety",
    "collect_live_open_orders_snapshot",
    "normalize_live_order",
]
