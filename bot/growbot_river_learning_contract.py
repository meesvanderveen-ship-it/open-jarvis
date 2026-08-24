"""Immutable, whitelisted learning context for the report-only sidecar.

The regular runtime may retain large feature packs and LLM payloads.  The
GrowBot/River sidecar neither needs nor is allowed to copy those payloads into
its append-only evidence logs.  This module extracts a small numeric snapshot
at the time a decision or paper execution outcome is recorded.

It has no imports from execution, C4.3, D3, configuration or profile-apply
code.  Producing a snapshot grants no authority to train, propose, apply or
execute anything.
"""
from __future__ import annotations

import math
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


LEARNING_CONTEXT_SCHEMA_VERSION = "growbot_river_learning_context_v3"
UNKNOWN_REGIME_VALUES = {"", "unknown", "none", "null", "n/a", "na"}
ALLOWED_STATE_KEYS = (
    "confidence",
    "d2_net_edge_pct",
    "expected_net_edge_pct",
    "reward_to_fee",
    "reward_to_risk",
    "spread_pct",
    "volatility_pct",
    "ticker_score",
    "volume_ratio",
    "trend_strength",
    # trend_strength above is a price-change ratio (end-start)/start over the
    # candle window -- it captures direction and magnitude of the move, but
    # nothing about whether that move is part of a genuine trend or just chop
    # (a market can have near-zero trend_strength while still being firmly
    # directionless, or vice versa). adx_1h (Average Directional Index, 1h
    # timeframe) fills that specific gap: it measures trend *conviction*
    # independent of direction. Added 2026-07-08 after a live SOL-USDC loss
    # review found this exact factor present (1h ADX ~10.9, i.e. a weak/
    # choppy market) but untracked anywhere in the learning state -- the bear
    # case at entry explicitly flagged it, but nothing fed it back into
    # evidence that accumulates across trades. This is additive only: no
    # gating logic reads it yet, it just becomes available for the online
    # River model to weigh once enough episodes carry it.
    "adx_1h",
    "liquidity_score",
    "orderbook_imbalance",
    "fee_pct",
    "slippage_pct",
    "mfe_pct",
    "mae_pct",
    "drawdown_pct",
    "exit_efficiency_proxy",
)
REGIME_CONTEXT_KEYS = (
    "adaptive_market_regime",
    "market_regime",
    "trend_regime",
    "volatility_regime",
    "liquidity_regime",
    "network_regime",
)
# Compact, non-numeric episode context.  Free text (reasons, blockers, prompts)
# is never allowlisted here; only short categorical labels are.
ALLOWED_CONTEXT_KEYS = ("ticker", "setup_type", "fill_status", "exit_result")
MAX_CONTEXT_TEXT_LEN = 48

# A minimal, source-agnostic regime taxonomy used only as a last-resort
# classifier when no explicit regime tag is available anywhere in the
# evidence.  It never overrides an explicit/historical regime string.
CANONICAL_REGIMES = (
    "trend_up",
    "trend_down",
    "range_chop",
    "high_volatility",
    "low_volatility",
    "drawdown_risk_off",
    "unknown",
)


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_finite_number(value: Any) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _at_path(sources: Sequence[Mapping[str, Any]], path: Sequence[str]) -> Any:
    for source in sources:
        node: Any = source
        for key in path:
            if not isinstance(node, Mapping) or key not in node:
                node = None
                break
            node = node[key]
        if node not in (None, ""):
            return node
    return None


def _first_number(sources: Sequence[Mapping[str, Any]], paths: Iterable[Sequence[str]]) -> float | None:
    for path in paths:
        value = _as_finite_number(_at_path(sources, path))
        if value is not None:
            return value
    return None


def _first_text(sources: Sequence[Mapping[str, Any]], paths: Iterable[Sequence[str]]) -> str:
    for path in paths:
        for source in sources:
            node: Any = source
            for key in path:
                if not isinstance(node, Mapping) or key not in node:
                    node = None
                    break
                node = node[key]
            if isinstance(node, Mapping):
                # The regime module (bot/strategy_engine.py's "regime" analysis
                # step) returns a dict ({"regime_label", "regime_confidence",
                # "regime_strength", ...}), not a plain string. Extract the
                # label instead of stringifying the whole dict, which used to
                # produce a garbled, useless tag like
                # "{'regime_label':_'mixed',_'regime_confidence':_0.86,_...}".
                node = node.get("regime_label")
            text = str(node or "").strip().lower().replace(" ", "_")
            if text and text not in UNKNOWN_REGIME_VALUES:
                return text
    return "unknown"


