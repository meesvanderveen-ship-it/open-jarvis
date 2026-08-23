"""Incremental, River-compatible scorer for parameter-learning evidence.

River is optional in this repository.  When it is installed the adapter runs a
small online classifier for diagnostics; when it is absent the persisted,
deterministic incremental statistics backend remains available.  Both backends
produce report-only scores and never mutate a BotConfig or invoke execution.
"""
from __future__ import annotations

import json
import math
import hashlib
import os
import pickle
import tempfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Sequence, Tuple

from bot.atomic_io import atomic_write_json
from bot.growbot_learning_adapter import EPISODE_ID_SCHEME
from bot.learnable_parameter_registry import get_parameter


RIVER_PHASE = "river_online_parameter_learner_v1"
REGIME_CONTEXT_VERSION = "known_market_regimes_with_direction_and_drift_v3"
MODEL_STATE_PATH = Path("reports/growbot_river/river-online-model-state.json")
REPORT_PATH = Path("reports/growbot_river/river-online-learning-latest.json")
NATIVE_MODEL_PATH = Path("reports/growbot_river/river-native-models.pkl")
NATIVE_MODEL_MANIFEST_PATH = Path("reports/growbot_river/river-native-models-manifest.json")
NATIVE_MODEL_SCHEMA = "river_native_streaming_models_v1"
NATIVE_INPUT_DEDUP_SCHEMA = "river_native_input_dedup_v1"
NON_MARKET_REGIMES = {"", "unknown", "backtest", "historical", "none", "null"}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and out not in (float("inf"), float("-inf")) else default


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _numeric_features(episode: Mapping[str, Any]) -> Dict[str, float]:
    raw = episode.get("state") if isinstance(episode.get("state"), Mapping) else {}
    features: Dict[str, float] = {}
    for key, value in raw.items():
        parsed = _as_float(value, float("nan"))
        if parsed == parsed and math.isfinite(parsed):
            features[str(key)] = parsed
    return features


