from __future__ import annotations

import csv
import json
import os
from collections import Counter, defaultdict, deque
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from bot.atomic_io import atomic_write_json
from bot.growbot_river_learning_contract import build_learning_context_snapshot, sanitize_learning_context_snapshot


STATE_PATH = Path("state/reflection_learning_context.json")
REPORT_JSON_PATH = Path("reports/reflection/reflection-learning-latest.json")
REPORT_MD_PATH = Path("reports/reflection/reflection-learning-latest.md")
MISSED_JSON_PATH = Path("reports/reflection/missed-opportunities-latest.json")
SOURCE_POLICY = "reflection_context_only_no_order_authority"
DEFAULT_TTL_MINUTES = 240
REFLECTION_LABELS = {
    "correct_wait",
    "missed_opportunity",
    "bad_avoid",
    "too_strict_wait",
    "correct_avoid",
    "false_signal_avoided",
    "good_trade",
    "bad_trade",
    "early_entry",
    "late_entry",
    "good_exit",
    "bad_exit",
    "missed_exit",
    "overtrading_risk",
    "insufficient_evidence",
}
WAIT_DECISIONS = {"wait", "watch", "skip", "no_trade", "reject", "hold", "entry_gate_skip", "entry_gate_watch"}
TRADE_DECISIONS = {"approve_trade", "buy", "enter", "open_position", "approve_trade_candidate"}
STRICT_BLOCKER_HINTS = ("strict", "threshold", "too_strict", "trigger_ready", "confidence", "conservative", "gate")