def _first_short_text(sources: Sequence[Mapping[str, Any]], paths: Iterable[Sequence[str]], *, max_len: int = MAX_CONTEXT_TEXT_LEN) -> str:
    """Return the first short, compact label found at any path.

    Unlike ``_first_text`` this is not regime-specific: it is used for small
    categorical episode context (ticker, setup type, fill status, exit
    result) and rejects values that look like free text rather than a label.
    """
    for path in paths:
        value = _at_path(sources, path)
        if value in (None, ""):
            continue
        text = str(value).strip().lower().replace(" ", "_")
        if not text or text in UNKNOWN_REGIME_VALUES or len(text) > max_len or " " in text:
            continue
        return text
    return ""


def _candle_ohlc(candle: Any) -> tuple[Optional[float], Optional[float], Optional[float]]:
    if isinstance(candle, Mapping):
        high = _as_finite_number(candle.get("high") if candle.get("high") is not None else candle.get("h"))
        low = _as_finite_number(candle.get("low") if candle.get("low") is not None else candle.get("l"))
        close = _as_finite_number(candle.get("close") if candle.get("close") is not None else candle.get("c"))
        return high, low, close
    if isinstance(candle, (list, tuple)) and len(candle) >= 5:
        return _as_finite_number(candle[2]), _as_finite_number(candle[3]), _as_finite_number(candle[4])
    return None, None, None


def derive_regime_metrics_from_candles(candles: Sequence[Any]) -> Dict[str, float]:
    """Derive a compact, source-time trend/volatility/drawdown signal.

    This only looks at candles already available at the time the snapshot is
    captured (e.g. the recent history embedded in a feature_pack, or a
    lookback window ending at a decision time).  It never consumes data from
    after the moment being described, so it carries no hindsight leakage.
    """
    highs: List[float] = []
    lows: List[float] = []
    closes: List[float] = []
    for candle in candles:
        high, low, close = _candle_ohlc(candle)
        if high is not None:
            highs.append(high)
        if low is not None:
            lows.append(low)
        if close is not None:
            closes.append(close)
    if len(closes) < 2:
        return {}
    metrics: Dict[str, float] = {}
    start, end = closes[0], closes[-1]
    if start > 0:
        metrics["trend_strength"] = round((end - start) / start, 10)
    avg_close = sum(closes) / len(closes)
    if highs and lows and avg_close > 0:
        metrics["volatility_pct"] = round((max(highs) - min(lows)) / avg_close, 10)
    peak = closes[0]
    max_drawdown = 0.0
    for value in closes:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, (value - peak) / peak)
    metrics["drawdown_pct"] = round(max_drawdown, 10)
    return metrics


def classify_compact_regime_from_metrics(
    *,
    trend_strength: Optional[float] = None,
    volatility_pct: Optional[float] = None,
    drawdown_pct: Optional[float] = None,
    trend_threshold: float = 0.012,
    high_volatility_threshold: float = 0.030,
    low_volatility_threshold: float = 0.006,
    drawdown_threshold: float = 0.05,
) -> str:
    """Bucket compact numeric evidence into the canonical regime taxonomy.

    This is a last-resort classifier only: it never overrides an explicit or
    historical regime tag.  Priority order (drawdown > high-vol > trend >
    low-vol > chop) is a deliberate, documented design choice, not a
    statistically fit model.
    """
    if drawdown_pct is not None and drawdown_pct <= -drawdown_threshold:
        return "drawdown_risk_off"
    if volatility_pct is not None and volatility_pct >= high_volatility_threshold:
        return "high_volatility"
    if trend_strength is not None:
        if trend_strength >= trend_threshold:
            return "trend_up"
        if trend_strength <= -trend_threshold:
            return "trend_down"
    if volatility_pct is not None and volatility_pct <= low_volatility_threshold:
        return "low_volatility"
    if trend_strength is not None or volatility_pct is not None:
        return "range_chop"
    return "unknown"


