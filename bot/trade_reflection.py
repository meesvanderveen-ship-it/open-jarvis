from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from bot.decision_outcome_tracker import extract_candles
from bot.growbot_river_learning_contract import build_learning_context_snapshot


STATE_DIR = Path("state")
STATE_DIR.mkdir(exist_ok=True)
DEFAULT_REFLECTIONS_FILE = STATE_DIR / "trade_reflections.jsonl"
DEFAULT_LEARNING_REPORT_FILE = Path("logs") / "trade_learning_report.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json_safe(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    try:
        if value is None or value == "":
            return Decimal(default)
        d = Decimal(str(value))
        if d.is_nan() or d.is_infinite():
            return Decimal(default)
        return d
    except (InvalidOperation, ValueError, TypeError):
        return Decimal(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(_to_decimal(value, str(default)))
    except Exception:
        return default


def _safe_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _normalize_ticker(ticker: Any) -> str:
    return _safe_str(ticker, "UNKNOWN").upper()


def _classify_outcome(realized_pnl: Any, realized_pnl_pct: Any = None) -> str:
    pnl = _to_decimal(realized_pnl, "0")
    pnl_pct = _to_decimal(realized_pnl_pct, "0")
    if pnl > Decimal("0") or pnl_pct > Decimal("0"):
        return "win"
    if pnl < Decimal("0") or pnl_pct < Decimal("0"):
        return "loss"
    return "flat"


def _extract_best_pattern(chart_patterns: Dict[str, Any]) -> Dict[str, Any]:
    patterns = chart_patterns.get("patterns", []) if isinstance(chart_patterns, dict) else []
    if not isinstance(patterns, list) or not patterns:
        return {}
    best = None
    best_score = Decimal("-1")
    for pattern in patterns:
        if not isinstance(pattern, dict):
            continue
        score = _to_decimal(pattern.get("quality"), "0")
        if score > best_score:
            best = pattern
            best_score = score
    return dict(best or {})


def _bucket_value(value: Any, default: str = "unknown") -> str:
    text = _safe_str(value, default).lower().replace(" ", "_")
    return text if text else default


def _market_context_buckets(
    *,
    feature_pack: Dict[str, Any],
    chart_patterns: Dict[str, Any],
    best_pattern: Dict[str, Any],
) -> Dict[str, str]:
    """Create coarse context buckets for anti-overfitting summaries.

    Buckets deliberately stay coarse. The goal is to recognize repeated setup
    conditions without fitting to exact prices, dates or one-off ticker behavior.
    """
    market_structure = chart_patterns.get("market_structure", {}) if isinstance(chart_patterns, dict) else {}
    if not isinstance(market_structure, dict):
        market_structure = {}

    risk_context = feature_pack.get("risk_context", {}) if isinstance(feature_pack, dict) else {}
    decision_context = feature_pack.get("decision_context", {}) if isinstance(feature_pack, dict) else {}
    market = feature_pack.get("market", {}) if isinstance(feature_pack, dict) else {}
    indicators = feature_pack.get("indicators", {}) if isinstance(feature_pack, dict) else {}

    volume_confirmation = _bucket_value(market_structure.get("volume_confirmation"), "unknown")
    range_position = _bucket_value(market_structure.get("range_position"), "unknown")
    breakout_status = _bucket_value(market_structure.get("breakout_status"), "none")
    pattern_type = _bucket_value(best_pattern.get("type"), "none") if best_pattern else "none"
    pattern_family = _bucket_value(best_pattern.get("family"), pattern_type) if best_pattern else "none"

    regime = _bucket_value(
        decision_context.get("regime")
        or risk_context.get("regime")
        or market.get("regime")
        or indicators.get("regime"),
        "unknown",
    )
    btc_context = _bucket_value(
        risk_context.get("btc_regime")
        or risk_context.get("btc_trend")
        or decision_context.get("btc_regime")
        or decision_context.get("btc_trend"),
        "unknown",
    )
    breadth = _bucket_value(
        risk_context.get("breadth")
        or risk_context.get("market_breadth")
        or decision_context.get("breadth")
        or decision_context.get("market_breadth"),
        "unknown",
    )

    return {
        "setup_type": "unclear",
        "pattern_type": pattern_type,
        "pattern_family": pattern_family,
        "range_position": range_position,
        "breakout_status": breakout_status,
        "volume_confirmation": volume_confirmation,
        "market_regime": regime,
        "btc_context": btc_context,
        "breadth": breadth,
    }


def _bucket_key(buckets: Dict[str, Any], fields: Optional[List[str]] = None) -> str:
    fields = fields or [
        "setup_type",
        "pattern_family",
        "range_position",
        "volume_confirmation",
        "market_regime",
        "btc_context",
    ]
    parts = [f"{field}={_bucket_value(buckets.get(field), 'unknown')}" for field in fields]
    return "|".join(parts)


def _sample_strength(sample_size: int) -> str:
    if sample_size < 3:
        return "observation"
    if sample_size < 8:
        return "weak"
    if sample_size < 20:
        return "moderate"
    return "strong"


def _lesson_weight(sample_size: int, losses: int, wins: int) -> str:
    strength = _sample_strength(sample_size)
    if strength == "observation":
        return "observation"
    if losses >= max(2, wins * 2) and sample_size >= 3:
        return f"{strength}_avoid"
    if wins >= max(2, losses * 2) and sample_size >= 3:
        return f"{strength}_prefer"
    return f"{strength}_mixed"


def _overfit_warning(sample_size: int) -> str:
    if sample_size <= 0:
        return "No matching reflection sample; do not infer edge from memory."
    if sample_size < 3:
        return "Single/few similar trades only: treat as anecdote, not a rule."
    if sample_size < 8:
        return "Small sample: use as weak context only; require independent current evidence."
    return "Use as context only; do not change thresholds without replay/backtest or walk-forward validation."


def _recency_weight(index_from_newest: int, half_life: float = 6.0) -> float:
    try:
        idx = max(0, int(index_from_newest))
        return round(0.5 ** (idx / max(1.0, float(half_life))), 4)
    except Exception:
        return 1.0


def _safe_div(numerator: Any, denominator: Any, default: float = 0.0) -> float:
    num = _to_float(numerator, 0.0)
    den = _to_float(denominator, 0.0)
    if den == 0:
        return default
    try:
        return num / den
    except Exception:
        return default


def _planner_expected_quality(trade_plan: Dict[str, Any], judge: Dict[str, Any], best_pattern: Dict[str, Any]) -> Dict[str, Any]:
    """Estimate pre-trade conviction from snapshots only.

    This is not a prediction model. It helps future reflections distinguish
    between a good outcome that followed strong evidence and a lucky outcome
    after weak evidence, reducing the chance of reinforcing the wrong lesson.
    """
    plan_action = _safe_str(trade_plan.get("plan_action"), "no_plan").lower()
    judge_decision = _safe_str(judge.get("decision"), "unknown").lower()
    planner_conf = _to_float(trade_plan.get("confidence"), 0.0)
    judge_conf = _to_float(judge.get("confidence"), 0.0)
    pattern_quality = _to_float(best_pattern.get("quality") if best_pattern else 0.0, 0.0)
    risk_points = 0
    if plan_action in {"prepare_buy", "prepare_reclaim", "prepare_breakout", "prepare_mean_reversion", "manage_existing"}:
        risk_points += 1
    if judge_decision in {"approve_trade", "hold", "hold_ok", "wait"}:
        risk_points += 1
    if planner_conf >= 70:
        risk_points += 1
    if judge_conf >= 70:
        risk_points += 1
    if pattern_quality >= 70:
        risk_points += 1

    if risk_points >= 4:
        strength = "high"
    elif risk_points >= 2:
        strength = "medium"
    elif risk_points >= 1:
        strength = "low"
    else:
        strength = "unknown"

    return {
        "pre_trade_evidence_strength": strength,
        "planner_confidence": planner_conf,
        "judge_confidence": judge_conf,
        "pattern_quality": pattern_quality,
        "plan_action": plan_action,
        "judge_decision": judge_decision,
    }


def _surprise_assessment(metrics: Dict[str, Any], trade_plan: Dict[str, Any], judge: Dict[str, Any], best_pattern: Dict[str, Any]) -> Dict[str, Any]:
    """Flag whether an outcome supports or contradicts the original thesis.

    A high-confidence loss is more informative than a low-confidence loss. A
    low-quality setup that wins can be luck rather than a repeatable edge. This
    mirrors a conservative decision-log reflection loop and helps avoid
    overfitting to realized PnL alone.
    """
    evidence = _planner_expected_quality(trade_plan, judge, best_pattern)
    outcome = _safe_str(metrics.get("outcome"), "unknown")
    pnl_pct = _to_float(metrics.get("realized_pnl_pct"), 0.0)
    strength = evidence.get("pre_trade_evidence_strength", "unknown")

    label = "as_expected_or_uninformative"
    ratio = 0.0
    warning = "Outcome is weak evidence by itself; require repeated context and current confirmation."
    if outcome == "loss" and strength in {"high", "medium"}:
        label = "negative_surprise"
        ratio = min(5.0, abs(pnl_pct) * (2.0 if strength == "high" else 1.25) * 100.0)
        warning = "Loss contradicted medium/high pre-trade evidence; review thesis quality before repeating."
    elif outcome == "win" and strength in {"low", "unknown"}:
        label = "positive_surprise_possible_luck"
        ratio = min(5.0, abs(pnl_pct) * 100.0)
        warning = "Win followed weak/unknown evidence; do not reinforce this setup without repeated samples."
    elif outcome == "win" and strength in {"high", "medium"}:
        label = "positive_confirmation"
        ratio = min(5.0, abs(pnl_pct) * (1.5 if strength == "high" else 1.0) * 100.0)
        warning = "Potential confirming evidence, but still needs repeated samples and replay/backtest validation."
    elif outcome == "loss" and strength in {"low", "unknown"}:
        label = "weak_setup_loss"
        ratio = min(5.0, abs(pnl_pct) * 100.0)
        warning = "Loss followed weak evidence; avoid treating it as a broad rule without more samples."

    return {
        **evidence,
        "outcome": outcome,
        "surprise_label": label,
        "surprise_ratio": round(ratio, 4),
        "warning": warning,
    }


def _performance_metrics(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Compute compact, JSON-safe performance metrics from reflection records."""
    pnls = []
    pnl_pcts = []
    wins = losses = flats = unknown = 0
    gross_win = 0.0
    gross_loss = 0.0
    for record in records:
        metrics = record.get("metrics", {}) if isinstance(record.get("metrics"), dict) else {}
        outcome = _safe_str(metrics.get("outcome"), "unknown")
        pnl = _to_float(metrics.get("realized_pnl"), 0.0)
        pnl_pct = _to_float(metrics.get("realized_pnl_pct"), 0.0)
        pnls.append(pnl)
        pnl_pcts.append(pnl_pct)
        if outcome == "win":
            wins += 1
            gross_win += max(0.0, pnl)
        elif outcome == "loss":
            losses += 1
            gross_loss += abs(min(0.0, pnl))
        elif outcome == "flat":
            flats += 1
        else:
            unknown += 1
    total = len(records)
    return {
        "sample_size": total,
        "wins": wins,
        "losses": losses,
        "flat": flats,
        "unknown": unknown,
        "win_rate": round(_safe_div(wins, wins + losses, 0.0), 4) if (wins + losses) else None,
        "avg_realized_pnl": round(sum(pnls) / total, 8) if total else 0.0,
        "avg_realized_pnl_pct": round(sum(pnl_pcts) / total, 8) if total else 0.0,
        "net_realized_pnl": round(sum(pnls), 8),
        "gross_win": round(gross_win, 8),
        "gross_loss": round(gross_loss, 8),
        "profit_factor": round(_safe_div(gross_win, gross_loss, 0.0), 4) if gross_loss else (None if gross_win == 0 else "inf"),
        "sample_strength": _sample_strength(total),
        "overfit_warning": _overfit_warning(total),
    }


def _group_records(records: List[Dict[str, Any]], group_key: str) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for record in records:
        if group_key == "setup_type":
            key = _bucket_value(record.get("setup_type"), "unclear")
        else:
            buckets = record.get("context_buckets", {}) if isinstance(record.get("context_buckets"), dict) else {}
            key = _bucket_value(buckets.get(group_key), "unknown")
        grouped[key].append(record)
    return dict(grouped)


def build_reflection_analytics(
    records: List[Dict[str, Any]],
    *,
    min_samples_for_signal: int = 3,
    top_n: int = 8,
) -> Dict[str, Any]:
    """Build read-only learning analytics from closed-trade reflections.

    The output is deliberately conservative: it reports observations, sample
    sizes and warnings, but does not produce new thresholds, sizing rules or
    executable signals.
    """
    records = [r for r in records if isinstance(r, dict)]
    min_samples_for_signal = max(2, int(min_samples_for_signal or 3))
    if not records:
        return {
            "enabled": True,
            "count": 0,
            "overall": _performance_metrics([]),
            "groups": {},
            "candidate_avoid_contexts": [],
            "candidate_prefer_contexts": [],
            "surprise_flags": [],
            "learning_policy": "Read-only analytics. Do not change live thresholds, sizing or risk rules without replay/backtest/walk-forward validation.",
        }

    overall = _performance_metrics(records)
    group_names = ["setup_type", "pattern_family", "range_position", "volume_confirmation", "market_regime", "btc_context"]
    groups: Dict[str, Any] = {}
    candidate_avoid: List[Dict[str, Any]] = []
    candidate_prefer: List[Dict[str, Any]] = []

    for group_name in group_names:
        payload: Dict[str, Any] = {}
        for key, group_records in _group_records(records, group_name).items():
            metrics = _performance_metrics(group_records)
            metrics["group"] = key
            payload[key] = metrics
            if metrics["sample_size"] >= min_samples_for_signal:
                losses = int(metrics.get("losses") or 0)
                wins = int(metrics.get("wins") or 0)
                signal = {
                    "dimension": group_name,
                    "value": key,
                    "sample_size": metrics["sample_size"],
                    "wins": wins,
                    "losses": losses,
                    "win_rate": metrics.get("win_rate"),
                    "sample_strength": metrics.get("sample_strength"),
                    "overfit_warning": metrics.get("overfit_warning"),
                }
                if losses >= max(2, wins * 2):
                    candidate_avoid.append({**signal, "lesson_weight": _lesson_weight(metrics["sample_size"], losses, wins)})
                if wins >= max(2, losses * 2):
                    candidate_prefer.append({**signal, "lesson_weight": _lesson_weight(metrics["sample_size"], losses, wins)})
        groups[group_name] = payload

    surprise_flags: List[Dict[str, Any]] = []
    for record in records[: max(top_n * 2, top_n)]:
        evidence = record.get("learning_evidence", {}) if isinstance(record.get("learning_evidence"), dict) else {}
        label = _safe_str(evidence.get("surprise_label"), "")
        if label in {"negative_surprise", "positive_surprise_possible_luck"}:
            surprise_flags.append({
                "ticker": _normalize_ticker(record.get("ticker")),
                "generated_at": record.get("generated_at"),
                "setup_type": record.get("setup_type"),
                "surprise_label": label,
                "surprise_ratio": evidence.get("surprise_ratio"),
                "warning": evidence.get("warning"),
                "bucket_key": (record.get("context_buckets") or {}).get("bucket_key") if isinstance(record.get("context_buckets"), dict) else None,
            })
            if len(surprise_flags) >= top_n:
                break

    candidate_avoid.sort(key=lambda x: (x.get("sample_size", 0), x.get("losses", 0)), reverse=True)
    candidate_prefer.sort(key=lambda x: (x.get("sample_size", 0), x.get("wins", 0)), reverse=True)
    return {
        "enabled": True,
        "count": len(records),
        "overall": overall,
        "groups": groups,
        "candidate_avoid_contexts": candidate_avoid[:top_n],
        "candidate_prefer_contexts": candidate_prefer[:top_n],
        "surprise_flags": surprise_flags,
        "min_samples_for_signal": min_samples_for_signal,
        "learning_policy": "Read-only analytics. Use as context only; do not change live thresholds, sizing or risk rules without replay/backtest/walk-forward validation.",
    }


def build_deterministic_trade_metrics(
    *,
    position_before: Dict[str, Any],
    closed_position: Optional[Dict[str, Any]] = None,
    exit_price: Any = None,
    realized_pnl: Any = None,
) -> Dict[str, Any]:
    """Build deterministic, JSON-safe metrics for a closed trade.

    This function intentionally avoids any LLM interpretation. It is safe to use
    in live execution paths because it cannot place, approve or modify orders.
    """
    closed_position = closed_position or {}
    entry_price = _to_decimal(position_before.get("entry_price"), "0")
    resolved_exit_price = _to_decimal(
        exit_price if exit_price is not None else closed_position.get("close_price"),
        "0",
    )
    base_size = _to_decimal(
        position_before.get("bot_managed_base")
        or position_before.get("position_size_base")
        or closed_position.get("position_size_base"),
        "0",
    )
    pnl = _to_decimal(
        realized_pnl if realized_pnl is not None else closed_position.get("realized_pnl"),
        "0",
    )
    pnl_pct = Decimal("0")
    if entry_price > Decimal("0") and resolved_exit_price > Decimal("0"):
        pnl_pct = (resolved_exit_price - entry_price) / entry_price

    holding_seconds: Optional[float] = None
    opened_at = _safe_str(position_before.get("opened_at") or position_before.get("entry_time"))
    closed_at = _safe_str(closed_position.get("close_time") or closed_position.get("closed_at") or _now_iso())
    if opened_at and closed_at:
        try:
            start = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
            end = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
            holding_seconds = max(0.0, (end - start).total_seconds())
        except Exception:
            holding_seconds = None

    return {
        "entry_price": float(entry_price) if entry_price > Decimal("0") else None,
        "exit_price": float(resolved_exit_price) if resolved_exit_price > Decimal("0") else None,
        "base_size_before_close": float(base_size) if base_size > Decimal("0") else 0.0,
        "realized_pnl": float(pnl),
        "realized_pnl_pct": float(pnl_pct),
        "outcome": _classify_outcome(pnl, pnl_pct),
        "holding_seconds": holding_seconds,
        "holding_hours": (holding_seconds / 3600.0) if holding_seconds is not None else None,
    }


def build_trade_reflection_input(
    *,
    ticker: str,
    position_before: Dict[str, Any],
    closed_position: Optional[Dict[str, Any]] = None,
    action: Optional[Dict[str, Any]] = None,
    feature_pack: Optional[Dict[str, Any]] = None,
    chart_patterns: Optional[Dict[str, Any]] = None,
    trade_plan: Optional[Dict[str, Any]] = None,
    judge: Optional[Dict[str, Any]] = None,
    execution_record: Optional[Dict[str, Any]] = None,
    realized_pnl: Any = None,
    exit_price: Any = None,
    source: str = "strategy_engine",
) -> Dict[str, Any]:
    """Create a compact post-trade reflection record.

    The record is deterministic and intentionally conservative. It is meant to
    give future planner/judge calls short memory of what worked or failed, not to
    create automatic trade permissions or blocks.
    """
    ticker = _normalize_ticker(ticker)
    position_before = position_before or {}
    closed_position = closed_position or {}
    action = action or {}
    feature_pack = feature_pack or {}
    chart_patterns = chart_patterns or {}
    trade_plan = trade_plan or {}
    judge = judge or {}
    execution_record = execution_record or {}

    metrics = build_deterministic_trade_metrics(
        position_before=position_before,
        closed_position=closed_position,
        exit_price=exit_price,
        realized_pnl=realized_pnl,
    )
    best_pattern = _extract_best_pattern(chart_patterns)
    setup_type = _safe_str(
        judge.get("setup_type")
        or trade_plan.get("setup_type")
        or position_before.get("setup_type")
        or action.get("setup_type"),
        "unclear",
    ).lower()
    close_reason = _safe_str(
        action.get("reason")
        or closed_position.get("close_reason")
        or execution_record.get("status"),
        "unknown_close_reason",
    )
    decision_context = feature_pack.get("decision_context", {}) if isinstance(feature_pack, dict) else {}
    risk_context = feature_pack.get("risk_context", {}) if isinstance(feature_pack, dict) else {}

    avoid_conditions: List[str] = []
    prefer_conditions: List[str] = []
    lesson_tags: List[str] = []

    outcome = metrics["outcome"]
    if outcome == "loss":
        lesson_tags.append("loss_review_required")
        if close_reason:
            avoid_conditions.append(f"avoid_similar_close_reason:{close_reason}")
        if setup_type:
            avoid_conditions.append(f"review_setup_type:{setup_type}")
    elif outcome == "win":
        lesson_tags.append("winner_context")
        if setup_type:
            prefer_conditions.append(f"prefer_when_setup_type_confirmed:{setup_type}")
    else:
        lesson_tags.append("flat_or_dust_close")

    if best_pattern:
        pattern_type = _safe_str(best_pattern.get("type"), "unknown_pattern")
        pattern_quality = _to_float(best_pattern.get("quality"), 0.0)
        lesson_tags.append(f"pattern:{pattern_type}")
        if outcome == "loss" and pattern_quality < 65:
            avoid_conditions.append(f"weak_pattern_quality:{pattern_type}:{pattern_quality:.0f}")
        if outcome == "win" and pattern_quality >= 65:
            prefer_conditions.append(f"confirmed_pattern:{pattern_type}:{pattern_quality:.0f}")

    market = feature_pack.get("market", {}) if isinstance(feature_pack, dict) else {}
    current_price = market.get("mid_price") or market.get("price")
    context_buckets = _market_context_buckets(
        feature_pack=feature_pack,
        chart_patterns=chart_patterns,
        best_pattern=best_pattern,
    )
    context_buckets["setup_type"] = setup_type
    context_buckets["bucket_key"] = _bucket_key(context_buckets)
    learning_evidence = _surprise_assessment(metrics, trade_plan, judge, best_pattern)
    learning_context = build_learning_context_snapshot(
        feature_pack,
        {
            "ticker": ticker,
            "judge": judge,
            "trade_plan": trade_plan,
            "decision_context": decision_context,
            "market_regime": context_buckets.get("market_regime"),
            "setup_type": setup_type,
            "fill_status": "filled",
            "exit_result": metrics.get("outcome"),
        },
        candles=extract_candles(feature_pack),
    )

    return _json_safe({
        "reflection_id": f"{ticker}-{_now_iso()}",
        "generated_at": _now_iso(),
        "source": source,
        "ticker": ticker,
        "setup_type": setup_type,
        "close_reason": close_reason,
        "metrics": metrics,
        "entry": {
            "entry_price": position_before.get("entry_price"),
            "entry_time": position_before.get("opened_at") or position_before.get("entry_time"),
            "entry_strategy": position_before.get("strategy") or position_before.get("entry_strategy"),
            "initial_size_quote": position_before.get("initial_size_quote") or position_before.get("position_size_quote"),
        },
        "exit": {
            "close_price": closed_position.get("close_price") or exit_price,
            "close_time": closed_position.get("close_time") or closed_position.get("closed_at"),
            "action_type": action.get("action"),
            "execution_status": execution_record.get("status"),
        },
        "planner_snapshot": {
            "plan_action": trade_plan.get("plan_action"),
            "trigger": trade_plan.get("trigger"),
            "invalidation": trade_plan.get("invalidation"),
            "confidence": trade_plan.get("confidence"),
            "pattern_alignment": trade_plan.get("pattern_alignment"),
        },
        "judge_snapshot": {
            "decision": judge.get("decision"),
            "confidence": judge.get("confidence"),
            "strategy": judge.get("strategy"),
            "reasons": _as_list(judge.get("reasons"))[:8],
        },
        "pattern_snapshot": {
            "best_pattern": best_pattern,
            "pattern_bias": chart_patterns.get("pattern_bias"),
            "best_pattern_score": chart_patterns.get("best_pattern_score"),
            "market_structure": chart_patterns.get("market_structure", {}),
        },
        "market_snapshot": {
            "current_price_at_close": current_price,
            "risk_context": risk_context,
            "decision_context": decision_context,
        },
        "context_buckets": context_buckets,
        "growbot_river_learning_context": learning_context,
        "learning_evidence": learning_evidence,
        "lesson": {
            "summary": _build_lesson_summary(
                ticker=ticker,
                outcome=outcome,
                setup_type=setup_type,
                close_reason=close_reason,
                best_pattern=best_pattern,
                realized_pnl=metrics.get("realized_pnl"),
                realized_pnl_pct=metrics.get("realized_pnl_pct"),
            ),
            "tags": lesson_tags,
            "avoid_conditions": avoid_conditions[:10],
            "prefer_conditions": prefer_conditions[:10],
            "quality_score": _quality_score(metrics, judge, trade_plan, best_pattern),
            "anti_overfit_note": "Stored as historical context only; no automatic parameter or threshold changes.",
        },
    })


def _build_lesson_summary(
    *,
    ticker: str,
    outcome: str,
    setup_type: str,
    close_reason: str,
    best_pattern: Dict[str, Any],
    realized_pnl: Any,
    realized_pnl_pct: Any,
) -> str:
    pattern_text = "no strong pattern"
    if best_pattern:
        pattern_text = f"pattern={_safe_str(best_pattern.get('type'), 'unknown')} quality={_safe_str(best_pattern.get('quality'), '0')}"
    return (
        f"{ticker} closed as {outcome}; setup={setup_type}; {pattern_text}; "
        f"close_reason={close_reason}; pnl={realized_pnl}; pnl_pct={realized_pnl_pct}."
    )


def _quality_score(
    metrics: Dict[str, Any],
    judge: Dict[str, Any],
    trade_plan: Dict[str, Any],
    best_pattern: Dict[str, Any],
) -> int:
    score = 50
    outcome = metrics.get("outcome")
    if outcome == "win":
        score += 20
    elif outcome == "loss":
        score -= 20

    judge_conf = _to_float(judge.get("confidence"), 0.0)
    planner_conf = _to_float(trade_plan.get("confidence"), 0.0)
    pattern_quality = _to_float(best_pattern.get("quality") if best_pattern else 0.0, 0.0)

    if judge_conf >= 70:
        score += 5
    if planner_conf >= 70:
        score += 5
    if pattern_quality >= 70:
        score += 5
    if outcome == "loss" and judge_conf >= 70:
        score -= 10
    if outcome == "loss" and planner_conf >= 70:
        score -= 10
    return max(0, min(100, int(score)))


class TradeReflectionStore:
    def __init__(self, path: Optional[Path] = None, max_records: int = 500):
        self.path = path or DEFAULT_REFLECTIONS_FILE
        self.max_records = max(1, int(max_records))
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, reflection: Dict[str, Any]) -> Dict[str, Any]:
        safe_reflection = _json_safe(reflection)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(safe_reflection, ensure_ascii=False) + "\n")
        self._compact_if_needed()
        return safe_reflection

    def load_recent(self, *, ticker: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        if not self.path.exists():
            return []
        ticker_norm = _normalize_ticker(ticker) if ticker else None
        records: List[Dict[str, Any]] = []
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if ticker_norm and _normalize_ticker(item.get("ticker")) != ticker_norm:
                continue
            records.append(item)
            if len(records) >= limit:
                break
        return records

    def summarize_recent_reflections(
        self,
        *,
        ticker: Optional[str] = None,
        limit: int = 12,
        min_samples_for_signal: int = 3,
    ) -> Dict[str, Any]:
        records = self.load_recent(ticker=ticker, limit=limit)
        if not records:
            return {
                "enabled": True,
                "count": 0,
                "ticker": _normalize_ticker(ticker) if ticker else None,
                "summary": "No recent closed-trade reflections available.",
                "outcome_counts": {},
                "setup_outcomes": {},
                "context_bucket_outcomes": {},
                "weighted_context_signals": [],
                "avoid_conditions": [],
                "prefer_conditions": [],
                "recent_lessons": [],
                "sample_strength": "none",
                "overfit_warning": "No matching reflection sample; do not infer edge from memory.",
                "memory_policy": "Reflection memory is soft context only; no automatic threshold, sizing or risk-rule changes.",
                "learning_analytics": build_reflection_analytics([], min_samples_for_signal=max(2, int(min_samples_for_signal or 3)), top_n=4),
            }

        min_samples_for_signal = max(2, int(min_samples_for_signal or 3))
        outcome_counts: Counter[str] = Counter()
        setup_counts: Dict[str, Counter[str]] = defaultdict(Counter)
        bucket_counts: Dict[str, Counter[str]] = defaultdict(Counter)
        bucket_examples: Dict[str, Dict[str, Any]] = {}
        avoid_counter: Counter[str] = Counter()
        prefer_counter: Counter[str] = Counter()
        recent_lessons: List[str] = []

        for idx, record in enumerate(records):
            recency = _recency_weight(idx)
            metrics = record.get("metrics", {}) if isinstance(record.get("metrics"), dict) else {}
            lesson = record.get("lesson", {}) if isinstance(record.get("lesson"), dict) else {}
            setup_type = _safe_str(record.get("setup_type"), "unclear")
            outcome = _safe_str(metrics.get("outcome"), "unknown")
            outcome_counts[outcome] += 1
            setup_counts[setup_type][outcome] += 1

            context_buckets = record.get("context_buckets", {}) if isinstance(record.get("context_buckets"), dict) else {}
            if not context_buckets:
                context_buckets = {"setup_type": setup_type, "bucket_key": f"setup_type={setup_type}"}
            bucket_key = _safe_str(context_buckets.get("bucket_key"), _bucket_key(context_buckets))
            bucket_counts[bucket_key][outcome] += 1
            bucket_counts[bucket_key]["weighted_total_x10000"] += int(recency * 10000)
            bucket_examples.setdefault(bucket_key, context_buckets)

            for condition in _as_list(lesson.get("avoid_conditions")):
                avoid_counter[condition] += 1
            for condition in _as_list(lesson.get("prefer_conditions")):
                prefer_counter[condition] += 1
            summary = _safe_str(lesson.get("summary"))
            if summary:
                recent_lessons.append(summary)

        setup_outcomes = {setup: dict(counter) for setup, counter in sorted(setup_counts.items())}
        context_bucket_outcomes: Dict[str, Dict[str, Any]] = {}
        weighted_context_signals: List[Dict[str, Any]] = []
        for bucket_key, counter in bucket_counts.items():
            wins = int(counter.get("win", 0))
            losses = int(counter.get("loss", 0))
            flats = int(counter.get("flat", 0))
            unknown = int(counter.get("unknown", 0))
            sample_size = wins + losses + flats + unknown
            if sample_size <= 0:
                continue
            strength = _sample_strength(sample_size)
            lesson_weight = _lesson_weight(sample_size, losses, wins)
            warning = _overfit_warning(sample_size)
            bucket_payload = {
                "sample_size": sample_size,
                "wins": wins,
                "losses": losses,
                "flat": flats,
                "unknown": unknown,
                "recency_weight_total": round(float(counter.get("weighted_total_x10000", 0)) / 10000.0, 4),
                "sample_strength": strength,
                "lesson_weight": lesson_weight,
                "overfit_warning": warning,
                "buckets": bucket_examples.get(bucket_key, {}),
            }
            context_bucket_outcomes[bucket_key] = bucket_payload
            if sample_size >= min_samples_for_signal:
                weighted_context_signals.append({"bucket_key": bucket_key, **bucket_payload})

        weighted_context_signals.sort(
            key=lambda item: (
                item.get("sample_size", 0),
                max(item.get("wins", 0), item.get("losses", 0)),
                item.get("recency_weight_total", 0),
            ),
            reverse=True,
        )
        avoid_conditions = [item for item, count in avoid_counter.most_common(8) if count >= 1]
        prefer_conditions = [item for item, count in prefer_counter.most_common(8) if count >= 1]
        sample_strength = _sample_strength(len(records))
        learning_analytics = build_reflection_analytics(records, min_samples_for_signal=min_samples_for_signal, top_n=4)
        compact_learning_analytics = {
            "overall": learning_analytics.get("overall", {}),
            "candidate_avoid_contexts": learning_analytics.get("candidate_avoid_contexts", [])[:4],
            "candidate_prefer_contexts": learning_analytics.get("candidate_prefer_contexts", [])[:4],
            "surprise_flags": learning_analytics.get("surprise_flags", [])[:4],
            "learning_policy": learning_analytics.get("learning_policy"),
        }
        return {
            "enabled": True,
            "count": len(records),
            "ticker": _normalize_ticker(ticker) if ticker else None,
            "summary": _build_summary_sentence(records, outcome_counts, avoid_conditions, prefer_conditions),
            "outcome_counts": dict(outcome_counts),
            "setup_outcomes": setup_outcomes,
            "context_bucket_outcomes": context_bucket_outcomes,
            "weighted_context_signals": weighted_context_signals[:6],
            "avoid_conditions": avoid_conditions,
            "prefer_conditions": prefer_conditions,
            "recent_lessons": recent_lessons[:6],
            "sample_strength": sample_strength,
            "min_samples_for_signal": min_samples_for_signal,
            "overfit_warning": _overfit_warning(len(records)),
            "memory_policy": "Reflection memory is soft context only; no automatic threshold, sizing or risk-rule changes.",
            "learning_analytics": compact_learning_analytics,
        }

    def load_all(self, *, ticker: Optional[str] = None, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Load reflection records newest first, safely ignoring corrupt lines."""
        if not self.path.exists():
            return []
        ticker_norm = _normalize_ticker(ticker) if ticker else None
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        records: List[Dict[str, Any]] = []
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if not isinstance(item, dict):
                continue
            if ticker_norm and _normalize_ticker(item.get("ticker")) != ticker_norm:
                continue
            records.append(item)
            if limit is not None and len(records) >= int(limit):
                break
        return records

    def analytics_summary(
        self,
        *,
        ticker: Optional[str] = None,
        limit: int = 200,
        min_samples_for_signal: int = 3,
    ) -> Dict[str, Any]:
        records = self.load_all(ticker=ticker, limit=max(1, int(limit or 200)))
        summary = build_reflection_analytics(records, min_samples_for_signal=min_samples_for_signal)
        summary["ticker"] = _normalize_ticker(ticker) if ticker else None
        summary["limit"] = limit
        summary["source_path"] = str(self.path)
        return summary

    def write_learning_report(
        self,
        *,
        output_path: Optional[Path] = None,
        ticker: Optional[str] = None,
        limit: int = 500,
        min_samples_for_signal: int = 3,
    ) -> Dict[str, Any]:
        output_path = output_path or DEFAULT_LEARNING_REPORT_FILE
        output_path.parent.mkdir(parents=True, exist_ok=True)
        report = self.analytics_summary(
            ticker=ticker,
            limit=limit,
            min_samples_for_signal=min_samples_for_signal,
        )
        report["generated_at"] = _now_iso()
        report["report_type"] = "trade_reflection_learning_report"
        report["safety_policy"] = "Offline/read-only learning report; never authorizes execution or parameter changes."
        tmp = output_path.with_suffix(output_path.suffix + ".tmp")
        tmp.write_text(json.dumps(_json_safe(report), ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, output_path)
        return report

    def _compact_if_needed(self) -> None:
        if not self.path.exists():
            return
        try:
            lines = [line for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]
        except Exception:
            return
        if len(lines) <= self.max_records:
            return
        keep = lines[-self.max_records:]
        tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp_path.write_text("\n".join(keep) + "\n", encoding="utf-8")
        os.replace(tmp_path, self.path)


def _build_summary_sentence(
    records: List[Dict[str, Any]],
    outcome_counts: Counter[str],
    avoid_conditions: List[str],
    prefer_conditions: List[str],
) -> str:
    total = len(records)
    wins = outcome_counts.get("win", 0)
    losses = outcome_counts.get("loss", 0)
    flats = outcome_counts.get("flat", 0)
    avoid = f" Avoid: {', '.join(avoid_conditions[:3])}." if avoid_conditions else ""
    prefer = f" Prefer: {', '.join(prefer_conditions[:3])}." if prefer_conditions else ""
    return f"Recent reflections: {total} closed trades; wins={wins}, losses={losses}, flat={flats}.{avoid}{prefer}"
