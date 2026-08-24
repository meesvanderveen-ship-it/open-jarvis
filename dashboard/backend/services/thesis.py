"""Trade Thesis report: one readable, per-ticker summary answering the four
questions an operator actually asks -- what would we buy and at what
condition/price, where do we stand right now, what is the reasoning behind
it, and what are the exit parameters (take-profit, stop-loss, trailing
stop, position size in USDC).

Combines two sources:
- state/positions.json: the ground truth for an open or most-recently-closed
  position (actual entry price, stop, take-profit, trailing config, size).
- logs/analysis.jsonl: the latest full judge/trade_plan reasoning per ticker
  (entry trigger conditions, thesis text, targets). This file is tailed from
  the end only -- it grows unbounded and individual lines are large (full
  feature packs), so a full read is never safe.
"""

from __future__ import annotations

import json
from typing import Any

from dashboard.backend.security.safe_paths import resolve_state_file, resolve_under_logs
from dashboard.backend.services.logs import _read_lines_from_end
from dashboard.backend.services.ticker_universe import get_allowed_tickers
from dashboard.backend.services.util import read_json_file

_ANALYSIS_TAIL_LINES = 400


def _latest_analysis_by_ticker() -> dict[str, dict]:
    path = resolve_under_logs("analysis.jsonl")
    if not path.is_file():
        return {}
    raw_lines, _ = _read_lines_from_end(path, _ANALYSIS_TAIL_LINES)
    latest: dict[str, dict] = {}
    for line in raw_lines:  # oldest first -> later duplicates overwrite -> latest wins
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        ticker = record.get("ticker")
        if not ticker:
            continue
        latest[ticker] = record
    return latest


def _positions_by_ticker() -> dict[str, dict]:
    path = resolve_state_file("positions.json")
    data = read_json_file(path, default={})
    if not isinstance(data, dict):
        return {}
    out: dict[str, dict] = {}
    for ticker, fields in data.items():
        if not isinstance(fields, dict):
            continue
        entry = dict(fields)
        entry["ticker"] = ticker
        entry["is_open"] = entry.get("close_time") is None
        out[ticker] = entry
    return out


def _all_orders() -> list[dict]:
    path = resolve_state_file("open_orders.json")
    data = read_json_file(path, default={})
    raw = data.get("orders", {}) if isinstance(data, dict) else {}
    return [o for o in raw.values() if isinstance(o, dict)]


def _order_fill_quote(order: dict) -> float | None:
    return _num(order.get("filled_quote") or order.get("size_quote"))


def _backfill_from_orders(position: dict, orders: list[dict]) -> dict:
    """A governed fill-reconciliation apply zeroes a closed position's own
    size/base fields (correctly -- current exposure really is zero), which
    also erases the historical "how big was this trade" record the report
    needs. Recover it from the linked entry/close orders when present."""
    position_order_id = str(position.get("order_id") or "")
    entry_order = next(
        (o for o in orders if str(o.get("exchange_order_id") or "") == position_order_id and str(o.get("side") or "").upper() == "BUY"),
        None,
    )
    close_orders = [
        o
        for o in orders
        if str(o.get("linked_position_id") or "") == position_order_id
        and str(o.get("side") or "").upper() == "SELL"
        and str(o.get("status") or "").lower() == "filled"
    ]
    close_order = max(close_orders, key=lambda o: str(o.get("filled_at") or o.get("closed_at") or ""), default=None)

    size_quote = _num(position.get("position_size_quote")) or (_order_fill_quote(entry_order) if entry_order else None)
    close_price = _num(position.get("close_price")) or (_num(close_order.get("avg_fill_price")) if close_order else None)

    realized_pnl = _num(position.get("realized_pnl"))
    if realized_pnl is None and entry_order and close_order:
        entry_cost = _order_fill_quote(entry_order)
        close_proceeds = _order_fill_quote(close_order)
        close_fees = _num(close_order.get("fees_paid"))
        if entry_cost is not None and close_proceeds is not None:
            realized_pnl = close_proceeds - entry_cost - (close_fees or 0.0)

    return {
        "size_quote_usdc": size_quote,
        "close_price": close_price,
        "realized_pnl": realized_pnl,
    }


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _entry_plan(trade_plan: dict) -> dict:
    """What would we buy, at what condition/price -- straight from the
    latest trade_plan, regardless of whether it currently describes a fresh
    entry or ongoing position management (both are useful context)."""
    return {
        "plan_action": trade_plan.get("plan_action"),
        "valid_new_entry_plan": bool(trade_plan.get("valid_trade_plan")),
        "condition_text": trade_plan.get("trigger") or trade_plan.get("reason") or "",
        "entry_zone_low": _num(trade_plan.get("entry_zone_low")),
        "entry_zone_high": _num(trade_plan.get("entry_zone_high")),
        "trigger_price": _num(trade_plan.get("trigger_price")),
        "do_not_chase_above": _num(trade_plan.get("do_not_chase_above")),
        "preferred_limit_price": _num(trade_plan.get("preferred_limit_price")),
    }


