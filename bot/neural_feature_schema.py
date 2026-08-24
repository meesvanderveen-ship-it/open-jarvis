from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.neural_reward_model import calculate_neural_reward


DATASET_PATH = Path("reports/live_learning/neural-training-dataset-latest.jsonl")
DATASET_SUMMARY_PATH = Path("reports/live_learning/neural-training-dataset-summary-latest.json")

NUMERIC_FEATURES = [
    "gate_confidence",
    "spread_pct",
    "orderbook_imbalance",
    "rsi_15m",
    "rsi_1h",
    "adx_1h",
    "ema_4h_alignment",
    "ema_1d_alignment",
    "price_to_support_pct",
    "price_to_resistance_pct",
    "volume_vs_avg",
    "d2_net_edge_pct",
    "reward_to_risk",
    "reward_to_fee",
]
CATEGORICAL_FEATURES = ["gate", "judge_decision", "setup_type", "learning_context_classification"]
BOOLEAN_FEATURES = ["pending_trigger_ready"]
PREDICTION_CLASSES = [
    "wait",
    "watch",
    "analyze",
    "prefer_limit_buy",
    "avoid_chase",
    "prefer_pullback",
    "prefer_no_trade",
    "missed_opportunity",
    "bad_wait",
    "good_wait",
    "good_entry_candidate",
    "bad_entry_candidate",
    "good_probe_candidate",
    "bad_probe_candidate",
    "correct_avoid",
    "false_positive_plan",
    "trigger_ready_but_waited",
    "planner_no_plan_missed_move",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def as_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(Decimal(str(value)))
    except (InvalidOperation, ValueError):
        return None


def as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "ready"}


def deep_get(payload: Any, paths: Iterable[Tuple[Any, ...]], default: Any = None) -> Any:
    for path in paths:
        node = payload
        ok = True
        for key in path:
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                ok = False
                break
        if ok and node not in (None, ""):
            return node
    return default


def _alignment(value: Any) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text in {"bull", "bullish", "up", "positive", "aligned_bullish"}:
        return 1
    if text in {"bear", "bearish", "down", "negative", "aligned_bearish"}:
        return -1
    if text in {"flat", "mixed", "neutral", "range"}:
        return 0
    number = as_float(value)
    if number is None:
        return None
    return 1 if number > 0 else (-1 if number < 0 else 0)


def _ema_alignment_from(fp: Dict[str, Any], timeframe: str) -> Optional[int]:
    """Classic 50/200 EMA alignment (+1 bull, -1 bear, 0 flat).

    The feature pack does not expose a precomputed ``ema_alignment`` key — only the
    raw ``ema_50``/``ema_200`` per timeframe (bot/market_data.py). The old schema read
    a non-existent ``indicators.<tf>.ema_alignment`` path and always got None, so this
    derives it from the values that actually exist.
    """
    e50 = as_float(deep_get(fp, [("indicators", timeframe, "ema_50"), ("raw_context", timeframe, "ema_50")], None))
    e200 = as_float(deep_get(fp, [("indicators", timeframe, "ema_200"), ("raw_context", timeframe, "ema_200")], None))
    if e50 is None or e200 is None:
        return None
    return 1 if e50 > e200 else (-1 if e50 < e200 else 0)


