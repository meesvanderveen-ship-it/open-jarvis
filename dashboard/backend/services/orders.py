from __future__ import annotations

from dashboard.backend import cache
from dashboard.backend.security.safe_paths import resolve_state_file
from dashboard.backend.services.shell_tool import run_json_tool
from dashboard.backend.services.util import read_json_file

# Mirrors bot/order_lifecycle.py::OPEN_ORDER_STATUSES. Kept as a local
# constant (read-only display logic only) rather than importing the bot
# package, so the dashboard never depends on bot internals for behavior.
OPEN_ORDER_STATUSES = {
    "planned",
    "pending",
    "submitted",
    "partially_filled",
    "open",
    "active",
    "new",
    "queued",
    "cancel_pending",
    "replace_pending",
}


def _is_open(order: dict) -> bool:
    status = (order.get("status") or "").lower()
    if status in OPEN_ORDER_STATUSES:
        return True
    try:
        remaining = float(order.get("remaining_size") or 0)
    except (TypeError, ValueError):
        remaining = 0
    return remaining > 0 and status not in {"filled", "cancelled", "rejected", "submit_rejected", "expired"}


def get_orders() -> dict:
    path = resolve_state_file("open_orders.json")
    data = read_json_file(path, default={})
    raw_orders = data.get("orders", {}) if isinstance(data, dict) else {}

    orders = []
    for key, fields in raw_orders.items():
        if not isinstance(fields, dict):
            continue
        entry = dict(fields)
        entry["order_key"] = key
        entry["is_open"] = _is_open(entry)
        orders.append(entry)

    open_orders = [o for o in orders if o["is_open"]]
    d3_exit_orders = [o for o in open_orders if "d3" in (o.get("phase") or "").lower() or (o.get("client_order_id") or "").startswith("phased3-")]

    summary_tool = cache.get_or_compute(
        "orders_summary_tool",
        lambda: run_json_tool("show_open_orders.py", ["--summary"]),
    )

    return {
        "orders": orders,
        "summary": {
            "total": len(orders),
            "open_count": len(open_orders),
            "open_d3_exit_count": len(d3_exit_orders),
            "tool_summary": summary_tool.get("summary", summary_tool),
        },
    }
