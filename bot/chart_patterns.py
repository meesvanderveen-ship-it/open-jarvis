from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


PatternDict = Dict[str, Any]


@dataclass(frozen=True)
class ChartPattern:
    type: str
    family: str
    direction: str
    timeframe: str
    quality: int
    confirmation: str
    trigger_level: Optional[float]
    invalidation_level: Optional[float]
    target_level: Optional[float]
    evidence: List[str]
    risk: str = ""

    def to_dict(self) -> PatternDict:
        data = asdict(self)
        data["quality"] = int(_clamp(data.get("quality", 0), 0, 100))
        return data


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        result = float(value)
        if result != result:  # NaN
            return default
        return result
    except Exception:
        return default


def _to_float_list(values: Any, limit: Optional[int] = None) -> List[float]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes, bytearray)):
        return []
    sliced = list(values[-limit:] if limit else values)
    return [_to_float(v) for v in sliced]


def _clamp(value: Any, low: float, high: float) -> float:
    val = _to_float(value, low)
    if val < low:
        return low
    if val > high:
        return high
    return val


def _pct_distance(a: float, b: float) -> Optional[float]:
    if not a or not b:
        return None
    try:
        return round(((a - b) / b) * 100.0, 4)
    except Exception:
        return None


def _mean(values: Iterable[float]) -> float:
    vals = [v for v in values if isinstance(v, (int, float))]
    if not vals:
        return 0.0
    return sum(vals) / len(vals)


def _safe_round(value: Optional[float], digits: int = 8) -> Optional[float]:
    if value is None:
        return None
    try:
        return round(float(value), digits)
    except Exception:
        return None


def _latest_close(raw: Dict[str, Any], indicators: Dict[str, Any]) -> float:
    close = _to_float(raw.get("latest_close"), 0.0)
    if close > 0:
        return close
    closes = _to_float_list(raw.get("closes"), limit=1)
    if closes:
        return closes[-1]
    return _to_float(indicators.get("close"), 0.0)


def _volume_confirmation(raw: Dict[str, Any], micro: Dict[str, Any]) -> Tuple[str, float]:
    volume_vs_avg = _to_float(micro.get("volume_vs_avg"), 0.0)
    if volume_vs_avg <= 0:
        volumes = _to_float_list(raw.get("volumes"), limit=20)
        if len(volumes) >= 5:
            recent_avg = _mean(volumes[:-1])
            volume_vs_avg = volumes[-1] / recent_avg if recent_avg else 0.0
    if volume_vs_avg >= 1.6:
        return "strong", round(volume_vs_avg, 4)
    if volume_vs_avg >= 1.15:
        return "moderate", round(volume_vs_avg, 4)
    if volume_vs_avg > 0:
        return "weak", round(volume_vs_avg, 4)
    return "unknown", 0.0


def _confirmation_from_quality(quality: int, volume_confirmation: str = "unknown") -> str:
    if quality >= 78 and volume_confirmation in {"strong", "moderate"}:
        return "confirmed"
    if quality >= 60:
        return "partial"
    if quality >= 40:
        return "early"
    return "weak"


def _get_tf_context(feature_pack: Dict[str, Any], timeframe: str) -> Dict[str, Any]:
    raw_context = feature_pack.get("raw_context", {}) if isinstance(feature_pack, dict) else {}
    indicators = feature_pack.get("indicators", {}) if isinstance(feature_pack, dict) else {}
    microstructure = feature_pack.get("microstructure", {}) if isinstance(feature_pack, dict) else {}
    return {
        "raw": raw_context.get(timeframe, {}) if isinstance(raw_context, dict) else {},
        "indicators": indicators.get(timeframe, {}) if isinstance(indicators, dict) else {},
        "micro": microstructure.get(timeframe, {}) if isinstance(microstructure, dict) else {},
    }