def _feature_sources(feature_pack: Mapping[str, Any], decision_context: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    feature = _as_dict(feature_pack)
    decision = _as_dict(decision_context)
    return [
        decision,
        _as_dict(decision.get("judge")),
        _as_dict(decision.get("entry_gate")),
        _as_dict(decision.get("trade_plan")),
        _as_dict(decision.get("d2")),
        _as_dict(decision.get("market_intelligence")),
        feature,
        _as_dict(feature.get("market")),
        _as_dict(feature.get("orderbook_context")),
        _as_dict(feature.get("microstructure")),
        _as_dict(feature.get("indicators")),
        _as_dict(feature.get("ticker")),
    ]


def _normalized_regime(value: Any) -> str:
    text = str(value or "").strip().lower().replace(" ", "_")
    return text if text and text not in UNKNOWN_REGIME_VALUES else "unknown"


def sanitize_learning_context_snapshot(snapshot: Mapping[str, Any] | None) -> Dict[str, Any]:
    """Canonicalize a stored snapshot before it enters another evidence layer.

    This is intentionally lossy.  It prevents an unexpected field in a local
    reflection/report file from becoming an append-only GrowBot/River input.
    """
    raw = _as_dict(snapshot)
    raw_state = _as_dict(raw.get("state"))
    state: Dict[str, float] = {}
    for key in ALLOWED_STATE_KEYS:
        value = _as_finite_number(raw_state.get(key))
        if value is not None:
            state[key] = round(value, 10)
    raw_regimes = _as_dict(raw.get("regime_context"))
    regime_context = {key: _normalized_regime(raw_regimes.get(key)) for key in REGIME_CONTEXT_KEYS}
    regime = _normalized_regime(raw.get("regime"))
    if regime == "unknown":
        regime = next(
            (regime_context[key] for key in ("adaptive_market_regime", "market_regime", "trend_regime") if regime_context[key] != "unknown"),
            "unknown",
        )
    if regime == "unknown":
        # Last resort only: no explicit/historical regime tag exists anywhere.
        # Bucket whatever compact numeric evidence is available into the
        # canonical taxonomy instead of leaving every such episode unknown.
        regime = classify_compact_regime_from_metrics(
            trend_strength=state.get("trend_strength"),
            volatility_pct=state.get("volatility_pct"),
            drawdown_pct=state.get("drawdown_pct"),
        )
    raw_context = _as_dict(raw.get("context"))
    context = {key: _first_short_text([raw_context], [(key,)]) for key in ALLOWED_CONTEXT_KEYS}
    return {
        "schema_version": LEARNING_CONTEXT_SCHEMA_VERSION,
        "captured_at_source_time": raw.get("captured_at_source_time") is True,
        "state": state,
        "regime": regime,
        "regime_context": regime_context,
        "context": context,
        "data_policy": {
            "allowlisted_fields_only": True,
            "raw_feature_pack_copied": False,
            "llm_prompt_or_response_copied": False,
            "execution_authority": False,
            "parameter_mutation_authority": False,
        },
    }


def build_learning_context_snapshot(
    feature_pack: Mapping[str, Any] | None = None,
    decision_context: Mapping[str, Any] | None = None,
    *,
    candles: Sequence[Any] | None = None,
) -> Dict[str, Any]:
    """Return a compact source-time snapshot safe for append-only evidence.

    Only an explicit allowlist of numeric features and regime dimensions is
    emitted.  Raw feature packs, prompts, order identifiers, account values,
    API credentials and arbitrary nested values are never copied.

    ``candles`` is optional and, when given, must already be bounded to data
    available at source time (e.g. a feature_pack's recent history, or a
    lookback window ending at a decision time).  It is used only to derive a
    compact trend/volatility/drawdown signal when the caller has not already
    supplied one explicitly.
    """
    feature = _as_dict(feature_pack)
    decision = _as_dict(decision_context)
    sources = _feature_sources(feature, decision)
    state_paths = {
        "confidence": (("confidence",),),
        "d2_net_edge_pct": (("d2_net_edge_pct",), ("net_edge_pct",), ("expected_net_edge_pct",), ("estimated_net_after_cost_opportunity_pct",)),
        "expected_net_edge_pct": (("expected_net_edge_pct",), ("net_edge_pct",), ("d2_net_edge_pct",), ("estimated_net_after_cost_opportunity_pct",)),
        "reward_to_fee": (("reward_to_fee",), ("reward_fee_ratio",), ("expected_reward_to_fee",)),
        "reward_to_risk": (("reward_to_risk",), ("reward_risk_ratio",), ("expected_reward_to_risk",)),
        "spread_pct": (("spread_pct",), ("estimated_spread_cost_pct",)),
        "volatility_pct": (("volatility_pct",), ("realized_volatility_pct",), ("atr_pct",)),
        "ticker_score": (("ticker_score",), ("score",)),
        "volume_ratio": (("volume_ratio",), ("relative_volume",)),
        "trend_strength": (("trend_strength",),),
        # Flat "adx_1h" first (already-normalized callers, e.g. neural_feature_schema
        # samples), then the raw feature_pack's nested indicators.1h.adx_14 shape
        # (bot/strategy_engine.py's actual live feature pack -- confirmed against
        # logs/analysis.jsonl for the 2026-07-07 SOL-USDC entry).
        "adx_1h": (("adx_1h",), ("indicators", "1h", "adx_14")),
        "liquidity_score": (("liquidity_score",),),
        "orderbook_imbalance": (("orderbook_imbalance",), ("imbalance",)),
        "fee_pct": (("fee_pct",), ("estimated_roundtrip_fee_pct",), ("roundtrip_fee_pct",)),
        "slippage_pct": (("slippage_pct",), ("estimated_slippage_buffer_pct",), ("slippage_buffer_pct",)),
        "mfe_pct": (("mfe_pct",), ("max_favorable_excursion_pct",)),
        "mae_pct": (("mae_pct",), ("max_adverse_excursion_pct",)),
        "drawdown_pct": (("drawdown_pct",),),
    }
    state: Dict[str, float] = {}
    for name, paths in state_paths.items():
        value = _first_number(sources, paths)
        if value is not None:
            state[name] = round(value, 10)

    best_bid = _first_number(sources, (("best_bid",),))
    best_ask = _first_number(sources, (("best_ask",),))
    if "spread_pct" not in state and best_bid is not None and best_ask is not None and best_bid > 0 and best_ask >= best_bid:
        state["spread_pct"] = round((best_ask - best_bid) / ((best_ask + best_bid) / 2.0), 10)

    if candles and not {"trend_strength", "volatility_pct", "drawdown_pct"} <= state.keys():
        for key, value in derive_regime_metrics_from_candles(candles).items():
            state.setdefault(key, value)

    regime_context = {
        "adaptive_market_regime": _first_text(sources, (("adaptive_market_regime",),)),
        "market_regime": _first_text(sources, (("market_regime",), ("regime",))),
        "trend_regime": _first_text(sources, (("trend_regime",), ("trend",))),
        "volatility_regime": _first_text(sources, (("volatility_regime",), ("volatility",))),
        "liquidity_regime": _first_text(sources, (("liquidity_regime",),)),
        "network_regime": _first_text(sources, (("network_regime",),)),
    }
    regime = next(
        (value for value in (
            regime_context["adaptive_market_regime"],
            regime_context["market_regime"],
            regime_context["trend_regime"],
        ) if value != "unknown"),
        "unknown",
    )
    context = {
        "ticker": _first_short_text(sources, (("ticker",), ("product_id",))),
        "setup_type": _first_short_text(sources, (("setup_type",),)),
        "fill_status": _first_short_text(sources, (("fill_status",), ("order_status",), ("lifecycle_action",))),
        "exit_result": _first_short_text(sources, (("exit_result",), ("label",), ("outcome_label",))),
    }
    return sanitize_learning_context_snapshot({
        "schema_version": LEARNING_CONTEXT_SCHEMA_VERSION,
        "captured_at_source_time": True,
        "state": state,
        "regime": regime,
        "regime_context": regime_context,
        "context": context,
        "data_policy": {
            "allowlisted_fields_only": True,
            "raw_feature_pack_copied": False,
            "llm_prompt_or_response_copied": False,
            "execution_authority": False,
            "parameter_mutation_authority": False,
        },
    })


__all__ = [
    "LEARNING_CONTEXT_SCHEMA_VERSION",
    "ALLOWED_STATE_KEYS",
    "ALLOWED_CONTEXT_KEYS",
    "CANONICAL_REGIMES",
    "REGIME_CONTEXT_KEYS",
    "UNKNOWN_REGIME_VALUES",
    "build_learning_context_snapshot",
    "classify_compact_regime_from_metrics",
    "derive_regime_metrics_from_candles",
    "sanitize_learning_context_snapshot",
]