def _fallback_hints(episode: Mapping[str, Any]) -> List[Dict[str, str]]:
    label = str(episode.get("label") or "").lower()
    state = episode.get("state") if isinstance(episode.get("state"), Mapping) else {}
    if "miss" in label or "no_fill" in label or "nonfill" in label:
        hints = [{"parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "direction": "loosen", "reason": "missed_opportunity"}]
        if _as_float(state.get("spread_pct")) >= 0.006:
            hints.append({"parameter": "MAX_SPREAD_PCT", "direction": "loosen", "reason": "no_fill_at_wide_spread"})
        return hints
    if label in {"bad_trade", "adverse_after_entry", "unprofitable_fill_after_costs", "bad_entry_candidate", "chase_then_adverse"}:
        return [
            {"parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "direction": "tighten", "reason": "bad_or_adverse_entry"},
            {"parameter": "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "direction": "tighten", "reason": "bad_or_adverse_entry"},
        ]
    return []


def _episode_hints(episode: Mapping[str, Any]) -> List[Dict[str, str]]:
    hints = [dict(item) for item in (episode.get("parameter_hints") or []) if isinstance(item, Mapping)]
    return hints or _fallback_hints(episode)


def _blank_parameter_state() -> Dict[str, Any]:
    return {
        "loosen_score": 0.0,
        "tighten_score": 0.0,
        "loosen_count": 0,
        "tighten_count": 0,
        "reward_sum": 0.0,
        "evidence_count": 0,
        "good_count": 0,
        "bad_count": 0,
        "missed_count": 0,
        "regimes": [],
        "regime_counts": {},
        "regime_direction": {},
        "reasons": [],
    }


def _is_missed_label(label: str) -> bool:
    return any(marker in label for marker in ("miss", "no_fill", "nonfill"))


def _merge_unique(values: Iterable[Any], *, limit: int) -> List[str]:
    output: List[str] = []
    for value in values:
        text = str(value or "").strip()
        if text and text not in output:
            output.append(text)
        if len(output) >= limit:
            break
    return output


_LAST_RIVER_IMPORT_ERROR: str = ""


def river_unavailable_reason() -> str:
    """The last captured import failure, for an operator dashboard.

    `_import_river()` must keep returning a plain `None` on failure so every
    call site's existing `if api is None` check keeps working; this exposes
    *why* separately so `river_native_sidecar_unavailable` is not a dead end.
    """
    return _LAST_RIVER_IMPORT_ERROR


def _import_river() -> Dict[str, Any] | None:
    """Load the real River package lazily so the report-only fallback survives.

    River is an optional sidecar dependency.  Absence must never stop the
    bot's existing learning, analysis or execution workflow.
    """
    global _LAST_RIVER_IMPORT_ERROR
    try:  # pragma: no cover - exercised in a dedicated optional-dependency environment
        import river
        from river import compose, drift, linear_model, metrics, preprocessing
    except ImportError as exc:
        _LAST_RIVER_IMPORT_ERROR = f"{type(exc).__name__}: {exc}"
        return None
    _LAST_RIVER_IMPORT_ERROR = ""
    return {
        "river": river,
        "compose": compose,
        "drift": drift,
        "linear_model": linear_model,
        "metrics": metrics,
        "preprocessing": preprocessing,
    }


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    except Exception:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _new_native_models(api: Mapping[str, Any]) -> Dict[str, Any]:
    compose = api["compose"]
    preprocessing = api["preprocessing"]
    linear_model = api["linear_model"]
    drift = api["drift"]
    metrics = api["metrics"]
    return {
        "schema": NATIVE_MODEL_SCHEMA,
        "river_version": str(getattr(api["river"], "__version__", "unknown")),
        "trade_classifier": compose.Pipeline(preprocessing.StandardScaler(), linear_model.LogisticRegression()),
        "reward_regressor": compose.Pipeline(preprocessing.StandardScaler(), linear_model.LinearRegression()),
        "reward_drift_detector": drift.ADWIN(),
        "classification_accuracy": metrics.Accuracy(),
        "reward_rmse": metrics.RMSE(),
        "processed_observations": 0,
        "drift_events": 0,
    }


def _load_native_models(root: Path, api: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    model_path = root / NATIVE_MODEL_PATH
    manifest_path = root / NATIVE_MODEL_MANIFEST_PATH
    manifest = _load_json(manifest_path)
    try:
        payload = model_path.read_bytes()
    except OSError:
        return _new_native_models(api), {"loaded": False, "reason": "snapshot_missing"}
    if (
        not manifest
        or manifest.get("schema") != NATIVE_MODEL_SCHEMA
        or manifest.get("sha256") != _sha256_bytes(payload)
    ):
        return _new_native_models(api), {"loaded": False, "reason": "snapshot_manifest_invalid"}
    try:
        models = pickle.loads(payload)
    except Exception:
        return _new_native_models(api), {"loaded": False, "reason": "snapshot_unreadable"}
    if not isinstance(models, dict) or models.get("schema") != NATIVE_MODEL_SCHEMA:
        return _new_native_models(api), {"loaded": False, "reason": "snapshot_schema_invalid"}
    return models, {"loaded": True, "reason": "snapshot_verified"}


def _write_native_models(root: Path, models: Mapping[str, Any]) -> Dict[str, str]:
    model_path = root / NATIVE_MODEL_PATH
    manifest_path = root / NATIVE_MODEL_MANIFEST_PATH
    payload = pickle.dumps(dict(models), protocol=pickle.HIGHEST_PROTOCOL)
    _atomic_write_bytes(model_path, payload)
    atomic_write_json(manifest_path, {
        "schema": NATIVE_MODEL_SCHEMA,
        "sha256": _sha256_bytes(payload),
        "written_at": now_iso(),
        "model_path": str(NATIVE_MODEL_PATH),
    })
    return {"model": str(NATIVE_MODEL_PATH), "manifest": str(NATIVE_MODEL_MANIFEST_PATH)}


def _native_features(episode: Mapping[str, Any], parameter: str) -> Dict[str, float]:
    features = _numeric_features(episode)
    # This sparse one-hot key lets one shared River model learn a separate
    # conditional contribution per parameter without exposing runtime knobs.
    features[f"parameter__{parameter}"] = 1.0
    return features


def _run_native_river(
    episodes: Sequence[Mapping[str, Any]],
    *,
    root: Path,
    reset_snapshot_for_input_dedup: bool = False,
) -> Dict[str, Any]:
    api = _import_river()
    if api is None:
        return {
            "backend": "deterministic_incremental_stats_river_compatible",
            "river_available": False,
            "diagnostic_accuracy": None,
            "parameter_estimates": {},
            "model_persistence": {"loaded": False, "reason": "river_package_unavailable"},
            "import_error_detail": river_unavailable_reason(),
        }
    if reset_snapshot_for_input_dedup:
        models = _new_native_models(api)
        persistence = {"loaded": False, "reason": "snapshot_rebuilt_for_native_input_dedup_contract"}
    else:
        models, persistence = _load_native_models(root, api)
    predictions: Dict[str, List[Dict[str, float]]] = defaultdict(list)
    learned = 0
    drift_events = 0
    classifier = models["trade_classifier"]
    regressor = models["reward_regressor"]
    detector = models["reward_drift_detector"]
    accuracy = models["classification_accuracy"]
    rmse = models["reward_rmse"]
    for episode in episodes:
        reward = _as_float(episode.get("reward"))
        target_good_trade = reward > 0
        detector.update(reward)
        if bool(getattr(detector, "drift_detected", False)):
            drift_events += 1
        for hint in _episode_hints(episode):
            parameter = str(hint.get("parameter") or "")
            direction = str(hint.get("direction") or "")
            if get_parameter(parameter) is None or direction not in {"loosen", "tighten"}:
                continue
            features = _native_features(episode, parameter)
            reward_prediction = _as_float(regressor.predict_one(features))
            probabilities = classifier.predict_proba_one(features) or {}
            good_probability = _as_float(probabilities.get(True), 0.5)
            trade_prediction = good_probability >= 0.5
            predictions[parameter].append({"expected_reward": reward_prediction, "good_trade_probability": good_probability})
            accuracy.update(target_good_trade, trade_prediction)
            rmse.update(reward, reward_prediction)
            classifier.learn_one(features, target_good_trade)
            regressor.learn_one(features, reward)
            learned += 1
    models["processed_observations"] = int(models.get("processed_observations") or 0) + learned
    models["drift_events"] = int(models.get("drift_events") or 0) + drift_events
    paths = _write_native_models(root, models)
    estimates = {
        parameter: {
            "expected_reward": round(sum(item["expected_reward"] for item in rows) / len(rows), 6),
            "good_trade_probability": round(sum(item["good_trade_probability"] for item in rows) / len(rows), 6),
            "prediction_count": len(rows),
        }
        for parameter, rows in predictions.items() if rows
    }
    return {
        "backend": "river_native_streaming_models",
        "river_available": True,
        "river_version": str(getattr(api["river"], "__version__", "unknown")),
        "diagnostic_accuracy": round(float(accuracy.get()), 6) if learned else None,
        "diagnostic_reward_rmse": round(float(rmse.get()), 6) if learned else None,
        "diagnostic_samples": learned,
        "parameter_estimates": estimates,
        "drift": {
            "detected_in_current_batch": drift_events > 0,
            "current_batch_events": drift_events,
            "total_events": int(models.get("drift_events") or 0),
            "adwin_width": int(getattr(detector, "width", 0) or 0),
            "adwin_estimation": round(_as_float(getattr(detector, "estimation", 0.0)), 6),
        },
        "model_persistence": {**persistence, "paths": paths},
    }


def validate_river_walk_forward(
    episodes: Sequence[Mapping[str, Any]],
    *,
    min_training_events: int = 50,
    min_holdout_events: int = 25,
) -> Dict[str, Any]:
    """Evaluate native River models on a chronological frozen holdout.

    This is a report-only diagnostic. It creates no model snapshot, does not
    update the persistent online model and can never release a parameter.
    """
    api = _import_river()
    if api is None:
        return {
            "status": "river_package_unavailable",
            "passed": False,
            "parameter_promotion_evidence_ready": False,
            "blockers": ["river_package_unavailable"],
            "state_write_performed": False,
            "import_error_detail": river_unavailable_reason(),
        }
    events: List[Tuple[str, int, Mapping[str, Any], str]] = []
    for index, episode in enumerate(episodes):
        if not isinstance(episode, Mapping):
            continue
        for hint in _episode_hints(episode):
            parameter = str(hint.get("parameter") or "")
            direction = str(hint.get("direction") or "")
            if get_parameter(parameter) is not None and direction in {"loosen", "tighten"}:
                events.append((str(episode.get("occurred_at") or "9999-12-31T00:00:00Z"), index, episode, parameter))
    events.sort(key=lambda row: (row[0], row[1], row[3]))
    required = min_training_events + min_holdout_events
    if len(events) < required:
        return {
            "status": "insufficient_events_for_walk_forward",
            "passed": False,
            "event_count": len(events),
            "min_training_events": min_training_events,
            "min_holdout_events": min_holdout_events,
            "parameter_promotion_evidence_ready": False,
            "blockers": ["insufficient_chronological_parameter_events"],
            "state_write_performed": False,
        }
    split_at = max(min_training_events, int(len(events) * 0.70))
    split_at = min(split_at, len(events) - min_holdout_events)
    models = _new_native_models(api)
    classifier = models["trade_classifier"]
    regressor = models["reward_regressor"]
    for _time, _index, episode, parameter in events[:split_at]:
        features = _native_features(episode, parameter)
        reward = _as_float(episode.get("reward"))
        classifier.learn_one(features, reward > 0)
        regressor.learn_one(features, reward)
    accuracy = api["metrics"].Accuracy()
    rmse = api["metrics"].RMSE()
    for _time, _index, episode, parameter in events[split_at:]:
        features = _native_features(episode, parameter)
        reward = _as_float(episode.get("reward"))
        probability = _as_float((classifier.predict_proba_one(features) or {}).get(True), 0.5)
        accuracy.update(reward > 0, probability >= 0.5)
        rmse.update(reward, _as_float(regressor.predict_one(features)))
    accuracy_value = float(accuracy.get())
    rmse_value = float(rmse.get())
    passed = accuracy_value >= 0.55 and rmse_value <= 0.75
    return {
        "status": "river_walk_forward_evaluated",
        "passed": passed,
        "event_count": len(events),
        "training_event_count": split_at,
        "holdout_event_count": len(events) - split_at,
        "chronological_split": True,
        "holdout_metrics": {"accuracy": round(accuracy_value, 6), "reward_rmse": round(rmse_value, 6)},
        "thresholds": {"min_accuracy": 0.55, "max_reward_rmse": 0.75},
        "parameter_promotion_evidence_ready": False,
        "blockers": [] if passed else ["river_holdout_metrics_below_threshold"],
        "state_write_performed": False,
        "policy": "diagnostic_only_holdout_never_releases_runtime_parameters",
    }


def _confidence(stats: Mapping[str, Any]) -> float:
    loosen = _as_float(stats.get("loosen_score"))
    tighten = _as_float(stats.get("tighten_score"))
    count = int(_as_float(stats.get("evidence_count")))
    total = loosen + tighten
    if total <= 0 or count <= 0:
        return 0.0
    direction_strength = abs(loosen - tighten) / total
    sample_strength = min(1.0, count / 30.0)
    regime_strength = min(1.0, len(stats.get("regimes") or []) / 3.0)
    return round(min(0.95, (0.30 + 0.65 * direction_strength * sample_strength) * (0.70 + 0.30 * regime_strength)), 4)


def _regime_effect_directions(stats: Mapping[str, Any]) -> Dict[str, str]:
    """Per-regime directional lean for one parameter: loosen / tighten / mixed."""
    raw = stats.get("regime_direction") if isinstance(stats.get("regime_direction"), Mapping) else {}
    directions: Dict[str, str] = {}
    for regime, scores in raw.items():
        if not isinstance(scores, Mapping):
            continue
        loosen = _as_float(scores.get("loosen"))
        tighten = _as_float(scores.get("tighten"))
        if loosen == 0.0 and tighten == 0.0:
            continue
        if loosen == tighten:
            directions[str(regime)] = "mixed"
        else:
            directions[str(regime)] = "loosen" if loosen > tighten else "tighten"
    return directions


def _regime_drift_hint(regime: str, regime_performance: Mapping[str, Mapping[str, Any]] | None) -> Dict[str, Any]:
    """Surface the shared per-regime drift diagnostic for one parameter's dominant regime."""
    entry = (regime_performance or {}).get(regime) if regime_performance else None
    if not isinstance(entry, Mapping):
        return {"regime": regime, "available": False, "reason": "insufficient_regime_observations"}
    return {
        "regime": regime,
        "available": True,
        "observations": int(_as_float(entry.get("count"))),
        "average_reward": round(_as_float(entry.get("average_reward")), 6),
        "prior_average_reward": round(_as_float(entry.get("prior_average_reward")), 6),
        "recent_average_reward": round(_as_float(entry.get("recent_average_reward")), 6),
        "drift_detected": bool(entry.get("drift_detected")),
    }


def _good_bad_missed_probabilities(stats: Mapping[str, Any]) -> Dict[str, Any]:
    good = int(_as_float(stats.get("good_count")))
    bad = int(_as_float(stats.get("bad_count")))
    evidence_count = max(1, int(_as_float(stats.get("evidence_count"))))
    missed = int(_as_float(stats.get("missed_count")))
    denom = good + bad
    return {
        "good_trade_probability": round(good / denom, 6) if denom > 0 else None,
        "bad_trade_probability": round(bad / denom, 6) if denom > 0 else None,
        "missed_opportunity_probability": round(missed / evidence_count, 6),
        "good_count": good,
        "bad_count": bad,
        "missed_count": missed,
    }


def _signals(
    parameter_stats: Mapping[str, Mapping[str, Any]],
    *,
    river_parameter_estimates: Mapping[str, Mapping[str, Any]] | None = None,
    regime_performance: Mapping[str, Mapping[str, Any]] | None = None,
) -> List[Dict[str, Any]]:
    signals: List[Dict[str, Any]] = []
    estimates = river_parameter_estimates or {}
    for parameter, stats in parameter_stats.items():
        definition = get_parameter(parameter)
        if definition is None:
            continue
        loosen = _as_float(stats.get("loosen_score"))
        tighten = _as_float(stats.get("tighten_score"))
        if loosen == tighten:
            continue
        direction = "loosen" if loosen > tighten else "tighten"
        confidence = _confidence(stats)
        estimate = estimates.get(parameter) if isinstance(estimates.get(parameter), Mapping) else {}
        river_reward = _as_float(estimate.get("expected_reward")) if estimate else None
        river_probability = _as_float(estimate.get("good_trade_probability")) if estimate else None
        ranking_score = confidence * (0.75 + (min(1.0, abs(river_reward or 0.0)) * 0.25))
        regime_counts = {str(k): int(_as_float(v)) for k, v in (stats.get("regime_counts") or {}).items()}
        dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"
        probabilities = _good_bad_missed_probabilities(stats)
        signals.append({
            "parameter": parameter,
            "direction": direction,
            "confidence": confidence,
            "evidence_count": int(_as_float(stats.get("evidence_count"))),
            "expected_reward": round(_as_float(stats.get("reward_sum")) / max(1, int(_as_float(stats.get("evidence_count")))), 6),
            "good_trade_probability": probabilities["good_trade_probability"],
            "bad_trade_probability": probabilities["bad_trade_probability"],
            "missed_opportunity_probability": probabilities["missed_opportunity_probability"],
            "river_expected_reward": round(river_reward, 6) if river_reward is not None else None,
            "river_good_trade_probability": round(river_probability, 6) if river_probability is not None else None,
            "river_prediction_count": int(_as_float(estimate.get("prediction_count"))) if estimate else 0,
            "candidate_ranking_score": round(ranking_score, 6),
            "directional_scores": {"loosen": round(loosen, 6), "tighten": round(tighten, 6)},
            "regimes": list(stats.get("regimes") or []),
            "regime_evidence_counts": regime_counts,
            "regime_effect_direction": _regime_effect_directions(stats),
            "dominant_regime": dominant_regime,
            "regime_drift_hint": _regime_drift_hint(dominant_regime, regime_performance),
            "reasons": list(stats.get("reasons") or [])[:5],
            "activation_route": definition.activation_route(),
            "approved_profile_supported": definition.name in {"MAX_SPREAD_PCT", "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT", "AUTONOMOUS_MAX_OPEN_ORDERS", "AUTONOMOUS_MAX_NEW_ORDERS_PER_CYCLE"},
            "safe_to_activate_now": False,
        })
    return sorted(
        signals,
        key=lambda row: (float(row["candidate_ranking_score"]), float(row["confidence"]), int(row["evidence_count"])),
        reverse=True,
    )


def _update_state(state: MutableMapping[str, Any], episodes: Sequence[Mapping[str, Any]]) -> Tuple[List[Mapping[str, Any]], Dict[str, int]]:
    processed = [str(value) for value in state.get("processed_episode_ids") or [] if str(value)]
    processed_set = set(processed)
    batch_ids: set[str] = set()
    fresh: List[Mapping[str, Any]] = []
    for episode in episodes:
        episode_id = str(episode.get("episode_id") or "")
        if not episode_id or episode_id in processed_set or episode_id in batch_ids:
            continue
        batch_ids.add(episode_id)
        fresh.append(episode)
    parameter_stats = state.get("parameter_stats") if isinstance(state.get("parameter_stats"), dict) else {}
    reward_window = [float(value) for value in (state.get("recent_rewards") or [])[-200:] if isinstance(value, (int, float))]
    label_counts = Counter(state.get("label_counts") if isinstance(state.get("label_counts"), dict) else {})
    classification = Counter(state.get("classification") if isinstance(state.get("classification"), dict) else {})
    regime_performance = state.get("regime_performance") if isinstance(state.get("regime_performance"), dict) else {}
    for episode in fresh:
        reward = _as_float(episode.get("reward"))
        reward_window.append(reward)
        label = str(episode.get("label") or "neutral")
        label_counts[label] += 1
        classification["good_or_avoided" if reward > 0 else ("bad_or_missed" if reward < 0 else "neutral")] += 1
        regime = str(episode.get("regime") or "unknown").strip().lower().replace(" ", "_")
        is_missed = _is_missed_label(label)
        if regime not in NON_MARKET_REGIMES:
            entry = regime_performance.setdefault(regime, {"count": 0, "reward_sum": 0.0, "recent_rewards": []})
            entry["count"] = int(_as_float(entry.get("count"))) + 1
            entry["reward_sum"] = _as_float(entry.get("reward_sum")) + reward
            regime_recent = entry.get("recent_rewards") if isinstance(entry.get("recent_rewards"), list) else []
            entry["recent_rewards"] = (regime_recent + [reward])[-100:]
        for hint in _episode_hints(episode):
            parameter = str(hint.get("parameter") or "")
            direction = str(hint.get("direction") or "")
            if get_parameter(parameter) is None or direction not in {"loosen", "tighten"}:
                continue
            stats = parameter_stats.setdefault(parameter, _blank_parameter_state())
            # Negative evidence gets full weight; a profitable outcome that
            # supports a change is only a weak directional signal.
            weight = 1.0 if reward <= 0 else 0.25
            stats[f"{direction}_score"] = _as_float(stats.get(f"{direction}_score")) + weight
            stats[f"{direction}_count"] = int(_as_float(stats.get(f"{direction}_count"))) + 1
            stats["reward_sum"] = _as_float(stats.get("reward_sum")) + reward
            stats["evidence_count"] = int(_as_float(stats.get("evidence_count"))) + 1
            if reward > 0:
                stats["good_count"] = int(_as_float(stats.get("good_count"))) + 1
            elif reward < 0:
                stats["bad_count"] = int(_as_float(stats.get("bad_count"))) + 1
            if is_missed:
                stats["missed_count"] = int(_as_float(stats.get("missed_count"))) + 1
            if regime not in NON_MARKET_REGIMES:
                stats["regimes"] = _merge_unique(list(stats.get("regimes") or []) + [regime], limit=12)
                regime_counts = stats.get("regime_counts") if isinstance(stats.get("regime_counts"), dict) else {}
                regime_counts[regime] = int(_as_float(regime_counts.get(regime))) + 1
                stats["regime_counts"] = regime_counts
                regime_direction = stats.get("regime_direction") if isinstance(stats.get("regime_direction"), dict) else {}
                direction_entry = regime_direction.setdefault(regime, {"loosen": 0.0, "tighten": 0.0})
                direction_entry[direction] = _as_float(direction_entry.get(direction)) + weight
                stats["regime_direction"] = regime_direction
            stats["reasons"] = _merge_unique(list(stats.get("reasons") or []) + [hint.get("reason")], limit=12)
    all_rewards = [float(value) for value in reward_window]
    recent = all_rewards[-30:]
    prior = all_rewards[:-30]
    prior_avg = sum(prior) / len(prior) if prior else 0.0
    recent_avg = sum(recent) / len(recent) if recent else 0.0
    regime_performance_summary = {}
    for regime, entry in regime_performance.items():
        regime_rewards = [float(value) for value in (entry.get("recent_rewards") or [])]
        regime_recent_window = regime_rewards[-20:]
        regime_prior_window = regime_rewards[:-20]
        regime_prior_avg = sum(regime_prior_window) / len(regime_prior_window) if regime_prior_window else 0.0
        regime_recent_avg = sum(regime_recent_window) / len(regime_recent_window) if regime_recent_window else 0.0
        regime_performance_summary[regime] = {
            "count": int(_as_float(entry.get("count"))),
            "average_reward": round(_as_float(entry.get("reward_sum")) / max(1, int(_as_float(entry.get("count")))), 6),
            "prior_average_reward": round(regime_prior_avg, 6),
            "recent_average_reward": round(regime_recent_avg, 6),
            "drift_detected": bool(
                len(regime_prior_window) >= 20 and len(regime_recent_window) >= 10
                and abs(regime_recent_avg - regime_prior_avg) >= 0.25
            ),
        }
    state.update({
        "schema_version": RIVER_PHASE,
        "episode_identity_scheme": EPISODE_ID_SCHEME,
        "regime_context_version": REGIME_CONTEXT_VERSION,
        "updated_at": now_iso(),
        "processed_episode_ids": (processed + [str(item.get("episode_id")) for item in fresh if str(item.get("episode_id") or "")])[-50_000:],
        "parameter_stats": parameter_stats,
        "recent_rewards": all_rewards[-200:],
        "label_counts": dict(label_counts),
        "classification": dict(classification),
        "regime_performance": regime_performance,
        "regime_drift": {
            "observations": len(all_rewards),
            "prior_average_reward": round(prior_avg, 6),
            "recent_average_reward": round(recent_avg, 6),
            "drift_detected": bool(len(prior) >= 30 and len(recent) >= 15 and abs(recent_avg - prior_avg) >= 0.25),
            "by_regime": regime_performance_summary,
            "distinct_regime_count": len(regime_performance_summary),
        },
    })
    return fresh, {
        "already_processed": len(episodes) - len(fresh),
        "newly_processed": len(fresh),
        "duplicate_episode_ids_in_input": max(0, len(episodes) - len(fresh) - len([item for item in episodes if str(item.get("episode_id") or "") in processed_set])),
    }


def _new_episodes_for_backend(
    episodes: Sequence[Mapping[str, Any]],
    processed_ids: Sequence[Any],
) -> List[Mapping[str, Any]]:
    """Return unique episodes not yet learned by a particular backend."""
    seen = {str(value) for value in processed_ids if str(value)}
    fresh: List[Mapping[str, Any]] = []
    for episode in episodes:
        episode_id = str(episode.get("episode_id") or "")
        if not episode_id or episode_id in seen:
            continue
        seen.add(episode_id)
        fresh.append(episode)
    return fresh


def run_river_online_parameter_learning(episodes: Sequence[Mapping[str, Any]], *, root: Path = Path(".")) -> Dict[str, Any]:
    """Incrementally consume new episodes and return scored parameter signals."""
    state_path = root / MODEL_STATE_PATH
    state = _load_json(state_path)
    identity_migration = bool(state) and state.get("episode_identity_scheme") != EPISODE_ID_SCHEME
    regime_context_migration = bool(state) and state.get("regime_context_version") != REGIME_CONTEXT_VERSION
    if identity_migration or regime_context_migration:
        # This state lives exclusively under reports/growbot_river. Rebuild it
        # from the current source batch once when an episode-ID or regime-data
        # contract changes, preventing stale report-only statistics from being
        # mixed with the new contract. No trading or production lifecycle state
        # is touched.
        state = {}
    fresh, processing = _update_state(state, episodes)
    processing["model_state_rebuilt_for_episode_identity"] = identity_migration
    processing["model_state_rebuilt_for_regime_context"] = regime_context_migration
    native_tracking_missing = state.get("native_processed_episode_schema") != NATIVE_INPUT_DEDUP_SCHEMA
    native_processed = state.get("native_processed_episode_ids") if isinstance(state.get("native_processed_episode_ids"), list) else []
    native_fresh = _new_episodes_for_backend(episodes, native_processed)
    backend = _run_native_river(
        native_fresh,
        root=root,
        # The deterministic fallback has its own processed-ID ledger.  When
        # River first becomes available it must receive one source-bounded,
        # report-only bootstrap batch instead of inheriting fallback markers.
        # An old native snapshot without this ledger is rebuilt to prevent
        # untraceable duplicate online training.
        reset_snapshot_for_input_dedup=native_tracking_missing,
    )
    native_available = backend.get("river_available") is True
    if native_available:
        state["native_processed_episode_schema"] = NATIVE_INPUT_DEDUP_SCHEMA
        state["native_processed_episode_ids"] = (
            [str(value) for value in native_processed if str(value)]
            + [str(item.get("episode_id")) for item in native_fresh if str(item.get("episode_id") or "")]
        )[-50_000:]
    processing.update({
        "native_already_processed": len(episodes) - len(native_fresh),
        "native_newly_processed": len(native_fresh) if native_available else 0,
        "native_input_dedup_contract_rebuilt": bool(native_available and native_tracking_missing),
        "native_input_dedup_schema": NATIVE_INPUT_DEDUP_SCHEMA if native_available else "",
    })
    parameter_stats = state.get("parameter_stats") if isinstance(state.get("parameter_stats"), dict) else {}
    regime_performance = (state.get("regime_drift") or {}).get("by_regime") if isinstance(state.get("regime_drift"), dict) else {}
    signals = _signals(
        parameter_stats,
        river_parameter_estimates=backend.get("parameter_estimates") if isinstance(backend.get("parameter_estimates"), dict) else {},
        regime_performance=regime_performance if isinstance(regime_performance, dict) else {},
    )
    walk_forward_validation = validate_river_walk_forward(episodes)
    report = {
        "phase": RIVER_PHASE,
        "generated_at": now_iso(),
        "backend": backend,
        "processing": processing,
        "episode_identity_scheme": EPISODE_ID_SCHEME,
        "regime_context_version": REGIME_CONTEXT_VERSION,
        "expected_reward_model": {
            "method": "river_linear_regression_when_available_else_incremental_per_parameter_reward_mean",
            "signals_ranked": len(signals),
        },
        "good_bad_trade_classification": state.get("classification") or {},
        "regime_drift": {
            "deterministic_summary": state.get("regime_drift") or {},
            "river_adwin": backend.get("drift") or {},
        },
        "parameter_signals": signals,
        "walk_forward_validation": walk_forward_validation,
        "model_state_path": str(MODEL_STATE_PATH),
        "safety_policy": {
            "online_learning_only": True,
            "report_only": True,
            "parameter_mutation_allowed": False,
            "execution_authority": False,
            "approved_profile_route_required": True,
        },
    }
    atomic_write_json(state_path, state)
    atomic_write_json(root / REPORT_PATH, report)
    return report


__all__ = [
    "MODEL_STATE_PATH",
    "NATIVE_MODEL_MANIFEST_PATH",
    "NATIVE_MODEL_PATH",
    "NATIVE_MODEL_SCHEMA",
    "NATIVE_INPUT_DEDUP_SCHEMA",
    "NON_MARKET_REGIMES",
    "REPORT_PATH",
    "REGIME_CONTEXT_VERSION",
    "RIVER_PHASE",
    "river_unavailable_reason",
    "run_river_online_parameter_learning",
    "validate_river_walk_forward",
]