def _range_levels(feature_pack: Dict[str, Any], timeframe: str, raw: Dict[str, Any]) -> Tuple[float, float]:
    structure = feature_pack.get("structure", {}) if isinstance(feature_pack, dict) else {}
    support = _to_float(structure.get("nearest_support") or structure.get("support_1h") or structure.get("range_low"), 0.0)
    resistance = _to_float(structure.get("nearest_resistance") or structure.get("resistance_1h") or structure.get("range_high"), 0.0)
    lows = _to_float_list(raw.get("lows"), limit=24)
    highs = _to_float_list(raw.get("highs"), limit=24)
    if support <= 0 and lows:
        support = min(lows)
    if resistance <= 0 and highs:
        resistance = max(highs)
    return support, resistance


def build_market_structure_context(feature_pack: Dict[str, Any], timeframe: str = "1h") -> Dict[str, Any]:
    """
    Build a compact, deterministic market-structure block.

    This is intentionally not a trading signal. It gives later analysts a stable view of
    where price sits in its local range, whether volume confirms the latest move, and
    whether current price action looks like breakout/retest/failure/chop.
    """
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw = tf["raw"]
    indicators = tf["indicators"]
    micro = tf["micro"]
    close = _latest_close(raw, indicators)
    support, resistance = _range_levels(feature_pack or {}, timeframe, raw)
    lows = _to_float_list(raw.get("lows"), limit=24)
    highs = _to_float_list(raw.get("highs"), limit=24)
    closes = _to_float_list(raw.get("closes"), limit=24)

    if support <= 0 and lows:
        support = min(lows)
    if resistance <= 0 and highs:
        resistance = max(highs)

    distance_to_support_pct = _pct_distance(close, support) if support > 0 else None
    distance_to_resistance_pct = _pct_distance(resistance, close) if resistance > 0 else None

    range_position = "unknown"
    if close > 0 and support > 0 and resistance > support:
        position = (close - support) / (resistance - support)
        if position <= 0.25:
            range_position = "near_support"
        elif position >= 0.75:
            range_position = "near_resistance"
        else:
            range_position = "mid_range"
        if close > resistance * 1.002:
            range_position = "breakout_zone"
        elif close < support * 0.998:
            range_position = "breakdown_zone"

    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    recent_high = max(highs[:-1]) if len(highs) >= 2 else (max(highs) if highs else 0.0)
    recent_low = min(lows[:-1]) if len(lows) >= 2 else (min(lows) if lows else 0.0)
    latest_high = highs[-1] if highs else 0.0
    latest_low = lows[-1] if lows else 0.0
    previous_close = closes[-2] if len(closes) >= 2 else 0.0

    breakout_status = "none"
    if close > 0 and recent_high > 0 and latest_high > recent_high * 1.001:
        if close >= recent_high * 0.998:
            breakout_status = "breakout"
        else:
            breakout_status = "failed_breakout"
    if close > 0 and recent_low > 0 and latest_low < recent_low * 0.999 and close > recent_low:
        breakout_status = "support_sweep_reclaim"
    if close > 0 and resistance > 0 and previous_close > resistance and close >= resistance * 0.995:
        breakout_status = "retest"

    return {
        "timeframe": timeframe,
        "range_position": range_position,
        "support_level": _safe_round(support),
        "resistance_level": _safe_round(resistance),
        "distance_to_support_pct": distance_to_support_pct,
        "distance_to_resistance_pct": distance_to_resistance_pct,
        "breakout_status": breakout_status,
        "volume_confirmation": volume_label,
        "volume_vs_avg": volume_vs_avg,
        "current_price": _safe_round(close),
        "recent_high": _safe_round(recent_high),
        "recent_low": _safe_round(recent_low),
    }


def _pattern(type_: str, family: str, direction: str, timeframe: str, quality: int, volume_label: str,
             trigger: Optional[float], invalidation: Optional[float], target: Optional[float],
             evidence: List[str], risk: str = "") -> ChartPattern:
    return ChartPattern(
        type=type_,
        family=family,
        direction=direction,
        timeframe=timeframe,
        quality=int(_clamp(quality, 0, 100)),
        confirmation=_confirmation_from_quality(int(_clamp(quality, 0, 100)), volume_label),
        trigger_level=_safe_round(trigger),
        invalidation_level=_safe_round(invalidation),
        target_level=_safe_round(target),
        evidence=evidence,
        risk=risk,
    )


