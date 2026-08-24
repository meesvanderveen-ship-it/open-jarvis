from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from bot.growbot_river_learning_contract import build_learning_context_snapshot

STATE_DIR = Path("state")
LOGS_DIR = Path("logs")
STATE_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

ACTIVE_STATUSES = {"pending"}
FINAL_STATUSES = {"resolved", "expired", "cancelled"}
ENTRY_PLAN_ACTIONS = {"prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion"}
ACTIVE_ENTRY_DECISIONS = {"approve_trade", "buy", "enter", "open_position"}
WAITLIKE_DECISIONS = {"wait", "watch", "skip", "no_trade", "reject", "hold", "entry_gate_skip", "entry_gate_watch"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if value is None or value == "":
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


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
    return None if d is None else float(d)


def _pct_change(start: Any, end: Any) -> Optional[float]:
    s = _to_decimal(start)
    e = _to_decimal(end)
    if s is None or e is None or s <= 0:
        return None
    return float((e - s) / s)


def _normalize_ticker(ticker: Any) -> str:
    return str(ticker or "").upper().strip()


def _safe_list(value: Any) -> List[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return []


def _first_present(mapping: Dict[str, Any], keys: Iterable[str]) -> Any:
    for key in keys:
        if key in mapping and mapping.get(key) not in (None, ""):
            return mapping.get(key)
    return None


def extract_current_price(feature_pack: Dict[str, Any]) -> Optional[float]:
    """Extract current/last price from the bot's flexible feature_pack shapes.

    Supports current Coinbase bot feature_pack shapes:
    - market.mid_price
    - orderbook_context.mid_price
    - raw_context timeframe latest_close / closes arrays
    """
    if not isinstance(feature_pack, dict):
        return None

    direct_paths = [
        ("current_price",),
        ("price",),
        ("last_price",),
        ("mid_price",),
        ("ticker", "price"),
        ("ticker", "last_price"),
        ("ticker", "mid_price"),
        ("market", "price"),
        ("market", "last_price"),
        ("market", "mid_price"),
        ("orderbook_context", "mid_price"),
        ("orderbook_context", "best_bid"),
        ("orderbook_context", "best_ask"),
        ("microstructure", "mid_price"),
        ("microstructure", "last_price"),
    ]

    for path in direct_paths:
        node: Any = feature_pack
        ok = True
        for key in path:
            if not isinstance(node, dict) or key not in node:
                ok = False
                break
            node = node.get(key)
        if ok:
            price = _to_float(node)
            if price and price > 0:
                return price

    for container_key in ("market", "orderbook_context"):
        container = feature_pack.get(container_key)
        if isinstance(container, dict):
            bid = _to_decimal(container.get("best_bid"))
            ask = _to_decimal(container.get("best_ask"))
            if bid and ask and bid > 0 and ask > 0:
                return float((bid + ask) / Decimal("2"))

    raw_context = feature_pack.get("raw_context")
    if isinstance(raw_context, dict):
        for tf_key in ("1h", "15m", "4h", "1d", "5m"):
            tf = raw_context.get(tf_key)
            if isinstance(tf, dict):
                price = _to_float(tf.get("latest_close"))
                if price and price > 0:
                    return price
                closes = _safe_list(tf.get("closes"))
                if closes:
                    price = _to_float(closes[-1])
                    if price and price > 0:
                        return price

    for tf_key in ("1h", "15m", "4h", "1d", "5m"):
        for container_key in ("timeframes", "candles", "ohlcv", "technical"):
            container = feature_pack.get(container_key)
            if isinstance(container, dict):
                candles = container.get(tf_key)
                price = _last_candle_price(candles)
                if price and price > 0:
                    return price

    for value in feature_pack.values():
        price = _last_candle_price(value)
        if price and price > 0:
            return price

    return None

def _last_candle_price(candles: Any) -> Optional[float]:
    rows = _safe_list(candles)
    if not rows:
        return None
    last = rows[-1]
    if isinstance(last, dict):
        return _to_float(_first_present(last, ("close", "c", "price", "last")))
    if isinstance(last, (list, tuple)) and len(last) >= 5:
        return _to_float(last[4])
    return None


def _candle_time(candle: Any) -> Optional[datetime]:
    if isinstance(candle, dict):
        raw = _first_present(candle, ("time", "timestamp", "start", "datetime", "date"))
        if isinstance(raw, (int, float)):
            try:
                # accept seconds or milliseconds
                val = float(raw)
                if val > 10_000_000_000:
                    val = val / 1000.0
                return datetime.fromtimestamp(val, tz=timezone.utc)
            except Exception:
                return None
        return _parse_dt(raw)
    if isinstance(candle, (list, tuple)) and candle:
        raw = candle[0]
        if isinstance(raw, (int, float)):
            try:
                val = float(raw)
                if val > 10_000_000_000:
                    val = val / 1000.0
                return datetime.fromtimestamp(val, tz=timezone.utc)
            except Exception:
                return None
        return _parse_dt(raw)
    return None


def _candle_high_low_close(candle: Any) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    if isinstance(candle, dict):
        high = _to_float(_first_present(candle, ("high", "h")))
        low = _to_float(_first_present(candle, ("low", "l")))
        close = _to_float(_first_present(candle, ("close", "c", "price", "last")))
        return high, low, close
    if isinstance(candle, (list, tuple)) and len(candle) >= 5:
        # common OHLCV: [time, open, high, low, close, volume]
        return _to_float(candle[2]), _to_float(candle[3]), _to_float(candle[4])
    return None, None, None


def _candles_from_raw_context_timeframe(tf: Any) -> List[Dict[str, Any]]:
    """Convert raw_context timeframe arrays to candle dictionaries."""
    if not isinstance(tf, dict):
        return []

    starts = _safe_list(tf.get("starts"))
    highs = _safe_list(tf.get("highs"))
    lows = _safe_list(tf.get("lows"))
    closes = _safe_list(tf.get("closes"))
    volumes = _safe_list(tf.get("volumes"))

    n = max(len(starts), len(highs), len(lows), len(closes), len(volumes))
    if n <= 0:
        return []

    rows: List[Dict[str, Any]] = []
    for idx in range(n):
        row = {
            "time": starts[idx] if idx < len(starts) else None,
            "high": highs[idx] if idx < len(highs) else None,
            "low": lows[idx] if idx < len(lows) else None,
            "close": closes[idx] if idx < len(closes) else None,
            "volume": volumes[idx] if idx < len(volumes) else None,
        }
        if row["high"] is not None or row["low"] is not None or row["close"] is not None:
            rows.append(row)
    return rows

def extract_candles(feature_pack: Dict[str, Any], preferred_timeframes: Sequence[str] = ("1h", "4h", "15m", "1d")) -> List[Any]:
    """Extract candle rows from supported feature_pack shapes."""
    if not isinstance(feature_pack, dict):
        return []

    raw_context = feature_pack.get("raw_context")
    if isinstance(raw_context, dict):
        for tf_key in preferred_timeframes:
            rows = _candles_from_raw_context_timeframe(raw_context.get(tf_key))
            if rows:
                return rows

    for tf_key in preferred_timeframes:
        for container_key in ("timeframes", "candles", "ohlcv", "technical"):
            container = feature_pack.get(container_key)
            if isinstance(container, dict) and isinstance(container.get(tf_key), list):
                return list(container.get(tf_key) or [])

    for key in ("candles", "ohlcv"):
        if isinstance(feature_pack.get(key), list):
            return list(feature_pack.get(key) or [])

    return []

def compute_path_metrics(
    *,
    start_price: Any,
    candles: Sequence[Any],
    start_time: Any = None,
    stop_loss: Any = None,
    take_profit_1: Any = None,
    take_profit_2: Any = None,
) -> Dict[str, Any]:
    """Compute simple MFE/MAE-style path metrics from candles after a decision.

    This is read-only analytics. It does not model exact fills; it only asks how
    price behaved after a decision/plan, which is enough for learning context.
    """
    start = _to_decimal(start_price)
    if start is None or start <= 0:
        return {
            "available": False,
            "reason": "invalid_start_price",
            "max_favorable_pct": None,
            "max_adverse_pct": None,
            "tp1_touched": False,
            "tp2_touched": False,
            "stop_touched": False,
            "exit_efficiency_proxy": None,
        }

    dt_start = _parse_dt(start_time)
    highs: List[Decimal] = []
    lows: List[Decimal] = []
    closes: List[Decimal] = []

    for candle in candles:
        ct = _candle_time(candle)
        if dt_start and ct and ct < dt_start:
            continue
        high, low, close = _candle_high_low_close(candle)
        hd = _to_decimal(high)
        ld = _to_decimal(low)
        cd = _to_decimal(close)
        if hd is not None and hd > 0:
            highs.append(hd)
        if ld is not None and ld > 0:
            lows.append(ld)
        if cd is not None and cd > 0:
            closes.append(cd)

    if not highs and not lows and not closes:
        return {
            "available": False,
            "reason": "no_future_candles",
            "max_favorable_pct": None,
            "max_adverse_pct": None,
            "tp1_touched": False,
            "tp2_touched": False,
            "stop_touched": False,
            "exit_efficiency_proxy": None,
        }

    max_high = max(highs or closes or [start])
    min_low = min(lows or closes or [start])
    last_close = closes[-1] if closes else None

    max_favorable = (max_high - start) / start
    max_adverse = (min_low - start) / start
    final_change = (last_close - start) / start if last_close is not None else None
    mfe = float(max_favorable)
    mae = float(max_adverse)
    final_pct = float(final_change) if final_change is not None else None
    exit_efficiency = None
    if final_pct is not None and mfe > 0:
        exit_efficiency = max(-1.0, min(1.5, final_pct / mfe))

    sl = _to_decimal(stop_loss)
    tp1 = _to_decimal(take_profit_1)
    tp2 = _to_decimal(take_profit_2)

    return {
        "available": True,
        "reason": "ok",
        "max_favorable_pct": round(mfe, 6),
        "max_adverse_pct": round(mae, 6),
        "final_change_pct": round(final_pct, 6) if final_pct is not None else None,
        "tp1_touched": bool(tp1 is not None and max_high >= tp1),
        "tp2_touched": bool(tp2 is not None and max_high >= tp2),
        "stop_touched": bool(sl is not None and min_low <= sl),
        "exit_efficiency_proxy": round(exit_efficiency, 6) if exit_efficiency is not None else None,
        "high_after_decision": float(max_high),
        "low_after_decision": float(min_low),
        "last_close_after_decision": float(last_close) if last_close is not None else None,
    }


def _decision_category(decision: str, plan_action: str, strategy: str) -> str:
    d = str(decision or "").lower().strip()
    p = str(plan_action or "").lower().strip()
    s = str(strategy or "").lower().strip()
    if d in ACTIVE_ENTRY_DECISIONS:
        return "approved_entry"
    if p in ENTRY_PLAN_ACTIONS:
        return "prepared_plan"
    if "skip" in s or d == "skip":
        return "skip"
    if "watch" in s or d == "watch":
        return "watch"
    if d in WAITLIKE_DECISIONS or not d:
        return "wait"
    return d


def classify_decision_outcome(
    *,
    decision_category: str,
    price_change_pct: Optional[float],
    path_metrics: Dict[str, Any],
    min_move_pct: float,
    adverse_move_pct: float,
) -> str:
    if price_change_pct is None:
        return "unresolved_no_price"
    tp1 = bool(path_metrics.get("tp1_touched"))
    stop = bool(path_metrics.get("stop_touched"))
    mfe = path_metrics.get("max_favorable_pct")
    mae = path_metrics.get("max_adverse_pct")

    strong_up = price_change_pct >= min_move_pct or tp1 or (_to_float(mfe) is not None and float(mfe) >= min_move_pct)
    strong_down = price_change_pct <= -adverse_move_pct or stop or (_to_float(mae) is not None and float(mae) <= -adverse_move_pct)

    if decision_category in {"approved_entry", "prepared_plan"}:
        if strong_up and not stop:
            return "plan_follow_through"
        if strong_down:
            return "false_positive_plan"
        return "plan_inconclusive"

    if decision_category in {"wait", "watch", "skip"}:
        if strong_up and not stop:
            return "missed_opportunity"
        if strong_down:
            return "correct_avoid"
        return "correct_wait_or_neutral"

    return "neutral_or_unclassified"


def build_decision_snapshot_records(
    *,
    ticker: str,
    analysis: Dict[str, Any],
    cycle_result: Optional[Dict[str, Any]] = None,
    feature_pack: Optional[Dict[str, Any]] = None,
    horizons_hours: Sequence[int] = (4, 12, 24),
    generated_at: Any = None,
) -> List[Dict[str, Any]]:
    ticker = _normalize_ticker(ticker or analysis.get("ticker"))
    if not ticker:
        return []
    feature_pack = feature_pack or analysis.get("feature_pack") or {}
    cycle_result = cycle_result or {}
    generated = _parse_dt(generated_at or analysis.get("generated_at") or cycle_result.get("generated_at")) or _now_utc()
    current_price = extract_current_price(feature_pack)
    if current_price is None:
        return []

    judge = analysis.get("judge") or {}
    entry_gate = analysis.get("entry_gate") or {}
    trade_plan = analysis.get("trade_plan") or {}
    chart_patterns = analysis.get("chart_patterns") or {}
    pending_trade_plan = analysis.get("pending_trade_plan") or {}
    strategy = str(cycle_result.get("strategy") or analysis.get("strategy") or "").strip()
    decision = str(judge.get("decision") or cycle_result.get("decision") or "wait").strip().lower()
    plan_action = str(trade_plan.get("plan_action") or "no_plan").strip().lower()
    category = _decision_category(decision, plan_action, strategy)
    learning_context = build_learning_context_snapshot(
        feature_pack,
        {
            **analysis,
            "ticker": ticker,
            "decision": decision,
            "judge": judge,
            "entry_gate": entry_gate,
            "trade_plan": trade_plan,
            "cycle_result": cycle_result,
        },
        candles=extract_candles(feature_pack),
    )

    base = {
        "ticker": ticker,
        "created_at": generated.isoformat(),
        "decision": decision,
        "decision_category": category,
        "strategy": strategy,
        "current_price": current_price,
        "judge": {
            "decision": decision,
            "confidence": judge.get("confidence"),
            "size_quote": judge.get("size_quote"),
            "side": judge.get("side"),
        },
        "entry_gate": {
            "decision": entry_gate.get("decision"),
            "confidence": entry_gate.get("confidence"),
            "setup_type": entry_gate.get("setup_type"),
        },
        "trade_plan": {
            "plan_action": plan_action,
            "setup_type": trade_plan.get("setup_type"),
            "entry_zone_low": trade_plan.get("entry_zone_low"),
            "entry_zone_high": trade_plan.get("entry_zone_high"),
            "trigger": trade_plan.get("trigger"),
            "stop_loss": trade_plan.get("stop_loss"),
            "take_profit_1": trade_plan.get("take_profit_1"),
            "take_profit_2": trade_plan.get("take_profit_2"),
            "do_not_chase_above": trade_plan.get("do_not_chase_above"),
            "confidence": trade_plan.get("confidence"),
        },
        "chart_patterns": {
            "best_pattern_score": chart_patterns.get("best_pattern_score"),
            "pattern_bias": chart_patterns.get("pattern_bias"),
            "summary": chart_patterns.get("summary"),
            "market_structure": chart_patterns.get("market_structure"),
        },
        "pending_trade_plan": {
            "status": pending_trade_plan.get("status"),
            "trigger_ready": pending_trade_plan.get("trigger_ready"),
            "should_force_full_analysis": pending_trade_plan.get("should_force_full_analysis"),
        },
        "growbot_river_learning_context": learning_context,
        "learning_policy": "Observation only. Decision outcomes never change live thresholds, sizing or risk rules without replay/backtest/walk-forward validation.",
    }

    records: List[Dict[str, Any]] = []
    for horizon in horizons_hours:
        try:
            h = int(horizon)
        except Exception:
            continue
        if h <= 0:
            continue
        record = deepcopy(base)
        record["record_id"] = f"{ticker}|{generated.isoformat()}|{h}h|{category}"
        record["horizon_hours"] = h
        record["due_at"] = (generated + timedelta(hours=h)).isoformat()
        record["status"] = "pending"
        records.append(record)
    return records


def _performance_metrics(records: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(records)
    counts: Dict[str, int] = {}
    by_category: Dict[str, Dict[str, int]] = {}
    for rec in records:
        label = str((rec.get("outcome") or {}).get("outcome_label") or rec.get("status") or "unknown")
        counts[label] = counts.get(label, 0) + 1
        cat = str(rec.get("decision_category") or "unknown")
        by_category.setdefault(cat, {})[label] = by_category.setdefault(cat, {}).get(label, 0) + 1
    return {
        "sample_size": total,
        "outcome_counts": counts,
        "by_decision_category": by_category,
    }


def build_decision_outcome_summary(records: Sequence[Dict[str, Any]], *, ticker: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    selected = [r for r in records if str(r.get("status")) == "resolved"]
    if ticker:
        t = _normalize_ticker(ticker)
        selected = [r for r in selected if _normalize_ticker(r.get("ticker")) == t]
    selected = selected[-max(1, int(limit)):]
    metrics = _performance_metrics(selected)
    missed = [r for r in selected if (r.get("outcome") or {}).get("outcome_label") == "missed_opportunity"][-10:]
    false_positive = [r for r in selected if (r.get("outcome") or {}).get("outcome_label") == "false_positive_plan"][-10:]
    correct_avoid = [r for r in selected if (r.get("outcome") or {}).get("outcome_label") == "correct_avoid"][-10:]
    return {
        "enabled": True,
        "ticker": _normalize_ticker(ticker) if ticker else None,
        "count": len(selected),
        "overall": metrics,
        "missed_opportunities": [_compact_outcome(r) for r in missed],
        "false_positive_plans": [_compact_outcome(r) for r in false_positive],
        "correct_avoids": [_compact_outcome(r) for r in correct_avoid],
        "learning_policy": "Decision outcomes are soft observations only; never change thresholds, sizing or risk rules without replay/backtest/walk-forward validation.",
    }


def _compact_outcome(record: Dict[str, Any]) -> Dict[str, Any]:
    outcome = record.get("outcome") or {}
    return {
        "ticker": record.get("ticker"),
        "created_at": record.get("created_at"),
        "horizon_hours": record.get("horizon_hours"),
        "decision_category": record.get("decision_category"),
        "decision": record.get("decision"),
        "plan_action": (record.get("trade_plan") or {}).get("plan_action"),
        "outcome_label": outcome.get("outcome_label"),
        "price_change_pct": outcome.get("price_change_pct"),
        "max_favorable_pct": (outcome.get("path_metrics") or {}).get("max_favorable_pct"),
        "max_adverse_pct": (outcome.get("path_metrics") or {}).get("max_adverse_pct"),
        "exit_efficiency_proxy": (outcome.get("path_metrics") or {}).get("exit_efficiency_proxy"),
        "growbot_river_learning_context": record.get("growbot_river_learning_context"),
    }


class DecisionOutcomeStore:
    def __init__(
        self,
        path: Path | str = STATE_DIR / "decision_outcomes.json",
        log_path: Path | str = LOGS_DIR / "decision_outcomes.jsonl",
        *,
        max_records: int = 2000,
        enabled: bool = True,
        min_move_pct: Any = Decimal("0.025"),
        adverse_move_pct: Any = Decimal("0.020"),
    ):
        self.path = Path(path)
        self.log_path = Path(log_path)
        self.max_records = max(1, int(max_records))
        self.enabled = bool(enabled)
        self.min_move_pct = float(_to_decimal(min_move_pct) or Decimal("0.025"))
        self.adverse_move_pct = float(_to_decimal(adverse_move_pct) or Decimal("0.020"))
        self.path.parent.mkdir(exist_ok=True)
        self.log_path.parent.mkdir(exist_ok=True)

    def _read_all(self) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return []
        if isinstance(payload, list):
            return [r for r in payload if isinstance(r, dict)]
        if isinstance(payload, dict):
            rows = payload.get("records") or payload.get("decision_outcomes") or []
            return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []
        return []

    def _write_all(self, records: List[Dict[str, Any]]) -> None:
        safe_records = [_json_safe(r) for r in records[-self.max_records:]]
        payload = {
            "updated_at": _now_iso(),
            "records": safe_records,
            "learning_policy": "Read-only decision outcome tracking. No live thresholds, sizing or risk rules are changed by this file.",
        }
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_log(self, event: str, payload: Dict[str, Any]) -> None:
        row = {"generated_at": _now_iso(), "event": event, **payload}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(_json_safe(row), ensure_ascii=False) + "\n")

    def list_records(self, *, status: Optional[str] = None, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        records = self._read_all()
        if status is not None:
            records = [r for r in records if str(r.get("status")) == status]
        if ticker:
            t = _normalize_ticker(ticker)
            records = [r for r in records if _normalize_ticker(r.get("ticker")) == t]
        return records

    def append_snapshots(self, records: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        incoming = [deepcopy(r) for r in records if isinstance(r, dict) and r.get("record_id")]
        if not incoming:
            return []
        existing = self._read_all()
        seen = {str(r.get("record_id")) for r in existing}
        added: List[Dict[str, Any]] = []
        for rec in incoming:
            if str(rec.get("record_id")) in seen:
                continue
            existing.append(rec)
            seen.add(str(rec.get("record_id")))
            added.append(rec)
        if added:
            self._write_all(existing)
            self._append_log("decision_outcome_snapshots_stored", {"count": len(added), "records": [_compact_outcome(r) for r in added]})
        return added

    def record_analysis_decision(
        self,
        *,
        ticker: str,
        analysis: Dict[str, Any],
        cycle_result: Optional[Dict[str, Any]] = None,
        feature_pack: Optional[Dict[str, Any]] = None,
        horizons_hours: Sequence[int] = (4, 12, 24),
    ) -> List[Dict[str, Any]]:
        records = build_decision_snapshot_records(
            ticker=ticker,
            analysis=analysis,
            cycle_result=cycle_result or {},
            feature_pack=feature_pack or analysis.get("feature_pack") or {},
            horizons_hours=horizons_hours,
        )
        return self.append_snapshots(records)

    def evaluate_due(
        self,
        *,
        feature_packs: Dict[str, Dict[str, Any]],
        now: Any = None,
    ) -> List[Dict[str, Any]]:
        if not self.enabled:
            return []
        now_dt = _parse_dt(now) or _now_utc()
        records = self._read_all()
        changed = False
        resolved: List[Dict[str, Any]] = []

        for rec in records:
            if str(rec.get("status")) != "pending":
                continue
            due = _parse_dt(rec.get("due_at"))
            if due is None or due > now_dt:
                continue
            ticker = _normalize_ticker(rec.get("ticker"))
            fp = feature_packs.get(ticker) or feature_packs.get(str(rec.get("ticker")))
            if not fp:
                continue
            current_price = extract_current_price(fp)
            if current_price is None:
                continue
            candles = extract_candles(fp)
            trade_plan = rec.get("trade_plan") or {}
            path = compute_path_metrics(
                start_price=rec.get("current_price"),
                candles=candles,
                start_time=rec.get("created_at"),
                stop_loss=trade_plan.get("stop_loss"),
                take_profit_1=trade_plan.get("take_profit_1"),
                take_profit_2=trade_plan.get("take_profit_2"),
            )
            price_change = _pct_change(rec.get("current_price"), current_price)
            label = classify_decision_outcome(
                decision_category=str(rec.get("decision_category") or ""),
                price_change_pct=price_change,
                path_metrics=path,
                min_move_pct=self.min_move_pct,
                adverse_move_pct=self.adverse_move_pct,
            )
            rec["status"] = "resolved"
            rec["resolved_at"] = now_dt.isoformat()
            rec["outcome"] = {
                "outcome_label": label,
                "current_price_at_resolution": current_price,
                "price_change_pct": round(price_change, 6) if price_change is not None else None,
                "path_metrics": path,
                "min_move_pct": self.min_move_pct,
                "adverse_move_pct": self.adverse_move_pct,
                "learning_policy": "Outcome labels are observations only; require replay/backtest/walk-forward validation before changing live rules.",
            }
            changed = True
            resolved.append(deepcopy(rec))

        if changed:
            self._write_all(records)
            self._append_log("decision_outcomes_resolved", {"count": len(resolved), "records": [_compact_outcome(r) for r in resolved]})
        return resolved

    def summary(self, *, ticker: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
        records = self._read_all()
        return build_decision_outcome_summary(records, ticker=ticker, limit=limit)

    def write_report(self, path: Path | str, *, ticker: Optional[str] = None, limit: int = 200) -> Dict[str, Any]:
        summary = self.summary(ticker=ticker, limit=limit)
        out = Path(path)
        out.parent.mkdir(exist_ok=True)
        out.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
        return summary
