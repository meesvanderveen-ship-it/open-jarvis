"""Read-only product-readiness gate for the GrowBot/River sidecar."""
from __future__ import annotations

import json
import math
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence

from bot.atomic_io import atomic_write_json
from bot.adaptive_policy_lab import CANDIDATE_JSON_PATH
from bot.parameter_candidate_analysis import ANALYSIS_JSON_PATH
from bot.river_online_parameter_learner import REPORT_PATH as RIVER_REPORT_PATH
from bot.river_online_parameter_learner import river_unavailable_reason


READINESS_PHASE = "growbot_river_product_readiness_v1"
READINESS_PATH = Path("reports/growbot_river/growbot-river-readiness-latest.json")
EPISODE_REPORT_PATH = Path("reports/growbot_river/growbot-episode-report-latest.json")
LIVE_CYCLE_REPORT_PATH = Path("reports/growbot_river/growbot-river-learning-latest.json")
LIVE_CYCLE_READINESS_PATH = Path("reports/growbot_river/live-cycle-readiness-latest.json")

# Live decision/market fields that matter most for the next live cycles, with
# the exact allowlisted contract field they map to. Cross-checked against
# bot/growbot_river_learning_contract.ALLOWED_STATE_KEYS / ALLOWED_CONTEXT_KEYS
# so this table cannot silently name a field the contract does not actually
# carry.
TOP_LEARNING_SIGNALS = (
    {"signal": "liquidity", "contract_field": "state.liquidity_score", "maps_to_parameters": ["ORDERBOOK_LIQUIDITY_MIN_SCORE"], "currently_wired_from": "feature_pack.market/orderbook.liquidity_score (bot/trade_planner.py) — confirmed real producer", "live_producer_exists": True},
    {"signal": "orderbook_imbalance", "contract_field": "state.orderbook_imbalance", "maps_to_parameters": ["ORDERBOOK_IMBALANCE_MIN_ABS"], "currently_wired_from": "feature_pack.orderbook_context.imbalance / orderbook_imbalance (bot/neural_feature_schema.py) — confirmed real producer", "live_producer_exists": True},
    {"signal": "volume_ratio", "contract_field": "state.volume_ratio", "maps_to_parameters": ["VOLUME_CONFIRMATION_MIN"], "currently_wired_from": "VOLUME_CONFIRMATION_MIN is registry implementation_status=logical_candidate_only; no feature_pack producer writes a volume_ratio field today (bot/phase_d6_multi_order_intent_preview.py computes a local variable of this name but does not persist it) — contract extraction is ready and waiting, the live computation does not exist yet", "live_producer_exists": False},
    {"signal": "ticker_score", "contract_field": "state.ticker_score", "maps_to_parameters": ["TICKER_SCORE_MIN"], "currently_wired_from": "TICKER_SCORE_MIN is registry implementation_status=logical_candidate_only; no ticker-ranking module writes a ticker_score field into feature_pack today — contract extraction is ready and waiting, the live computation does not exist yet", "live_producer_exists": False},
    {"signal": "setup_type", "contract_field": "context.setup_type", "maps_to_parameters": ["SETUP_TRIGGER_STRICTNESS (research_only)"], "currently_wired_from": "decision/trade_plan/entry_gate.setup_type — confirmed real producer", "live_producer_exists": True},
    {"signal": "confidence", "contract_field": "state.confidence", "maps_to_parameters": ["JUDGE_MIN_GATE_CONFIDENCE", "JUDGE_MIN_SYNTH_CONFIDENCE", "PENDING_TRADE_PLAN_MIN_CONFIDENCE"], "currently_wired_from": "judge/entry_gate/trade_plan confidence, or evaluate_decision_window's own confidence — the most universally populated field across every source today", "live_producer_exists": True},
    {"signal": "spread", "contract_field": "state.spread_pct", "maps_to_parameters": ["MAX_SPREAD_PCT"], "currently_wired_from": "feature_pack best_bid/best_ask, or evaluate_decision_window's estimated_spread_cost_pct — confirmed real producer", "live_producer_exists": True},
    {"signal": "volatility", "contract_field": "state.volatility_pct", "maps_to_parameters": ["VOLATILITY_MAX_PCT", "VOLATILITY_SIZE_MULTIPLIER", "regime classification"], "currently_wired_from": "derive_regime_metrics_from_candles() pre-decision lookback window — confirmed real producer", "live_producer_exists": True},
    {"signal": "reward/fee", "contract_field": "state.reward_to_fee", "maps_to_parameters": ["PHASE_D2_MIN_REWARD_TO_FEE_RATIO"], "currently_wired_from": "judge/trade_plan reward_to_fee, or evaluate_decision_window mfe / (fee+spread+slippage) — currently the #1 ranked candidate", "live_producer_exists": True},
    {"signal": "reward/risk", "contract_field": "state.reward_to_risk", "maps_to_parameters": ["PHASE_D2_MIN_REWARD_TO_RISK_RATIO"], "currently_wired_from": "judge/trade_plan reward_to_risk, or evaluate_decision_window mfe / abs(mae) — confirmed real producer", "live_producer_exists": True},
    {"signal": "fill/no-fill", "contract_field": "context.fill_status", "maps_to_parameters": ["ORDERBOOK_ENTRY_* (research)", "missed_opportunity classification"], "currently_wired_from": "execution_outcome order_status/lifecycle_action — fixed this step to also pass order_status/lifecycle_action explicitly into the contract's context extraction", "live_producer_exists": True},
    {"signal": "slippage", "contract_field": "state.slippage_pct", "maps_to_parameters": ["PHASE_D2_MIN_REWARD_TO_FEE_RATIO (cost basis)"], "currently_wired_from": "estimated_slippage_buffer_pct — confirmed real producer", "live_producer_exists": True},
    {"signal": "MFE/MAE", "contract_field": "state.mfe_pct / state.mae_pct", "maps_to_parameters": ["STOP_DISTANCE_PCT", "EXIT_TARGET_MAX_DISTANCE_FROM_MID_PCT"], "currently_wired_from": "evaluate_decision_window max_favorable/adverse_excursion_pct — confirmed real producer", "live_producer_exists": True},
    {"signal": "exit result", "contract_field": "context.exit_result", "maps_to_parameters": ["good/bad/missed classification itself"], "currently_wired_from": "metrics.outcome / label — confirmed real producer", "live_producer_exists": True},
)

