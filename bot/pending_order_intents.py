from __future__ import annotations

import json
import re
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

ACTIVE_STATUSES = {"active", "waiting", "trigger_ready", "needs_fresh_analysis", "stale"}
FINAL_STATUSES = {"expired", "invalidated", "cancelled", "promoted", "replaced", "failed"}
PROMOTION_READY_STATUSES = {"trigger_ready", "needs_fresh_analysis"}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_utc().isoformat()


def _parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        raw = str(value).strip()
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _to_decimal(value: Any, default: Optional[str] = None) -> Optional[Decimal]:
    if value is None or value == "":
        if default is None:
            return None
        value = default
    try:
        dec = value if isinstance(value, Decimal) else Decimal(str(value))
        if dec.is_nan() or dec.is_infinite():
            return None
        return dec
    except (InvalidOperation, ValueError, TypeError):
        if default is None:
            return None
        try:
            return Decimal(str(default))
        except Exception:
            return None


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


def _normalize_ticker(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-")


def _as_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, (dict, bytes, bytearray)):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value).strip()
    return [text] if text else []


def _first_decimal(*values: Any) -> Optional[Decimal]:
    for value in values:
        dec = _to_decimal(value)
        if dec is not None and dec > 0:
            return dec
    return None

def _collect_text_fragments(obj: Any, *, max_items: int = 80) -> List[str]:
    """Collect short human-readable fragments from nested LLM/gate structures.

    Used only for paper watchlist-intent extraction. It never authorizes an
    order; it helps preserve levels that are present in free-text gate reasons
    such as "support 1.1848" or "acceptance above 9.82".
    """
    out: List[str] = []

    def walk(value: Any) -> None:
        if len(out) >= max_items:
            return
        if value is None:
            return
        if isinstance(value, str):
            s = value.strip()
            if s:
                out.append(s[:600])
            return
        if isinstance(value, dict):
            # Prefer semantically useful keys and avoid large raw payloads.
            preferred = (
                "reason", "reasons", "warning", "warnings", "trigger",
                "invalidation", "cancel_if", "replace_if", "summary",
                "key_trigger", "thesis", "why_now", "setup", "comment",
                "entry_gate", "judge", "analysis",
            )
            for key, child in value.items():
                key_l = str(key).lower()
                if any(fragment in key_l for fragment in preferred):
                    walk(child)
            return
        if isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray, dict)):
            for item in value:
                walk(item)
                if len(out) >= max_items:
                    break

    walk(obj)
    return out


def _parse_decimal_token(raw: str) -> Optional[Decimal]:
    token = str(raw or "").strip().replace(",", "")
    # Drop punctuation around regex fragments.
    token = token.strip("()[]{}~≈:$;,. ")
    return _to_decimal(token)


def _nearest_keyword_distance(text_l: str, token_start: int, token_end: int, keywords: Tuple[str, ...]) -> Optional[int]:
    """Return the nearest distance from a token to any keyword occurrence.

    This avoids tagging every number in a sentence as resistance merely because
    the word "resistance" appears somewhere else in the same sentence.
    """
    best: Optional[int] = None
    for keyword in keywords:
        start = 0
        while True:
            idx = text_l.find(keyword, start)
            if idx < 0:
                break
            kw_mid = idx + max(1, len(keyword)) // 2
            token_mid = token_start + max(1, token_end - token_start) // 2
            dist = abs(token_mid - kw_mid)
            if best is None or dist < best:
                best = dist
            start = idx + 1
    return best


def _looks_like_indicator_or_microstructure_value(text_l: str, token_start: int, token_end: int) -> Optional[str]:
    """Reject RSI/ADX/volume/spread/orderbook sizes as price levels.

    The paper pending-intent layer may read free text. Without this filter it can
    accidentally store values such as RSI 72.2 or ADX 33.3 as resistance levels.
    """
    local = text_l[max(0, token_start - 42): min(len(text_l), token_end + 42)]
    left = text_l[max(0, token_start - 28): token_start]
    right = text_l[token_end: min(len(text_l), token_end + 28)]
    indicator_words = (
        "rsi", "adx", "ema", "sma", "macd", "volume", "vol ", "volume_vs",
        "spread", "bps", "%", "imbalance", "depth", "liquidity",
        "top bid", "top ask", "bid size", "ask size", "best-bid", "best-ask",
        "book pressure", "orderbook", "order book", "fear", "confidence",
    )
    for word in indicator_words:
        if word in local:
            # Allow price terms to rescue the token only when they are closer
            # than the indicator term. This preserves phrases like
            # "resistance 10.658" while rejecting "RSI 81" in the same text.
            price_words = ("support", "resistance", "range low", "range high", "donchian", "bb upper", "bb lower", "high ~", "low ~")
            price_dist = _nearest_keyword_distance(text_l, token_start, token_end, price_words)
            indicator_dist = _nearest_keyword_distance(text_l, token_start, token_end, (word,))
            if price_dist is None or (indicator_dist is not None and indicator_dist <= price_dist):
                return f"indicator_or_microstructure_value:{word.strip()}"
    # The numeric-token regex already avoids tokens directly attached to h/m
    # (for example 1h or 15m). Do not reject a real price merely because a
    # timeframe appears elsewhere in the same local phrase.
    return None


def _price_level_anchor(current_price: Optional[Decimal], support: Optional[Decimal], resistance: Optional[Decimal]) -> Optional[Decimal]:
    for candidate in (current_price, resistance, support):
        if candidate is not None and candidate > 0:
            return candidate
    return None


def _price_level_reject_reason(
    dec: Decimal,
    *,
    current_price: Optional[Decimal] = None,
    structured_support: Optional[Decimal] = None,
    structured_resistance: Optional[Decimal] = None,
) -> Optional[str]:
    anchor = _price_level_anchor(current_price, structured_support, structured_resistance)
    if anchor is None or anchor <= 0:
        return None
    low = anchor * Decimal("0.50")
    high = anchor * Decimal("1.50")
    if dec < low or dec > high:
        return f"outside_plausible_price_range:{dec} not in [{low}, {high}]"
    return None