def canonical_features(source: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(source.get("features"), dict):
        return {name: source["features"].get(name) for name in [*CATEGORICAL_FEATURES, *BOOLEAN_FEATURES, *NUMERIC_FEATURES]}
    fp = source.get("feature_pack") if isinstance(source.get("feature_pack"), dict) else source
    decision_context = fp.get("decision_context") if isinstance(fp.get("decision_context"), dict) else {}
    risk = fp.get("risk_context") if isinstance(fp.get("risk_context"), dict) else {}
    market = fp.get("market") if isinstance(fp.get("market"), dict) else {}
    indicators = fp.get("indicators") if isinstance(fp.get("indicators"), dict) else {}
    orderbook = fp.get("orderbook_context") if isinstance(fp.get("orderbook_context"), dict) else {}
    raw = fp.get("raw_context") if isinstance(fp.get("raw_context"), dict) else {}
    entry_gate = fp.get("entry_gate") if isinstance(fp.get("entry_gate"), dict) else risk.get("entry_gate") if isinstance(risk.get("entry_gate"), dict) else {}
    pending = decision_context.get("pending_order_intent") if isinstance(decision_context.get("pending_order_intent"), dict) else {}
    learning = decision_context.get("live_learning") if isinstance(decision_context.get("live_learning"), dict) else {}

    return {
        "gate": str(deep_get(source, [("entry_gate", "decision"), ("gate",), ("decision",)], entry_gate.get("decision") or "unknown")).lower(),
        "gate_confidence": as_float(deep_get(source, [("entry_gate", "confidence"), ("confidence",)], entry_gate.get("confidence"))),
        "judge_decision": str(deep_get(source, [("judge", "decision"), ("analysis", "judge", "decision"), ("decision",)], "unknown")).lower(),
        "setup_type": str(deep_get(source, [("trade_plan", "setup_type"), ("analysis", "trade_plan", "setup_type"), ("setup_type",)], entry_gate.get("setup_type") or "unclear")).lower(),
        "pending_trigger_ready": as_bool(pending.get("trigger_ready") or pending.get("should_force_full_analysis")),
        "spread_pct": as_float(deep_get(fp, [("spread_pct",), ("market", "spread_pct"), ("orderbook_context", "spread_pct")], market.get("spread_pct"))),
        "orderbook_imbalance": as_float(deep_get(fp, [("orderbook_context", "imbalance"), ("orderbook_context", "orderbook_imbalance"), ("market", "orderbook_imbalance")], orderbook.get("imbalance"))),
        "rsi_15m": as_float(deep_get(fp, [("indicators", "15m", "rsi_14"), ("raw_context", "15m", "rsi_14"), ("indicators", "15m", "rsi")], None)),
        "rsi_1h": as_float(deep_get(fp, [("indicators", "1h", "rsi_14"), ("raw_context", "1h", "rsi_14"), ("indicators", "1h", "rsi")], None)),
        "adx_1h": as_float(deep_get(fp, [("indicators", "1h", "adx_14"), ("raw_context", "1h", "adx_14"), ("indicators", "1h", "adx")], None)),
        "ema_4h_alignment": _ema_alignment_from(fp, "4h"),
        "ema_1d_alignment": _ema_alignment_from(fp, "1d"),
        "price_to_support_pct": as_float(deep_get(fp, [("structure", "price_to_support_pct"), ("market_structure", "price_to_support_pct")], None)),
        "price_to_resistance_pct": as_float(deep_get(fp, [("structure", "price_to_resistance_pct"), ("market_structure", "price_to_resistance_pct")], None)),
        "volume_vs_avg": as_float(deep_get(fp, [("indicators", "1h", "volume_vs_avg"), ("raw_context", "1h", "volume_vs_avg")], None)),
        "learning_context_classification": str(learning.get("classification") or decision_context.get("learning_context_classification") or "WATCH"),
        "d2_net_edge_pct": as_float(deep_get(source, [("d2", "expected_net_edge_pct"), ("execution", "expected_net_edge_pct"), ("expected_net_edge_pct",)], None)),
        "reward_to_risk": as_float(deep_get(source, [("d2", "reward_to_risk"), ("reward_to_risk",)], None)),
        "reward_to_fee": as_float(deep_get(source, [("d2", "reward_to_fee"), ("reward_to_fee",)], None)),
    }


def infer_action_taken(source: Dict[str, Any]) -> str:
    for path in [("action_taken",), ("action",), ("cycle_result", "action"), ("judge", "decision"), ("entry_gate", "decision")]:
        value = deep_get(source, [path], None)
        if value:
            text = str(value).strip().lower()
            if text in {"approve_trade", "buy", "place_limit_buy"}:
                return "place_limit_buy"
            if text in {"watch", "skip", "wait", "analyze"}:
                return text
    return "wait"


def infer_action_candidate(source: Dict[str, Any]) -> str:
    plan_action = str(deep_get(source, [("trade_plan", "plan_action"), ("analysis", "trade_plan", "plan_action")], "") or "").lower()
    if "buy" in plan_action or "reclaim" in plan_action or "breakout" in plan_action:
        return "place_limit_buy"
    return str(source.get("action_candidate") or "wait")


def infer_outcome(source: Dict[str, Any]) -> Dict[str, Any]:
    raw = source.get("outcome") if isinstance(source.get("outcome"), dict) else source
    return {
        "filled": as_bool(deep_get(raw, [("filled",), ("fill",), ("order_filled",)], False)),
        "missed_opportunity": as_bool(deep_get(raw, [("missed_opportunity",), ("missed",), ("is_missed_opportunity",)], False)),
        "adverse_move": as_bool(deep_get(raw, [("adverse_move",), ("adverse",), ("clear_adverse_move",)], False)),
        "realized_pnl_pct": as_float(deep_get(raw, [("realized_pnl_pct",), ("pnl_pct",)], None)),
        "max_favorable_move_pct": as_float(deep_get(raw, [("max_favorable_move_pct",), ("mfe_pct",), ("favorable_move_pct",)], None)),
        "max_adverse_move_pct": as_float(deep_get(raw, [("max_adverse_move_pct",), ("mae_pct",), ("adverse_move_pct",)], None)),
        "stop_breach": as_bool(deep_get(raw, [("stop_breach",), ("stop_breached",)], False)),
    }


def prediction_class_for_sample(sample: Dict[str, Any]) -> str:
    reward_raw = sample.get("reward")
    if isinstance(reward_raw, dict):
        reward_raw = reward_raw.get("reward") or reward_raw.get("score") or reward_raw.get("value")
    reward = float(reward_raw or 0.0)
    features = sample.get("features") if isinstance(sample.get("features"), dict) else {}
    pending_plan = sample.get("pending_trade_plan") if isinstance(sample.get("pending_trade_plan"), dict) else {}
    if pending_plan.get("trigger_ready"):
        features = {**features, "pending_trigger_ready": True}
    outcome = sample.get("outcome") if isinstance(sample.get("outcome"), dict) else {}
    reward_obj = sample.get("reward") if isinstance(sample.get("reward"), dict) else {}
    if str(reward_obj.get("label") or "").lower() == "missed_opportunity":
        outcome = {**outcome, "missed_opportunity": True}
    action = str(sample.get("action_taken") or sample.get("decision") or "").lower()
    candidate = str(sample.get("action_candidate") or "").lower()
    if outcome.get("adverse_move") or outcome.get("stop_breach") or reward <= -0.75:
        if candidate == "place_limit_buy":
            return "bad_entry_candidate"
        return "avoid_chase"
    if outcome.get("missed_opportunity") and action in {"wait", "watch", "skip"}:
        if features.get("pending_trigger_ready"):
            return "trigger_ready_but_waited"
        if "no_plan" in str(deep_get(sample, [("source_reason",), ("reason",)], "")).lower():
            return "planner_no_plan_missed_move"
        return "missed_opportunity"
    if reward >= 0.75 and (action == "place_limit_buy" or candidate == "place_limit_buy"):
        entry_mode = str(deep_get(sample, [("entry_mode",), ("features", "entry_mode")], "") or "").lower()
        return "good_probe_candidate" if "starter" in entry_mode or "probe" in entry_mode else "good_entry_candidate"
    if features.get("pending_trigger_ready") and reward >= 0:
        return "prefer_pullback"
    if reward >= 0.25 and action in {"wait", "skip"}:
        return "correct_avoid" if outcome.get("adverse_move") else "good_wait"
    if reward <= -0.25 and candidate == "place_limit_buy":
        return "false_positive_plan"
    if action == "watch":
        return "watch"
    return "wait"


def build_sample(source: Dict[str, Any], *, source_name: str, index: int, created_at: Optional[str] = None) -> Dict[str, Any]:
    ticker = str(deep_get(source, [("ticker",), ("product_id",), ("feature_pack", "ticker"), ("market", "ticker")], "BTC-USDC") or "BTC-USDC").upper()
    features = canonical_features(source)
    sample = {
        "sample_id": hashlib.sha256(f"{source_name}:{index}:{json.dumps(source, sort_keys=True, default=str)[:2000]}".encode("utf-8")).hexdigest()[:24],
        "created_at": created_at or str(source.get("generated_at") or source.get("created_at") or now_iso()),
        "ticker": ticker,
        "cycle_type": str(source.get("cycle_type") or source.get("source") or "full"),
        "features": features,
        "action_taken": infer_action_taken(source),
        "action_candidate": infer_action_candidate(source),
        "outcome": infer_outcome(source),
    }
    reward = calculate_neural_reward(sample)
    sample["reward"] = reward.reward
    sample["reward_reasons"] = reward.reward_reasons
    sample["target_class"] = prediction_class_for_sample(sample)
    return sample


def encode_features(features: Dict[str, Any], categories: Optional[Dict[str, List[str]]] = None) -> List[float]:
    vector: List[float] = []
    for name in NUMERIC_FEATURES:
        value = as_float(features.get(name))
        vector.append(0.0 if value is None else float(value))
    for name in BOOLEAN_FEATURES:
        vector.append(1.0 if as_bool(features.get(name)) else 0.0)
    for name in CATEGORICAL_FEATURES:
        value = str(features.get(name) or "unknown").lower()
        choices = (categories or {}).get(name) or ["unknown"]
        vector.extend([1.0 if value == choice else 0.0 for choice in choices])
    return vector


def build_categories(rows: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    values: Dict[str, set[str]] = {name: {"unknown"} for name in CATEGORICAL_FEATURES}
    for row in rows:
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        for name in CATEGORICAL_FEATURES:
            values[name].add(str(features.get(name) or "unknown").lower())
    return {name: sorted(v) for name, v in values.items()}


__all__ = [
    "BOOLEAN_FEATURES",
    "CATEGORICAL_FEATURES",
    "DATASET_PATH",
    "DATASET_SUMMARY_PATH",
    "NUMERIC_FEATURES",
    "PREDICTION_CLASSES",
    "build_categories",
    "build_sample",
    "canonical_features",
    "encode_features",
    "prediction_class_for_sample",
]
