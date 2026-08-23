from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None:
            return Decimal(default)
        if isinstance(value, Decimal):
            return value
        text = str(value).strip()
        if not text:
            return Decimal(default)
        return Decimal(text)
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


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


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _first_present(*values: Any) -> Tuple[Any, bool]:
    """Return the first value that is present, including an explicit zero."""
    for value in values:
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value, True
    return "", False


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _order_config_base_size(order: Dict[str, Any]) -> str:
    cfg = order.get("order_configuration")
    if not isinstance(cfg, dict):
        return ""
    for value in cfg.values():
        if not isinstance(value, dict):
            continue
        base_size = _first_non_empty(value.get("base_size"), value.get("size"))
        if base_size:
            return base_size
    return ""


def _snapshot_fees(order: Dict[str, Any], fills: Iterable[Dict[str, Any]]) -> Tuple[str, bool]:
    commission_detail = order.get("commission_detail_total")
    commission_detail = commission_detail if isinstance(commission_detail, dict) else {}
    value, recorded = _first_present(
        order.get("total_fees"),
        order.get("fees"),
        order.get("fee"),
        commission_detail.get("total_commission"),
    )
    if recorded:
        return str(_to_decimal(value, "0")), True

    total = Decimal("0")
    saw_fill_fee = False
    for fill in fills or []:
        if not isinstance(fill, dict):
            continue
        details = fill.get("commission_detail_total")
        details = details if isinstance(details, dict) else {}
        fill_fee, has_fee = _first_present(
            fill.get("commission"),
            fill.get("total_fees"),
            fill.get("fee"),
            details.get("total_commission"),
        )
        if has_fee:
            total += _to_decimal(fill_fee, "0")
            saw_fill_fee = True
    return str(total), saw_fill_fee


