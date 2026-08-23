from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bot.approved_parameter_profile import APPROVED_PARAMETER_PROFILE_WHITELIST
from bot.atomic_io import atomic_write_json
from bot.neural_feature_schema import (
    PREDICTION_CLASSES,
    build_categories,
    canonical_features,
    encode_features,
)


MODEL_VERSION = "neural_shadow_policy_v1"
DEFAULT_MODEL_PATH = Path("state/neural_shadow_policy.json")
DEFAULT_REPORT_PATH = Path("reports/live_learning/neural-shadow-policy-latest.json")
DEFAULT_EVAL_PATH = Path("reports/live_learning/neural-shadow-policy-eval-latest.json")


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def load_jsonl(path: str | Path) -> Tuple[List[Dict[str, Any]], int]:
    rows: List[Dict[str, Any]] = []
    corrupt = 0
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return rows, corrupt
    for line in lines:
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except Exception:
            corrupt += 1
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows, corrupt


def _softmax(scores: Dict[str, float]) -> Dict[str, float]:
    if not scores:
        return {}
    top = max(scores.values())
    exps = {k: math.exp(max(-50.0, min(50.0, v - top))) for k, v in scores.items()}
    total = sum(exps.values()) or 1.0
    return {k: v / total for k, v in exps.items()}


def _top_reasons(features: Dict[str, Any], prediction: str) -> List[str]:
    reasons: List[str] = []
    if features.get("ema_4h_alignment") == -1 or features.get("ema_1d_alignment") == -1:
        reasons.append("4h/1d trend bearish")
    if not features.get("pending_trigger_ready"):
        reasons.append("pending trigger not ready")
    rsi = features.get("rsi_1h")
    if isinstance(rsi, (int, float)) and rsi > 68:
        reasons.append("1h RSI elevated")
    resistance = features.get("price_to_resistance_pct")
    if isinstance(resistance, (int, float)) and resistance < 0.02:
        reasons.append("near resistance")
    spread = features.get("spread_pct")
    if isinstance(spread, (int, float)) and spread > 0.006:
        reasons.append("spread cost elevated")
    if prediction in {"prefer_limit_buy", "prefer_pullback"} and features.get("pending_trigger_ready"):
        reasons.append("pending trigger ready")
    return reasons[:3] or ["model baseline pattern"]