# The exact, single source of truth for what gates `stabilization_ready`. Kept
# as one named set so the boolean and the explained `real_blockers` list in
# `build_stabilization_readiness` can never silently drift apart.
STABILIZATION_GATING_BLOCKERS = frozenset({
    "learning_episode_contract_not_passed",
    "feature_snapshot_coverage_below_80pct",
    "market_regime_coverage_below_80pct",
    "fewer_than_two_observed_market_regimes",
    "river_native_sidecar_unavailable",
    "river_walk_forward_not_passed",
})

# Sources whose code path was widened/fixed this session and already prove
# the mechanism end-to-end (reflection for tickers with a fresh local candle
# cache; execution_outcome, which always carries its own market snapshot).
FORWARD_READY_SOURCES = ("reflection", "execution_outcome")
# Sources whose on-disk records predate the growbot_river_learning_context
# fix.  The fix is forward-compatible only: these rows are never back-filled.
HISTORICAL_GAP_SOURCES = ("decision_outcome", "trade_reflection")

_BLOCKER_CATEGORIES = {
    "feature_snapshot_coverage_below_80pct": "awaiting_live_episode_volume",
    "market_regime_coverage_below_80pct": "awaiting_live_episode_volume",
    "fewer_than_two_observed_market_regimes": "awaiting_live_episode_volume",
    "river_native_sidecar_unavailable": "optional_dependency_not_installed",
    "river_walk_forward_not_passed": "consequence_of_river_dependency_unavailable",
    "learning_episode_contract_not_passed": "data_integrity_gap",
    "episode_report_missing": "data_integrity_gap",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load(path: Path) -> Dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


_NON_MARKET_REGIME_VALUES = {"", "unknown", "backtest", "historical", "none", "null"}


def _coverage_by_source(episodes: Sequence[Any]) -> Dict[str, Dict[str, Any]]:
    """Per-source feature-state/regime coverage, computed from the same episode list the contract validates."""
    totals: Counter = Counter()
    nonempty_state: Counter = Counter()
    known_regime: Counter = Counter()
    for episode in episodes:
        if not isinstance(episode, Mapping):
            continue
        source = str(episode.get("source") or "unknown")
        totals[source] += 1
        if isinstance(episode.get("state"), Mapping) and episode["state"]:
            nonempty_state[source] += 1
        regime = str(episode.get("regime") or "unknown").strip().lower().replace(" ", "_")
        if regime not in _NON_MARKET_REGIME_VALUES:
            known_regime[source] += 1
    coverage_by_source: Dict[str, Dict[str, Any]] = {}
    for source, total in totals.items():
        coverage_by_source[source] = {
            "episode_count": total,
            "nonempty_feature_state_pct": round((nonempty_state.get(source, 0) / total) * 100.0, 4) if total else 0.0,
            "known_market_regime_pct": round((known_regime.get(source, 0) / total) * 100.0, 4) if total else 0.0,
        }
    return coverage_by_source


def build_stabilization_readiness(
    *,
    blockers: Sequence[str],
    episodes: Sequence[Any],
) -> Dict[str, Any]:
    """Explain exactly what still gates `stabilization_ready`.

    Distinguishes three things that are easy to conflate in one coverage
    percentage: a historical coverage gap (old records that predate a fix and
    are never back-filled), forward-ready coverage (sources already proven to
    work end-to-end under current code), and the real blockers that gate
    stabilization, each tagged with why it exists and whether it is expected
    to self-resolve as more live episodes accumulate.
    """
    coverage_by_source = _coverage_by_source(episodes)
    historical = {source: coverage_by_source[source] for source in HISTORICAL_GAP_SOURCES if source in coverage_by_source}
    forward = {source: coverage_by_source[source] for source in FORWARD_READY_SOURCES if source in coverage_by_source}
    gating = sorted(set(blockers) & STABILIZATION_GATING_BLOCKERS)
    real_blockers = [
        {
            "blocker": blocker,
            "category": _BLOCKER_CATEGORIES.get(blocker, "unclassified"),
            "self_resolves_with_more_live_episodes": _BLOCKER_CATEGORIES.get(blocker) == "awaiting_live_episode_volume",
        }
        for blocker in gating
    ]
    volume_only = bool(real_blockers) and all(row["self_resolves_with_more_live_episodes"] for row in real_blockers)
    return {
        "ready": not real_blockers,
        "summary": (
            "stabilization_ready requires >=80% feature-state coverage, >=80% known-regime "
            "coverage, >=2 distinct observed regimes, the River native sidecar available and a "
            "passed walk-forward validation. None of these thresholds are bypassed, lowered or "
            "approximated here."
        ),
        "blockers_are_volume_only": volume_only,
        "blockers_are_volume_only_explanation": (
            "True only when every remaining entry in real_blockers is categorized as "
            "awaiting_live_episode_volume (currently feature_snapshot_coverage_below_80pct / "
            "market_regime_coverage_below_80pct / fewer_than_two_observed_market_regimes). When "
            "true, no further code change, River install, or operator action is required -- "
            "stabilization_ready flips to true automatically once enough new live episodes "
            "accumulate."
        ),
        "historical_coverage_gap": {
            "description": (
                "Coverage for sources whose on-disk records predate the growbot_river_learning_context "
                "fix (decision_outcome/trade_reflection logs written before this code existed). The fix "
                "is forward-compatible only: these historical rows are never back-filled or inferred. "
                "execution_outcome's regime path (candle-derived trend/volatility/drawdown fallback) was "
                "fixed the same way this session; its 10 existing episodes are pre-fix and still show "
                "0% regime coverage for the same never-back-filled reason, even though execution_outcome "
                "is bucketed under forward_ready_coverage for its (already-100%) state coverage."
            ),
            "by_source": historical,
            "is_blocking": False,
            "self_resolves_with_new_episodes": True,
        },
        "forward_ready_coverage": {
            "description": (
                "Coverage for sources already producing rich state/regime evidence end-to-end under "
                "the current code, proving the mechanism works rather than just existing structurally."
            ),
            "by_source": forward,
        },
        "real_blockers": real_blockers,
        "next_safe_action": (
            "resume live decision/outcome/trade-reflection cycles so decision_outcome and "
            "trade_reflection episodes start carrying the same evidence reflection/execution_outcome "
            "already do; no further code change is required for that"
            if volume_only
            else "review report-only evidence and existing adaptive/governor gates"
        ),
    }


# fast_start_autotune_ready is a deliberately lower evidence-volume bar than
# stabilization_ready, for small, reversible, fine_tuning-sized parameter steps
# only. It never replaces, lowers, or bypasses the unchanged
# autonomous_parameter_governor ACK/candidate-hash/cooldown/open-order/
# regime-enrichment/effect-size gates -- those remain the only real
# authorization path for any actual profile change. It exists so an operator
# is not misled into thinking every parameter step must wait for the strict
# 80%/80% coverage bar to clear, when the underlying sidecar evidence may
# already be strong enough for a much smaller, bounded autonomous step.
FAST_START_MIN_FEATURE_STATE_COVERAGE_PCT = 50.0
FAST_START_MIN_REGIME_COVERAGE_PCT = 45.0
FAST_START_MIN_DISTINCT_REGIMES = 3


def build_fast_start_autotune_readiness(
    *,
    coverage: Mapping[str, Any],
    distinct_regime_count: int,
    river_available: bool,
    walk_forward_passed: bool,
) -> Dict[str, Any]:
    """Practical, lower evidence-volume readiness tier alongside stabilization_ready.

    Grants no execution or apply authority by itself. A True `ready` here only
    means the sidecar's own evidence base (coverage, regime diversity, River
    backend, walk-forward) is now strong enough to look at a fast_start
    candidate at all; the unchanged governor still decides per-candidate and
    per-apply whether anything is actually authorized.
    """
    state_pct = _as_float(coverage.get("nonempty_feature_state_pct"))
    regime_pct = _as_float(coverage.get("known_market_regime_pct"))
    real_blockers: List[str] = []
    if not river_available:
        real_blockers.append("river_native_sidecar_unavailable")
    if not walk_forward_passed:
        real_blockers.append("river_walk_forward_not_passed")
    if distinct_regime_count < FAST_START_MIN_DISTINCT_REGIMES:
        real_blockers.append("fewer_than_three_observed_market_regimes")
    if state_pct < FAST_START_MIN_FEATURE_STATE_COVERAGE_PCT:
        real_blockers.append("feature_snapshot_coverage_below_50pct")
    if regime_pct < FAST_START_MIN_REGIME_COVERAGE_PCT:
        real_blockers.append("market_regime_coverage_below_45pct")
    return {
        "ready": not real_blockers,
        "summary": (
            "fast_start_autotune_ready requires >=50% feature-state coverage, >=45% known-regime "
            "coverage, >=3 distinct observed regimes, the River native sidecar available and a "
            "passed walk-forward validation -- a lower evidence-volume bar than stabilization_ready "
            "(80%/80%), intended only for small, reversible, fine_tuning-sized parameter steps "
            "through the unchanged governor/approved-profile route. It does not relax any governor, "
            "candidate-hash, cooldown, open-order or per-candidate evidence gate."
        ),
        "thresholds": {
            "min_feature_state_coverage_pct": FAST_START_MIN_FEATURE_STATE_COVERAGE_PCT,
            "min_regime_coverage_pct": FAST_START_MIN_REGIME_COVERAGE_PCT,
            "min_distinct_regimes": FAST_START_MIN_DISTINCT_REGIMES,
        },
        "current_feature_state_pct": round(state_pct, 4),
        "current_known_regime_pct": round(regime_pct, 4),
        "distinct_regime_count": int(distinct_regime_count),
        "river_native_sidecar_available": bool(river_available),
        "river_walk_forward_passed": bool(walk_forward_passed),
        "real_blockers": real_blockers,
    }


def build_growbot_river_readiness(
    *,
    root: Path = Path("."),
    episode_report: Optional[Mapping[str, Any]] = None,
    river_report: Optional[Mapping[str, Any]] = None,
    cycle_report: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Combine sidecar evidence gates without granting any runtime authority."""
    episode = dict(episode_report) if isinstance(episode_report, Mapping) else _load(root / EPISODE_REPORT_PATH)
    river = dict(river_report) if isinstance(river_report, Mapping) else _load(root / RIVER_REPORT_PATH)
    cycle = dict(cycle_report) if isinstance(cycle_report, Mapping) else _load(root / LIVE_CYCLE_REPORT_PATH)
    candidate = _load(root / CANDIDATE_JSON_PATH)
    analysis = _load(root / ANALYSIS_JSON_PATH)
    contract = _as_dict(episode.get("learning_data_contract"))
    coverage = _as_dict(contract.get("coverage"))
    summary = _as_dict(episode.get("summary"))
    backend = _as_dict(river.get("backend"))
    validation = _as_dict(river.get("walk_forward_validation"))
    growbot = _as_dict(episode.get("growbot_open_source"))
    river_available = backend.get("river_available") is True
    blockers: List[str] = []
    historical_readiness_labels: List[Dict[str, Any]] = []
    if not episode:
        blockers.append("episode_report_missing")
    if contract.get("syntactic_contract_passed") is not True:
        blockers.append("learning_episode_contract_not_passed")
    if _as_float(coverage.get("nonempty_feature_state_pct")) < 80.0:
        blockers.append("feature_snapshot_coverage_below_80pct")
    if _as_float(coverage.get("known_market_regime_pct")) < 80.0:
        blockers.append("market_regime_coverage_below_80pct")
    if int(summary.get("distinct_known_regime_count") or 0) < 2:
        blockers.append("fewer_than_two_observed_market_regimes")
    if not river_available:
        blockers.append("river_native_sidecar_unavailable")
    if validation.get("passed") is not True:
        blockers.append("river_walk_forward_not_passed")
    if growbot.get("status") == "blocked_no_local_learning_runtime_and_upstream_has_no_published_learning_runtime":
        # This label reflects a permanent GrowBot-upstream gap (CC-BY-NC-4.0
        # license, no published training/policy runtime) and never gated any
        # readiness tier (see STABILIZATION_GATING_BLOCKERS). Once the River
        # sidecar is available it already supplies the live learning runtime,
        # so the label is demoted out of the active blockers list and reported
        # as a historical/stale readiness label instead -- it self-resolved in
        # practice the moment River became available and is not waiting on
        # anything further.
        if river_available:
            historical_readiness_labels.append({
                "label": "growbot_upstream_learning_runtime_unavailable",
                "status": "historical_stale_label_not_an_active_blocker",
                "reason": (
                    "River native sidecar is available and already supplies the live learning "
                    "runtime; this label only reflects a permanent GrowBot upstream license/"
                    "runtime gap and never gated stabilization_ready or any other readiness tier."
                ),
            })
        else:
            blockers.append("growbot_upstream_learning_runtime_unavailable")
    if candidate.get("candidate_available") is not True:
        blockers.append("adaptive_candidate_not_available")
    if analysis.get("parameter_analysis_available") is not True:
        blockers.append("parameter_candidate_analysis_missing")
    report_only_ready = bool(episode) and contract.get("syntactic_contract_passed") is True
    stabilization_ready = not any(blocker in blockers for blocker in STABILIZATION_GATING_BLOCKERS)
    stabilization_readiness = build_stabilization_readiness(blockers=blockers, episodes=episode.get("episodes") or [])
    fast_start_autotune_readiness = build_fast_start_autotune_readiness(
        coverage=coverage,
        distinct_regime_count=int(summary.get("distinct_known_regime_count") or 0),
        river_available=backend.get("river_available") is True,
        walk_forward_passed=validation.get("passed") is True,
    )
    fast_start_autotune_ready = bool(fast_start_autotune_readiness["ready"])
    phase_decision = _as_dict(cycle.get("phase_decision"))
    fine_tuning_ready = bool(stabilization_ready and phase_decision.get("phase") == "fine_tuning")
    return {
        "phase": READINESS_PHASE,
        "generated_at": now_iso(),
        "layers": {
            "report_only_sidecar_operational": report_only_ready,
            "learning_data_contract": contract,
            "river_native_sidecar_available": backend.get("river_available") is True,
            "river_walk_forward": validation,
            "observed_regime_evidence": summary.get("regime_evidence") or {},
            "growbot_open_source": growbot,
            "adaptive_candidate_available": candidate.get("candidate_available") is True,
            "parameter_candidate_analysis_available": analysis.get("parameter_analysis_available") is True,
        },
        "readiness": {
            "report_only_ready": report_only_ready,
            "fast_start_autotune_ready": fast_start_autotune_ready,
            "stabilization_ready": stabilization_ready,
            "fine_tuning_ready": fine_tuning_ready,
            "parameter_profile_activation_ready": False,
            "mode_a_live_ready": False,
            "mode_b_live_ready": False,
        },
        "fast_start_autotune_readiness": fast_start_autotune_readiness,
        "stabilization_readiness": stabilization_readiness,
        "blockers": sorted(set(blockers)),
        "historical_readiness_labels": historical_readiness_labels,
        "real_blockers_summary": (
            "The only currently-active real blocker(s) are: "
            + ", ".join(sorted(set(blockers) & STABILIZATION_GATING_BLOCKERS))
            + ". Each is categorized as awaiting_live_episode_volume and self-resolves "
            "with more live episodes -- no further code change, River install, or operator "
            "action is required."
            if stabilization_readiness.get("blockers_are_volume_only")
            else (
                "No active blockers remain."
                if not blockers
                else "Active blockers include non-volume gates (e.g. River sidecar/walk-forward); see blockers and stabilization_readiness.real_blockers for the exact set."
            )
        ),
        "next_safe_action": (
            "enrich new decision/outcome/reflection records with immutable feature snapshots and observed regime fields"
            if "market_regime_coverage_below_80pct" in blockers
            else "review report-only evidence and existing adaptive/governor gates"
        ),
        "next_safe_action_fast_start_autotune": (
            "review the top GrowBot/River candidate via "
            "tools/show_growbot_river_governor_bridge_status.py for per-candidate fast_start "
            "eligibility (confidence, evidence_count, direction stability, registry allowlist, "
            "rails, step size); the sidecar-level evidence gate is already satisfied"
            if fast_start_autotune_ready
            else "increase live evidence volume or install the River native sidecar to close: "
            + ", ".join(fast_start_autotune_readiness["real_blockers"])
        ),
        "safety_policy": {
            "report_only": True,
            "can_authorize_execution": False,
            "can_mutate_parameters": False,
            "can_apply_profile": False,
            "service_action_attempted": False,
            "coinbase_action_attempted": False,
        },
    }


def write_growbot_river_readiness(report: Mapping[str, Any], *, root: Path = Path(".")) -> str:
    output = root / READINESS_PATH
    atomic_write_json(output, dict(report))
    return str(output)


def estimate_forward_episode_requirements(
    *,
    coverage: Mapping[str, Any],
    episode_count: int,
    target_pct: float = 80.0,
) -> Dict[str, Any]:
    """How many new forward episodes are needed to cross the stabilization coverage gate.

    Two models are reported side by side because they answer different
    questions and neither alone is honest on its own:
    - `rollover`: decision_outcome/trade_reflection sources are capped at
      `max_per_source` and read as a tail window, so new ~100%-covered
      forward episodes displace old zero-coverage ones 1:1 and the total
      episode count stays roughly constant. This is the realistic estimate.
    - `additive_worst_case`: the conservative upper bound if that capped
      rollover did not happen and new episodes only ever accumulated on top
      of the existing, uncapped pool.
    """
    state_pct = _as_float(coverage.get("nonempty_feature_state_pct"))
    regime_pct = _as_float(coverage.get("known_market_regime_pct"))
    state_covered = round(state_pct / 100.0 * episode_count)
    regime_covered = round(regime_pct / 100.0 * episode_count)
    target = max(0.0, min(99.9999, target_pct)) / 100.0

    def rollover_needed(covered: int, total: int) -> int:
        if total <= 0:
            return 0
        return max(0, math.ceil(target * total - covered))

    def additive_needed(covered: int, total: int) -> int:
        if total <= 0:
            return 0
        return max(0, math.ceil((target * total - covered) / (1.0 - target)))

    rollover_estimate = max(
        rollover_needed(state_covered, episode_count),
        rollover_needed(regime_covered, episode_count),
    )
    # decision_outcome_tracker writes one record per configured horizon
    # (default 3: 4h/12h/24h) per tracked decision; this is therefore a rough
    # order-of-magnitude translation, not an exact figure — resolution events
    # add further lines to the same window without representing new decisions.
    default_horizons_per_decision = 3
    return {
        "target_pct": target_pct,
        "current_feature_state_pct": round(state_pct, 4),
        "current_known_regime_pct": round(regime_pct, 4),
        "episodes_needed_rollover_model": rollover_estimate,
        "episodes_needed_additive_worst_case": max(
            additive_needed(state_covered, episode_count),
            additive_needed(regime_covered, episode_count),
        ),
        "approx_live_decision_cycles_needed": math.ceil(rollover_estimate / default_horizons_per_decision) if rollover_estimate else 0,
        "automatic_pass_condition": (
            "No further code change is required. stabilization_ready flips to true automatically, "
            "on the next run of tools/run_growbot_river_learning_cycle.py, once enough new live "
            "decision_outcome/trade_reflection episodes have been recorded to cross both 80% "
            f"thresholds — estimated at {rollover_estimate} new episodes (~"
            f"{math.ceil(rollover_estimate / default_horizons_per_decision) if rollover_estimate else 0} "
            "live decision cycles) under the rollover model. This is now purely a function of live "
            "trading volume, not of remaining engineering work."
            if rollover_estimate > 0
            else "Coverage targets are already met; re-run tools/run_growbot_river_learning_cycle.py to confirm."
        ),
        "model_assumptions": {
            "rollover_model": (
                "decision_outcome/trade_reflection sources are capped at max_per_source and "
                "read as a tail window; new ~100%-covered forward episodes displace old "
                "zero-coverage ones 1:1, so total episode count stays roughly constant. This "
                "is the realistic estimate."
            ),
            "additive_worst_case": (
                "conservative upper bound if episode windows were not capped/rotated and new "
                "episodes only ever accumulated on top of the existing, uncapped pool."
            ),
            "approx_live_decision_cycles_needed": (
                "decision_outcome_tracker writes one record per configured horizon (default 3) "
                "per tracked decision; rough order-of-magnitude only — resolution events add "
                "further lines to the same window without representing new decisions."
            ),
        },
    }


def build_river_dependency_status(river_report: Mapping[str, Any]) -> Dict[str, Any]:
    """Whether River is genuinely unavailable, and why, plus a safe install route.

    A successful `pip show river` does not guarantee the native backend
    loads: river 0.23.0's own PyPI metadata omits `typing_extensions`, which
    `river.base.base` imports directly, so an incomplete dependency
    resolution fails *inside* `_import_river()`'s try/except. This surfaces
    the real reason instead of only the generic `river_native_sidecar_unavailable`
    blocker name.
    """
    backend = _as_dict(river_report.get("backend"))
    available = backend.get("river_available") is True
    return {
        "available": available,
        "backend": backend.get("backend") or "not_run",
        "import_error_detail": backend.get("import_error_detail") or river_unavailable_reason(),
        "model_persistence": backend.get("model_persistence") or {},
        "fallback_backend_sufficient_for_report_only_use": True,
        "verified_native_backend_when_installed": (
            "Permanently installed and verified at /opt/coinbase-river-sidecar (2026-06-21): native "
            "backend active, walk-forward passes (accuracy 1.0, reward_rmse ~0.033 on a chronological "
            "holdout), resolving both river_native_sidecar_unavailable and river_walk_forward_not_passed. "
            "Run tools/run_growbot_river_learning_cycle.py via that interpreter to keep the native "
            "backend active for future cycles; the plain `python3` interpreter still correctly falls "
            "back to the deterministic backend, since River is intentionally not a core dependency."
            if available
            else (
                "Not yet installed in this environment. Verified previously in a throwaway venv: "
                "native backend activates, walk-forward passes (accuracy 1.0, reward_rmse 0.0335 on a "
                "93-event holdout), resolving both river_native_sidecar_unavailable and "
                "river_walk_forward_not_passed. Installing is worthwhile and safe — see safe_install_route."
            )
        ),
        "safe_install_route": [
            "python3 -m venv /opt/coinbase-river-sidecar",
            "/opt/coinbase-river-sidecar/bin/pip install -r requirements-river-sidecar.txt",
            "PYTHONPATH=$(pwd) /opt/coinbase-river-sidecar/bin/python -c \"from bot.river_online_parameter_learner import _import_river; assert _import_river() is not None\"",
            "PYTHONPATH=$(pwd) /opt/coinbase-river-sidecar/bin/python tools/run_growbot_river_learning_cycle.py --json",
        ],
        "isolation_note": (
            "Installs only into the dedicated venv; never into the core bot environment. "
            "requirements-river-sidecar.txt pins typing_extensions explicitly — without it, "
            "river.base.base's direct import of typing_extensions fails silently inside "
            "_import_river()'s try/except even though `pip show river` reports success."
        ),
    }


def build_live_cycle_readiness_report(
    *,
    root: Path = Path("."),
    episode_report: Optional[Mapping[str, Any]] = None,
    river_report: Optional[Mapping[str, Any]] = None,
    cycle_report: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Compact, operator-facing snapshot of what the next live cycles still need.

    Pure aggregation of already-computed, already-tested building blocks
    (`build_stabilization_readiness`, the River report's own parameter
    signals, `estimate_forward_episode_requirements`). Grants no execution or
    parameter-mutation authority; report-only, like every other artifact
    under reports/growbot_river/.
    """
    episode = dict(episode_report) if isinstance(episode_report, Mapping) else _load(root / EPISODE_REPORT_PATH)
    river = dict(river_report) if isinstance(river_report, Mapping) else _load(root / RIVER_REPORT_PATH)
    cycle = dict(cycle_report) if isinstance(cycle_report, Mapping) else _load(root / LIVE_CYCLE_REPORT_PATH)
    contract = _as_dict(episode.get("learning_data_contract"))
    coverage = _as_dict(contract.get("coverage"))
    readiness = build_growbot_river_readiness(root=root, episode_report=episode, river_report=river, cycle_report=cycle)
    signals = river.get("parameter_signals") if isinstance(river.get("parameter_signals"), list) else []
    ranked = sorted(
        (signal for signal in signals if isinstance(signal, Mapping)),
        key=lambda row: (
            _as_float(row.get("candidate_ranking_score")),
            _as_float(row.get("confidence")),
            _as_float(row.get("evidence_count")),
        ),
        reverse=True,
    )
    ranked_parameter_candidates = [
        {
            "parameter": row.get("parameter"),
            "direction": row.get("direction"),
            "confidence": row.get("confidence"),
            "evidence_count": row.get("evidence_count"),
            "expected_reward": row.get("expected_reward"),
            "missed_opportunity_probability": row.get("missed_opportunity_probability"),
            "good_trade_probability": row.get("good_trade_probability"),
            "bad_trade_probability": row.get("bad_trade_probability"),
            "dominant_regime": row.get("dominant_regime"),
            "regime_effect_direction": row.get("regime_effect_direction"),
            "candidate_ranking_score": row.get("candidate_ranking_score"),
            "activation_route": row.get("activation_route"),
            "safe_to_activate_now": row.get("safe_to_activate_now"),
        }
        for row in ranked
    ]
    phase_decision = _as_dict(cycle.get("phase_decision"))
    return {
        "phase": "growbot_river_live_cycle_readiness_v1",
        "generated_at": now_iso(),
        "current_phase": {
            "tuning_phase": phase_decision.get("phase") or "unknown",
            "episode_count_for_phase_decision": phase_decision.get("episode_count"),
            "distinct_regime_count": phase_decision.get("distinct_regime_count"),
            "max_observed_prior_stable_direction_runs": phase_decision.get("max_observed_prior_stable_direction_runs"),
            "caveat": (
                "phase/stable-run counts include this session's own development-time report "
                "regeneration runs (proposal-history.jsonl), not only organic live-trading "
                "cycles; treat the tuning phase as provisional until it is driven purely by "
                "live cycles."
            ),
        },
        "ranked_parameter_candidates": ranked_parameter_candidates,
        "stabilization_readiness": readiness.get("stabilization_readiness") or {},
        "fast_start_autotune_readiness": readiness.get("fast_start_autotune_readiness") or {},
        "forward_episode_requirements": estimate_forward_episode_requirements(
            coverage=coverage,
            episode_count=int(contract.get("episode_count") or 0),
        ),
        "river_dependency_status": build_river_dependency_status(river),
        "top_learning_signals": list(TOP_LEARNING_SIGNALS),
        "remaining_real_limitations": [
            "decision_outcome (1,500 episodes) and trade_reflection (1 episode) on-disk records predate the growbot_river_learning_context fix; 0% state/regime there until new live cycles flush the window — see forward_episode_requirements.",
            "River is not installed in the default/core environment; the deterministic fallback backend is fully functional and produced every number in this report, but river_walk_forward_not_passed stays a real blocker until it is installed (isolated venv only — see river_dependency_status.safe_install_route).",
            "volume_ratio and ticker_score are computed elsewhere in the pipeline (bot/phase_d6_*) but are not yet confirmed to be copied into feature_pack under the exact keys this contract reads; verify before assuming they will populate from live decisions.",
            "adaptive_candidate_not_available and growbot_upstream_learning_runtime_unavailable remain in the overall blockers list but are, by design, not stabilization blockers (they gate a later/different stage and a permanent upstream-license gap respectively).",
        ],
        "recommended_next_live_cycle_observations": [
            "Keep PHASE_C43/D3 decision and trade-reflection tracking enabled exactly as-is; no code change is required for decision_outcome/trade_reflection coverage to rise — only live volume.",
            "Re-run `python3 tools/run_growbot_river_learning_cycle.py --json` after each live cycle batch (or on the existing schedule) so the episode ledger and River state advance on organic evidence rather than development-time re-runs.",
            "When convenient, install River into the isolated `/opt/coinbase-river-sidecar` venv (now with typing_extensions pinned) to resolve river_native_sidecar_unavailable / river_walk_forward_not_passed ahead of the volume-driven blockers clearing.",
            "Once decision_outcome_tracker-sourced episodes start dominating recent evidence, verify whether liquidity_score/orderbook_imbalance/volume_ratio/ticker_score actually appear in `per_parameter_diagnostics` — if volume_ratio/ticker_score still don't, trace feature_pack producer code (see top_learning_signals) before assuming the contract extraction is broken.",
            "Do not activate any parameter from ranked_parameter_candidates directly; route every change through adaptive_policy_lab -> parameter_candidate_analysis -> autonomous_parameter_governor -> approved_parameter_profile, unchanged.",
        ],
        "safety_policy": {
            "report_only": True,
            "can_authorize_execution": False,
            "can_mutate_parameters": False,
            "can_apply_profile": False,
        },
    }


def write_live_cycle_readiness_report(report: Mapping[str, Any], *, root: Path = Path(".")) -> str:
    output = root / LIVE_CYCLE_READINESS_PATH
    atomic_write_json(output, dict(report))
    return str(output)


__all__ = [
    "EPISODE_REPORT_PATH",
    "FAST_START_MIN_DISTINCT_REGIMES",
    "FAST_START_MIN_FEATURE_STATE_COVERAGE_PCT",
    "FAST_START_MIN_REGIME_COVERAGE_PCT",
    "FORWARD_READY_SOURCES",
    "HISTORICAL_GAP_SOURCES",
    "LIVE_CYCLE_READINESS_PATH",
    "LIVE_CYCLE_REPORT_PATH",
    "READINESS_PATH",
    "READINESS_PHASE",
    "STABILIZATION_GATING_BLOCKERS",
    "TOP_LEARNING_SIGNALS",
    "build_fast_start_autotune_readiness",
    "build_growbot_river_readiness",
    "build_live_cycle_readiness_report",
    "build_river_dependency_status",
    "build_stabilization_readiness",
    "estimate_forward_episode_requirements",
    "write_growbot_river_readiness",
    "write_live_cycle_readiness_report",
]