def _build_ticker_thesis(ticker: str, position: dict | None, analysis: dict | None, orders: list[dict]) -> dict:
    position = position or {}
    analysis = analysis or {}
    backfill = _backfill_from_orders(position, orders) if position else {}
    trade_plan = analysis.get("trade_plan") or {}
    judge = analysis.get("judge") or {}
    market = (analysis.get("feature_pack") or {}).get("market") or {}

    has_position = bool(position)
    is_open = bool(position.get("is_open"))
    status = "open" if is_open else ("closed" if has_position else "watching")

    take_profit = _num(position.get("take_profit_price")) or _num(trade_plan.get("take_profit_1"))
    take_profit_2 = _num(trade_plan.get("take_profit_2"))
    stop_loss = _num(position.get("stop_price")) or _num(trade_plan.get("stop_loss"))
    invalidation = _num(position.get("invalidation_price")) or _num(trade_plan.get("invalidation_price"))

    trailing_trigger_pct = _num(position.get("trailing_trigger_pct"))
    trailing_distance_pct = _num(position.get("trailing_distance_pct"))

    thesis_reasons = [str(r) for r in (judge.get("reasons") or []) if r]
    monitoring_rules = [str(r) for r in (trade_plan.get("monitoring_rules") or []) if r]
    must_reject_if = [str(r) for r in (judge.get("must_reject_if") or []) if r]

    return {
        "ticker": ticker,
        "status": status,
        "as_of": analysis.get("generated_at") or position.get("updated_at"),
        "current_price": _num(market.get("mid_price")),
        "setup_type": position.get("setup_type") or position.get("source_setup_type") or trade_plan.get("setup_type"),
        "entry_plan": _entry_plan(trade_plan),
        "thesis_reasons": thesis_reasons,
        "monitoring_rules": monitoring_rules,
        "must_reject_if": must_reject_if,
        "judge_confidence": judge.get("confidence"),
        "judge_decision": judge.get("decision"),
        "take_profit_price": take_profit,
        "take_profit_2_price": take_profit_2,
        "stop_loss_price": stop_loss,
        "invalidation_price": invalidation,
        "trailing_stop": {
            "active": bool(position.get("trailing_active")),
            "trigger_pct": trailing_trigger_pct,
            "distance_pct": trailing_distance_pct,
            "highest_price_seen": _num(position.get("highest_price_seen")),
        },
        "position": {
            "entry_price": _num(position.get("entry_price")),
            "entry_time": position.get("entry_time"),
            "entry_reason": position.get("entry_reason"),
            "size_base": _num(position.get("position_size_base")),
            "size_quote_usdc": backfill.get("size_quote_usdc"),
            "close_price": backfill.get("close_price"),
            "close_time": position.get("close_time") or position.get("closed_at"),
            "close_reason": position.get("close_reason"),
            "realized_pnl": backfill.get("realized_pnl"),
        }
        if has_position
        else None,
        "analysis_available": bool(analysis),
    }


def get_thesis_report() -> dict:
    positions = _positions_by_ticker()
    analyses = _latest_analysis_by_ticker()
    orders = _all_orders()
    tickers = sorted(set(positions) | set(analyses))
    items = [_build_ticker_thesis(t, positions.get(t), analyses.get(t), orders) for t in tickers]
    # An open position stays visible regardless of the current ticker
    # universe -- only closed/watching entries for tickers the bot no longer
    # follows are filtered out.
    allowed = get_allowed_tickers()
    if allowed:
        allowed_set = set(allowed)
        items = [i for i in items if i["status"] == "open" or i["ticker"].upper() in allowed_set]
    items.sort(key=lambda i: (i["status"] != "open", i["status"] != "closed", i["ticker"]))
    return {
        "tickers": items,
        "summary": {
            "open_count": sum(1 for i in items if i["status"] == "open"),
            "closed_count": sum(1 for i in items if i["status"] == "closed"),
            "watching_count": sum(1 for i in items if i["status"] == "watching"),
        },
    }