def _parameter_suggestions(rows: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    suggestions: Dict[str, Dict[str, Any]] = {}
    adverse_wide = 0
    missed = 0
    for row in rows:
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        outcome = row.get("outcome") if isinstance(row.get("outcome"), dict) else {}
        spread = features.get("spread_pct")
        if isinstance(spread, (int, float)) and spread > 0.006 and outcome.get("adverse_move"):
            adverse_wide += 1
        if outcome.get("missed_opportunity"):
            missed += 1
    if adverse_wide:
        suggestions["MAX_SPREAD_PCT"] = {
            "suggested": "0.0045",
            "reason": "poor fills/adverse moves at wider spreads",
            "safe_to_apply": False,
        }
    if missed:
        suggestions["PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT"] = {
            "suggested": "0.0100",
            "reason": "missed opportunities observed under current threshold",
            "safe_to_apply": False,
        }
    unknown = sorted(set(suggestions) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if unknown:
        raise ValueError("unknown neural parameter suggestion keys: " + ",".join(unknown))
    return suggestions


def validate_parameter_suggestions(suggestions: Dict[str, Any]) -> None:
    unknown = sorted(set(suggestions) - APPROVED_PARAMETER_PROFILE_WHITELIST)
    if unknown:
        raise ValueError("unknown neural parameter suggestion keys: " + ",".join(unknown))


def train_shadow_policy(
    rows: List[Dict[str, Any]],
    *,
    model_out: str | Path = DEFAULT_MODEL_PATH,
    report_out: str | Path = DEFAULT_REPORT_PATH,
    min_samples: int = 50,
) -> Dict[str, Any]:
    trained_at = _now_iso()
    categories = build_categories(rows)
    counts = Counter(str(row.get("target_class") or "wait") for row in rows)
    sample_count = len(rows)
    status = "trained_shadow_only" if sample_count >= min_samples else "insufficient_samples_shadow_only"

    backend = "pure_python_centroid"
    centroids: Dict[str, List[float]] = {}
    class_counts: Dict[str, int] = {}
    vectors_by_class: Dict[str, List[List[float]]] = defaultdict(list)
    for row in rows:
        target = str(row.get("target_class") or "wait")
        if target not in PREDICTION_CLASSES:
            target = "wait"
        features = row.get("features") if isinstance(row.get("features"), dict) else {}
        vectors_by_class[target].append(encode_features(features, categories))
    for cls in PREDICTION_CLASSES:
        vectors = vectors_by_class.get(cls) or []
        class_counts[cls] = len(vectors)
        if not vectors:
            centroids[cls] = []
            continue
        width = len(vectors[0])
        centroids[cls] = [sum(vec[i] for vec in vectors) / len(vectors) for i in range(width)]

    model = {
        "model_version": MODEL_VERSION,
        "backend": backend,
        "status": status,
        "trained_at": trained_at,
        "sample_count": sample_count,
        "min_samples": int(min_samples),
        "execution_allowed": False,
        "categories": categories,
        "class_counts": class_counts,
        "centroids": centroids,
        "majority_class": counts.most_common(1)[0][0] if counts else "wait",
        "one_class_dataset_warning": len([cls for cls, count in counts.items() if int(count or 0) > 0]) <= 1,
        "neural_shadow_one_class_passivity_bias": bool(
            len([cls for cls, count in counts.items() if int(count or 0) > 0]) == 1
            and int(counts.get("prefer_no_trade", 0)) == sample_count
            and sample_count > 0
        ),
        "balanced_label_recommendation": "bounded exploration needed for balanced labels",
        "parameter_suggestions": _parameter_suggestions(rows),
        "safety_policy": {
            "shadow_only": True,
            "execution_allowed": False,
            "parameter_mutation_allowed": False,
            "approved_profile_route_required": True,
        },
    }
    atomic_write_json(model_out, model)
    report = {
        "phase": MODEL_VERSION,
        "generated_at": trained_at,
        "status": status,
        "backend": backend,
        "sample_count": sample_count,
        "min_samples": int(min_samples),
        "model_path": str(model_out),
        "class_counts": dict(counts),
        "one_class_dataset_warning": len([cls for cls, count in counts.items() if int(count or 0) > 0]) <= 1,
        "neural_shadow_one_class_passivity_bias": bool(
            len([cls for cls, count in counts.items() if int(count or 0) > 0]) == 1
            and int(counts.get("prefer_no_trade", 0)) == sample_count
            and sample_count > 0
        ),
        "balanced_label_recommendation": "bounded exploration needed for balanced labels",
        "parameter_suggestions": model["parameter_suggestions"],
        "execution_allowed": False,
        "read_only_training": True,
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
        "parameter_mutation_performed": False,
    }
    atomic_write_json(report_out, report)
    return report


def load_shadow_model(path: str | Path = DEFAULT_MODEL_PATH) -> Dict[str, Any]:
    payload = _load_json(Path(path))
    if not isinstance(payload, dict):
        return {}
    if payload.get("model_version") != MODEL_VERSION:
        return {}
    if bool(payload.get("execution_allowed")):
        return {}
    return payload


def predict_with_model(model: Dict[str, Any], feature_pack: Dict[str, Any], *, ticker: str = "BTC-USDC", min_confidence: float = 0.65) -> Dict[str, Any]:
    if not model:
        return {
            "ticker": ticker,
            "prediction": "wait",
            "confidence": 0.0,
            "scores": {},
            "top_reasons": ["model unavailable"],
            "model_version": MODEL_VERSION,
            "trained_at": "",
            "available": False,
        }
    features = canonical_features(feature_pack)
    nonzero_classes = [
        cls
        for cls, count in (model.get("class_counts") if isinstance(model.get("class_counts"), dict) else {}).items()
        if int(count or 0) > 0
    ]
    if len(nonzero_classes) == 1:
        prediction = nonzero_classes[0]
        confidence = 0.10 if prediction == "prefer_no_trade" else 0.25
        return {
            "ticker": ticker,
            "prediction": prediction,
            "confidence": confidence,
            "scores": {cls: (1.0 if cls == prediction else 0.0) for cls in PREDICTION_CLASSES},
            "top_reasons": _top_reasons(features, prediction),
            "model_version": MODEL_VERSION,
            "trained_at": str(model.get("trained_at") or ""),
            "available": True,
            "diagnostic_only": True,
            "confidence_cap_for_decision": confidence,
            "one_class_dataset_warning": True,
        }
    vector = encode_features(features, model.get("categories") if isinstance(model.get("categories"), dict) else {})
    scores: Dict[str, float] = {}
    for cls in PREDICTION_CLASSES:
        centroid = model.get("centroids", {}).get(cls) if isinstance(model.get("centroids"), dict) else []
        if not centroid:
            count = int((model.get("class_counts") or {}).get(cls) or 0)
            scores[cls] = math.log1p(count) - 4.0
            continue
        width = min(len(vector), len(centroid))
        distance = math.sqrt(sum((vector[i] - float(centroid[i])) ** 2 for i in range(width)))
        prior = math.log1p(int((model.get("class_counts") or {}).get(cls) or 0))
        scores[cls] = prior - distance
    probs = _softmax(scores)
    prediction, confidence = max(probs.items(), key=lambda item: item[1]) if probs else ("wait", 0.0)
    if confidence < min_confidence and prediction in {"prefer_limit_buy", "prefer_pullback"}:
        prediction = "analyze"
    return {
        "ticker": ticker,
        "prediction": prediction,
        "confidence": round(float(confidence), 4),
        "scores": {k: round(v, 4) for k, v in sorted(probs.items())},
        "top_reasons": _top_reasons(features, prediction),
        "model_version": MODEL_VERSION,
        "trained_at": str(model.get("trained_at") or ""),
        "available": True,
    }


def build_shadow_context(
    feature_pack: Dict[str, Any],
    *,
    ticker: str,
    enabled: bool = True,
    execution_allowed: bool = False,
    agreement_required: bool = False,
    model_path: str | Path = DEFAULT_MODEL_PATH,
    min_confidence: float = 0.65,
) -> Dict[str, Any]:
    base = {
        "enabled": bool(enabled),
        "execution_allowed": False,
        "agreement_required": bool(agreement_required),
        "model_available": False,
        "prediction": "unavailable",
        "confidence": 0.0,
        "top_reasons": [],
        "model_version": MODEL_VERSION,
        "safety_policy": "soft_context_only_no_order_authority",
        "diagnostic_only": True,
        "can_block_planner": False,
        "can_block_judge": False,
        "can_authorize_execution": False,
    }
    if execution_allowed:
        base["blocked_reason"] = "execution_allowed_true_blocked_without_hash_gated_approval_route"
        return base
    if not enabled:
        base["blocked_reason"] = "disabled"
        return base
    model = load_shadow_model(model_path)
    if not model:
        base["blocked_reason"] = "model_missing_or_invalid"
        return base
    pred = predict_with_model(model, feature_pack, ticker=ticker, min_confidence=min_confidence)
    base.update({
        "model_available": True,
        "prediction": pred.get("prediction"),
        "confidence": pred.get("confidence"),
        "scores": pred.get("scores"),
            "top_reasons": pred.get("top_reasons") or [],
            "trained_at": pred.get("trained_at"),
            "diagnostic_only": bool(pred.get("diagnostic_only", True)),
            "confidence_cap_for_decision": pred.get("confidence_cap_for_decision"),
            "one_class_dataset_warning": bool(pred.get("one_class_dataset_warning", False)),
            "can_block_planner": False,
            "can_block_judge": False,
            "can_authorize_execution": False,
        })
    return base


def neural_learning_status_from_config(cfg: Any, *, root: str | Path = ".") -> Dict[str, Any]:
    project_root = Path(root)
    model_path = Path(getattr(cfg, "neural_shadow_policy_model_path", str(DEFAULT_MODEL_PATH)))
    report_path = Path(getattr(cfg, "neural_shadow_policy_report_path", str(DEFAULT_REPORT_PATH)))
    model = load_shadow_model(project_root / model_path if not model_path.is_absolute() else model_path)
    report = _load_json(project_root / report_path if not report_path.is_absolute() else report_path)
    enabled = bool(getattr(cfg, "neural_shadow_policy_enabled", True))
    training_enabled = bool(getattr(cfg, "neural_shadow_policy_training_enabled", True))
    execution_allowed = bool(getattr(cfg, "neural_shadow_policy_execution_allowed", False))
    status = "shadow_only"
    if execution_allowed:
        status = "blocked_execution_flag"
    elif not model:
        status = "model_unavailable"
    elif str(model.get("status")) == "insufficient_samples_shadow_only":
        status = "insufficient_samples_shadow_only"
    counts = (model or report or {}).get("class_counts") if isinstance((model or report or {}).get("class_counts"), dict) else {}
    nonzero = [cls for cls, count in counts.items() if int(count or 0) > 0]
    one_class = len(nonzero) <= 1 and bool(counts)
    sample_count = int((model or report or {}).get("sample_count") or sum(int(count or 0) for count in counts.values()))
    passivity_bias = bool(one_class and int(counts.get("prefer_no_trade", 0)) == sample_count and sample_count > 0)
    return {
        "enabled": enabled,
        "training_enabled": training_enabled,
        "execution_allowed": execution_allowed,
        "agreement_required": bool(getattr(cfg, "neural_shadow_policy_agreement_required", False)),
        "model_available": bool(model),
        "model_path": str(model_path),
        "latest_report": str(report_path),
        "sample_count": sample_count,
        "last_trained_at": str((model or {}).get("trained_at") or report.get("generated_at") or ""),
        "status": status,
        "class_counts": counts,
        "one_class_dataset_warning": bool((model or report or {}).get("one_class_dataset_warning") or one_class),
        "neural_shadow_one_class_passivity_bias": bool((model or report or {}).get("neural_shadow_one_class_passivity_bias") or passivity_bias),
        "balanced_label_recommendation": (model or report or {}).get("balanced_label_recommendation") or "bounded exploration needed for balanced labels",
    }


def evaluate_shadow_policy(rows: List[Dict[str, Any]], *, model_path: str | Path = DEFAULT_MODEL_PATH, json_out: str | Path = DEFAULT_EVAL_PATH) -> Dict[str, Any]:
    model = load_shadow_model(model_path)
    total = 0
    correct = 0
    counts: Dict[str, int] = {}
    for row in rows:
        pred = predict_with_model(model, row, ticker=str(row.get("ticker") or "BTC-USDC"))
        target = str(row.get("target_class") or "")
        got = str(pred.get("prediction") or "")
        counts[got] = counts.get(got, 0) + 1
        total += 1
        if got == target:
            correct += 1
    report = {
        "phase": "neural_shadow_policy_eval_v1",
        "generated_at": _now_iso(),
        "model_path": str(model_path),
        "sample_count": total,
        "accuracy": round(correct / total, 4) if total else 0.0,
        "prediction_counts": counts,
        "model_available": bool(model),
        "execution_allowed": False,
        "one_class_dataset_warning": len([cls for cls, count in counts.items() if int(count or 0) > 0]) <= 1 and bool(counts),
        "neural_shadow_one_class_passivity_bias": bool(
            len([cls for cls, count in counts.items() if int(count or 0) > 0]) == 1
            and int(counts.get("prefer_no_trade", 0)) == total
            and total > 0
        ),
        "balanced_label_recommendation": "bounded exploration needed for balanced labels",
        "coinbase_call_attempted": False,
        "llm_call_attempted": False,
    }
    atomic_write_json(json_out, report)
    return report


__all__ = [
    "DEFAULT_EVAL_PATH",
    "DEFAULT_MODEL_PATH",
    "DEFAULT_REPORT_PATH",
    "MODEL_VERSION",
    "build_shadow_context",
    "evaluate_shadow_policy",
    "load_jsonl",
    "load_shadow_model",
    "neural_learning_status_from_config",
    "predict_with_model",
    "train_shadow_policy",
    "validate_parameter_suggestions",
]
