"""GrowBot provenance and episode adapter for the existing learning data.

This module deliberately has no import path to order submission, C4.3 or D3.
An episode is a compact representation of a completed trade cycle, wait, no
fill or missed opportunity.  Its only persistent output is an append-only
learning ledger under ``reports/growbot_river``.

The verified upstream ``britcruise9/GrowBot`` V0 tree is hardware setup code
and simulation assets, not a published learning runtime.  Its CC BY-NC 4.0
license is also not automatically suitable for a trading product.  We record
that provenance and never import or execute its hardware code here.
"""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from bot.atomic_io import atomic_write_json
from bot.growbot_river_learning_contract import ALLOWED_STATE_KEYS, sanitize_learning_context_snapshot


GROWBOT_PHASE = "growbot_learning_adapter_v1"
EPISODE_ID_SCHEME = "growbot_episode_id_collision_safe_v2"
EPISODE_CONTRACT_VERSION = "growbot_river_episode_contract_v1"
REPORT_PATH = Path("reports/growbot_river/growbot-episode-report-latest.json")
EPISODE_LEDGER_PATH = Path("reports/growbot_river/history/episodes.jsonl")
GROWBOT_UPSTREAM_REPOSITORY = "https://github.com/britcruise9/GrowBot"
GROWBOT_UPSTREAM_COMMIT = "0eccd6460c289fbae710a9efc2fee57bfafa65c5"
GROWBOT_UPSTREAM_LICENSE = "CC-BY-NC-4.0"
GROWBOT_LOCAL_CANDIDATE_DIRS = ("third_party/GrowBot", "vendor/GrowBot", "GrowBot")

SOURCE_PATHS: Tuple[Tuple[str, Path], ...] = (
    ("reflection", Path("reports/reflection/reflection-learning-latest.json")),
    ("decision_outcome", Path("logs/decision_outcomes.jsonl")),
    ("execution_outcome", Path("logs/execution_outcomes.jsonl")),
    ("trade_reflection", Path("logs/trade_reflections.jsonl")),
    ("backtest", Path("reports/backtests/btc-eth-parameter-backtest-latest.json")),
)
NEURAL_SHADOW_REPORT_PATH = Path("reports/live_learning/neural-shadow-policy-latest.json")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if out == out and out not in (float("inf"), float("-inf")) else default