def _nested_order(payload: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {}
    # Coinbase can return either {"order": {...}} or the order object itself.
    order = payload.get("order")
    if isinstance(order, dict):
        return dict(order)
    return dict(payload)


def _raw_response_shape(payload: Any) -> Dict[str, Any]:
    shape: Dict[str, Any] = {
        "payload_type": type(payload).__name__,
    }
    if isinstance(payload, dict):
        keys = sorted(str(key) for key in payload.keys())
        shape["top_level_keys"] = keys[:20]
        nested = payload.get("order")
        if isinstance(nested, dict):
            shape["order_keys"] = sorted(str(key) for key in nested.keys())[:20]
        fills = payload.get("fills")
        if isinstance(fills, list):
            shape["fills_count"] = len(fills)
    elif isinstance(payload, list):
        shape["list_length"] = len(payload)
        if payload and isinstance(payload[0], dict):
            shape["first_item_keys"] = sorted(str(key) for key in payload[0].keys())[:20]
    return shape


def _client_order_id(order: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> str:
    fallback = fallback or {}
    return _first_non_empty(
        order.get("client_order_id"),
        order.get("client_order_id".upper()),
        order.get("clientOrderId"),
        fallback.get("client_order_id"),
    )


def _exchange_order_id(order: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> str:
    fallback = fallback or {}
    return _first_non_empty(
        order.get("order_id"),
        order.get("id"),
        order.get("orderId"),
        order.get("exchange_order_id"),
        fallback.get("exchange_order_id"),
        fallback.get("order_id"),
    )


def _ticker(order: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> str:
    fallback = fallback or {}
    return _first_non_empty(order.get("product_id"), order.get("product"), order.get("ticker"), fallback.get("ticker"), fallback.get("product_id")).upper()


def _side(order: Dict[str, Any], fallback: Optional[Dict[str, Any]] = None) -> str:
    fallback = fallback or {}
    return _first_non_empty(order.get("side"), fallback.get("side")).upper()


def _raw_status(order: Dict[str, Any]) -> str:
    return _first_non_empty(order.get("status"), order.get("order_status"), order.get("completion_percentage_status"), order.get("state")).upper()


def normalize_order_status(raw_status: Any, *, filled_base: Any = "0") -> str:
    """Normalize Coinbase/local order statuses to a small lifecycle vocabulary."""
    status = str(raw_status or "").strip().lower()
    base = _to_decimal(filled_base, "0")

    if status in {"filled", "done", "completed", "complete", "settled"}:
        return "filled"
    if status in {"cancelled", "canceled", "cancelled_order", "canceled_order"}:
        return "cancelled"
    if status in {"expired", "timed_out", "timeout"}:
        return "expired"
    if status in {"rejected", "failed", "failure"}:
        return "rejected"
    if status in {"pending_cancel", "cancel_pending"}:
        return "cancel_pending"
    if status in {"open", "active", "pending", "submitted", "accepted", "new", "created"}:
        return "partially_filled" if base > Decimal("0") else "open"
    if base > Decimal("0"):
        return "partially_filled"
    return "unknown"


def classify_coinbase_order_type(order_payload: Any) -> Dict[str, Any]:
    """Classify a read-only Coinbase order payload by Advanced Trade config."""
    order = _nested_order(order_payload)
    cfg = order.get("order_configuration")
    cfg = cfg if isinstance(cfg, dict) else {}
    cfg_keys = sorted(str(key) for key in cfg.keys())
    order_type = str(order.get("order_type") or "").strip().upper()
    post_only = None
    time_in_force = _first_non_empty(order.get("time_in_force"))
    limit_price = ""
    quote_size = ""
    base_size = ""
    conclusion = "unknown"

    if "market_market_ioc" in cfg:
        market_cfg = cfg.get("market_market_ioc") if isinstance(cfg.get("market_market_ioc"), dict) else {}
        quote_size = _first_non_empty(market_cfg.get("quote_size"), order.get("quote_size"))
        base_size = _first_non_empty(market_cfg.get("base_size"), order.get("base_size"))
        conclusion = "market_order"
    else:
        for key in ("limit_limit_gtc", "limit_limit_ioc", "limit_limit_fok"):
            limit_cfg = cfg.get(key) if isinstance(cfg.get(key), dict) else {}
            if not limit_cfg:
                continue
            post_only = bool(limit_cfg.get("post_only"))
            limit_price = _first_non_empty(limit_cfg.get("limit_price"), order.get("limit_price"))
            quote_size = _first_non_empty(limit_cfg.get("quote_size"), order.get("quote_size"))
            base_size = _first_non_empty(limit_cfg.get("base_size"), order.get("base_size"))
            conclusion = "post_only_limit" if post_only else "limit_order"
            break

    if conclusion == "unknown":
        if order_type == "MARKET":
            conclusion = "market_order"
        elif order_type == "LIMIT":
            conclusion = "limit_order"

    return _json_safe(
        {
            "order_type": order_type,
            "order_configuration_keys": cfg_keys,
            "order_configuration": cfg,
            "time_in_force": time_in_force,
            "post_only": post_only,
            "limit_price": limit_price,
            "quote_size": quote_size,
            "base_size": base_size,
            "conclusion": conclusion,
            "confidence": "high" if cfg_keys else ("medium" if order_type in {"MARKET", "LIMIT"} else "low"),
            "read_only": True,
        }
    )


def summarize_fills(fills: Iterable[Dict[str, Any]], *, fallback_price: Any = "0") -> Dict[str, Any]:
    total_base = Decimal("0")
    total_quote = Decimal("0")
    count = 0
    normalized: List[Dict[str, Any]] = []

    for fill in fills or []:
        if not isinstance(fill, dict):
            continue
        count += 1
        price = _to_decimal(fill.get("price") or fill.get("average_filled_price") or fallback_price, "0")
        size = _to_decimal(fill.get("size") or fill.get("filled_size") or fill.get("base_size"), "0")
        quote = _to_decimal(fill.get("quote_size") or fill.get("filled_value") or fill.get("commissionless_value") or fill.get("trade_value"), "0")
        size_in_quote = str(fill.get("size_in_quote") or "").strip().lower() in {"1", "true", "yes"}
        if size_in_quote:
            if quote <= Decimal("0"):
                quote = size
            base = quote / price if price > Decimal("0") else Decimal("0")
        else:
            base = size
            if quote <= Decimal("0") and price > Decimal("0") and base > Decimal("0"):
                quote = base * price
        total_base += max(Decimal("0"), base)
        total_quote += max(Decimal("0"), quote)
        normalized.append({
            "price": str(price),
            "base_size": str(max(Decimal("0"), base)),
            "quote_size": str(max(Decimal("0"), quote)),
            "raw": fill,
        })

    avg_price = (total_quote / total_base) if total_base > Decimal("0") and total_quote > Decimal("0") else _to_decimal(fallback_price, "0")
    return _json_safe({
        "fill_count": count,
        "filled_base": str(total_base),
        "filled_quote": str(total_quote),
        "avg_fill_price": str(avg_price),
        "fills": normalized,
    })


def normalized_filled_quote_value(
    order_payload: Any,
    *,
    filled_base: Any = "0",
    avg_fill_price: Any = "0",
    fallback_local_order: Optional[Dict[str, Any]] = None,
    fills_summary: Optional[Dict[str, Any]] = None,
) -> Decimal:
    local = fallback_local_order or {}
    order = _nested_order(order_payload)
    nested = _nested_order(order.get("raw_order")) if isinstance(order.get("raw_order"), dict) else {}
    summary = fills_summary if isinstance(fills_summary, dict) else {}
    nested_summary = nested.get("fills_summary") if isinstance(nested.get("fills_summary"), dict) else {}

    for value in (
        summary.get("filled_quote") if _to_decimal(summary.get("filled_quote"), "0") > Decimal("0") else None,
        order.get("filled_value"),
        order.get("filled_quote"),
        order.get("filled_quote_value"),
        nested.get("filled_value"),
        nested.get("filled_quote"),
        nested.get("filled_quote_value"),
        nested_summary.get("filled_quote"),
        local.get("filled_quote_value"),
        local.get("filled_quote"),
    ):
        dec = _to_decimal(value, "0")
        if dec > Decimal("0"):
            return dec

    base_dec = _to_decimal(filled_base, "0")
    avg_dec = _to_decimal(avg_fill_price, "0")
    if base_dec > Decimal("0") and avg_dec > Decimal("0"):
        return base_dec * avg_dec
    return Decimal("0")


def normalize_coinbase_order_snapshot(
    order_payload: Any,
    *,
    fills: Optional[List[Dict[str, Any]]] = None,
    fallback_local_order: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a stable, JSON-safe read-only snapshot for Coinbase/local order data.

    This function performs no network calls and no state writes. It is meant as
    the adapter between Coinbase's changing response shapes and the bot's
    C.4.3/D.2/D.3 lifecycle logic.
    """
    local = fallback_local_order or {}
    order = _nested_order(order_payload)
    limit_price = _first_non_empty(
        order.get("limit_price"),
        ((order.get("order_configuration") or {}).get("limit_limit_gtc") or {}).get("limit_price") if isinstance(order.get("order_configuration"), dict) else None,
        local.get("limit_price"),
        "0",
    )
    avg_price = _first_non_empty(
        order.get("average_filled_price"),
        order.get("avg_fill_price"),
        order.get("average_fill_price"),
        local.get("avg_fill_price"),
        limit_price,
        "0",
    )
    filled_base = _first_non_empty(
        order.get("filled_size"),
        order.get("filled_base"),
        order.get("filled_size_base"),
        order.get("completion_percentage") and local.get("filled_size"),
        local.get("filled_size"),
        "0",
    )
    fills_summary = summarize_fills(fills or [], fallback_price=avg_price)
    if _to_decimal(fills_summary.get("filled_base"), "0") > _to_decimal(filled_base, "0"):
        filled_base = str(fills_summary.get("filled_base"))
        avg_price = str(fills_summary.get("avg_fill_price") or avg_price)

    filled_quote = str(
        normalized_filled_quote_value(
            order,
            filled_base=filled_base,
            avg_fill_price=avg_price,
            fallback_local_order=local,
            fills_summary=fills_summary,
        )
    )

    raw_status = _raw_status(order) or str(local.get("status") or "")
    normalized_status = normalize_order_status(raw_status, filled_base=filled_base)
    order_type_classification = classify_coinbase_order_type(order)
    remaining_value, remaining_recorded = _first_present(
        order.get("remaining_size"),
        order.get("remaining_base"),
        order.get("leaves_quantity"),
        local.get("remaining_size"),
    )
    if not remaining_recorded:
        requested_base = _to_decimal(_order_config_base_size(order), "0")
        remaining_value = max(Decimal("0"), requested_base - _to_decimal(filled_base, "0"))
        remaining_recorded = requested_base > Decimal("0")
    # Coinbase's terminal FILLED response often omits a remaining-size field.
    # Preserve the explicit normalized terminal zero so downstream closeout code
    # can require it without guessing from an absent field.
    if normalized_status == "filled" and not remaining_recorded:
        remaining_value = Decimal("0")
        remaining_recorded = True
    settled_value, settled_recorded = _first_present(order.get("settled"), local.get("settled"))
    fees, fees_recorded = _snapshot_fees(order, fills or [])

    return _json_safe({
        "generated_at": _now_iso(),
        "client_order_id": _client_order_id(order, local),
        "exchange_order_id": _exchange_order_id(order, local),
        "ticker": _ticker(order, local),
        "side": _side(order, local),
        "status": raw_status,
        "raw_status": raw_status,
        "normalized_status": normalized_status,
        "limit_price": str(_to_decimal(limit_price, "0")),
        "filled_base": str(_to_decimal(filled_base, "0")),
        "filled_quote": str(_to_decimal(filled_quote, "0")),
        "avg_fill_price": str(_to_decimal(avg_price, "0")),
        "fill_count": int(fills_summary.get("fill_count") or 0),
        "remaining_size": str(_to_decimal(remaining_value, "0")),
        "remaining_size_recorded": bool(remaining_recorded),
        "settled": _as_bool(settled_value),
        "settled_recorded": bool(settled_recorded),
        "fees": fees,
        "fees_recorded": bool(fees_recorded),
        "fills_summary": fills_summary,
        "order_type_classification": order_type_classification,
        "raw_order": order,
        "safety_policy": {
            "read_only_snapshot": True,
            "does_not_submit": True,
            "does_not_cancel": True,
            "does_not_modify_local_state": True,
        },
    })


def fetch_coinbase_order_snapshot(
    *,
    coinbase_client: Any,
    order_id: str,
    local_order: Optional[Dict[str, Any]] = None,
    include_fills: bool = True,
) -> Dict[str, Any]:
    """Fetch and normalize one Coinbase order snapshot.

    The only external operations are read-only get_order/list_fills calls on the
    supplied client. The function never places, cancels or replaces orders.
    """
    raw_order = coinbase_client.get_order(order_id)
    fills: List[Dict[str, Any]] = []
    if include_fills and hasattr(coinbase_client, "get_recent_fills_for_order"):
        fills = list(coinbase_client.get_recent_fills_for_order(order_id, limit=100) or [])
    return normalize_coinbase_order_snapshot(raw_order, fills=fills, fallback_local_order=local_order)


def _lookup_order_via_list_orders(
    *,
    coinbase_client: Any,
    local_order: Optional[Dict[str, Any]],
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    local = local_order or {}
    product_id = _ticker({}, local)
    client_order_id = str(local.get("client_order_id") or "").strip()
    exchange_order_id = str(local.get("exchange_order_id") or local.get("order_id") or "").strip()
    if not product_id:
        raise RuntimeError("product_id_missing_for_list_orders_fallback")
    payload = coinbase_client.list_orders(product_id=product_id, limit=250)
    orders = payload.get("orders") if isinstance(payload, dict) else None
    if not isinstance(orders, list):
        raise RuntimeError("list_orders_response_missing_orders")
    for item in orders:
        if not isinstance(item, dict):
            continue
        nested = _nested_order(item)
        if client_order_id and _client_order_id(nested, local) == client_order_id:
            return nested, payload
        if exchange_order_id and _exchange_order_id(nested, local) == exchange_order_id:
            return nested, payload
    raise RuntimeError("order_not_found_in_list_orders_fallback")


def fetch_coinbase_order_snapshot_with_diagnostics(
    *,
    coinbase_client: Any,
    order_id: str,
    local_order: Optional[Dict[str, Any]] = None,
    include_fills: bool = True,
) -> Dict[str, Any]:
    """Fetch and normalize a Coinbase order snapshot with safe diagnostics.

    Read-only only. This function never submits, cancels or replaces orders.
    """
    local = local_order or {}
    client_order_id = str(local.get("client_order_id") or "").strip()
    exchange_order_id = str(order_id or local.get("exchange_order_id") or local.get("order_id") or "").strip()
    product_id = _ticker({}, local)
    attempted_methods: List[str] = []
    failed_methods: List[Dict[str, Any]] = []
    succeeded_method = ""
    error_type = ""
    error_message = ""
    error_stage = ""
    raw_shape: Dict[str, Any] = {}
    raw_order: Dict[str, Any] = {}

    lookup_methods: List[Tuple[str, Any]] = [
        (
            "get_order_by_exchange_order_id",
            lambda: (coinbase_client.get_order(exchange_order_id), "lookup_order"),
        ),
    ]
    if hasattr(coinbase_client, "list_orders") and product_id:
        lookup_methods.append(
            (
                "list_orders_by_product_id_match_client_or_exchange_order_id",
                lambda: (*_lookup_order_via_list_orders(coinbase_client=coinbase_client, local_order=local_order), "lookup_order"),
            )
        )

    for method_name, resolver in lookup_methods:
        attempted_methods.append(method_name)
        try:
            result = resolver()
            if len(result) == 3:
                payload, _, _ = result
            else:
                payload, _ = result
            raw_shape = _raw_response_shape(payload)
            raw_order = _nested_order(payload)
            succeeded_method = method_name
            break
        except Exception as exc:
            error_type = type(exc).__name__
            error_message = str(exc)
            error_stage = "lookup_order"
            failed_methods.append(
                {
                    "method": method_name,
                    "error_type": error_type,
                    "error_message": error_message,
                    "error_stage": error_stage,
                }
            )

    if not raw_order:
        return _json_safe(
            {
                "coinbase_call_attempted": True,
                "coinbase_call_succeeded": False,
                "coinbase_snapshot_unavailable": True,
                "coinbase_error_type": error_type or "RuntimeError",
                "coinbase_error_message": error_message or "coinbase_order_lookup_failed",
                "coinbase_error_stage": error_stage or "lookup_order",
                "coinbase_order_lookup_method_attempted": attempted_methods,
                "coinbase_order_lookup_succeeded_method": "",
                "coinbase_order_lookup_failed_methods": failed_methods,
                "order_id_used": exchange_order_id,
                "client_order_id_used": client_order_id,
                "product_id_used": product_id,
                "include_fills": bool(include_fills),
                "raw_response_shape": raw_shape,
                "fills_summary": {"fill_count": 0, "filled_base": "0", "filled_quote": "0", "avg_fill_price": "0", "fills": []},
                "warnings": [f"coinbase_poll_failed:{error_type or 'RuntimeError'}"],
                "blockers": ["coinbase_snapshot_unavailable"],
                "no_coinbase_submit": True,
                "no_coinbase_cancel": True,
                "no_coinbase_replace": True,
                "state_write_performed": False,
            }
        )

    fills: List[Dict[str, Any]] = []
    fills_error: Optional[Dict[str, Any]] = None
    if include_fills and hasattr(coinbase_client, "get_recent_fills_for_order"):
        attempted_methods.append("list_fills_by_exchange_order_id")
        try:
            fills = list(coinbase_client.get_recent_fills_for_order(exchange_order_id, limit=100) or [])
        except Exception as exc:
            fills_error = {
                "method": "list_fills_by_exchange_order_id",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "error_stage": "lookup_fills",
            }
            failed_methods.append(dict(fills_error))

    normalized = normalize_coinbase_order_snapshot(raw_order, fills=fills, fallback_local_order=local_order)
    normalized_status = str(normalized.get("normalized_status") or "").strip().lower()
    warnings: List[str] = []
    blockers: List[str] = []

    if fills_error:
        warnings.append(f"coinbase_fills_lookup_failed:{fills_error['error_type']}")
        if normalized_status == "open":
            normalized["evidence_source"] = "coinbase_status_only_fallback_open"
        else:
            blockers.append("coinbase_fill_details_unavailable_for_non_open_status")

    if normalized_status in {"partially_filled", "filled"} and not (
        _to_decimal(normalized.get("filled_base"), "0") > Decimal("0")
        or int(((normalized.get("fills_summary") or {}).get("fill_count")) or 0) > 0
    ):
        blockers.append("fill_evidence_required_for_partial_or_filled_apply")

    normalized.update(
        _json_safe(
            {
                "coinbase_call_attempted": True,
                "coinbase_call_succeeded": True,
                "coinbase_snapshot_unavailable": False,
                "coinbase_error_type": fills_error.get("error_type") if fills_error else "",
                "coinbase_error_message": fills_error.get("error_message") if fills_error else "",
                "coinbase_error_stage": fills_error.get("error_stage") if fills_error else "",
                "coinbase_order_lookup_method_attempted": attempted_methods,
                "coinbase_order_lookup_succeeded_method": succeeded_method,
                "coinbase_order_lookup_failed_methods": failed_methods,
                "order_id_used": exchange_order_id,
                "client_order_id_used": client_order_id,
                "product_id_used": product_id,
                "include_fills": bool(include_fills),
                "raw_response_shape": raw_shape,
                "warnings": warnings,
                "blockers": blockers,
                "no_coinbase_submit": True,
                "no_coinbase_cancel": True,
                "no_coinbase_replace": True,
                "state_write_performed": False,
            }
        )
    )
    return normalized


__all__ = [
    "classify_coinbase_order_type",
    "fetch_coinbase_order_snapshot",
    "fetch_coinbase_order_snapshot_with_diagnostics",
    "normalize_coinbase_order_snapshot",
    "normalize_order_status",
    "normalized_filled_quote_value",
    "summarize_fills",
]