def now_utc() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def isoformat_z(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value in (None, ""):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _to_decimal(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if out.is_nan() or out.is_infinite():
        return None
    return out


def _to_float(value: Any) -> Optional[float]:
    dec = _to_decimal(value)
    return None if dec is None else float(dec)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> List[Any]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _first(mapping: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def config_from_env(env: Optional[Dict[str, str]] = None, **overrides: Any) -> Dict[str, Any]:
    env_map = env or os.environ
    windows = str(env_map.get("REFLECTION_EVAL_WINDOWS_HOURS", "4,8,12,24"))
    cfg = {
        "roundtrip_fee_pct": _to_float(env_map.get("REFLECTION_EVAL_DEFAULT_ROUNDTRIP_FEE_PCT")) or 0.012,
        "slippage_buffer_pct": _to_float(env_map.get("REFLECTION_EVAL_DEFAULT_SLIPPAGE_BUFFER_PCT")) or 0.0025,
        "min_net_opportunity_pct": _to_float(env_map.get("REFLECTION_EVAL_MIN_NET_OPPORTUNITY_PCT")) or 0.005,
        "max_acceptable_mae_pct": _to_float(env_map.get("REFLECTION_EVAL_MAX_ACCEPTABLE_MAE_PCT")) or 0.010,
        "windows_hours": [int(p) for p in windows.split(",") if p.strip().isdigit()],
    }
    cfg.update({k: v for k, v in overrides.items() if v is not None})
    if not cfg["windows_hours"]:
        cfg["windows_hours"] = [4, 8, 12, 24]
    return cfg


def _candle_time(candle: Dict[str, Any]) -> Optional[datetime]:
    raw = _first(candle, ("timestamp", "time", "datetime", "date", "start"))
    if isinstance(raw, (int, float)):
        value = float(raw)
        if value > 10_000_000_000:
            value /= 1000.0
        return datetime.fromtimestamp(value, tz=timezone.utc)
    return parse_time(raw)


def _normalize_candle(row: Dict[str, Any], *, product_id: str = "", timeframe: str = "") -> Optional[Dict[str, Any]]:
    high = _to_float(_first(row, ("high", "h")))
    low = _to_float(_first(row, ("low", "l")))
    close = _to_float(_first(row, ("close", "c", "price", "last")))
    ts = _candle_time(row)
    if ts is None or high is None or low is None or close is None:
        return None
    return {
        "timestamp": isoformat_z(ts),
        "start": int(ts.timestamp()),
        "open": _to_float(_first(row, ("open", "o"))) or close,
        "high": high,
        "low": low,
        "close": close,
        "volume": _to_float(_first(row, ("volume", "v"))) or 0.0,
        "product_id": str(row.get("product_id") or product_id).upper(),
        "timeframe": str(row.get("timeframe") or timeframe).upper(),
    }


def load_local_candles(root: Path = Path("."), *, ticker: str) -> List[Dict[str, Any]]:
    ticker_norm = str(ticker or "").upper().replace("-", "_").lower()
    paths = [
        root / "data/candles" / f"{ticker_norm}_1h.csv",
        root / "data/candles" / f"{ticker_norm}_15m.csv",
        root / f"research_data/coinbase/candles/product={str(ticker).upper()}/timeframe=1H/study_window=3y.json",
    ]
    rows: List[Dict[str, Any]] = []
    for path in paths:
        if not path.exists():
            continue
        try:
            if path.suffix == ".csv":
                with path.open("r", encoding="utf-8", newline="") as handle:
                    raw_rows = list(csv.DictReader(handle))
                product = str(ticker).upper()
                rows = [c for c in (_normalize_candle(r, product_id=product, timeframe="1H") for r in raw_rows) if c]
            else:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, list):
                    rows = [c for c in (_normalize_candle(r) for r in payload if isinstance(r, dict)) if c]
        except Exception:
            rows = []
        if rows:
            return sorted(rows, key=lambda c: int(c["start"]))
    return []


def _candles_for_window(candles: Sequence[Dict[str, Any]], decision_time: datetime, hours: int) -> List[Dict[str, Any]]:
    end = decision_time + timedelta(hours=hours)
    selected = []
    for candle in candles:
        ts = _candle_time(candle)
        if ts and decision_time <= ts <= end:
            selected.append(candle)
    return selected


def _extract_price(decision: Dict[str, Any]) -> Optional[float]:
    feature_pack = _as_dict(decision.get("feature_pack"))
    market = _as_dict(feature_pack.get("market"))
    orderbook = _as_dict(feature_pack.get("orderbook_context"))
    trade_plan = _as_dict(decision.get("trade_plan"))
    for value in (
        decision.get("entry_reference_price"),
        decision.get("current_price"),
        trade_plan.get("entry_mid_price"),
        market.get("mid_price"),
        orderbook.get("mid_price"),
        market.get("price"),
        market.get("last_price"),
        orderbook.get("best_ask"),
    ):
        price = _to_float(value)
        if price and price > 0:
            return price
    return None


def _spread_pct(decision: Dict[str, Any]) -> float:
    feature_pack = _as_dict(decision.get("feature_pack"))
    market = _as_dict(feature_pack.get("market"))
    orderbook = _as_dict(feature_pack.get("orderbook_context"))
    direct = _to_float(market.get("spread_pct") or orderbook.get("bid_ask_spread_pct") or decision.get("estimated_spread_cost_pct"))
    if direct is not None:
        return max(0.0, direct)
    bid = _to_float(orderbook.get("best_bid") or market.get("best_bid"))
    ask = _to_float(orderbook.get("best_ask") or market.get("best_ask"))
    mid = _to_float(orderbook.get("mid_price") or market.get("mid_price"))
    if bid and ask and mid and mid > 0:
        return max(0.0, (ask - bid) / mid)
    return 0.0


def _risk_warnings(decision: Dict[str, Any]) -> List[str]:
    feature_pack = _as_dict(decision.get("feature_pack"))
    external = _as_dict(_as_dict(_as_dict(feature_pack.get("decision_context")).get("external_context")).get("market_intelligence"))
    summary = _as_dict(external.get("summary"))
    warnings = _as_list(summary.get("risk_warnings")) + _as_list(decision.get("market_intelligence_risk_warnings"))
    return [str(w) for w in warnings if str(w)]


def _setup_visible(decision: Dict[str, Any]) -> bool:
    if decision.get("setup_visible") is not None:
        return bool(decision.get("setup_visible"))
    setup = str(decision.get("setup_type") or _as_dict(decision.get("entry_gate")).get("setup_type") or _as_dict(decision.get("trade_plan")).get("setup_type") or "")
    reasons = _as_list(_as_dict(decision.get("entry_gate")).get("reasons")) + _as_list(_as_dict(decision.get("judge")).get("reasons"))
    trigger = _as_dict(decision.get("trade_plan")).get("trigger")
    return bool(setup.strip() or trigger or reasons)


def _fillable_entry(decision: Dict[str, Any]) -> bool:
    if decision.get("fillable_entry_estimate") is not None:
        return bool(decision.get("fillable_entry_estimate"))
    return _spread_pct(decision) <= 0.006


def _main_blocker(decision: Dict[str, Any]) -> str:
    for key in ("main_blocker", "blocker", "reject_reason", "reason"):
        if decision.get(key):
            return str(decision.get(key))
    gate = _as_dict(decision.get("entry_gate"))
    warnings = _as_list(gate.get("warnings"))
    return str(warnings[0]) if warnings else ""


def _strict_blocker(blocker: str) -> bool:
    lower = blocker.lower()
    return any(hint in lower for hint in STRICT_BLOCKER_HINTS)


def _invalidation_price(decision: Dict[str, Any], entry_price: float) -> Optional[float]:
    plan = _as_dict(decision.get("trade_plan"))
    raw = _first(plan, ("stop_loss", "invalidation_price", "invalidation")) or decision.get("invalidation_price")
    val = _to_float(raw)
    if val and val > 0:
        return val
    return None


def _lookback_candles(candles: Sequence[Dict[str, Any]], decision_time: Optional[datetime], *, hours: int = 24) -> List[Dict[str, Any]]:
    """Candles strictly at-or-before decision time; never looks into the future."""
    if decision_time is None:
        return []
    start = decision_time - timedelta(hours=hours)
    rows = []
    for candle in candles:
        ts = _candle_time(candle)
        if ts is not None and start <= ts <= decision_time:
            rows.append(candle)
    return rows


def _compact_episode_evidence(
    *,
    ticker: str,
    setup_type: Any,
    label: str,
    confidence: float,
    spread_pct: float,
    fee_pct: float,
    slippage_pct: float,
    net_edge_pct: Optional[float] = None,
    mfe_pct: Optional[float] = None,
    mae_pct: Optional[float] = None,
) -> Dict[str, Any]:
    total_cost = fee_pct + spread_pct + slippage_pct
    reward_to_fee = round(mfe_pct / total_cost, 6) if mfe_pct is not None and total_cost > 0 else None
    reward_to_risk = round(mfe_pct / abs(mae_pct), 6) if mfe_pct is not None and mae_pct is not None and mae_pct < 0 else None
    return {
        "ticker": ticker,
        "setup_type": setup_type,
        "exit_result": label,
        "confidence": confidence,
        "estimated_net_after_cost_opportunity_pct": net_edge_pct,
        "estimated_roundtrip_fee_pct": fee_pct,
        "estimated_spread_cost_pct": spread_pct,
        "estimated_slippage_buffer_pct": slippage_pct,
        "max_favorable_excursion_pct": mfe_pct,
        "max_adverse_excursion_pct": mae_pct,
        "reward_to_fee": reward_to_fee,
        "reward_to_risk": reward_to_risk,
    }


def _resolve_episode_learning_context(
    decision: Dict[str, Any],
    evidence: Dict[str, Any],
    lookback_candles: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Preserve any pre-existing source-time context; otherwise derive one.

    A decision that already carries non-empty state or a known regime was
    captured earlier in the pipeline (decision_outcome_tracker, trade
    reflection, ...) and must not be silently overwritten by this
    retrospective evaluation.  Only a genuinely empty/unknown context is
    filled in from the evidence this function already computes.
    """
    existing = decision.get("growbot_river_learning_context") if isinstance(decision.get("growbot_river_learning_context"), dict) else {}
    existing_state = existing.get("state") if isinstance(existing.get("state"), dict) else {}
    existing_regime = str(existing.get("regime") or "").strip().lower()
    if existing_state or (existing_regime and existing_regime not in {"", "unknown", "none", "null"}):
        return sanitize_learning_context_snapshot(existing)
    return build_learning_context_snapshot(decision.get("feature_pack"), evidence, candles=lookback_candles)


def evaluate_decision_window(
    decision: Dict[str, Any],
    candles: Sequence[Dict[str, Any]],
    *,
    future_window_hours: int,
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    cfg = config or config_from_env()
    decision_time = parse_time(decision.get("decision_time") or decision.get("created_at") or decision.get("generated_at") or decision.get("timestamp"))
    ticker = str(decision.get("ticker") or decision.get("product_id") or "").upper()
    decision_type = str(decision.get("decision_type") or decision.get("decision") or _as_dict(decision.get("judge")).get("decision") or "").lower()
    entry_price = _extract_price(decision)
    lookback = _lookback_candles(candles, decision_time)
    base = {
        "ticker": ticker,
        "decision_time": isoformat_z(decision_time) if decision_time else None,
        "decision_type": decision_type or "unknown",
        "setup_type": decision.get("setup_type") or _as_dict(decision.get("entry_gate")).get("setup_type") or _as_dict(decision.get("trade_plan")).get("setup_type"),
        "main_blocker": _main_blocker(decision),
        "side_bias": decision.get("side_bias") or _as_dict(decision.get("judge")).get("side") or "BUY",
        "future_window_hours": int(future_window_hours),
        "entry_reference_price": entry_price,
        "estimated_roundtrip_fee_pct": cfg["roundtrip_fee_pct"],
        "estimated_spread_cost_pct": _spread_pct(decision),
        "estimated_slippage_buffer_pct": cfg["slippage_buffer_pct"],
        "fillable_entry_estimate": _fillable_entry(decision),
        "fillable_exit_estimate": True,
        "invalidation_would_have_triggered": False,
        "label": "insufficient_evidence",
        "confidence": 0.2,
        "reason": "insufficient_decision_or_candle_data",
    }
    if not decision_time or not entry_price or not candles:
        evidence = _compact_episode_evidence(
            ticker=ticker, setup_type=base["setup_type"], label=base["label"], confidence=base["confidence"],
            spread_pct=base["estimated_spread_cost_pct"], fee_pct=cfg["roundtrip_fee_pct"], slippage_pct=cfg["slippage_buffer_pct"],
        )
        base["growbot_river_learning_context"] = _resolve_episode_learning_context(decision, evidence, lookback)
        return {**base, "available": False, "reason": "insufficient_candle_data" if not candles else "missing_decision_time_or_entry_price"}
    future = _candles_for_window(candles, decision_time, int(future_window_hours))
    if not future:
        evidence = _compact_episode_evidence(
            ticker=ticker, setup_type=base["setup_type"], label=base["label"], confidence=base["confidence"],
            spread_pct=base["estimated_spread_cost_pct"], fee_pct=cfg["roundtrip_fee_pct"], slippage_pct=cfg["slippage_buffer_pct"],
        )
        base["growbot_river_learning_context"] = _resolve_episode_learning_context(decision, evidence, lookback)
        return {**base, "available": False, "reason": "insufficient_candle_data"}
    max_high = max(float(c["high"]) for c in future)
    min_low = min(float(c["low"]) for c in future)
    mfe = (max_high - entry_price) / entry_price
    mae = (min_low - entry_price) / entry_price
    high_ts = next((_candle_time(c) for c in future if float(c["high"]) == max_high), None)
    low_ts = next((_candle_time(c) for c in future if float(c["low"]) == min_low), None)
    inv = _invalidation_price(decision, entry_price)
    inv_hit = bool(inv and min_low <= inv)
    inv_time = next((_candle_time(c) for c in future if inv and float(c["low"]) <= inv), None)
    mfe_time = high_ts
    inv_first = bool(inv_hit and inv_time and mfe_time and inv_time <= mfe_time)
    net = mfe - cfg["roundtrip_fee_pct"] - base["estimated_spread_cost_pct"] - cfg["slippage_buffer_pct"]
    setup_visible = _setup_visible(decision)
    risk_warnings = _risk_warnings(decision)
    label = "correct_wait"
    confidence = 0.45
    reason = "no_cost_aware_opportunity_after_anti_hindsight_filters"
    if decision_type in TRADE_DECISIONS:
        if mae <= -cfg["max_acceptable_mae_pct"] and net < cfg["min_net_opportunity_pct"]:
            label, confidence, reason = "bad_trade", 0.65, "trade_had_fast_adverse_path_and_no_net_edge"
        elif mae <= -cfg["max_acceptable_mae_pct"]:
            label, confidence, reason = "early_entry", 0.6, "trade_absorbed_unacceptable_mae"
        elif net >= cfg["min_net_opportunity_pct"]:
            label, confidence, reason = "good_trade", 0.55, "trade_had_positive_net_mfe_after_costs"
        else:
            label, confidence, reason = "overtrading_risk", 0.55, "approved_trade_candidate_had_low_reward_to_fee"
        if decision_type == "approve_trade_candidate" and mae <= -cfg["max_acceptable_mae_pct"] and mfe > 0:
            label, confidence, reason = "overtrading_risk", 0.65, "candidate_looked_like_false_breakout_after_approval"
    else:
        anti_hindsight_ok = (
            setup_visible
            and base["fillable_entry_estimate"]
            and net >= cfg["min_net_opportunity_pct"]
            and abs(mae) <= cfg["max_acceptable_mae_pct"]
            and not inv_first
            and not risk_warnings
        )
        if anti_hindsight_ok:
            if _strict_blocker(base["main_blocker"]):
                label, confidence, reason = "too_strict_wait", 0.72, "visible_setup_positive_net_path_and_strict_blocker"
            else:
                label, confidence, reason = "missed_opportunity", 0.65, "visible_setup_positive_net_path_passed_anti_hindsight_filters"
        elif risk_warnings:
            label, confidence, reason = "correct_wait", 0.68, "market_intelligence_risk_warning_blocked_hindsight_label"
        elif inv_first or inv_hit:
            label, confidence, reason = "correct_wait", 0.65, "invalidation_would_have_triggered_before_or_during_opportunity"
        elif not setup_visible:
            label, confidence, reason = "correct_wait", 0.55, "price_moved_but_setup_was_not_visible_at_decision_time"
        elif abs(mae) > cfg["max_acceptable_mae_pct"]:
            label, confidence, reason = "correct_wait", 0.62, "mae_exceeded_acceptable_drawdown"
        elif net < cfg["min_net_opportunity_pct"]:
            label, confidence, reason = "correct_wait", 0.58, "net_after_cost_opportunity_below_minimum_edge"
    evidence = _compact_episode_evidence(
        ticker=ticker, setup_type=base["setup_type"], label=label, confidence=confidence,
        spread_pct=base["estimated_spread_cost_pct"], fee_pct=cfg["roundtrip_fee_pct"], slippage_pct=cfg["slippage_buffer_pct"],
        net_edge_pct=round(net, 6), mfe_pct=round(mfe, 6), mae_pct=round(mae, 6),
    )
    return {
        **base,
        "available": True,
        "max_favorable_excursion_pct": round(mfe, 6),
        "max_adverse_excursion_pct": round(mae, 6),
        "time_to_mfe_minutes": int((mfe_time - decision_time).total_seconds() // 60) if mfe_time else None,
        "time_to_mae_minutes": int((low_ts - decision_time).total_seconds() // 60) if low_ts else None,
        "estimated_net_after_cost_opportunity_pct": round(net, 6),
        "invalidation_would_have_triggered": inv_hit,
        "invalidation_would_have_triggered_before_mfe": inv_first,
        "setup_visible_at_decision_time": setup_visible,
        "market_intelligence_risk_warnings": risk_warnings,
        "label": label,
        "confidence": confidence,
        "reason": reason,
        "growbot_river_learning_context": _resolve_episode_learning_context(decision, evidence, lookback),
    }


def _decision_from_analysis(row: Dict[str, Any]) -> Dict[str, Any]:
    judge = _as_dict(row.get("judge"))
    gate = _as_dict(row.get("entry_gate") or _as_dict(row.get("feature_pack")).get("entry_gate"))
    plan = _as_dict(row.get("trade_plan"))
    return {
        "ticker": row.get("ticker") or _as_dict(row.get("feature_pack")).get("ticker"),
        "decision_time": row.get("generated_at") or row.get("created_at"),
        "decision": judge.get("decision") or row.get("decision") or "wait",
        "decision_type": judge.get("decision") or row.get("decision") or "wait",
        "setup_type": gate.get("setup_type") or plan.get("setup_type"),
        "main_blocker": _first(row, ("main_blocker", "reject_reason")) or "; ".join(str(x) for x in _as_list(gate.get("warnings"))[:2]),
        "feature_pack": row.get("feature_pack"),
        "entry_gate": gate,
        "judge": judge,
        "trade_plan": plan,
        "growbot_river_learning_context": row.get("growbot_river_learning_context") if isinstance(row.get("growbot_river_learning_context"), dict) else {},
    }


def iter_jsonl(path: Path, *, since: Optional[datetime] = None, until: Optional[datetime] = None, limit: int = 2000) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    try:
        # Stream line-by-line and keep only a bounded tail instead of loading
        # the whole file as one string: this log can grow far larger than the
        # window we ever read, and the old `.read_text().splitlines()` held
        # the full file (plus a full copy as a list of lines) in memory just
        # to discard everything but the last `limit` lines.
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            tail_lines = deque(handle, maxlen=max(1, limit))
    except FileNotFoundError:
        return []
    for line in tail_lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(row, dict):
            continue
        ts = parse_time(row.get("generated_at") or row.get("created_at") or row.get("timestamp"))
        if since and ts and ts < since:
            continue
        if until and ts and ts > until:
            continue
        rows.append(row)
    return rows


def collect_decisions(root: Path = Path("."), *, since: Optional[datetime] = None, until: Optional[datetime] = None, fixture_only: bool = False) -> List[Dict[str, Any]]:
    if fixture_only:
        return fixture_decisions()
    decisions: List[Dict[str, Any]] = []
    for row in iter_jsonl(root / "logs/analysis.jsonl", since=since, until=until):
        dec = _decision_from_analysis(row)
        if dec.get("ticker") and dec.get("decision_time"):
            decisions.append(dec)
    state = root / "state/decision_outcomes.json"
    try:
        payload = json.loads(state.read_text(encoding="utf-8"))
        records = payload.get("records") if isinstance(payload, dict) else []
    except Exception:
        records = []
    for rec in records if isinstance(records, list) else []:
        if not isinstance(rec, dict):
            continue
        ts = parse_time(rec.get("created_at"))
        if since and ts and ts < since:
            continue
        if until and ts and ts > until:
            continue
        decisions.append(
            {
                "ticker": rec.get("ticker"),
                "decision_time": rec.get("created_at"),
                "decision": rec.get("decision"),
                "decision_type": rec.get("decision_category") or rec.get("decision"),
                "current_price": rec.get("current_price"),
                "setup_type": _as_dict(rec.get("entry_gate")).get("setup_type") or _as_dict(rec.get("trade_plan")).get("setup_type"),
                "trade_plan": rec.get("trade_plan"),
                "entry_gate": rec.get("entry_gate"),
                "growbot_river_learning_context": rec.get("growbot_river_learning_context") if isinstance(rec.get("growbot_river_learning_context"), dict) else {},
            }
        )
    unique: Dict[str, Dict[str, Any]] = {}
    for dec in decisions:
        key = f"{dec.get('ticker')}|{dec.get('decision_time')}|{dec.get('decision_type')}"
        unique[key] = dec
    return list(unique.values())


def fixture_decisions() -> List[Dict[str, Any]]:
    return [
        {"ticker": "BTC-USDC", "decision_time": "2026-06-14T00:00:00Z", "decision": "wait", "decision_type": "wait", "current_price": 100.0, "setup_visible": True, "setup_type": "reclaim_reversal", "main_blocker": "trigger_ready_too_strict_threshold", "feature_pack": {"market": {"spread_pct": 0.0005}}},
        {"ticker": "BTC-USDC", "decision_time": "2026-06-14T04:00:00Z", "decision": "approve_trade", "decision_type": "approve_trade", "current_price": 104.0, "setup_visible": True, "setup_type": "breakout", "feature_pack": {"market": {"spread_pct": 0.0005}}},
    ]


def fixture_candles() -> Dict[str, List[Dict[str, Any]]]:
    start = datetime(2026, 6, 14, tzinfo=timezone.utc)
    prices = [100, 100.2, 99.8, 101.5, 103.0, 104.0, 103.5, 105.0, 104.0, 101.0, 100.0, 99.0, 98.8]
    rows = []
    for idx, price in enumerate(prices):
        ts = start + timedelta(hours=idx)
        rows.append({"timestamp": isoformat_z(ts), "start": int(ts.timestamp()), "open": price, "high": price * 1.004, "low": price * 0.997, "close": price, "volume": 1.0, "product_id": "BTC-USDC", "timeframe": "1H"})
    return {"BTC-USDC": rows}


def build_reflection_learning_report(
    *,
    root: Path = Path("."),
    since: Optional[datetime] = None,
    until: Optional[datetime] = None,
    windows_hours: Optional[Sequence[int]] = None,
    no_network: bool = True,
    fixture_only: bool = False,
    min_net_opportunity_pct: Optional[float] = None,
    max_acceptable_mae_pct: Optional[float] = None,
) -> Dict[str, Any]:
    cfg = config_from_env(min_net_opportunity_pct=min_net_opportunity_pct, max_acceptable_mae_pct=max_acceptable_mae_pct)
    if windows_hours:
        cfg["windows_hours"] = [int(h) for h in windows_hours if int(h) > 0]
    decisions = collect_decisions(root, since=since, until=until, fixture_only=fixture_only)
    candle_cache = fixture_candles() if fixture_only else {}
    evaluations: List[Dict[str, Any]] = []
    for decision in decisions:
        ticker = str(decision.get("ticker") or "").upper()
        candles = candle_cache.get(ticker)
        if candles is None:
            candles = load_local_candles(root, ticker=ticker)
            candle_cache[ticker] = candles
        for window in cfg["windows_hours"]:
            evaluations.append(evaluate_decision_window(decision, candles, future_window_hours=window, config=cfg))
    label_counts = Counter(str(ev.get("label")) for ev in evaluations)
    blockers = Counter(str(ev.get("main_blocker") or "unknown") for ev in evaluations if ev.get("main_blocker"))
    setup_totals: Dict[str, Counter] = defaultdict(Counter)
    mfe_values = [ev.get("max_favorable_excursion_pct") for ev in evaluations if ev.get("max_favorable_excursion_pct") is not None]
    mae_values = [ev.get("max_adverse_excursion_pct") for ev in evaluations if ev.get("max_adverse_excursion_pct") is not None]
    net_values = [ev.get("estimated_net_after_cost_opportunity_pct") for ev in evaluations if ev.get("estimated_net_after_cost_opportunity_pct") is not None]
    for ev in evaluations:
        setup_totals[str(ev.get("setup_type") or "unknown")][str(ev.get("label"))] += 1
    over = label_counts["overtrading_risk"] + label_counts["bad_trade"] + label_counts["early_entry"]
    missed = label_counts["missed_opportunity"] + label_counts["too_strict_wait"]
    correct_wait = label_counts["correct_wait"] + label_counts["correct_avoid"] + label_counts["false_signal_avoided"]
    if missed >= 6 and missed > (over * 2):
        recommendation = "propose_candidate_profile"
        overall_bias = "too_strict"
    elif over > missed and over >= 2:
        recommendation = "keep_current"
        overall_bias = "too_loose"
    elif evaluations:
        recommendation = "keep_current" if missed < 3 else "investigate_probe"
        overall_bias = "balanced"
    else:
        recommendation = "keep_current"
        overall_bias = "unknown"
    evidence_strength = "high" if len(evaluations) >= 40 else "medium" if len(evaluations) >= 10 else "low"
    report = {
        "phase": "reflection_learning_context_v1",
        "generated_at": isoformat_z(now_utc()),
        "available": bool(evaluations),
        "read_only": True,
        "no_network": bool(no_network),
        "fixture_only": bool(fixture_only),
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "coinbase_submit_cancel_replace_calls_attempted": False,
        "env_mutation_performed": False,
        "production_order_state_mutation_performed": False,
        "counts": {
            "wait_decisions": sum(1 for d in decisions if str(d.get("decision") or d.get("decision_type")).lower() in WAIT_DECISIONS),
            "approve_trade_decisions": sum(1 for d in decisions if str(d.get("decision") or d.get("decision_type")).lower() in TRADE_DECISIONS),
            "executed_trades": 0,
            "insufficient_evidence": label_counts["insufficient_evidence"],
            "correct_wait": label_counts["correct_wait"],
            "missed_opportunity": label_counts["missed_opportunity"],
            "too_strict_wait": label_counts["too_strict_wait"],
            "correct_avoid": label_counts["correct_avoid"],
            "overtrading_risk": label_counts["overtrading_risk"],
        },
        "label_counts": dict(label_counts),
        "top_blockers": blockers.most_common(10),
        "setup_type_label_counts": {setup: dict(counter) for setup, counter in setup_totals.items()},
        "mfe_distribution": _distribution(mfe_values),
        "mae_distribution": _distribution(mae_values),
        "net_after_cost_distribution": _distribution(net_values),
        "evaluations": evaluations,
        "proposal": {
            "recommendation": recommendation,
            "safe_to_activate_now": False,
            "requires_operator_review": recommendation != "keep_current",
            "candidate_type": "bounded_exploration_or_threshold_adjustment" if recommendation == "propose_candidate_profile" else "none",
            "suggested_scope": "only_reclaim_reversal_or_support_reclaim" if recommendation == "propose_candidate_profile" else "",
            "evidence": {
                "missed_opportunity_count": missed,
                "correct_wait_count": correct_wait,
                "overtrading_risk_count": over,
            },
        },
        "summary": {
            "overall_bias": overall_bias,
            "evidence_strength": evidence_strength,
            "missed_opportunity_count": missed,
            "correct_wait_count": correct_wait,
            "overtrading_risk_count": over,
            "dominant_blockers": [item[0] for item in blockers.most_common(5)],
            "setup_patterns": sorted(set(str(ev.get("setup_type")) for ev in evaluations if ev.get("setup_type"))),
            "recommendations": [recommendation],
        },
        "cost_assumptions": cfg,
    }
    if not evaluations:
        report["available"] = False
        report["reason"] = "insufficient_candle_data"
    return report


def _distribution(values: Sequence[Any]) -> Dict[str, Any]:
    clean = sorted(float(v) for v in values if v is not None)
    if not clean:
        return {"count": 0, "min": None, "median": None, "max": None}
    return {"count": len(clean), "min": clean[0], "median": clean[len(clean) // 2], "max": clean[-1]}


def build_context_state(report: Dict[str, Any], *, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> Dict[str, Any]:
    generated = now_utc()
    summary = deepcopy(_as_dict(report.get("summary")))
    if not summary:
        summary = {
            "overall_bias": "unknown",
            "evidence_strength": "low",
            "missed_opportunity_count": 0,
            "correct_wait_count": 0,
            "overtrading_risk_count": 0,
            "dominant_blockers": [],
            "setup_patterns": [],
            "recommendations": [],
        }
    if summary.get("evidence_strength") not in {"medium", "high"}:
        summary["evidence_strength"] = "low"
    return {
        "generated_at": isoformat_z(generated),
        "ttl_minutes": int(ttl_minutes),
        "expires_at": isoformat_z(generated + timedelta(minutes=ttl_minutes)),
        "available": bool(report.get("available")) and summary.get("evidence_strength") != "low",
        "stale": False,
        "source_policy": SOURCE_POLICY,
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
        "summary": summary,
    }


def load_reflection_learning_context(path: Path = STATE_PATH, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    if not path.exists():
        return {
            "available": False,
            "stale": True,
            "summary": {"overall_bias": "unknown", "evidence_strength": "low", "missed_opportunity_count": 0, "correct_wait_count": 0, "overtrading_risk_count": 0, "dominant_blockers": [], "setup_patterns": [], "recommendations": []},
            "can_authorize_execution": False,
            "can_block_execution": False,
            "can_mutate_parameters": False,
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"available": False, "stale": True, "summary": {"overall_bias": "unknown", "evidence_strength": "low"}, "can_authorize_execution": False, "can_block_execution": False, "can_mutate_parameters": False}
    expires = parse_time(data.get("expires_at"))
    data["stale"] = True if expires is None else (now or now_utc()) >= expires
    data["can_authorize_execution"] = False
    data["can_block_execution"] = False
    data["can_mutate_parameters"] = False
    return data


def feature_pack_reflection_learning_context(root: Path = Path(".")) -> Dict[str, Any]:
    ctx = load_reflection_learning_context(root / STATE_PATH)
    return {
        "available": bool(ctx.get("available")),
        "stale": bool(ctx.get("stale")),
        "summary": deepcopy(_as_dict(ctx.get("summary"))),
        "can_authorize_execution": False,
        "can_block_execution": False,
        "can_mutate_parameters": False,
    }


def inject_reflection_learning_feature_pack(feature_pack: Dict[str, Any], root: Path = Path("."), *, env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    pack = feature_pack if isinstance(feature_pack, dict) else {}
    if (env or os.environ).get("ENABLE_REFLECTION_LEARNING_CONTEXT", "false").strip().lower() not in {"1", "true", "yes", "on"}:
        return pack
    decision_context = pack.setdefault("decision_context", {})
    external = decision_context.setdefault("external_context", {})
    external["reflection_learning"] = feature_pack_reflection_learning_context(root)
    return pack


def write_report_outputs(report: Dict[str, Any], *, root: Path = Path("."), json_out: Optional[Path] = None) -> Dict[str, str]:
    json_path = root / (json_out or REPORT_JSON_PATH)
    md_path = root / REPORT_MD_PATH
    missed_path = root / MISSED_JSON_PATH
    state_path = root / STATE_PATH
    for path in (json_path, md_path, missed_path, state_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(json_path, report)
    missed = [ev for ev in report.get("evaluations", []) if ev.get("label") in {"missed_opportunity", "too_strict_wait"}]
    atomic_write_json(missed_path, {"generated_at": report.get("generated_at"), "count": len(missed), "items": missed, "source_policy": SOURCE_POLICY})
    atomic_write_json(state_path, build_context_state(report))
    md_path.write_text(render_report_markdown(report), encoding="utf-8")
    from bot.reflection_persistence import (
        append_parameter_pressure_events,
        append_reflection_evaluations,
        load_reflection_events,
        write_reflection_snapshots,
    )

    ledger = append_reflection_evaluations(report, root=root)
    reflection_events, _corrupt = load_reflection_events(root)
    pressure = append_parameter_pressure_events(reflection_events, root=root)
    snapshots = write_reflection_snapshots(report, root=root)
    return {
        "json": str(json_path),
        "markdown": str(md_path),
        "missed": str(missed_path),
        "state": str(state_path),
        "reflection_ledger": ledger["path"],
        "parameter_pressure_ledger": pressure["path"],
        **snapshots,
    }


def render_report_markdown(report: Dict[str, Any]) -> str:
    counts = _as_dict(report.get("counts"))
    summary = _as_dict(report.get("summary"))
    proposal = _as_dict(report.get("proposal"))
    lines = [
        "# Reflection Learning Context",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Available: {report.get('available')}",
        f"Source policy: {SOURCE_POLICY}",
        "",
        "## Summary",
        f"- overall_bias: {summary.get('overall_bias')}",
        f"- evidence_strength: {summary.get('evidence_strength')}",
        f"- recommendation: {proposal.get('recommendation')}",
        f"- safe_to_activate_now: {proposal.get('safe_to_activate_now')}",
        "",
        "## Counts",
    ]
    for key in sorted(counts):
        lines.append(f"- {key}: {counts[key]}")
    lines.extend(
        [
            "",
            "## Safety",
            "- read_only: true",
            "- can_authorize_execution: false",
            "- can_block_execution: false",
            "- can_mutate_parameters: false",
            "- no Coinbase submit/cancel/replace calls",
            "- no .env mutation",
            "- no production order-state mutation",
        ]
    )
    return "\n".join(lines) + "\n"


__all__ = [
    "REFLECTION_LABELS",
    "STATE_PATH",
    "SOURCE_POLICY",
    "build_context_state",
    "build_reflection_learning_report",
    "evaluate_decision_window",
    "feature_pack_reflection_learning_context",
    "inject_reflection_learning_feature_pack",
    "load_reflection_learning_context",
    "write_report_outputs",
]