def _dedupe_extracted_levels(levels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out: List[Dict[str, Any]] = []
    for item in levels:
        try:
            dec = _to_decimal(item.get("value"))
            value_key = str(dec.normalize()) if dec is not None else str(item.get("value"))
        except Exception:
            value_key = str(item.get("value"))
        key = (str(item.get("kind") or ""), value_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _extract_levels_from_texts(
    texts: Iterable[str],
    *,
    current_price: Optional[Decimal] = None,
    structured_support: Optional[Decimal] = None,
    structured_resistance: Optional[Decimal] = None,
) -> Tuple[Optional[Decimal], Optional[Decimal], List[Dict[str, Any]]]:
    """Extract support/resistance-like price levels from free-text reasons.

    B.6.3 hardens this extraction so indicator/microstructure values such as
    RSI, ADX, spread percentages, order-book sizes and confidence scores do not
    become fake support/resistance levels. This remains paper-only monitoring
    context and never authorizes execution.
    """
    support_keywords = (
        "support", "range low", "donchian low", "bb lower", "lower bound",
        "low/support", "near support", "pullback", "retest", "stabilisatie",
        "range_low", "swing low",
    )
    resistance_keywords = (
        "resistance", "range high", "donchian high", "bb upper",
        "breakout", "reclaim", "acceptance above", "close above",
        "hold above", "swing high", "range_high", "trigger area",
    )
    current_keywords = ("current", "current price", "mid-range", "sitting", "near")
    found: List[Dict[str, Any]] = []
    support: Optional[Decimal] = None
    resistance: Optional[Decimal] = None

    token_re = re.compile(r"(?<![A-Za-z0-9])(?:\d{1,6}(?:,\d{3})*|\d+)(?:\.\d+)?(?![A-Za-z0-9])")
    for text in texts:
        if not text:
            continue
        text_s = str(text)
        text_l = text_s.lower()
        for match in token_re.finditer(text_s):
            dec = _parse_decimal_token(match.group(0))
            if dec is None or dec <= 0:
                continue
            indicator_reason = _looks_like_indicator_or_microstructure_value(text_l, match.start(), match.end())
            if indicator_reason:
                continue
            range_reason = _price_level_reject_reason(
                dec,
                current_price=current_price,
                structured_support=structured_support,
                structured_resistance=structured_resistance,
            )
            if range_reason:
                continue

            support_dist = _nearest_keyword_distance(text_l, match.start(), match.end(), support_keywords)
            resistance_dist = _nearest_keyword_distance(text_l, match.start(), match.end(), resistance_keywords)
            current_dist = _nearest_keyword_distance(text_l, match.start(), match.end(), current_keywords)
            max_keyword_distance = 72

            kind: Optional[str] = None
            if support_dist is not None and support_dist <= max_keyword_distance:
                kind = "support"
            if resistance_dist is not None and resistance_dist <= max_keyword_distance:
                if kind is None or resistance_dist < (support_dist or 9999):
                    kind = "resistance"
            if kind is None and current_dist is not None and current_dist <= 36:
                kind = "context"
            if kind is None:
                continue

            item = {"kind": kind, "value": str(dec), "text": text_s[:240]}
            found.append(item)
            if kind == "support" and (support is None or dec < support):
                support = dec
            elif kind == "resistance" and (resistance is None or dec > resistance):
                resistance = dec

    found = _dedupe_extracted_levels(found)[:20]
    return support, resistance, found


def _watchlist_candidate_diagnostics(
    *,
    cfg: Any,
    ticker: str,
    analysis: Dict[str, Any],
    feature_pack: Dict[str, Any],
) -> Dict[str, Any]:
    analysis = analysis if isinstance(analysis, dict) else {}
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    entry_gate = analysis.get("entry_gate") if isinstance(analysis.get("entry_gate"), dict) else {}
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    decision = str(entry_gate.get("decision") or "").strip().lower()
    judge_decision = str(judge.get("decision") or "wait").strip().lower()
    confidence = _confidence_from(entry_gate, judge, default=0)
    min_confidence = int(getattr(cfg, "paper_pending_intent_min_gate_confidence", 50))
    current_price = extract_current_price(feature_pack)
    support, resistance = _extract_support_resistance(feature_pack)
    text_fragments = _collect_text_fragments({"entry_gate": entry_gate, "judge": judge, "analysis": analysis})
    text_support, text_resistance, extracted = _extract_levels_from_texts(
        text_fragments,
        current_price=current_price,
        structured_support=support,
        structured_resistance=resistance,
    )
    effective_support = support or text_support
    effective_resistance = _choose_watch_resistance(
        structured_resistance=resistance,
        text_resistance=text_resistance,
        current_price=current_price,
    )

    reason = "eligible"
    if not bool(getattr(cfg, "enable_paper_watchlist_intents_from_gate_watch", True)):
        reason = "paper_watchlist_intents_disabled"
    elif not _normalize_ticker(ticker):
        reason = "ticker_missing"
    elif decision not in {"watch", "analyze", "priority_analyze"}:
        reason = f"entry_gate_decision_not_watch_or_analyze:{decision or 'missing'}"
    elif judge_decision not in {"wait", "reject", "no_trade"}:
        reason = f"judge_decision_not_wait_like:{judge_decision}"
    elif confidence < min_confidence:
        reason = f"below_min_gate_confidence:{confidence}<{min_confidence}"
    elif current_price is None and effective_support is None and effective_resistance is None:
        reason = "no_structured_or_text_levels_available"

    return {
        "ticker": _normalize_ticker(ticker),
        "enabled": bool(getattr(cfg, "enable_paper_watchlist_intents_from_gate_watch", True)),
        "entry_gate_decision": decision,
        "judge_decision": judge_decision,
        "confidence": confidence,
        "min_confidence": min_confidence,
        "current_price": _decimal_str(current_price),
        "feature_support": _decimal_str(support),
        "feature_resistance": _decimal_str(resistance),
        "text_support": _decimal_str(text_support),
        "text_resistance": _decimal_str(text_resistance),
        "effective_support": _decimal_str(effective_support),
        "effective_resistance": _decimal_str(effective_resistance),
        "extracted_text_levels": extracted,
        "reason": reason,
        "eligible": reason == "eligible",
        "safety_policy": "diagnostic_only_pending_intents_are_not_orders",
    }


def _recursive_find_first_numeric(obj: Any, key_fragments: Tuple[str, ...]) -> Optional[Decimal]:
    if isinstance(obj, dict):
        # Prefer exact-ish key matches at the current level before recursing.
        for key, value in obj.items():
            key_l = str(key).lower()
            if any(fragment in key_l for fragment in key_fragments):
                dec = _to_decimal(value)
                if dec is not None and dec > 0:
                    return dec
        for value in obj.values():
            dec = _recursive_find_first_numeric(value, key_fragments)
            if dec is not None and dec > 0:
                return dec
    elif isinstance(obj, list):
        for item in obj:
            dec = _recursive_find_first_numeric(item, key_fragments)
            if dec is not None and dec > 0:
                return dec
    return None


def extract_current_price(feature_pack: Dict[str, Any]) -> Optional[Decimal]:
    if not isinstance(feature_pack, dict):
        return None
    market = feature_pack.get("market") if isinstance(feature_pack.get("market"), dict) else {}
    orderbook = feature_pack.get("orderbook_context") if isinstance(feature_pack.get("orderbook_context"), dict) else {}
    indicators = feature_pack.get("indicators") if isinstance(feature_pack.get("indicators"), dict) else {}
    raw_context = feature_pack.get("raw_context") if isinstance(feature_pack.get("raw_context"), dict) else {}
    return _first_decimal(
        feature_pack.get("current_price"),
        feature_pack.get("price"),
        feature_pack.get("last_price"),
        feature_pack.get("mid_price"),
        market.get("mid_price"),
        market.get("price"),
        market.get("last_price"),
        orderbook.get("mid_price"),
        orderbook.get("best_ask"),
        orderbook.get("best_bid"),
        ((indicators.get("1h") or {}) if isinstance(indicators.get("1h"), dict) else {}).get("close"),
        ((indicators.get("4h") or {}) if isinstance(indicators.get("4h"), dict) else {}).get("close"),
        ((raw_context.get("1h") or {}) if isinstance(raw_context.get("1h"), dict) else {}).get("latest_close"),
        ((raw_context.get("4h") or {}) if isinstance(raw_context.get("4h"), dict) else {}).get("latest_close"),
    )


def _extract_support_resistance(feature_pack: Dict[str, Any]) -> Tuple[Optional[Decimal], Optional[Decimal]]:
    support = _recursive_find_first_numeric(
        feature_pack,
        (
            "nearest_support",
            "support",
            "range_low",
            "swing_low",
            "donchian_low",
            "bb_lower",
        ),
    )
    resistance = _recursive_find_first_numeric(
        feature_pack,
        (
            "nearest_resistance",
            "resistance",
            "range_high",
            "swing_high",
            "donchian_high",
            "bb_upper",
        ),
    )
    return support, resistance


def _choose_watch_resistance(
    *,
    structured_resistance: Optional[Decimal],
    text_resistance: Optional[Decimal],
    current_price: Optional[Decimal],
) -> Optional[Decimal]:
    """Choose a safer monitoring trigger for breakout/reclaim watch intents.

    Some feature packs expose a broad/derived resistance below the market while
    the gate text names the actual Donchian/range resistance being watched. For
    paper pending intents, prefer the plausible text level when it is closer to
    current price or above the structured level. This does not execute anything;
    it only reduces noisy instant trigger_ready records.
    """
    candidates = [value for value in (structured_resistance, text_resistance) if value is not None and value > 0]
    if not candidates:
        return None
    if current_price is None or current_price <= 0:
        return max(candidates)
    plausible = [
        value for value in candidates
        if _price_level_reject_reason(value, current_price=current_price) is None
    ] or candidates
    # Prefer levels at/above current for breakout monitoring. If all are below
    # current, choose the highest one so trigger_ready is less eager/noisy.
    above_current = [value for value in plausible if value >= current_price]
    if above_current:
        return min(above_current, key=lambda value: abs(value - current_price))
    return max(plausible)


def _decimal_str(value: Optional[Decimal]) -> Optional[str]:
    if value is None or value <= 0:
        return None
    return str(value)


def _confidence_from(*sources: Dict[str, Any], default: int = 0) -> int:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in ("confidence", "composite_confidence", "execution_quality_score"):
            try:
                raw = source.get(key)
                if raw is not None:
                    return max(0, min(100, int(float(raw))))
            except Exception:
                continue
    return default


def _intent_id(ticker: str, source_kind: str) -> str:
    clean = _normalize_ticker(ticker).replace("-", "") or "UNKNOWN"
    return f"pending-{clean}-{source_kind.replace('_', '-')}-{uuid.uuid4().hex[:16]}"


def _ttl_hours(cfg: Any, execution_plan: Optional[Dict[str, Any]] = None) -> int:
    if isinstance(execution_plan, dict):
        try:
            hours = int(float(execution_plan.get("expiry_hours") or 0))
            if hours > 0:
                return hours
        except Exception:
            pass
    return max(1, int(getattr(cfg, "paper_pending_intent_ttl_hours", 12)))


def build_pending_intent_from_execution_plan(
    *,
    cfg: Any,
    ticker: str,
    analysis: Dict[str, Any],
    execution_plan: Dict[str, Any],
    feature_pack: Dict[str, Any],
    cycle_source: str = "strategy_engine",
) -> Optional[Dict[str, Any]]:
    """Build a paper pending intent from execution_action=pending_plan_only.

    This is not an order and never reserves quote/base. It is only a monitoring
    record that may later promote the ticker back to fresh analysis.
    """
    if not isinstance(execution_plan, dict):
        return None
    action = str(execution_plan.get("execution_action") or "").strip().lower()
    if action != "pending_plan_only":
        return None

    ticker = _normalize_ticker(ticker)
    if not ticker:
        return None
    analysis = analysis if isinstance(analysis, dict) else {}
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    trade_plan = analysis.get("trade_plan") if isinstance(analysis.get("trade_plan"), dict) else {}
    entry_low = _first_decimal(trade_plan.get("entry_zone_low"), trade_plan.get("entry_low"), trade_plan.get("support"))
    entry_high = _first_decimal(trade_plan.get("entry_zone_high"), trade_plan.get("entry_high"), trade_plan.get("trigger_price"), trade_plan.get("trigger_level"))
    support, resistance = _extract_support_resistance(feature_pack)
    if entry_low is None:
        entry_low = support
    if entry_high is None:
        entry_high = resistance or entry_low

    trigger_price = _first_decimal(trade_plan.get("trigger_price"), trade_plan.get("trigger_level"), entry_high, resistance)
    invalidation = _first_decimal(trade_plan.get("invalidation_price"), trade_plan.get("invalidation_level"), trade_plan.get("stop_loss"))
    do_not_chase = _first_decimal(trade_plan.get("do_not_chase_above"), resistance)
    current_price = extract_current_price(feature_pack)

    created = _now_utc()
    hours = _ttl_hours(cfg, execution_plan)
    expires = created + timedelta(hours=hours)
    confidence = _confidence_from(execution_plan, analysis.get("judge", {}) if isinstance(analysis.get("judge"), dict) else {}, trade_plan, default=0)

    return {
        "intent_id": _intent_id(ticker, "pending_plan_only"),
        "ticker": ticker,
        "status": "active",
        "source_kind": "execution_planner_pending_plan_only",
        "cycle_source": cycle_source,
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "execution_action": "pending_plan_only",
        "side": "NONE",
        "order_type": "pending_plan_only",
        "entry_zone_low": _decimal_str(entry_low),
        "entry_zone_high": _decimal_str(entry_high),
        "trigger_price": _decimal_str(trigger_price),
        "invalidation_price": _decimal_str(invalidation),
        "do_not_chase_above": _decimal_str(do_not_chase),
        "current_price_at_creation": _decimal_str(current_price),
        "confidence": confidence,
        "reason": execution_plan.get("reason") or "execution_planner_pending_plan_only",
        "cancel_if": _as_list(execution_plan.get("cancel_if")),
        "replace_if": _as_list(execution_plan.get("replace_if")),
        "gpt_output": _json_safe(execution_plan),
        "trade_plan_snapshot": _json_safe(trade_plan),
        "requires_fresh_judge_and_risk": True,
        "paper_only": True,
        "live_order_submitted": False,
        "safety_policy": "Pending intents are monitoring context only and never authorize or place orders.",
    }


def build_watchlist_intent_from_analysis(
    *,
    cfg: Any,
    ticker: str,
    analysis: Dict[str, Any],
    feature_pack: Dict[str, Any],
    cycle_source: str = "strategy_engine",
) -> Optional[Dict[str, Any]]:
    """Build a paper watchlist intent from gate watch/analyze context.

    This captures useful wait/watch setups such as support/reclaim levels without
    placing or reserving anything. It is deliberately conservative and schema-light.
    """
    if not bool(getattr(cfg, "enable_paper_watchlist_intents_from_gate_watch", True)):
        return None
    ticker = _normalize_ticker(ticker)
    if not ticker:
        return None
    analysis = analysis if isinstance(analysis, dict) else {}
    feature_pack = feature_pack if isinstance(feature_pack, dict) else {}
    entry_gate = analysis.get("entry_gate") if isinstance(analysis.get("entry_gate"), dict) else {}
    judge = analysis.get("judge") if isinstance(analysis.get("judge"), dict) else {}
    decision = str(entry_gate.get("decision") or "").strip().lower()
    if decision not in {"watch", "analyze", "priority_analyze"}:
        return None
    judge_decision = str(judge.get("decision") or "wait").strip().lower()
    if judge_decision not in {"wait", "reject", "no_trade"}:
        return None
    confidence = _confidence_from(entry_gate, judge, default=0)
    if confidence < int(getattr(cfg, "paper_pending_intent_min_gate_confidence", 50)):
        return None

    diagnostics = _watchlist_candidate_diagnostics(
        cfg=cfg,
        ticker=ticker,
        analysis=analysis,
        feature_pack=feature_pack,
    )
    if not diagnostics.get("eligible"):
        return None

    current_price = extract_current_price(feature_pack)
    support, resistance = _extract_support_resistance(feature_pack)
    text_support = _to_decimal(diagnostics.get("text_support"))
    text_resistance = _to_decimal(diagnostics.get("text_resistance"))
    if support is None:
        support = text_support
    resistance = _choose_watch_resistance(
        structured_resistance=resistance,
        text_resistance=text_resistance,
        current_price=current_price,
    )

    # For watchlist buys, prefer a support/reclaim zone. If only current price is
    # available, create a very narrow watch zone around current context, but do
    # not treat it as order permission.
    if support is not None and support > 0:
        entry_low = support * Decimal("0.9975")
        entry_high = support * Decimal("1.0025")
    elif current_price is not None and current_price > 0:
        entry_low = current_price * Decimal("0.995")
        entry_high = current_price * Decimal("1.005")
    else:
        entry_low = None
        entry_high = None

    trigger_price = resistance or entry_high
    invalidation = None
    if support is not None and support > 0:
        invalidation = support * Decimal("0.9925")
    elif current_price is not None and current_price > 0:
        invalidation = current_price * Decimal("0.985")
    do_not_chase = resistance or (current_price * Decimal("1.020") if current_price is not None and current_price > 0 else None)

    created = _now_utc()
    hours = max(1, int(getattr(cfg, "paper_pending_intent_ttl_hours", 12)))
    expires = created + timedelta(hours=hours)
    reasons = _as_list(entry_gate.get("reasons"))[:8] or _as_list(judge.get("reasons"))[:8]

    return {
        "intent_id": _intent_id(ticker, "gate_watch"),
        "ticker": ticker,
        "status": "active",
        "source_kind": "gate_watch_order_intent",
        "cycle_source": cycle_source,
        "created_at": created.isoformat(),
        "updated_at": created.isoformat(),
        "expires_at": expires.isoformat(),
        "execution_action": "pending_plan_only",
        "side": "NONE",
        "order_type": "watchlist_pending_intent",
        "entry_zone_low": _decimal_str(entry_low),
        "entry_zone_high": _decimal_str(entry_high),
        "trigger_price": _decimal_str(trigger_price),
        "invalidation_price": _decimal_str(invalidation),
        "do_not_chase_above": _decimal_str(do_not_chase),
        "current_price_at_creation": _decimal_str(current_price),
        "confidence": confidence,
        "setup_type": entry_gate.get("setup_type") or ((analysis.get("synth") or {}) if isinstance(analysis.get("synth"), dict) else {}).get("setup_type"),
        "reason": "gate_watch_saved_as_paper_pending_intent",
        "reasons": reasons,
        "level_extraction": {
            "method": "feature_pack_plus_text_fallback",
            "diagnostics": _json_safe(diagnostics),
        },
        "entry_gate_snapshot": _json_safe(entry_gate),
        "judge_snapshot": _json_safe({
            "decision": judge.get("decision"),
            "confidence": judge.get("confidence"),
            "strategy": judge.get("strategy"),
            "reasons": _as_list(judge.get("reasons"))[:8],
        }),
        "requires_fresh_judge_and_risk": True,
        "paper_only": True,
        "live_order_submitted": False,
        "safety_policy": "Watchlist intents are monitoring context only and never authorize or place orders.",
    }


def _intent_is_promotion_ready(intent: Dict[str, Any]) -> bool:
    status = str(intent.get("status") or "").strip().lower()
    if status in PROMOTION_READY_STATUSES:
        return True
    last = intent.get("last_evaluation") if isinstance(intent.get("last_evaluation"), dict) else {}
    return bool(last.get("trigger_ready") or last.get("should_force_full_analysis"))


def build_pending_order_intent_context(ticker: str, intents: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Build a prompt/prefilter-safe context for paper pending order-intents.

    This context is monitoring-only. It can promote a ticker to fresh analysis,
    but it must never authorize or place an order.
    """
    normalized = _normalize_ticker(ticker)
    candidates = []
    for intent in intents or []:
        if not isinstance(intent, dict):
            continue
        if normalized and _normalize_ticker(intent.get("ticker")) != normalized:
            continue
        status = str(intent.get("status") or "active").strip().lower()
        if status not in ACTIVE_STATUSES:
            continue
        candidates.append(intent)
    candidates.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
    active = candidates[0] if candidates else None
    if not active:
        return {
            "enabled": True,
            "ticker": normalized,
            "has_active_intent": False,
            "trigger_ready": False,
            "should_force_full_analysis": False,
            "status": "none",
            "reason": "no_active_pending_order_intent",
            "safety_policy": "pending_intent_context_never_authorizes_execution",
        }

    status = str(active.get("status") or "active").strip().lower()
    last_eval = active.get("last_evaluation") if isinstance(active.get("last_evaluation"), dict) else {}
    promotion_ready = _intent_is_promotion_ready(active)
    return {
        "enabled": True,
        "ticker": normalized,
        "has_active_intent": True,
        "status": status,
        "intent_id": active.get("intent_id"),
        "source_kind": active.get("source_kind"),
        "confidence": active.get("confidence"),
        "setup_type": active.get("setup_type"),
        "created_at": active.get("created_at"),
        "updated_at": active.get("updated_at"),
        "expires_at": active.get("expires_at"),
        "trigger_price": active.get("trigger_price"),
        "invalidation_price": active.get("invalidation_price"),
        "do_not_chase_above": active.get("do_not_chase_above"),
        "entry_zone_low": active.get("entry_zone_low"),
        "entry_zone_high": active.get("entry_zone_high"),
        "last_evaluation": last_eval,
        "trigger_ready": bool(promotion_ready),
        "should_force_full_analysis": bool(promotion_ready),
        "requires_fresh_judge_and_risk": True,
        "reason": last_eval.get("reason") or active.get("reason") or "active_pending_order_intent",
        "safety_policy": "pending_intent_context_never_authorizes_execution_requires_fresh_judge_and_risk",
    }


def evaluate_pending_intent(intent: Dict[str, Any], feature_pack: Dict[str, Any], *, now: Optional[datetime] = None, max_chase_distance_pct: Decimal = Decimal("0.0200")) -> Dict[str, Any]:
    current_dt = now or _now_utc()
    ticker = _normalize_ticker(intent.get("ticker"))
    status = str(intent.get("status") or "active").strip().lower()
    current_price = extract_current_price(feature_pack if isinstance(feature_pack, dict) else {})
    expires_at = _parse_dt(intent.get("expires_at"))

    if status in FINAL_STATUSES:
        return {"ticker": ticker, "status": status, "action": "keep_final", "trigger_ready": False, "reason": "intent_already_final", "current_price": _decimal_str(current_price)}
    if expires_at is not None and current_dt >= expires_at:
        return {"ticker": ticker, "status": "expired", "action": "expire", "trigger_ready": False, "reason": "paper_pending_intent_expired", "current_price": _decimal_str(current_price)}
    if current_price is None or current_price <= 0:
        return {"ticker": ticker, "status": "waiting", "action": "keep", "trigger_ready": False, "reason": "current_price_unavailable", "current_price": None}

    invalidation = _to_decimal(intent.get("invalidation_price"))
    if invalidation is not None and invalidation > 0 and current_price <= invalidation:
        return {"ticker": ticker, "status": "invalidated", "action": "invalidate", "trigger_ready": False, "reason": "paper_pending_intent_invalidation_breached", "current_price": _decimal_str(current_price)}

    do_not_chase = _to_decimal(intent.get("do_not_chase_above"))
    if do_not_chase is not None and do_not_chase > 0 and current_price > do_not_chase:
        chase_distance = (current_price - do_not_chase) / current_price if current_price > 0 else Decimal("0")
        if chase_distance > max_chase_distance_pct:
            return {
                "ticker": ticker,
                "status": "invalidated",
                "action": "invalidate",
                "trigger_ready": False,
                "reason": "paper_pending_intent_do_not_chase_breached",
                "current_price": _decimal_str(current_price),
                "distance_above_do_not_chase_pct": str(chase_distance * Decimal("100")),
            }

    low = _to_decimal(intent.get("entry_zone_low"))
    high = _to_decimal(intent.get("entry_zone_high"))
    if low is not None and high is not None and low > high:
        low, high = high, low
    in_zone = False
    if low is not None and high is not None and low > 0 and high > 0:
        in_zone = low <= current_price <= high
    elif low is not None and low > 0:
        in_zone = current_price >= low
    elif high is not None and high > 0:
        in_zone = current_price <= high

    trigger = _to_decimal(intent.get("trigger_price"))
    trigger_crossed = trigger is not None and trigger > 0 and current_price >= trigger

    if in_zone or trigger_crossed:
        return {
            "ticker": ticker,
            "status": "trigger_ready",
            "action": "mark_trigger_ready",
            "trigger_ready": True,
            "should_force_full_analysis": True,
            "reason": "paper_pending_intent_trigger_ready_requires_fresh_analysis",
            "current_price": _decimal_str(current_price),
            "in_entry_zone": in_zone,
            "trigger_crossed": trigger_crossed,
        }

    return {
        "ticker": ticker,
        "status": "waiting",
        "action": "keep",
        "trigger_ready": False,
        "should_force_full_analysis": False,
        "reason": "paper_pending_intent_waiting",
        "current_price": _decimal_str(current_price),
    }


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def _status_is_open(status: Any) -> bool:
    return str(status or "active").strip().lower() in ACTIVE_STATUSES


def _status_is_final(status: Any) -> bool:
    return str(status or "").strip().lower() in FINAL_STATUSES


def _level_distance_pct(a: Any, b: Any) -> Optional[Decimal]:
    da = _to_decimal(a)
    db = _to_decimal(b)
    if da is None or db is None or da <= 0 or db <= 0:
        return None
    anchor = max(abs(da), abs(db), Decimal("0.00000001"))
    return abs(da - db) / anchor


def _intent_level_signature(intent: Dict[str, Any]) -> Dict[str, Optional[Decimal]]:
    return {
        "trigger_price": _to_decimal(intent.get("trigger_price")),
        "entry_zone_low": _to_decimal(intent.get("entry_zone_low")),
        "entry_zone_high": _to_decimal(intent.get("entry_zone_high")),
        "invalidation_price": _to_decimal(intent.get("invalidation_price")),
        "do_not_chase_above": _to_decimal(intent.get("do_not_chase_above")),
    }


def _intents_are_effectively_same(existing: Dict[str, Any], incoming: Dict[str, Any], *, tolerance_pct: Decimal) -> bool:
    """Return True when an incoming paper intent is just a refresh of an existing one.

    This is intentionally conservative. It only suppresses churn for open
    non-promotion states. It never downgrades a trigger_ready/needs_fresh_analysis
    record and never creates execution permission.
    """
    if _normalize_ticker(existing.get("ticker")) != _normalize_ticker(incoming.get("ticker")):
        return False
    existing_status = str(existing.get("status") or "active").strip().lower()
    incoming_status = str(incoming.get("status") or "active").strip().lower()
    if existing_status in PROMOTION_READY_STATUSES or incoming_status in PROMOTION_READY_STATUSES:
        return False
    if existing_status not in ACTIVE_STATUSES or incoming_status not in ACTIVE_STATUSES:
        return False
    if str(existing.get("source_kind") or "") != str(incoming.get("source_kind") or ""):
        return False
    if str(existing.get("setup_type") or "") != str(incoming.get("setup_type") or ""):
        return False

    existing_sig = _intent_level_signature(existing)
    incoming_sig = _intent_level_signature(incoming)
    comparable = 0
    for key in ("trigger_price", "entry_zone_low", "entry_zone_high", "invalidation_price", "do_not_chase_above"):
        old = existing_sig.get(key)
        new = incoming_sig.get(key)
        if old is None and new is None:
            continue
        if old is None or new is None:
            return False
        comparable += 1
        dist = _level_distance_pct(old, new)
        if dist is None or dist > tolerance_pct:
            return False
    return comparable >= 2


def _should_drop_final_intent(intent: Dict[str, Any], *, now: datetime, final_retention_hours: int) -> bool:
    if final_retention_hours <= 0:
        return False
    if not _status_is_final(intent.get("status")):
        return False
    dt = _parse_dt(intent.get("updated_at") or intent.get("created_at"))
    if dt is None:
        return False
    return (now - dt) > timedelta(hours=final_retention_hours)


class PendingOrderIntentStore:
    """JSON-backed paper pending-order-intent store.

    Pending intents are not open orders. They do not reserve quote/base and do
    not submit/cancel/replace Coinbase orders. They are watchlist context for
    the master bot only.
    """

    def __init__(
        self,
        path: str | Path = "state/pending_order_intents.json",
        log_path: str | Path = "logs/pending_order_intents.jsonl",
        max_records: int = 500,
        enabled: bool = True,
        *,
        max_replaced_per_ticker: int = 8,
        final_retention_hours: int = 72,
        dedupe_tolerance_pct: Decimal | str | float = Decimal("0.0025"),
        enable_dedupe_refresh: bool = True,
    ) -> None:
        self.path = Path(path)
        self.log_path = Path(log_path)
        self.max_records = max(1, int(max_records))
        self.enabled = bool(enabled)
        self.max_replaced_per_ticker = max(0, _safe_int(max_replaced_per_ticker, 8))
        self.final_retention_hours = max(0, _safe_int(final_retention_hours, 72))
        self.dedupe_tolerance_pct = _to_decimal(dedupe_tolerance_pct, "0.0025") or Decimal("0.0025")
        self.enable_dedupe_refresh = bool(enable_dedupe_refresh)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self._write_state({"intents": {}})

    def _read_state(self) -> Dict[str, Any]:
        try:
            if not self.path.exists():
                return {"intents": {}}
            with self.path.open("r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return {"intents": {}}
            if not isinstance(data.get("intents"), dict):
                data["intents"] = {}
            return data
        except Exception:
            return {"intents": {}}

    def _write_state(self, data: Dict[str, Any]) -> None:
        from bot.atomic_io import atomic_write_json

        atomic_write_json(self.path, _json_safe(data), sort_keys=True)

    def append_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        event = {"generated_at": _now_iso(), "event_type": event_type, **_json_safe(payload)}
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")

    def all_intents(self) -> List[Dict[str, Any]]:
        intents = self._read_state().get("intents", {})
        if not isinstance(intents, dict):
            return []
        return [dict(v) for v in intents.values() if isinstance(v, dict)]

    def active_intents(self, ticker: Optional[str] = None) -> List[Dict[str, Any]]:
        normalized = _normalize_ticker(ticker)
        out: List[Dict[str, Any]] = []
        for intent in self.all_intents():
            if str(intent.get("status") or "active").strip().lower() not in ACTIVE_STATUSES:
                continue
            if normalized and _normalize_ticker(intent.get("ticker")) != normalized:
                continue
            out.append(intent)
        out.sort(key=lambda x: str(x.get("updated_at") or x.get("created_at") or ""), reverse=True)
        return out

    def context_for_ticker(self, ticker: str) -> Dict[str, Any]:
        return build_pending_order_intent_context(ticker, self.active_intents(ticker))

    def _refresh_existing_intent(self, existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
        refreshed = dict(existing)
        refreshed["updated_at"] = _now_iso()
        refreshed["last_seen_at"] = refreshed["updated_at"]
        refreshed["refresh_count"] = _safe_int(refreshed.get("refresh_count"), 0) + 1
        refreshed["last_refresh_reason"] = "deduped_similar_paper_pending_intent"
        # Keep the existing intent_id/status/lifecycle, but refresh useful context.
        for key in (
            "confidence",
            "reason",
            "reasons",
            "current_price_at_creation",
            "level_extraction",
            "entry_gate_snapshot",
            "judge_snapshot",
        ):
            if key in incoming:
                refreshed[key] = _json_safe(incoming.get(key))
        refreshed["dedupe_safety_policy"] = "Dedup refresh preserves monitoring-only semantics and never authorizes execution."
        return refreshed

    def _find_similar_active_intent(self, intents: Dict[str, Any], incoming: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
        if not self.enable_dedupe_refresh:
            return None
        ticker = _normalize_ticker(incoming.get("ticker"))
        if not ticker:
            return None
        best: Optional[Tuple[str, Dict[str, Any]]] = None
        for key, old in intents.items():
            if not isinstance(old, dict):
                continue
            if _normalize_ticker(old.get("ticker")) != ticker:
                continue
            status = str(old.get("status") or "active").strip().lower()
            if status not in {"active", "waiting", "stale"}:
                continue
            if _intents_are_effectively_same(old, incoming, tolerance_pct=self.dedupe_tolerance_pct):
                if best is None or str(old.get("updated_at") or old.get("created_at") or "") > str(best[1].get("updated_at") or best[1].get("created_at") or ""):
                    best = (str(key), old)
        return best

    def _apply_retention(self, intents: Dict[str, Any]) -> Dict[str, int]:
        """Compact noisy final history while preserving active/open audit state."""
        removed_by_age = 0
        removed_by_per_ticker = 0
        removed_by_max_records = 0
        now = _now_utc()

        for key, value in list(intents.items()):
            if not isinstance(value, dict):
                intents.pop(key, None)
                removed_by_age += 1
                continue
            if _should_drop_final_intent(value, now=now, final_retention_hours=self.final_retention_hours):
                intents.pop(key, None)
                removed_by_age += 1

        if self.max_replaced_per_ticker > 0:
            replaced_by_ticker: Dict[str, List[Tuple[str, Dict[str, Any]]]] = {}
            for key, value in intents.items():
                if not isinstance(value, dict):
                    continue
                if str(value.get("status") or "").strip().lower() != "replaced":
                    continue
                ticker = _normalize_ticker(value.get("ticker")) or "UNKNOWN"
                replaced_by_ticker.setdefault(ticker, []).append((str(key), value))
            for ticker, rows in replaced_by_ticker.items():
                rows.sort(key=lambda kv: str((kv[1] or {}).get("updated_at") or (kv[1] or {}).get("created_at") or ""), reverse=True)
                for key, _value in rows[self.max_replaced_per_ticker:]:
                    if key in intents:
                        intents.pop(key, None)
                        removed_by_per_ticker += 1

        if len(intents) > self.max_records:
            # Drop final records first, oldest first. Never drop active/open intents for retention.
            final_items = [
                (key, value)
                for key, value in intents.items()
                if isinstance(value, dict) and _status_is_final(value.get("status"))
            ]
            final_items.sort(key=lambda kv: str((kv[1] or {}).get("updated_at") or (kv[1] or {}).get("created_at") or ""))
            for key, _value in final_items:
                if len(intents) <= self.max_records:
                    break
                intents.pop(key, None)
                removed_by_max_records += 1

        return {
            "removed_by_age": removed_by_age,
            "removed_by_per_ticker_limit": removed_by_per_ticker,
            "removed_by_max_records": removed_by_max_records,
        }

    def store_intent(self, intent: Dict[str, Any], *, replace_same_ticker: bool = True) -> Optional[Dict[str, Any]]:
        if not self.enabled:
            return None
        if not isinstance(intent, dict):
            return None
        ticker = _normalize_ticker(intent.get("ticker"))
        if not ticker:
            return None
        state = self._read_state()
        intents = state.setdefault("intents", {})
        if not isinstance(intents, dict):
            intents = {}
            state["intents"] = intents

        incoming = dict(intent)
        incoming["ticker"] = ticker

        similar = self._find_similar_active_intent(intents, incoming)
        if similar is not None:
            existing_key, existing = similar
            refreshed = self._refresh_existing_intent(existing, incoming)
            intents[existing_key] = refreshed
            retention = self._apply_retention(intents)
            self._write_state(state)
            self.append_event(
                "paper_pending_intent_deduped_refresh",
                {
                    "intent_id": existing_key,
                    "ticker": ticker,
                    "refresh_count": refreshed.get("refresh_count"),
                    "retention": retention,
                    "intent": refreshed,
                    "safety_policy": "dedupe_refresh_preserves_existing_monitoring_intent_and_never_authorizes_execution",
                },
            )
            return refreshed

        if replace_same_ticker:
            for key, old in list(intents.items()):
                if not isinstance(old, dict):
                    continue
                if _normalize_ticker(old.get("ticker")) != ticker:
                    continue
                if str(old.get("status") or "active").strip().lower() not in ACTIVE_STATUSES:
                    continue
                old = dict(old)
                old["status"] = "replaced"
                old["updated_at"] = _now_iso()
                old["replacement_reason"] = "replaced_by_newer_paper_pending_intent_for_same_ticker"
                intents[key] = old
                self.append_event("paper_pending_intent_replaced", {"intent": old})

        record = incoming
        intent_id = str(record.get("intent_id") or _intent_id(ticker, str(record.get("source_kind") or "pending"))).strip()
        record["intent_id"] = intent_id
        record["ticker"] = ticker
        record["updated_at"] = _now_iso()
        intents[intent_id] = record

        retention = self._apply_retention(intents)
        self._write_state(state)
        self.append_event("paper_pending_intent_stored", {"intent": record, "retention": retention})
        if any(retention.values()):
            self.append_event("paper_pending_intent_retention_applied", {"retention": retention, "total_after": len(intents)})
        return record

    def update_intent(self, intent_id: str, updates: Dict[str, Any], *, event_type: str = "paper_pending_intent_updated") -> Optional[Dict[str, Any]]:
        state = self._read_state()
        intents = state.setdefault("intents", {})
        intent = intents.get(str(intent_id))
        if not isinstance(intent, dict):
            return None
        intent.update(dict(updates or {}))
        intent["updated_at"] = _now_iso()
        intents[str(intent_id)] = intent
        retention = self._apply_retention(intents)
        self._write_state(state)
        payload = {"intent_id": intent_id, "updates": updates, "intent": intent}
        if any(retention.values()):
            payload["retention"] = retention
        self.append_event(event_type, payload)
        if any(retention.values()):
            self.append_event("paper_pending_intent_retention_applied", {"retention": retention, "total_after": len(intents)})
        return dict(intent)

    def evaluate_intents(self, feature_packs: Dict[str, Dict[str, Any]], *, max_chase_distance_pct: Decimal = Decimal("0.0200"), mark_needs_fresh_analysis: bool = False) -> Dict[str, Any]:
        if not self.enabled:
            return {"generated_at": _now_iso(), "enabled": False, "reviewed": 0, "actions": [], "reason": "paper_pending_intents_disabled"}
        actions: List[Dict[str, Any]] = []
        feature_packs = feature_packs if isinstance(feature_packs, dict) else {}
        for intent in self.active_intents():
            ticker = _normalize_ticker(intent.get("ticker"))
            feature_pack = feature_packs.get(ticker)
            if not isinstance(feature_pack, dict):
                evaluation = {
                    "ticker": ticker,
                    "status": "stale",
                    "action": "mark_stale",
                    "trigger_ready": False,
                    "should_force_full_analysis": False,
                    "reason": "paper_pending_intent_stale_missing_feature_pack",
                    "current_price": None,
                }
            else:
                evaluation = evaluate_pending_intent(intent, feature_pack, max_chase_distance_pct=max_chase_distance_pct)
                if mark_needs_fresh_analysis and bool(evaluation.get("trigger_ready") or evaluation.get("should_force_full_analysis")):
                    evaluation = dict(evaluation)
                    evaluation["status"] = "needs_fresh_analysis"
                    evaluation["action"] = "mark_needs_fresh_analysis"
                    evaluation["reason"] = "paper_pending_intent_needs_fresh_analysis_before_any_execution"
                    evaluation["trigger_ready"] = True
                    evaluation["should_force_full_analysis"] = True
            action = str(evaluation.get("action") or "keep")
            updates: Dict[str, Any] = {
                "last_evaluated_at": _now_iso(),
                "last_evaluation": evaluation,
                "status": evaluation.get("status") or intent.get("status") or "waiting",
            }
            event_type = "paper_pending_intent_reviewed"
            if action in {"expire", "invalidate", "mark_trigger_ready", "mark_needs_fresh_analysis", "mark_stale"}:
                event_type = f"paper_pending_intent_{updates['status']}"
            updated = self.update_intent(str(intent.get("intent_id")), updates, event_type=event_type)
            actions.append({"intent_id": intent.get("intent_id"), "ticker": ticker, "action": action, "evaluation": evaluation, "updated": bool(updated)})
        result = {"generated_at": _now_iso(), "enabled": True, "reviewed": len(actions), "actions": actions, "summary": self.summary()}
        self.append_event("paper_pending_intents_cycle_reviewed", result)
        return result

    def diagnostic_count(self) -> int:
        count = 0
        for intent in self.all_intents():
            iid = str(intent.get("intent_id") or "")
            ticker = str(intent.get("ticker") or "")
            reason = str(intent.get("reason") or "")
            if iid.startswith("paper-diagnostic-") or ticker.startswith("TEST-") or reason.startswith("phase_b6_diagnostic_"):
                count += 1
        return count

    def summary(self) -> Dict[str, Any]:
        intents = self.all_intents()
        active_intents = self.active_intents()
        by_status: Dict[str, int] = {}
        by_active_status: Dict[str, int] = {}
        by_source: Dict[str, int] = {}
        trigger_ready: List[Dict[str, Any]] = []
        needs_fresh_analysis: List[Dict[str, Any]] = []
        promotion_ready: List[Dict[str, Any]] = []

        for intent in intents:
            status = str(intent.get("status") or "active").strip().lower()
            source = str(intent.get("source_kind") or "unknown").strip().lower()
            by_status[status] = by_status.get(status, 0) + 1
            by_source[source] = by_source.get(source, 0) + 1

        # Observability is intentionally based only on currently active/open intents.
        # Replaced/invalidated/expired records may keep an old last_evaluation with
        # trigger_ready=true for audit purposes, but they must not appear in current
        # trigger/promotion summaries.
        for intent in active_intents:
            status = str(intent.get("status") or "active").strip().lower()
            by_active_status[status] = by_active_status.get(status, 0) + 1
            last = intent.get("last_evaluation") if isinstance(intent.get("last_evaluation"), dict) else {}
            item = {
                "intent_id": intent.get("intent_id"),
                "ticker": intent.get("ticker"),
                "status": status,
                "reason": last.get("reason"),
                "current_price": last.get("current_price"),
                "requires_fresh_judge_and_risk": True,
            }
            if status == "trigger_ready":
                trigger_ready.append(item)
                promotion_ready.append(item)
            elif status == "needs_fresh_analysis":
                needs_fresh_analysis.append(item)
                promotion_ready.append(item)
            elif status in PROMOTION_READY_STATUSES or _intent_is_promotion_ready(intent):
                # Defensive fallback for older state files where status was not
                # migrated yet but the active intent has a ready last_evaluation.
                promotion_ready.append(item)

        replaced_by_ticker: Dict[str, int] = {}
        for intent in intents:
            if str(intent.get("status") or "").strip().lower() != "replaced":
                continue
            ticker = _normalize_ticker(intent.get("ticker")) or "UNKNOWN"
            replaced_by_ticker[ticker] = replaced_by_ticker.get(ticker, 0) + 1

        return {
            "generated_at": _now_iso(),
            "total_intents": len(intents),
            "active_intents": len(active_intents),
            "open_intents": len(active_intents),
            "by_status": by_status,
            "by_active_status": by_active_status,
            "by_source": by_source,
            "trigger_ready": trigger_ready,
            "needs_fresh_analysis": needs_fresh_analysis,
            "promotion_ready": promotion_ready,
            "retention": {
                "max_records": self.max_records,
                "max_replaced_per_ticker": self.max_replaced_per_ticker,
                "final_retention_hours": self.final_retention_hours,
                "dedupe_tolerance_pct": str(self.dedupe_tolerance_pct),
                "enable_dedupe_refresh": self.enable_dedupe_refresh,
                "replaced_by_ticker": replaced_by_ticker,
            },
            "diagnostic_intent_count": self.diagnostic_count(),
            "safety_policy": "Pending intents are not orders and never authorize execution.",
        }


__all__ = [
    "PendingOrderIntentStore",
    "build_pending_intent_from_execution_plan",
    "build_watchlist_intent_from_analysis",
    "evaluate_pending_intent",
    "extract_current_price",
    "build_pending_order_intent_context",
    "_watchlist_candidate_diagnostics",
]