def detect_support_sweep_reclaim(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, indicators, micro = tf["raw"], tf["indicators"], tf["micro"]
    lows = _to_float_list(raw.get("lows"), limit=24)
    closes = _to_float_list(raw.get("closes"), limit=24)
    highs = _to_float_list(raw.get("highs"), limit=24)
    if len(lows) < 8 or len(closes) < 8:
        return []
    support = min(lows[:-1])
    latest_low = lows[-1]
    close = closes[-1]
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    if support <= 0 or close <= 0:
        return []
    swept = latest_low < support * 0.998
    reclaimed = close > support * 1.001
    green_close = close >= _to_float_list(raw.get("opens"), limit=1)[-1] if _to_float_list(raw.get("opens"), limit=1) else True
    if not (swept and reclaimed):
        return []
    quality = 52
    if green_close:
        quality += 8
    if volume_label in {"strong", "moderate"}:
        quality += 12
    if close > _to_float(indicators.get("ema_20"), close * 2) or _to_float(indicators.get("ema_20"), 0) <= 0:
        quality += 5
    target = max(highs[:-1]) if highs[:-1] else None
    return [_pattern(
        "support_sweep_reclaim", "reclaim", "bullish", timeframe, quality, volume_label,
        trigger=support, invalidation=latest_low, target=target,
        evidence=[
            "latest low swept below recent support",
            "close reclaimed back above support",
            f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
        ],
        risk="Reclaim remains vulnerable if next candles lose the reclaimed support.",
    )]


def detect_breakout_retest(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=24)
    lows = _to_float_list(raw.get("lows"), limit=24)
    closes = _to_float_list(raw.get("closes"), limit=24)
    if len(highs) < 10 or len(lows) < 10 or len(closes) < 10:
        return []
    prior_resistance = max(highs[:-3])
    latest_low = lows[-1]
    close = closes[-1]
    previous_close = closes[-2]
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    broke_before = max(closes[-4:-1]) > prior_resistance * 1.002 if prior_resistance > 0 else False
    retested = latest_low <= prior_resistance * 1.006 and close >= prior_resistance * 0.997
    held = close >= previous_close * 0.995
    if not (broke_before and retested and held):
        return []
    quality = 58
    if volume_label in {"strong", "moderate"}:
        quality += 12
    if close > prior_resistance:
        quality += 8
    return [_pattern(
        "breakout_retest", "breakout", "bullish", timeframe, quality, volume_label,
        trigger=prior_resistance, invalidation=min(lows[-3:]), target=prior_resistance + (prior_resistance - min(lows[-8:])),
        evidence=[
            "recent close traded above prior range resistance",
            "latest candle retested the breakout area",
            f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
        ],
        risk="Retest is invalid if price closes back inside the old range.",
    )]


def detect_failed_breakout(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=24)
    closes = _to_float_list(raw.get("closes"), limit=24)
    lows = _to_float_list(raw.get("lows"), limit=24)
    if len(highs) < 8 or len(closes) < 8:
        return []
    prior_resistance = max(highs[:-1])
    latest_high = highs[-1]
    close = closes[-1]
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    if prior_resistance <= 0:
        return []
    if latest_high > prior_resistance * 1.002 and close < prior_resistance * 0.998:
        quality = 60 + (8 if volume_label in {"strong", "moderate"} else 0)
        return [_pattern(
            "failed_breakout", "breakout_failure", "bearish", timeframe, quality, volume_label,
            trigger=prior_resistance, invalidation=latest_high, target=min(lows[:-1]) if lows[:-1] else None,
            evidence=[
                "price traded above recent resistance intraperiod",
                "close failed back below resistance",
                f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
            ],
            risk="Spot-long entries are vulnerable until price reclaims the failed breakout level.",
        )]
    return []


def detect_compression_squeeze(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, indicators, micro = tf["raw"], tf["indicators"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=20)
    lows = _to_float_list(raw.get("lows"), limit=20)
    closes = _to_float_list(raw.get("closes"), limit=20)
    if len(highs) < 12 or len(lows) < 12 or len(closes) < 12:
        return []
    close = closes[-1]
    range_pct = (max(highs[-12:]) - min(lows[-12:])) / close if close else 0.0
    bb_width = _to_float(indicators.get("bb_width_pct"), 0.0)
    adx = _to_float(indicators.get("adx_14"), 0.0)
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    is_compressed = (0 < bb_width < 0.045) or (0 < range_pct < 0.055 and adx < 22)
    if not is_compressed:
        return []
    resistance = max(highs[-12:])
    support = min(lows[-12:])
    quality = 45
    if bb_width and bb_width < 0.035:
        quality += 10
    if adx < 18:
        quality += 7
    if volume_label == "weak":
        quality += 3
    return [_pattern(
        "compression_squeeze", "compression", "neutral", timeframe, quality, volume_label,
        trigger=resistance, invalidation=support, target=None,
        evidence=[
            f"narrow recent range_pct={round(range_pct, 5)}",
            f"bb_width_pct={round(bb_width, 5)} adx_14={round(adx, 3)}",
            f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
        ],
        risk="Compression is not directional; wait for breakout acceptance or failed-breakout evidence.",
    )]


def detect_range_midpoint_rejection(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=24)
    lows = _to_float_list(raw.get("lows"), limit=24)
    closes = _to_float_list(raw.get("closes"), limit=24)
    opens = _to_float_list(raw.get("opens"), limit=24)
    if len(highs) < 10 or len(lows) < 10 or len(closes) < 3 or len(opens) < 3:
        return []
    resistance = max(highs[:-1])
    support = min(lows[:-1])
    if resistance <= support:
        return []
    midpoint = support + ((resistance - support) / 2.0)
    close = closes[-1]
    latest_high = highs[-1]
    red = closes[-1] < opens[-1]
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    if latest_high >= midpoint * 0.998 and close < midpoint * 0.995 and red:
        quality = 48 + (8 if volume_label in {"strong", "moderate"} else 0)
        return [_pattern(
            "range_midpoint_rejection", "range", "bearish", timeframe, quality, volume_label,
            trigger=midpoint, invalidation=latest_high, target=support,
            evidence=[
                "price tested local range midpoint",
                "latest candle closed back below midpoint",
                f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
            ],
            risk="Mid-range rejection weakens long entries unless support is reclaimed with confirmation.",
        )]
    return []


def detect_double_bottom(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    lows = _to_float_list(raw.get("lows"), limit=30)
    highs = _to_float_list(raw.get("highs"), limit=30)
    closes = _to_float_list(raw.get("closes"), limit=30)
    if len(lows) < 16 or len(closes) < 16:
        return []
    first_idx = min(range(0, len(lows) // 2), key=lambda i: lows[i])
    second_idx = min(range(len(lows) // 2, len(lows)), key=lambda i: lows[i])
    low1, low2 = lows[first_idx], lows[second_idx]
    if low1 <= 0 or low2 <= 0:
        return []
    similarity = abs(low1 - low2) / max(low1, low2)
    neckline = max(highs[first_idx:second_idx + 1]) if second_idx > first_idx else max(highs)
    close = closes[-1]
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    if similarity <= 0.012 and close > min(low1, low2) * 1.01:
        quality = 50 + (12 if close > neckline else 0) + (7 if volume_label in {"strong", "moderate"} else 0)
        return [_pattern(
            "double_bottom", "reversal", "bullish", timeframe, quality, volume_label,
            trigger=neckline, invalidation=min(low1, low2), target=neckline + (neckline - min(low1, low2)) if neckline else None,
            evidence=[
                "two similar swing lows detected",
                f"low_similarity_pct={round(similarity * 100, 4)}",
                f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
            ],
            risk="Double bottom is incomplete until neckline/trigger acceptance is clear.",
        )]
    return []


def detect_double_top(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=30)
    lows = _to_float_list(raw.get("lows"), limit=30)
    closes = _to_float_list(raw.get("closes"), limit=30)
    if len(highs) < 16 or len(closes) < 16:
        return []
    first_idx = max(range(0, len(highs) // 2), key=lambda i: highs[i])
    second_idx = max(range(len(highs) // 2, len(highs)), key=lambda i: highs[i])
    high1, high2 = highs[first_idx], highs[second_idx]
    if high1 <= 0 or high2 <= 0:
        return []
    similarity = abs(high1 - high2) / max(high1, high2)
    neckline = min(lows[first_idx:second_idx + 1]) if second_idx > first_idx else min(lows)
    close = closes[-1]
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    if similarity <= 0.012 and close < max(high1, high2) * 0.992:
        quality = 50 + (12 if close < neckline else 0) + (7 if volume_label in {"strong", "moderate"} else 0)
        return [_pattern(
            "double_top", "reversal", "bearish", timeframe, quality, volume_label,
            trigger=neckline, invalidation=max(high1, high2), target=neckline - (max(high1, high2) - neckline) if neckline else None,
            evidence=[
                "two similar swing highs detected",
                f"high_similarity_pct={round(similarity * 100, 4)}",
                f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
            ],
            risk="Double top warns against chasing spot longs near resistance.",
        )]
    return []


def detect_higher_low_reclaim(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, indicators, micro = tf["raw"], tf["indicators"], tf["micro"]
    lows = _to_float_list(raw.get("lows"), limit=12)
    closes = _to_float_list(raw.get("closes"), limit=12)
    highs = _to_float_list(raw.get("highs"), limit=12)
    if len(lows) < 6 or len(closes) < 6:
        return []
    ema20 = _to_float(indicators.get("ema_20"), 0.0)
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    higher_lows = lows[-1] > min(lows[-6:-3]) and min(lows[-3:]) > min(lows[-8:-5] or lows[:3])
    reclaim = ema20 > 0 and closes[-1] > ema20 and closes[-2] <= ema20
    if higher_lows and reclaim:
        quality = 58 + (8 if volume_label in {"strong", "moderate"} else 0)
        return [_pattern(
            "higher_low_reclaim", "trend_continuation", "bullish", timeframe, quality, volume_label,
            trigger=ema20, invalidation=min(lows[-4:]), target=max(highs),
            evidence=[
                "recent lows are forming higher-low structure",
                "latest close reclaimed short-term moving average",
                f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
            ],
            risk="Trend continuation weakens if the higher low is lost.",
        )]
    return []


def detect_lower_high_rejection(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, indicators, micro = tf["raw"], tf["indicators"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=12)
    closes = _to_float_list(raw.get("closes"), limit=12)
    lows = _to_float_list(raw.get("lows"), limit=12)
    if len(highs) < 6 or len(closes) < 6:
        return []
    ema20 = _to_float(indicators.get("ema_20"), 0.0)
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    lower_high = max(highs[-3:]) < max(highs[-8:-4]) if len(highs) >= 8 else False
    rejection = ema20 > 0 and highs[-1] >= ema20 * 0.998 and closes[-1] < ema20
    if lower_high and rejection:
        quality = 55 + (8 if volume_label in {"strong", "moderate"} else 0)
        return [_pattern(
            "lower_high_rejection", "trend_warning", "bearish", timeframe, quality, volume_label,
            trigger=ema20, invalidation=max(highs[-3:]), target=min(lows),
            evidence=[
                "lower-high structure detected",
                "latest candle rejected near short-term moving average",
                f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}",
            ],
            risk="Avoid spot-long entries until lower-high structure is invalidated.",
        )]
    return []


def detect_triangle_or_wedge_family(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    highs = _to_float_list(raw.get("highs"), limit=20)
    lows = _to_float_list(raw.get("lows"), limit=20)
    closes = _to_float_list(raw.get("closes"), limit=20)
    if len(highs) < 12 or len(lows) < 12 or len(closes) < 12:
        return []

    early_high = max(highs[:6])
    late_high = max(highs[-6:])
    early_low = min(lows[:6])
    late_low = min(lows[-6:])
    high_slope = (late_high - early_high) / early_high if early_high else 0.0
    low_slope = (late_low - early_low) / early_low if early_low else 0.0
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    patterns: List[ChartPattern] = []

    flat_resistance = abs(high_slope) <= 0.01
    flat_support = abs(low_slope) <= 0.01
    rising_support = low_slope > 0.008
    falling_resistance = high_slope < -0.008
    rising_resistance = high_slope > 0.008
    falling_support = low_slope < -0.008

    resistance = max(highs[-10:])
    support = min(lows[-10:])

    if flat_resistance and rising_support:
        quality = 48 + (8 if volume_label in {"weak", "moderate"} else 0)
        patterns.append(_pattern(
            "ascending_triangle", "triangle", "bullish", timeframe, quality, volume_label,
            trigger=resistance, invalidation=support, target=resistance + (resistance - support),
            evidence=["flat resistance with rising lows", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Pattern remains only a watch candidate until resistance is accepted.",
        ))
    if flat_support and falling_resistance:
        quality = 48 + (8 if volume_label in {"weak", "moderate"} else 0)
        patterns.append(_pattern(
            "descending_triangle", "triangle", "bearish", timeframe, quality, volume_label,
            trigger=support, invalidation=resistance, target=support - (resistance - support),
            evidence=["flat support with falling highs", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Spot-long entries are vulnerable unless falling resistance is reclaimed.",
        ))
    if falling_resistance and rising_support:
        quality = 45 + (8 if volume_label in {"weak", "moderate"} else 0)
        patterns.append(_pattern(
            "symmetrical_triangle", "triangle", "neutral", timeframe, quality, volume_label,
            trigger=resistance, invalidation=support, target=None,
            evidence=["converging highs and lows", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Direction is unresolved; wait for acceptance outside the triangle.",
        ))
    if rising_resistance and rising_support and high_slope > low_slope:
        quality = 43
        patterns.append(_pattern(
            "rising_wedge", "wedge", "bearish", timeframe, quality, volume_label,
            trigger=support, invalidation=resistance, target=min(lows),
            evidence=["rising highs and lows with widening/weakening structure", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Rising wedge is a warning against late chasing.",
        ))
    if falling_resistance and falling_support and abs(high_slope) > abs(low_slope):
        quality = 43
        patterns.append(_pattern(
            "falling_wedge", "wedge", "bullish", timeframe, quality, volume_label,
            trigger=resistance, invalidation=support, target=max(highs),
            evidence=["falling highs and lows with compression", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Falling wedge needs a reclaim/trigger before it is actionable.",
        ))
    return patterns


def detect_flag_family(feature_pack: Dict[str, Any], timeframe: str = "1h") -> List[ChartPattern]:
    tf = _get_tf_context(feature_pack or {}, timeframe)
    raw, micro = tf["raw"], tf["micro"]
    closes = _to_float_list(raw.get("closes"), limit=24)
    highs = _to_float_list(raw.get("highs"), limit=24)
    lows = _to_float_list(raw.get("lows"), limit=24)
    if len(closes) < 14:
        return []
    impulse = (closes[-8] - closes[-14]) / closes[-14] if closes[-14] else 0.0
    consolidation = (closes[-1] - closes[-8]) / closes[-8] if closes[-8] else 0.0
    recent_range = (max(highs[-8:]) - min(lows[-8:])) / closes[-1] if closes[-1] else 0.0
    volume_label, volume_vs_avg = _volume_confirmation(raw, micro)
    patterns: List[ChartPattern] = []
    if impulse >= 0.035 and abs(consolidation) <= 0.025 and recent_range <= 0.06:
        quality = 50 + (8 if volume_label in {"weak", "moderate"} else 0)
        patterns.append(_pattern(
            "bull_flag", "flag", "bullish", timeframe, quality, volume_label,
            trigger=max(highs[-8:]), invalidation=min(lows[-8:]), target=max(highs[-8:]) + (closes[-8] - closes[-14]),
            evidence=["bullish impulse followed by tight consolidation", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Bull flag is premature without breakout from consolidation.",
        ))
    if impulse <= -0.035 and abs(consolidation) <= 0.025 and recent_range <= 0.06:
        quality = 50 + (8 if volume_label in {"weak", "moderate"} else 0)
        patterns.append(_pattern(
            "bear_flag", "flag", "bearish", timeframe, quality, volume_label,
            trigger=min(lows[-8:]), invalidation=max(highs[-8:]), target=min(lows[-8:]) - abs(closes[-8] - closes[-14]),
            evidence=["bearish impulse followed by tight consolidation", f"volume_confirmation={volume_label} volume_vs_avg={volume_vs_avg}"],
            risk="Bear flag argues against spot-long entries until invalidated.",
        ))
    return patterns


def _pattern_bias(patterns: List[PatternDict]) -> str:
    bullish = sum(p.get("quality", 0) for p in patterns if p.get("direction") == "bullish")
    bearish = sum(p.get("quality", 0) for p in patterns if p.get("direction") == "bearish")
    if bullish >= bearish + 15 and bullish >= 45:
        return "bullish"
    if bearish >= bullish + 15 and bearish >= 45:
        return "bearish"
    return "neutral"


def _summary(patterns: List[PatternDict], market_structure: Dict[str, Any]) -> str:
    if not patterns:
        pos = market_structure.get("range_position", "unknown")
        vol = market_structure.get("volume_confirmation", "unknown")
        return f"No high-quality chart pattern detected. Market structure: {pos}, volume confirmation: {vol}."
    best = patterns[0]
    return (
        f"Best pattern: {best.get('type')} ({best.get('direction')}, quality={best.get('quality')}, "
        f"confirmation={best.get('confirmation')}). Market structure: "
        f"{market_structure.get('range_position', 'unknown')}, "
        f"volume={market_structure.get('volume_confirmation', 'unknown')}."
    )


def build_chart_pattern_context(feature_pack: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build deterministic, JSON-safe chart-pattern context for analysts and judge.

    The output is deliberately advisory. It should be treated as structured technical
    evidence, not as an order signal. Missing or malformed feature fields return a
    neutral context instead of raising, so live trading flow cannot crash on this layer.
    """
    try:
        if not isinstance(feature_pack, dict):
            raise TypeError("feature_pack_not_dict")

        timeframes = ["1h", "4h"]
        detected: List[ChartPattern] = []
        for timeframe in timeframes:
            detected.extend(detect_support_sweep_reclaim(feature_pack, timeframe))
            detected.extend(detect_breakout_retest(feature_pack, timeframe))
            detected.extend(detect_failed_breakout(feature_pack, timeframe))
            detected.extend(detect_compression_squeeze(feature_pack, timeframe))
            detected.extend(detect_range_midpoint_rejection(feature_pack, timeframe))
            detected.extend(detect_double_bottom(feature_pack, timeframe))
            detected.extend(detect_double_top(feature_pack, timeframe))
            detected.extend(detect_higher_low_reclaim(feature_pack, timeframe))
            detected.extend(detect_lower_high_rejection(feature_pack, timeframe))
            detected.extend(detect_triangle_or_wedge_family(feature_pack, timeframe))
            detected.extend(detect_flag_family(feature_pack, timeframe))

        patterns = [p.to_dict() for p in detected]
        patterns.sort(key=lambda p: int(p.get("quality", 0)), reverse=True)
        patterns = patterns[:8]
        market_structure = build_market_structure_context(feature_pack, "1h")
        best_score = int(patterns[0].get("quality", 0)) if patterns else 0
        bias = _pattern_bias(patterns)

        return {
            "enabled": True,
            "source": "deterministic_chart_patterns_v1b",
            "patterns": patterns,
            "market_structure": market_structure,
            "best_pattern_score": best_score,
            "pattern_bias": bias,
            "summary": _summary(patterns, market_structure),
            "analyst_instructions": [
                "Treat deterministic patterns as technical hints, not truth.",
                "Analyst may identify additional patterns only with concrete evidence.",
                "No pattern may directly trigger a trade without planner/judge/risk validation.",
            ],
        }
    except Exception as exc:
        return {
            "enabled": False,
            "source": "deterministic_chart_patterns_v1b",
            "patterns": [],
            "market_structure": {
                "timeframe": "1h",
                "range_position": "unknown",
                "support_level": None,
                "resistance_level": None,
                "distance_to_support_pct": None,
                "distance_to_resistance_pct": None,
                "breakout_status": "unknown",
                "volume_confirmation": "unknown",
                "volume_vs_avg": 0.0,
                "current_price": None,
                "recent_high": None,
                "recent_low": None,
            },
            "best_pattern_score": 0,
            "pattern_bias": "neutral",
            "summary": "Chart-pattern context unavailable; continue with neutral pattern context.",
            "error": str(exc),
        }