def _load_json(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _relative_or_absolute(root: Path, source_path: str | Path) -> Path:
    candidate = Path(source_path)
    return candidate if candidate.is_absolute() else root / candidate


def discover_growbot_open_source(root: Path = Path("."), *, source_path: str | Path | None = None) -> Dict[str, Any]:
    """Describe, but never import, an available GrowBot source tree.

    A local source tree may be useful once it has a trading-compatible license
    and a documented learning API. Dynamic imports are intentionally forbidden:
    third-party code has no authority over the trading runtime or this sidecar.
    """
    candidates: List[Path] = []
    if source_path not in (None, ""):
        candidates.append(_relative_or_absolute(root, source_path))
    candidates.extend(root / relative for relative in GROWBOT_LOCAL_CANDIDATE_DIRS)
    local = next((path for path in candidates if path.is_dir()), None)
    upstream = {
        "repository_url": GROWBOT_UPSTREAM_REPOSITORY,
        "verified_commit": GROWBOT_UPSTREAM_COMMIT,
        "license": GROWBOT_UPSTREAM_LICENSE,
        "upstream_learning_runtime_available": False,
        "upstream_code_inventory": [
            "setup/growbot/{audio,camera,imu,leds,pins,servos}.py",
            "simulation/growbot_current_body.xml",
            "hardware/mechanical setup assets",
        ],
        "upstream_learning_code_status": "README states training harness, reward functions and trained policies are still in development",
    }
    if local is None:
        return {
            "source_type": "upstream_metadata_only",
            "local_source_found": False,
            "source_code_executed": False,
            "integration_mode": "episode_contract_inspired_by_upstream_learning_loop",
            "status": "blocked_no_local_learning_runtime_and_upstream_has_no_published_learning_runtime",
            "blockers": [
                "britcruise9_growbot_has_no_published_training_or_policy_runtime",
                "upstream_cc_by_nc_4_license_requires_operator_legal_review_for_trading_use",
                "third_party_growbot_code_is_never_dynamically_imported",
            ],
            "upstream": upstream,
        }

    license_path = next((path for path in (local / "LICENSE", local / "LICENSE.md", local / "COPYING") if path.exists()), None)
    try:
        license_text = license_path.read_text(encoding="utf-8", errors="replace")[:4_000] if license_path else ""
    except OSError:
        license_text = ""
    python_files = sorted(path.relative_to(local).as_posix() for path in local.rglob("*.py") if path.is_file())
    learning_files = [
        path for path in python_files
        if any(token in path.lower() for token in ("train", "learn", "policy", "reward", "agent", "model"))
    ]
    noncommercial = "noncommercial" in license_text.lower() or "by-nc" in license_text.lower()
    return {
        "source_type": "local_source_manifest",
        "local_source_found": True,
        "local_source_path": str(local),
        "source_code_executed": False,
        "integration_mode": "manifest_and_contract_only_pending_explicit_api_and_license_review",
        "status": "local_source_detected_but_not_executed",
        "blockers": [
            "third_party_growbot_code_is_never_dynamically_imported",
            "operator_must_confirm_learning_api_contract_before_adapter_execution",
            *( ["local_license_appears_noncommercial"] if noncommercial else [] ),
        ],
        "local_inventory": {
            "license_path": str(license_path) if license_path else "",
            "python_file_count": len(python_files),
            "learning_related_files": learning_files[:50],
            "learning_runtime_detected": bool(learning_files),
        },
        "upstream": upstream,
    }


def _load_jsonl_tail(path: Path, limit: int) -> Tuple[List[Dict[str, Any]], int]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception:
        return [], 0
    rows: List[Dict[str, Any]] = []
    corrupt = 0
    for line in lines[-max(0, limit):]:
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            corrupt += 1
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, corrupt


def _label(row: Mapping[str, Any]) -> str:
    raw = (
        row.get("label")
        or row.get("outcome_label")
        or row.get("primary_label")
        or row.get("result")
        or row.get("event")
        or _as_dict(row.get("metrics")).get("outcome")
        or "neutral"
    )
    if raw in (None, ""):
        labels = row.get("labels")
        if isinstance(labels, list):
            raw = next((item for item in labels if str(item or "").strip()), "")
    label = str(raw).strip().lower() or "neutral"
    return {"win": "good_trade", "loss": "bad_trade", "flat": "neutral"}.get(label, label)


def _episode_type(source: str, label: str, row: Mapping[str, Any]) -> str:
    if source == "trade_reflection":
        return "closed_trade"
    if "miss" in label or "no_fill" in label or "nonfill" in label:
        return "missed_opportunity_or_no_fill"
    if "wait" in label or str(row.get("decision") or "").lower() in {"wait", "skip", "watch"}:
        return "wait_or_avoid"
    if source == "execution_outcome" or row.get("filled") or str(row.get("order_status") or "").lower() == "filled":
        return "execution_outcome"
    if "trade" in label or "profit" in label or "loss" in label:
        return "closed_trade"
    return "decision_cycle"


def _reward(label: str, row: Mapping[str, Any]) -> Tuple[float, List[str]]:
    metrics = _as_dict(row.get("metrics"))
    pnl = _as_float(row.get("realized_pnl_pct") or row.get("net_pnl_pct") or metrics.get("realized_pnl_pct"), 0.0)
    reasons: List[str] = []
    if label in {"good_trade", "profitable_fill_after_costs", "good_limit_execution", "good_entry_candidate"} or pnl > 0:
        return min(1.0, max(0.20, pnl * 25.0 if pnl else 0.75)), ["positive_closed_or_execution_outcome"]
    if label in {"bad_trade", "adverse_after_entry", "unprofitable_fill_after_costs", "bad_entry_candidate", "chase_then_adverse"} or pnl < 0:
        return max(-1.0, min(-0.20, pnl * 25.0 if pnl else -0.75)), ["negative_closed_or_execution_outcome"]
    if "miss" in label or "no_fill" in label or "nonfill" in label:
        reasons.append("missed_opportunity_or_no_fill")
        return -0.50, reasons
    if label in {"correct_wait", "correct_avoid", "good_wait", "correct_wait_avoided_adverse"}:
        return 0.50, ["correct_wait_or_avoid"]
    return 0.0, ["insufficient_reward_evidence"]


def _learning_context(row: Mapping[str, Any]) -> Dict[str, Any]:
    return sanitize_learning_context_snapshot(_as_dict(row.get("growbot_river_learning_context")))


_STATE_KEY_RAW_ALIASES: Dict[str, Tuple[str, ...]] = {
    # decision_outcome_tracker.py's compact logs/decision_outcomes.jsonl
    # records carry these directly at top level (no growbot_river_learning_context
    # wrapper), under the tracker's own field names rather than the canonical
    # mfe_pct/mae_pct contract keys.
    "mfe_pct": ("max_favorable_pct", "max_favorable_excursion_pct"),
    "mae_pct": ("max_adverse_pct", "max_adverse_excursion_pct"),
}


def _state(row: Mapping[str, Any], *, learning_context: Optional[Mapping[str, Any]] = None) -> Dict[str, Any]:
    learning_context = learning_context if learning_context is not None else _learning_context(row)
    features = _as_dict(learning_context.get("state")) or _as_dict(row.get("feature_pack")) or _as_dict(row.get("features"))
    path_metrics = _as_dict(_as_dict(row.get("outcome")).get("path_metrics"))
    market = _as_dict(row.get("market_snapshot"))
    state: Dict[str, Any] = {}
    for key in ALLOWED_STATE_KEYS:
        value = features.get(key, row.get(key))
        if value in (None, ""):
            for alias in _STATE_KEY_RAW_ALIASES.get(key, ()):
                value = row.get(alias, path_metrics.get(alias))
                if value not in (None, ""):
                    break
        if value not in (None, ""):
            state[key] = value
    if market:
        bid = _as_float(market.get("best_bid"), 0.0)
        ask = _as_float(market.get("best_ask"), 0.0)
        if bid > 0 and ask >= bid:
            state["spread_pct"] = (ask - bid) / max((ask + bid) / 2.0, 1e-12)
    return state


def _regime(row: Mapping[str, Any], *, learning_context: Optional[Mapping[str, Any]] = None) -> str:
    learning_context = learning_context if learning_context is not None else _learning_context(row)
    context_regime = str(learning_context.get("regime") or "").strip().lower().replace(" ", "_")
    if context_regime and context_regime not in {"unknown", "none", "null"}:
        return context_regime
    for key in ("adaptive_market_regime", "market_regime", "regime", "trend_regime"):
        value = str(row.get(key) or "").strip().lower().replace(" ", "_")
        if value and value not in {"unknown", "none", "null"}:
            return value
    return "unknown"


def _compact_evidence(label: str, row: Mapping[str, Any], *, learning_context: Mapping[str, Any]) -> Dict[str, Any]:
    """Compact, allowlisted categorical evidence kept alongside numeric state.

    These are short labels only (fill/no-fill, exit result, missed-opportunity
    signal); no free text, prompts or raw payloads are stored here.
    """
    context = _as_dict(learning_context.get("context"))
    fill_status = context.get("fill_status") or str(row.get("lifecycle_action") or row.get("order_status") or "").strip().lower() or "unknown"
    exit_result = context.get("exit_result") or label
    missed_opportunity_signal = any(token in label for token in ("miss", "no_fill", "nonfill", "too_strict"))
    return {
        "fill_status": fill_status,
        "exit_result": exit_result,
        "missed_opportunity_signal": missed_opportunity_signal,
    }


_MISSED_LABEL_MARKERS = ("miss", "no_fill", "nonfill")
_BAD_LABELS = {"bad_trade", "adverse_after_entry", "unprofitable_fill_after_costs", "bad_entry_candidate", "chase_then_adverse"}

# Compact, deterministic state-threshold evidence.  Each row is
# (state_key, comparator, threshold, parameter, direction, reason).  These
# mirror the same default thresholds already used as the registry's current
# values (`bot/learnable_parameter_registry.py`), so a hint only fires when
# the observed evidence is actually on the wrong side of the live setting.
# Direction is the *evidence-supported* change, never an instruction to mutate
# anything: the river/scheduler/governor chain still gates every activation.
_MISSED_OR_NO_FILL_STATE_HINTS: Tuple[Tuple[str, str, float, str, str, str], ...] = (
    ("spread_pct", "ge", 0.0060, "MAX_SPREAD_PCT", "loosen", "spread_at_or_above_current_max"),
    ("expected_net_edge_pct", "lt", 0.0125, "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "loosen", "net_edge_below_current_minimum"),
    ("reward_to_fee", "lt", 3.0, "PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "loosen", "reward_to_fee_below_current_minimum"),
    ("reward_to_risk", "lt", 1.5, "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "loosen", "reward_to_risk_below_current_minimum"),
    ("liquidity_score", "lt", 0.50, "ORDERBOOK_LIQUIDITY_MIN_SCORE", "loosen", "liquidity_score_below_current_minimum"),
    ("orderbook_imbalance", "abs_lt", 0.15, "ORDERBOOK_IMBALANCE_MIN_ABS", "loosen", "orderbook_imbalance_below_current_minimum"),
    ("volume_ratio", "lt", 1.0, "VOLUME_CONFIRMATION_MIN", "loosen", "volume_ratio_below_current_minimum"),
    ("ticker_score", "lt", 50.0, "TICKER_SCORE_MIN", "loosen", "ticker_score_below_current_minimum"),
    ("confidence", "between", (0.45, 0.62), "JUDGE_MIN_GATE_CONFIDENCE", "loosen", "confidence_just_below_gate_threshold"),
)
_BAD_OUTCOME_STATE_HINTS: Tuple[Tuple[str, str, float, str, str, str], ...] = (
    ("spread_pct", "ge", 0.0060, "MAX_SPREAD_PCT", "tighten", "wide_spread_preceded_bad_outcome"),
    ("expected_net_edge_pct", "lt", 0.0125, "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "tighten", "thin_net_edge_preceded_bad_outcome"),
    ("reward_to_risk", "lt", 1.5, "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "tighten", "thin_reward_to_risk_preceded_bad_outcome"),
    ("confidence", "ge", 0.62, "JUDGE_MIN_GATE_CONFIDENCE", "tighten", "high_confidence_still_had_bad_outcome"),
    ("volatility_pct", "ge", 0.030, "VOLATILITY_MAX_PCT", "tighten", "high_volatility_preceded_bad_outcome"),
    ("drawdown_pct", "le", -0.05, "STOP_DISTANCE_PCT", "tighten", "deep_drawdown_preceded_bad_outcome"),
    ("liquidity_score", "lt", 0.50, "ORDERBOOK_LIQUIDITY_MIN_SCORE", "tighten", "low_liquidity_preceded_bad_outcome"),
)

# `classify_decision_outcome` (bot/decision_outcome_tracker.py) labels any
# stop-touched approved_entry/prepared_plan episode "false_positive_plan",
# regardless of what price did afterward -- it never lands in _BAD_LABELS, so
# without this dedicated rule STOP_DISTANCE_PCT never sees "loosen" evidence
# from the largest available data source. `mfe_pct` (max favorable excursion
# in the same decision window) is already a real, allowlisted state field
# (bot/reflection_learning_context.py::evaluate_decision_window); a stop that
# was touched while the window still moved favorably by >=1% is evidence the
# stop was tighter than the setup needed.
_STOP_TOO_TIGHT_LABELS = {"false_positive_plan"}
_STOP_TOO_TIGHT_STATE_HINTS: Tuple[Tuple[str, str, float, str, str, str], ...] = (
    ("mfe_pct", "ge", 0.01, "STOP_DISTANCE_PCT", "loosen", "stop_touched_but_favorable_move_still_occurred_in_window"),
)

# No trailing-specific evidence existed at all before this: `exit_efficiency_proxy`
# (bot/decision_outcome_tracker.py::compute_path_metrics, final_change_pct / mfe)
# is already computed for every resolved decision but was never surfaced past
# _compact_outcome() or read into the GrowBot/River state contract. A
# genuinely favorable episode (label == "plan_follow_through") whose price
# still moved favorably (mfe_pct) but had mostly reverted by the end of the
# decision window (a low exit_efficiency_proxy) is evidence that a live
# trailing stop would have locked in more of that move -- i.e. the trailing
# distance is wider than the setup needed. This does not distinguish "trigger
# too high" from "distance too wide" (both would show the same signature
# here), so it only targets the distance parameter, which this data can
# support without overreaching.
_TRAILING_TOO_LOOSE_LABELS = {"plan_follow_through"}
_TRAILING_TOO_LOOSE_MIN_MFE_PCT = 0.01
_TRAILING_TOO_LOOSE_MAX_EXIT_EFFICIENCY = 0.3


def _trailing_too_loose_hint(state: Mapping[str, Any]) -> List[Dict[str, str]]:
    mfe = _as_float(state.get("mfe_pct"), default=float("nan"))
    efficiency = _as_float(state.get("exit_efficiency_proxy"), default=float("nan"))
    if mfe != mfe or efficiency != efficiency:
        return []
    if mfe >= _TRAILING_TOO_LOOSE_MIN_MFE_PCT and efficiency <= _TRAILING_TOO_LOOSE_MAX_EXIT_EFFICIENCY:
        return [{
            "parameter": "PHASE_D2_DEFAULT_TRAILING_DISTANCE_PCT",
            "direction": "tighten",
            "reason": "favorable_move_mostly_given_back_before_window_end",
        }]
    return []


def _threshold_hit(state: Mapping[str, Any], key: str, comparator: str, threshold: Any) -> bool:
    value = _as_float(state.get(key), default=float("nan"))
    if value != value:  # NaN: field not present in this episode's state
        return False
    if comparator == "ge":
        return value >= float(threshold)
    if comparator == "le":
        return value <= float(threshold)
    if comparator == "lt":
        return value < float(threshold)
    if comparator == "abs_lt":
        return abs(value) < float(threshold)
    if comparator == "between":
        low, high = threshold
        return float(low) <= value < float(high)
    return False


def _state_threshold_hints(state: Mapping[str, Any], rules: Sequence[Tuple[str, str, float, str, str, str]]) -> List[Dict[str, str]]:
    hints: List[Dict[str, str]] = []
    for key, comparator, threshold, parameter, direction, reason in rules:
        if _threshold_hit(state, key, comparator, threshold):
            hints.append({"parameter": parameter, "direction": direction, "reason": reason})
    return hints


def _parameter_hints(label: str, row: Mapping[str, Any], state: Mapping[str, Any]) -> List[Dict[str, str]]:
    text = " ".join(str(row.get(key) or "").lower() for key in ("main_blocker", "blocker", "reason", "labels"))
    hints: List[Dict[str, str]] = []
    mapped = (
        ("spread", "MAX_SPREAD_PCT", "loosen"),
        ("expected_net_edge", "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "loosen"),
        ("reward_to_fee", "PHASE_D2_MIN_REWARD_TO_FEE_RATIO", "loosen"),
        ("reward_to_risk", "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "loosen"),
        ("target_distance", "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT", "loosen"),
    )
    is_missed_or_no_fill = any(marker in label for marker in _MISSED_LABEL_MARKERS)
    if is_missed_or_no_fill:
        for marker, parameter, direction in mapped:
            if marker in text:
                hints.append({"parameter": parameter, "direction": direction, "reason": f"{marker}_cluster"})
        hints.extend(_state_threshold_hints(state, _MISSED_OR_NO_FILL_STATE_HINTS))
    if label in _BAD_LABELS:
        hints.extend([
            {"parameter": "MAX_SPREAD_PCT", "direction": "tighten", "reason": "adverse_or_bad_entry"},
            {"parameter": "PHASE_D2_MIN_EXPECTED_NET_EDGE_PCT", "direction": "tighten", "reason": "adverse_or_bad_entry"},
            {"parameter": "PHASE_D2_MIN_REWARD_TO_RISK_RATIO", "direction": "tighten", "reason": "adverse_or_bad_entry"},
        ])
        hints.extend(_state_threshold_hints(state, _BAD_OUTCOME_STATE_HINTS))
    if label in _STOP_TOO_TIGHT_LABELS:
        hints.extend(_state_threshold_hints(state, _STOP_TOO_TIGHT_STATE_HINTS))
    if label in _TRAILING_TOO_LOOSE_LABELS:
        hints.extend(_trailing_too_loose_hint(state))
    # Deduplicate by (parameter, direction): a single episode must not inflate
    # one parameter's evidence count just because several rules fired for it.
    deduped: Dict[Tuple[str, str], Dict[str, str]] = {}
    for hint in hints:
        key = (hint["parameter"], hint["direction"])
        deduped.setdefault(key, hint)
    return list(deduped.values())


def normalize_episode(source: str, row: Mapping[str, Any], *, ordinal: int = 0) -> Dict[str, Any]:
    """Translate an existing outcome/reflection row into a GrowBot episode."""
    label = _label(row)
    reward, reward_reasons = _reward(label, row)
    occurred_at = str(row.get("decision_time") or row.get("created_at") or row.get("generated_at") or "")
    ticker = str(row.get("ticker") or "unknown")
    identity = {
        "source": source,
        "occurred_at": occurred_at,
        "ticker": ticker,
        "label": label,
        "client_order_id": row.get("client_order_id"),
        "reflection_event_id": row.get("event_id"),
        "decision": row.get("decision") or row.get("decision_type") or row.get("execution_action"),
        "reason": row.get("reason") or row.get("main_blocker"),
    }
    # Keep the v1-compatible base identity so an existing append-only ledger
    # can retain its first observation.  `build_episodes` adds a stable
    # evidence-hash suffix only when this compact identity collides.
    episode_id = hashlib.sha256(json.dumps(identity, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    evidence_hash = hashlib.sha256(json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()
    learning_context = _learning_context(row)
    state = _state(row, learning_context=learning_context)
    return {
        "episode_id": episode_id,
        "base_episode_id": episode_id,
        "episode_id_scheme": EPISODE_ID_SCHEME,
        "evidence_hash": evidence_hash,
        "source": source,
        "occurred_at": occurred_at,
        "episode_type": _episode_type(source, label, row),
        "ticker": ticker,
        "label": label,
        "state": state,
        "regime": _regime(row, learning_context=learning_context),
        "decision_context": {
            "decision": row.get("decision") or row.get("decision_type") or row.get("execution_action"),
            "setup_type": row.get("setup_type") or "unknown",
            "main_blocker": row.get("main_blocker") or row.get("blocker") or "",
        },
        "compact_evidence": _compact_evidence(label, row, learning_context=learning_context),
        "action": "parameter_setting_or_threshold_selection",
        "reward": reward,
        "reward_reasons": reward_reasons,
        "parameter_hints": _parameter_hints(label, row, state),
        "raw_evidence_ref": {"source": source, "ticker": ticker, "label": label},
        "execution_authority": False,
    }


def _source_rows(root: Path, *, max_per_source: int) -> Tuple[List[Tuple[str, Dict[str, Any]]], Dict[str, Any]]:
    rows: List[Tuple[str, Dict[str, Any]]] = []
    sources: Dict[str, Any] = {}
    reflection = _load_json(root / SOURCE_PATHS[0][1])
    evaluations = reflection.get("evaluations") if isinstance(reflection.get("evaluations"), list) else []
    valid_evaluations = [row for row in evaluations if isinstance(row, dict) and _label(row) != "insufficient_evidence"]
    for row in valid_evaluations[-max_per_source:]:
        rows.append(("reflection", row))
    sources["reflection"] = {"path": str(SOURCE_PATHS[0][1]), "records_loaded": len(valid_evaluations[-max_per_source:]), "available": bool(reflection)}

    for source, relative in SOURCE_PATHS[1:4]:
        loaded, corrupt = _load_jsonl_tail(root / relative, max_per_source)
        expanded: List[Dict[str, Any]] = []
        for row in loaded:
            if source == "decision_outcome":
                records = row.get("records")
                if isinstance(records, list):
                    expanded.extend(item for item in records if isinstance(item, dict))
                # Rows without a "records" list are engine-level count-only
                # heartbeats (e.g. "decision_outcome_snapshots_stored_by_engine").
                # They carry no decision evidence and must be dropped rather
                # than counted as zero-state episodes.
            elif source == "trade_reflection":
                reflection_row = row.get("reflection")
                if isinstance(reflection_row, dict):
                    expanded.append(dict(reflection_row))
                # Rows without a "reflection" dict are periodic
                # "trade_learning_cycle_summary" heartbeats; dropped for the
                # same reason.
            else:
                expanded.append(row)
        rows.extend((source, row) for row in expanded[-max_per_source:])
        sources[source] = {"path": str(relative), "records_loaded": len(expanded[-max_per_source:]), "corrupt_lines": corrupt, "available": (root / relative).exists()}

    backtest = _load_json(root / SOURCE_PATHS[4][1])
    raw_results = backtest.get("results") if isinstance(backtest, dict) else None
    result_rows = raw_results if isinstance(raw_results, list) else ([raw_results] if isinstance(raw_results, dict) else [])
    backtest_rows = 0
    for result in result_rows:
        if not isinstance(result, dict):
            continue
        labels = _as_dict(result.get("labels"))
        for label, count in labels.items():
            if _as_float(count) <= 0:
                continue
            rows.append(("backtest", {
                "generated_at": backtest.get("generated_at"),
                "ticker": result.get("ticker") or "backtest",
                "label": label,
                "sample_weight": int(_as_float(count)),
                "market_regime": "backtest",
                "timeframe": result.get("timeframe") or "historical",
                "reason": "historical_parameter_backtest_label_count",
            }))
            backtest_rows += 1
    sources["backtest"] = {"path": str(SOURCE_PATHS[4][1]), "records_loaded": backtest_rows, "available": bool(backtest)}
    # The existing neural policy remains shadow-only.  Its report is recorded
    # as context for provenance, not converted into a parameter vote.
    neural_shadow = _load_json(root / NEURAL_SHADOW_REPORT_PATH)
    sources["neural_shadow"] = {
        "path": str(NEURAL_SHADOW_REPORT_PATH),
        "available": bool(neural_shadow),
        "backend": neural_shadow.get("backend") if neural_shadow else "",
        "sample_count": neural_shadow.get("sample_count") if neural_shadow else 0,
        "parameter_suggestion_count": len(_as_dict(neural_shadow.get("parameter_suggestions"))),
        "use": "provenance_only_shadow_policy_not_a_direct_parameter_vote",
    }
    return rows, sources


def build_episodes(root: Path = Path("."), *, max_per_source: int = 1500) -> Dict[str, Any]:
    source_rows, sources = _source_rows(root, max_per_source=max_per_source)
    episodes: List[Dict[str, Any]] = []
    evidence_by_base: Dict[str, set[str]] = {}
    source_duplicates = 0
    collision_resolutions = 0
    for index, (source, row) in enumerate(source_rows):
        episode = normalize_episode(source, row, ordinal=index)
        base_id = str(episode["base_episode_id"])
        evidence_hash = str(episode["evidence_hash"])
        prior_hashes = evidence_by_base.setdefault(base_id, set())
        if evidence_hash in prior_hashes:
            source_duplicates += 1
            continue
        if prior_hashes:
            episode["episode_id"] = hashlib.sha256(f"{base_id}:{evidence_hash}".encode("utf-8")).hexdigest()
            collision_resolutions += 1
        prior_hashes.add(evidence_hash)
        episodes.append(episode)
    return {
        "episodes": episodes,
        "sources": sources,
        "episode_identity": {
            "scheme": EPISODE_ID_SCHEME,
            "raw_source_rows": len(source_rows),
            "source_duplicate_rows_dropped": source_duplicates,
            "compact_identity_collisions_resolved": collision_resolutions,
        },
    }


def _ledger_ids(path: Path) -> set[str]:
    rows, _ = _load_jsonl_tail(path, 10_000_000)
    return {str(row.get("episode_id")) for row in rows if str(row.get("episode_id") or "")}


def append_new_episodes(episodes: Sequence[Mapping[str, Any]], *, root: Path = Path("."), path: Path = EPISODE_LEDGER_PATH) -> Dict[str, int]:
    """Append unique episodes; never rewrite or delete the learning memory."""
    ledger = root / path
    ledger.parent.mkdir(parents=True, exist_ok=True)
    existing = _ledger_ids(ledger)
    added = 0
    with ledger.open("a", encoding="utf-8") as handle:
        for episode in episodes:
            episode_id = str(episode.get("episode_id") or "")
            if not episode_id or episode_id in existing:
                continue
            handle.write(json.dumps(dict(episode), sort_keys=True, separators=(",", ":"), default=str) + "\n")
            existing.add(episode_id)
            added += 1
    return {"added": added, "existing_or_duplicate": max(0, len(episodes) - added), "total_after": len(existing)}


def summarize_episodes(episodes: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    rows = list(episodes)
    labels = Counter(str(row.get("label") or "neutral") for row in rows)
    types = Counter(str(row.get("episode_type") or "unknown") for row in rows)
    rewards = [_as_float(row.get("reward")) for row in rows]
    regimes = sorted({str(row.get("regime") or "unknown") for row in rows})
    known_regime_rows = [row for row in rows if str(row.get("regime") or "unknown") not in {"unknown", "backtest"}]
    hint_count = sum(len(row.get("parameter_hints") or []) for row in rows if isinstance(row, Mapping))
    return {
        "episode_count": len(rows),
        "label_counts": dict(labels),
        "episode_type_counts": dict(types),
        "reward_summary": {
            "average_reward": round(sum(rewards) / len(rewards), 6) if rewards else 0.0,
            "positive_reward_count": sum(1 for value in rewards if value > 0),
            "negative_reward_count": sum(1 for value in rewards if value < 0),
            "neutral_reward_count": sum(1 for value in rewards if value == 0),
        },
        "regimes": regimes,
        "distinct_known_regime_count": len([regime for regime in regimes if regime not in {"unknown", "backtest"}]),
        "regime_evidence": {
            "known_regime_episode_count": len(known_regime_rows),
            "unknown_or_non_market_regime_episode_count": len(rows) - len(known_regime_rows),
            "known_regime_coverage_pct": round((len(known_regime_rows) / len(rows)) * 100.0, 4) if rows else 0.0,
            "non_market_regimes_excluded": ["backtest"],
        },
        "parameter_hint_count": hint_count,
    }


def validate_episode_contracts(episodes: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Validate evidence quality without filling gaps from current context."""
    rows = list(episodes)
    required_fields = {
        "episode_id": str,
        "source": str,
        "episode_type": str,
        "state": dict,
        "regime": str,
        "decision_context": dict,
        "action": str,
        "reward": (int, float),
        "reward_reasons": list,
        "raw_evidence_ref": dict,
    }
    missing_by_field = Counter()
    invalid_rows = 0
    source_counts = Counter()
    state_nonempty = 0
    outcome_evidence = 0
    known_regime = 0
    parameter_hints = 0
    for row in rows:
        if not isinstance(row, Mapping):
            invalid_rows += 1
            continue
        source_counts[str(row.get("source") or "unknown")] += 1
        row_invalid = False
        for field, expected_type in required_fields.items():
            value = row.get(field)
            if not isinstance(value, expected_type) or (expected_type is str and not str(value).strip()):
                missing_by_field[field] += 1
                row_invalid = True
        if row_invalid:
            invalid_rows += 1
        if isinstance(row.get("state"), Mapping) and row.get("state"):
            state_nonempty += 1
        if abs(_as_float(row.get("reward"))) > 0:
            outcome_evidence += 1
        if str(row.get("regime") or "").strip().lower() not in {"", "unknown", "backtest", "historical", "none", "null"}:
            known_regime += 1
        if isinstance(row.get("parameter_hints"), list):
            parameter_hints += len(row["parameter_hints"])
    total = len(rows)
    coverage = lambda count: round((count / total) * 100.0, 4) if total else 0.0
    syntactic_pass = total > 0 and invalid_rows == 0
    feature_coverage = coverage(state_nonempty)
    regime_coverage = coverage(known_regime)
    outcome_coverage = coverage(outcome_evidence)
    promotion_blockers: List[str] = []
    if not syntactic_pass:
        promotion_blockers.append("episode_contract_invalid")
    if feature_coverage < 80.0:
        promotion_blockers.append("insufficient_feature_snapshot_coverage")
    if regime_coverage < 80.0:
        promotion_blockers.append("insufficient_regime_enrichment_coverage")
    if outcome_coverage < 50.0:
        promotion_blockers.append("insufficient_observed_outcome_coverage")
    if parameter_hints < 40:
        promotion_blockers.append("insufficient_parameter_directional_evidence")
    return {
        "schema_version": EPISODE_CONTRACT_VERSION,
        "episode_count": total,
        "syntactic_contract_passed": syntactic_pass,
        "invalid_episode_count": invalid_rows,
        "missing_or_invalid_fields": dict(missing_by_field),
        "source_counts": dict(source_counts),
        "coverage": {
            "nonempty_feature_state_pct": feature_coverage,
            "known_market_regime_pct": regime_coverage,
            "observed_nonzero_reward_pct": outcome_coverage,
            "parameter_hint_count": parameter_hints,
        },
        "parameter_promotion_evidence_ready": False,
        "promotion_blockers": promotion_blockers,
        "policy": {
            "unknown_fields_are_not_inferred": True,
            "learning_to_execution_allowed": False,
            "approved_profile_route_required": True,
        },
    }


def build_growbot_episode_report(
    root: Path = Path("."),
    *,
    max_per_source: int = 1500,
    append_memory: bool = True,
    growbot_source_path: str | Path | None = None,
) -> Dict[str, Any]:
    built = build_episodes(root, max_per_source=max_per_source)
    episodes = built["episodes"]
    memory = append_new_episodes(episodes, root=root) if append_memory else {"added": 0, "existing_or_duplicate": len(episodes), "total_after": 0}
    summary = summarize_episodes(episodes)
    learning_data_contract = validate_episode_contracts(episodes)
    return {
        "phase": GROWBOT_PHASE,
        "generated_at": now_iso(),
        "episode_model": {
            "episode": "trade cycle or missed opportunity",
            "state": "feature_pack + regime + decision context",
            "action": "parameter setting / threshold / sizing choice",
            "reward": "net PnL, avoided loss, missed opportunity, fill quality and fee impact",
            "memory": "append-only learning ledger",
            "policy": "report-only parameter proposal",
        },
        "growbot_open_source": discover_growbot_open_source(root, source_path=growbot_source_path),
        "sources": built["sources"],
        "episode_identity": built["episode_identity"],
        "summary": summary,
        "learning_data_contract": learning_data_contract,
        "memory": {"path": str(EPISODE_LEDGER_PATH), "append_only": True, **memory},
        "episodes": episodes,
        "safety_policy": {
            "report_only": True,
            "no_coinbase_calls": True,
            "order_submission_allowed": False,
            "parameter_mutation_allowed": False,
            "approved_profile_route_required": True,
        },
    }


def write_growbot_episode_report(report: Mapping[str, Any], *, root: Path = Path("."), path: Path = REPORT_PATH) -> str:
    output = root / path
    atomic_write_json(output, dict(report))
    return str(output)


__all__ = [
    "EPISODE_LEDGER_PATH",
    "EPISODE_CONTRACT_VERSION",
    "GROWBOT_PHASE",
    "GROWBOT_UPSTREAM_COMMIT",
    "GROWBOT_UPSTREAM_LICENSE",
    "GROWBOT_UPSTREAM_REPOSITORY",
    "REPORT_PATH",
    "append_new_episodes",
    "build_episodes",
    "build_growbot_episode_report",
    "discover_growbot_open_source",
    "normalize_episode",
    "summarize_episodes",
    "validate_episode_contracts",
    "write_growbot_episode_report",
]
